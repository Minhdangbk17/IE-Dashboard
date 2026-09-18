"""Right First Time (RFT) report — truy vấn và tổng hợp từ dữ liệu Batch.

Khung sườn (scaffold): pipeline lọc (Capacity/Date range/Group By Day-Week-Month)
và cấu trúc pivot theo kỳ ĐÃ hoàn chỉnh, dùng lại đúng khái niệm production_date
(cắt ca 7h sáng, `core/production_time.py`) và quy ước loại Fabric Type không hợp
lệ (`INVALID_FABRIC_TYPES`) đã áp dụng cho `downtime`/`batch_matrix`.

PHẦN CÒN THIẾU (chờ người dùng hướng dẫn chi tiết): `classify_rft_category()` —
quy tắc phân loại MỘT mẻ vào 1 trong 6 nhóm (`RFT_CATEGORIES`) hiện luôn trả về
`None` (chưa phân loại được nhóm nào) nên mọi bảng/biểu đồ hiện ra đúng cấu trúc
nhưng số liệu = 0. Khi có quy tắc cụ thể, CHỈ cần sửa hàm đó — routes/template/JS
không cần đổi. Các cột `batch_details` có khả năng liên quan (xem
`models/dyeing.py::BATCH_DETAIL_FIELDS`, CHƯA xác nhận ý nghĩa từng giá trị):
`batch_type`, `formula_type`, `process_type`, `redye`, `is_rework`, `correction_cnt`,
`total_correction_cnt`, `formula_code`.

Nguồn dữ liệu: `availability_logs` (capacity_kg, production_date, fabric_type) LEFT
JOIN `batch_details` (khoá `lower(trim(a.batch)) = lower(trim(b.dyelot))`, CÙNG khoá
JOIN đã verify 99.7% khớp ở `batch_matrix`/`downtime` — xem
`memory-bank/activeContext.md`).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from core.brand_program_importer import ensure_brand_program_table
from core.database import DatabaseError, execute_query, get_db
from core.production_time import get_production_date

# Nhãn "Brand - Program" suy từ batch/dyelot -> greige_code -> brand_program_mapping — cùng
# cơ chế `downtime/service.py`/`batch_matrix/service.py`.
_BRAND_PROGRAM_LABEL_SQL = "CASE WHEN COALESCE(bpm.brand, '') <> '' AND COALESCE(bpm.brand_program, '') <> '' THEN bpm.brand || ' - ' || bpm.brand_program ELSE '' END"
_BRAND_PROGRAM_JOIN_SQL = "LEFT JOIN brand_program_mapping bpm ON lower(trim(bpm.greige_code)) = lower(trim(b.greige_code))"

# Tên hiển thị theo ĐÚNG thứ tự tab yêu cầu — slug dùng làm khoá URL/DOM, KHÔNG đổi
# sau khi đã có người dùng thật thao tác (đổi slug sẽ vỡ link/DOM id đang dùng).
RFT_CATEGORY_SLUGS: dict[str, str] = {
    "lab_to_lab": "Lab to Lab",
    "lab_to_bulk": "Lab to Bulk",
    "bulk_to_bulk": "Bulk to Bulk",
    "second_batch": "2nd Batch",
    "rework": "Rework",
    "adjust_color": "Adjust Color",
}
RFT_CATEGORIES = tuple(RFT_CATEGORY_SLUGS.values())
INVALID_FABRIC_TYPES = ("Unknow", "Unknown", "All", "")


def _parse_capacities(capacities: str | list[str] | None) -> list[float]:
    """Parse capacities=25,50; ALL/rỗng nghĩa là không lọc theo Capacity."""
    if capacities is None:
        return []
    values = capacities if isinstance(capacities, list) else str(capacities).split(",")
    parsed: list[float] = []
    for value in values:
        text = str(value).strip()
        if not text or text.upper() == "ALL":
            return []
        try:
            number = float(text)
        except ValueError:
            continue
        if number not in parsed:
            parsed.append(number)
    return parsed


def _parse_text_filter(value: str | list[str] | None) -> list[str]:
    """Parse fabric_types=/brand_programs= query param (CSV hoặc list) — rỗng/'ALL' nghĩa
    là không lọc theo chiều đó, cùng quy ước với `_parse_capacities()`."""
    if not value:
        return []
    values = value if isinstance(value, list) else str(value).split(",")
    result: list[str] = []
    for item in values:
        text = str(item).strip()
        if not text or text.upper() == "ALL":
            return []
        if text not in result:
            result.append(text)
    return result


def _parse_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
    return None


def _period(day: date, group_by: str) -> tuple[str, str]:
    if group_by == "month":
        return day.strftime("%Y-%m"), day.strftime("%b-%y")
    if group_by == "week":
        year, week, _ = day.isocalendar()
        return f"{year}-W{week:02d}", f"W{week:02d} {year}"
    return day.isoformat(), day.strftime("%d %b %Y")


# Cờ báo cho UI (Dyeing Hub Dashboard) biết `classify_rft_category()` đã có quy tắc phân
# loại THẬT hay vẫn là khung sườn luôn trả None — khi False, mọi Rate% đều = 0 KHÔNG PHẢI
# vì nhà máy không đạt chuẩn, mà vì chưa có logic phân loại. Dashboard dựa vào cờ này để
# hiện trạng thái "đang chờ cấu hình" thay vì đường phẳng 0% (dễ hiểu nhầm là dữ liệu thật
# xấu). **Đổi cờ này thành True NGAY KHI thay xong nội dung `classify_rft_category()`** —
# cùng 1 lần sửa, đừng quên bước này.
RFT_CLASSIFICATION_READY = False


def classify_rft_category(row: dict[str, Any]) -> str | None:
    """Phân loại 1 mẻ (dict đã JOIN đủ cột `availability_logs`+`batch_details`) vào
    ĐÚNG 1 trong 6 nhóm `RFT_CATEGORIES`, hoặc `None` nếu chưa xác định được nhóm.

    TODO (chờ người dùng cung cấp quy tắc chi tiết cho từng bảng — hiện luôn trả
    `None`, xem docstring đầu file để biết các cột `batch_details` khả dụng). Nhớ đổi
    `RFT_CLASSIFICATION_READY = True` ở trên khi thay xong."""
    return None


def _batch_rows(
    selected_capacities: list[float], from_date: str | None, to_date: str | None,
) -> list[dict[str, Any]]:
    """Lấy toàn bộ mẻ khớp bộ lọc Capacity/Date, kèm cột `batch_details` cần cho phân loại
    + nhãn Brand Program — query TRỰC TIẾP (chưa có Daily Rollup, xem module docstring),
    chấp nhận được ở quy mô dữ liệu hiện tại vì đây là khung sườn chưa tối ưu hiệu năng.
    KHÔNG lọc theo Fabric Type/Brand Program ở đây — lọc ở Python trong
    `get_rft_pivot_data()` để tính được `available_fabric_types`/`available_brand_programs`
    từ CÙNG 1 lần query (độc lập với chính 2 filter đó)."""
    ensure_brand_program_table(get_db())
    sql = f"""
        SELECT a."id" AS availability_log_id, a."batch" AS batch, a."capacity_kg" AS capacity_kg,
               a."fabric_type" AS fabric_type, a."start_time" AS start_time, a."end_time" AS end_time,
               b."batch_type" AS batch_type, b."formula_type" AS formula_type, b."process_type" AS process_type,
               b."redye" AS redye, b."is_rework" AS is_rework, b."correction_cnt" AS correction_cnt,
               {_BRAND_PROGRAM_LABEL_SQL} AS brand_program
        FROM availability_logs a
        LEFT JOIN batch_details b ON lower(trim(a."batch")) = lower(trim(b."dyelot"))
        {_BRAND_PROGRAM_JOIN_SQL}
        WHERE a."batch" IS NOT NULL AND TRIM(CAST(a."batch" AS TEXT)) <> ''
          AND a."fabric_type" IS NOT NULL
          AND LOWER(TRIM(CAST(a."fabric_type" AS TEXT))) NOT IN (?, ?, ?, ?)
    """
    params: list[Any] = [value.lower() for value in INVALID_FABRIC_TYPES]
    if selected_capacities:
        placeholders = ", ".join("?" for _ in selected_capacities)
        sql += f" AND CAST(a.\"capacity_kg\" AS REAL) IN ({placeholders})"
        params.extend(selected_capacities)
    try:
        rows = execute_query(sql, params)
    except DatabaseError:
        return []

    result: list[dict[str, Any]] = []
    for row in rows:
        record_time = _parse_datetime(row["end_time"]) or _parse_datetime(row["start_time"])
        if record_time is None:
            continue
        production_date = get_production_date(record_time)
        if from_date and production_date.isoformat() < from_date:
            continue
        if to_date and production_date.isoformat() > to_date:
            continue
        result.append({**dict(row), "production_date": production_date})
    return result


def _empty_pivot(category: str, group_by: str) -> dict[str, Any]:
    return {
        "category": category,
        "filters": {"capacities": [], "fabric_types": [], "brand_programs": [], "from_date": None, "to_date": None, "group_by": group_by},
        "periods": [], "period_keys": [],
        "rows": [{"label": category, "values": [], "total": 0}],
        "total_row": [],
        "chart": {"categories": [], "values": [], "rate_values": []},
        "kpis": {"total_batches": 0, "category_batches": 0, "rate_pct": 0.0},
        "available_fabric_types": [], "available_brand_programs": [],
        "classification_ready": RFT_CLASSIFICATION_READY,
    }


def get_rft_pivot_data(
    category: str, capacities: str | list[str] | None = None,
    fabric_types: str | list[str] | None = None, brand_programs: str | list[str] | None = None,
    from_date: str | None = None, to_date: str | None = None, group_by: str = "date",
) -> dict[str, Any]:
    """Bảng + biểu đồ cho ĐÚNG 1 trong 6 nhóm RFT theo Day/Week/Month — cùng bộ lọc
    Capacity/Fabric Type/Brand Program/Date range như Downtime. `category` phải là 1 giá
    trị trong `RFT_CATEGORIES` (route đã validate qua `RFT_CATEGORY_SLUGS`)."""
    if category not in RFT_CATEGORIES:
        raise ValueError(f"Nhóm RFT không hợp lệ: {category}")
    group_by = group_by if group_by in {"date", "week", "month"} else "date"
    selected_capacities = _parse_capacities(capacities)
    selected_fabric_types = _parse_text_filter(fabric_types)
    selected_brand_programs = _parse_text_filter(brand_programs)
    # Lấy toàn bộ mẻ khớp Capacity/Date TRƯỚC (chưa lọc Fabric Type/Brand Program) để
    # `available_fabric_types`/`available_brand_programs` phản ánh đúng phạm vi đang chọn,
    # ĐỘC LẬP với chính 2 filter đó (cùng nguyên tắc `downtime/service.py::
    # _available_fabric_types_and_brand_programs()`), rồi mới lọc tiếp ở Python.
    all_rows = _batch_rows(selected_capacities, from_date, to_date)
    available_fabric_types = sorted({row["fabric_type"] for row in all_rows if row["fabric_type"]})
    available_brand_programs = sorted({row["brand_program"] for row in all_rows if row["brand_program"]})

    fabric_filter = set(selected_fabric_types) if selected_fabric_types else None
    brand_filter = set(selected_brand_programs) if selected_brand_programs else None
    rows = [
        row for row in all_rows
        if (fabric_filter is None or row["fabric_type"] in fabric_filter)
        and (brand_filter is None or row["brand_program"] in brand_filter)
    ]
    if not rows:
        empty = _empty_pivot(category, group_by)
        empty["available_fabric_types"] = available_fabric_types
        empty["available_brand_programs"] = available_brand_programs
        return empty

    periods: dict[str, dict[str, Any]] = {}
    total_batches: set[str] = set()
    for row in rows:
        key, label = _period(row["production_date"], group_by)
        period = periods.setdefault(key, {"label": label, "count": 0, "batches": set()})
        batch_key = str(row["batch"]).strip()
        period["batches"].add(batch_key)
        total_batches.add(batch_key)
        if classify_rft_category(row) == category:
            period["count"] += 1

    ordered = sorted(periods.items())
    labels = [value["label"] for _, value in ordered]
    period_keys = [key for key, _ in ordered]
    values = [value["count"] for _, value in ordered]
    # Rate % THEO TỪNG KỲ (không phải chỉ tổng cả khoảng) — dùng cho widget dạng
    # trend-line (VD Dyeing Hub Dashboard), khác `kpis.rate_pct` vốn chỉ tính 1 số
    # tổng hợp cho CẢ khoảng ngày đã lọc. Chia theo đúng số mẻ CỦA KỲ ĐÓ (không phải
    # `total_batches` toàn khoảng) để không bị lệch nếu số mẻ/kỳ không đều nhau.
    rate_values = [
        round(value["count"] / len(value["batches"]) * 100, 1) if value["batches"] else 0.0
        for _, value in ordered
    ]
    category_batches = sum(values)

    return {
        "category": category,
        "filters": {
            "capacities": selected_capacities or "all", "fabric_types": selected_fabric_types or "all",
            "brand_programs": selected_brand_programs or "all", "from_date": from_date, "to_date": to_date, "group_by": group_by,
        },
        "periods": labels, "period_keys": period_keys,
        "rows": [{"label": category, "values": values, "total": category_batches}],
        "total_row": values,
        "chart": {"categories": labels, "values": values, "rate_values": rate_values},
        "kpis": {
            "total_batches": len(total_batches),
            "category_batches": category_batches,
            "rate_pct": round(category_batches / len(total_batches) * 100, 1) if total_batches else 0.0,
        },
        "available_fabric_types": available_fabric_types, "available_brand_programs": available_brand_programs,
        "classification_ready": RFT_CLASSIFICATION_READY,
    }
