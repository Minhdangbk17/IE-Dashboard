"""Right First Time (RFT) report — truy vấn và tổng hợp từ `rft_dye_results`.

Nguồn dữ liệu: bảng `rft_dye_results` (import từ file "RFT report.xlsx" — QC xuất, xem
`core/rft_importer.py`), khoá `dyelot`. LEFT JOIN `availability_logs` (khoá
`lower(trim(a.batch)) = lower(trim(r.dyelot))`, CÙNG khoá JOIN đã verify 99.7% khớp ở
`batch_matrix`/`downtime`) chỉ để suy ra `capacity_kg`/`fabric_type`/`production_date` — 1
dòng RFT KHÔNG khớp `availability_logs` (thường gặp ở MachineType "Small Machine", chưa được
theo dõi Availability) vẫn được GIỮ LẠI (không loại bỏ), chỉ không có `production_date` nên
rơi vào cột pivot "Unknown Date" thay vì bị mất.

Quy tắc phân loại 6 tab (`classify_rft_category`): cột `Stage` (chuẩn hoá lower+trim) map
trực tiếp sang 1 trong 6 `RFT_CATEGORIES` qua `STAGE_TO_CATEGORY`. Giá trị Stage không khớp
nhóm nào KHÔNG bị gộp vào tab nào cả (đếm riêng qua `other_stage_count`, hiển thị như 1 chỉ
báo dữ liệu cần rà soát nguồn, không phải lỗi tính toán).

Riêng 2 tab "Rework"/"Adjust Color": CHỈ tính các mẻ có MachineType ">=500kg" (loại "Small
Machine"), theo yêu cầu người dùng — xem `_is_large_machine()`.

Công thức KPI mỗi tab: `rate_pct = số mẻ ResultDYE='OK' trong CHÍNH tab đó / tổng số mẻ CỦA
CHÍNH tab đó` (đo "tỷ lệ đạt ngay lần đầu" của loại lần chạy đó) — KHÔNG phải tỷ trọng so với
tổng 6 tab như thiết kế cũ.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from core.brand_program_importer import ensure_brand_program_table
from core.database import DatabaseError, execute_query, get_db
from core.production_time import get_production_date
from core.rft_importer import LARGE_MACHINE_KEY

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

# Map Stage (đã chuẩn hoá .strip().lower()) -> tên tab hiển thị. Giá trị không có trong map
# này KHÔNG được phân vào tab nào (xem docstring đầu file).
STAGE_TO_CATEGORY: dict[str, str] = {
    "lab to lab": "Lab to Lab",
    "lab to bulk": "Lab to Bulk",
    "bulk to bulk": "Bulk to Bulk",
    "2nd batch": "2nd Batch",
    "rework": "Rework",
    "adjust color": "Adjust Color",
}
# 2 tab CHỈ tính máy >=500kg (loại "Small Machine") — quyết định nghiệp vụ riêng cho 2 nhóm
# này, KHÔNG áp dụng cho 4 tab còn lại.
RESTRICTED_TO_LARGE_MACHINE = {"Rework", "Adjust Color"}

# Cờ báo cho UI (Dyeing Hub Dashboard) biết `classify_rft_category()` đã có quy tắc phân loại
# THẬT — bật True kể từ khi có nguồn `rft_dye_results` (xem `RFT_CLASSIFICATION_READY` cũ,
# trước đó luôn False vì hàm luôn trả None).
RFT_CLASSIFICATION_READY = True

_BRAND_PROGRAM_LABEL_SQL = "CASE WHEN COALESCE(bpm.brand, '') <> '' AND COALESCE(bpm.brand_program, '') <> '' THEN bpm.brand || ' - ' || bpm.brand_program ELSE '' END"


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
    """Parse machine_types=/fabric_types=/brand_programs= query param (CSV hoặc list) — rỗng/
    'ALL' nghĩa là không lọc theo chiều đó, cùng quy ước với `_parse_capacities()`."""
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


def _is_large_machine(machine_type: Any) -> bool:
    return str(machine_type or "").replace(" ", "").strip().lower() == LARGE_MACHINE_KEY


def classify_rft_category(row: dict[str, Any]) -> str | None:
    """Phân loại 1 mẻ (dict có field `stage` từ `rft_dye_results`) vào ĐÚNG 1 trong 6 nhóm
    `RFT_CATEGORIES`, hoặc `None` nếu Stage không khớp giá trị nào (không bịa nhóm gộp —
    xem docstring đầu file)."""
    stage = str(row.get("stage") or "").strip().lower()
    return STAGE_TO_CATEGORY.get(stage)


def _rft_rows(selected_capacities: list[float], from_date: str | None, to_date: str | None) -> list[dict[str, Any]]:
    """Lấy toàn bộ dòng `rft_dye_results` khớp bộ lọc Capacity/Date, kèm nhãn Brand Program —
    query TRỰC TIẾP (chưa có Daily Rollup, cùng quyết định đã áp dụng lúc scaffold). KHÔNG lọc
    theo Machine Type/Fabric Type/Brand Program ở đây — lọc ở Python trong
    `get_rft_pivot_data()` để tính được `available_*` từ CÙNG 1 lần query, độc lập với chính
    3 filter đó (cùng nguyên tắc `downtime/service.py::_available_fabric_types_and_brand_programs()`)."""
    ensure_brand_program_table(get_db())
    sql = f"""
        SELECT r."id" AS rft_id, r."dyelot" AS dyelot, r."customer" AS customer, r."color" AS color,
               r."order_no" AS order_no, r."greige_code" AS greige_code, r."machine_type" AS machine_type,
               r."nc_dg" AS nc_dg, r."result_dye" AS result_dye, r."new_batch2" AS new_batch2,
               r."rework_count" AS rework_count, r."stage" AS stage, r."recipe" AS recipe, r."body_rib" AS body_rib,
               a."capacity_kg" AS capacity_kg, a."fabric_type" AS fabric_type,
               a."start_time" AS start_time, a."end_time" AS end_time,
               {_BRAND_PROGRAM_LABEL_SQL} AS brand_program
        FROM rft_dye_results r
        LEFT JOIN availability_logs a ON lower(trim(a."batch")) = lower(trim(r."dyelot"))
        LEFT JOIN brand_program_mapping bpm ON lower(trim(bpm."greige_code")) = lower(trim(r."greige_code"))
        WHERE r."dyelot" IS NOT NULL AND TRIM(CAST(r."dyelot" AS TEXT)) <> ''
    """
    params: list[Any] = []
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
        production_date = get_production_date(record_time) if record_time is not None else None
        # Không xác định được production_date (không khớp availability_logs — thường là
        # MachineType "Small Machine" chưa theo dõi Availability): vẫn GIỮ dòng khi KHÔNG có
        # filter ngày (rơi vào bucket "Unknown Date" lúc pivot), nhưng LOẠI khi người dùng đã
        # chủ động lọc From/To Date (không đủ căn cứ xác nhận có nằm trong khoảng hay không).
        if from_date and (production_date is None or production_date.isoformat() < from_date):
            continue
        if to_date and (production_date is None or production_date.isoformat() > to_date):
            continue
        result.append({**dict(row), "production_date": production_date})
    return result


def _empty_pivot(category: str, group_by: str) -> dict[str, Any]:
    return {
        "category": category,
        "filters": {
            "capacities": [], "machine_types": [], "fabric_types": [], "brand_programs": [],
            "from_date": None, "to_date": None, "group_by": group_by,
        },
        "periods": [], "period_keys": [],
        "rows": [{"label": category, "values": [], "total": 0.0}],
        "total_row": [],
        "chart": {"categories": [], "values": [], "rate_values": []},
        "kpis": {"total_batches": 0, "ok_batches": 0, "rate_pct": 0.0},
        "available_fabric_types": [], "available_brand_programs": [], "available_machine_types": [],
        "other_stage_count": 0,
        "classification_ready": RFT_CLASSIFICATION_READY,
    }


def get_rft_pivot_data(
    category: str, capacities: str | list[str] | None = None,
    machine_types: str | list[str] | None = None,
    fabric_types: str | list[str] | None = None, brand_programs: str | list[str] | None = None,
    from_date: str | None = None, to_date: str | None = None, group_by: str = "date",
) -> dict[str, Any]:
    """Bảng + biểu đồ cho ĐÚNG 1 trong 6 nhóm RFT theo Day/Week/Month — cùng bộ lọc
    Capacity/Machine Type/Fabric Type/Brand Program/Date range. `category` phải là 1 giá trị
    trong `RFT_CATEGORIES` (route đã validate qua `RFT_CATEGORY_SLUGS`)."""
    if category not in RFT_CATEGORIES:
        raise ValueError(f"Nhóm RFT không hợp lệ: {category}")
    group_by = group_by if group_by in {"date", "week", "month"} else "date"
    selected_capacities = _parse_capacities(capacities)
    selected_machine_types = _parse_text_filter(machine_types)
    selected_fabric_types = _parse_text_filter(fabric_types)
    selected_brand_programs = _parse_text_filter(brand_programs)

    all_rows = _rft_rows(selected_capacities, from_date, to_date)
    available_fabric_types = sorted({row["fabric_type"] for row in all_rows if row["fabric_type"]})
    available_brand_programs = sorted({row["brand_program"] for row in all_rows if row["brand_program"]})
    available_machine_types = sorted({row["machine_type"] for row in all_rows if row["machine_type"]})

    machine_filter = set(selected_machine_types) if selected_machine_types else None
    fabric_filter = set(selected_fabric_types) if selected_fabric_types else None
    brand_filter = set(selected_brand_programs) if selected_brand_programs else None
    rows = [
        row for row in all_rows
        if (machine_filter is None or row["machine_type"] in machine_filter)
        and (fabric_filter is None or row["fabric_type"] in fabric_filter)
        and (brand_filter is None or row["brand_program"] in brand_filter)
    ]

    # Đếm riêng (KHÔNG gộp vào tab nào) số mẻ có Stage không khớp 6 nhóm, trong ĐÚNG phạm vi
    # filter hiện tại — chỉ báo dữ liệu nguồn cần rà soát, không phải lỗi tính toán.
    other_stage_count = len({
        str(row["dyelot"]).strip() for row in rows if classify_rft_category(row) is None
    })

    tab_rows = [row for row in rows if classify_rft_category(row) == category]
    if category in RESTRICTED_TO_LARGE_MACHINE:
        tab_rows = [row for row in tab_rows if _is_large_machine(row["machine_type"])]

    if not tab_rows:
        empty = _empty_pivot(category, group_by)
        empty["filters"] = {
            "capacities": selected_capacities or "all", "machine_types": selected_machine_types or "all",
            "fabric_types": selected_fabric_types or "all", "brand_programs": selected_brand_programs or "all",
            "from_date": from_date, "to_date": to_date, "group_by": group_by,
        }
        empty["available_fabric_types"] = available_fabric_types
        empty["available_brand_programs"] = available_brand_programs
        empty["available_machine_types"] = available_machine_types
        empty["other_stage_count"] = other_stage_count
        return empty

    periods: dict[str, dict[str, Any]] = {}
    for row in tab_rows:
        if row["production_date"] is not None:
            key, label = _period(row["production_date"], group_by)
        else:
            key, label = "unknown", "Unknown Date"
        period = periods.setdefault(key, {"label": label, "batches": set(), "ok_batches": set()})
        batch_key = str(row["dyelot"]).strip()
        period["batches"].add(batch_key)
        if row["result_dye"] == "OK":
            period["ok_batches"].add(batch_key)

    # Sort theo key kỳ, "unknown" LUÔN xuống cuối (không sort theo alphabet chung — 'u' của
    # "unknown" có thể chen giữa các key ngày/tuần/tháng dạng số).
    known_items = sorted((item for item in periods.items() if item[0] != "unknown"), key=lambda item: item[0])
    ordered = known_items + ([("unknown", periods["unknown"])] if "unknown" in periods else [])

    labels = [value["label"] for _, value in ordered]
    period_keys = [key for key, _ in ordered]
    total_values = [len(value["batches"]) for _, value in ordered]
    rate_values = [
        round(len(value["ok_batches"]) / len(value["batches"]) * 100, 1) if value["batches"] else 0.0
        for _, value in ordered
    ]

    total_batches = {str(row["dyelot"]).strip() for row in tab_rows}
    ok_batches = {str(row["dyelot"]).strip() for row in tab_rows if row["result_dye"] == "OK"}
    overall_rate = round(len(ok_batches) / len(total_batches) * 100, 1) if total_batches else 0.0

    return {
        "category": category,
        "filters": {
            "capacities": selected_capacities or "all", "machine_types": selected_machine_types or "all",
            "fabric_types": selected_fabric_types or "all", "brand_programs": selected_brand_programs or "all",
            "from_date": from_date, "to_date": to_date, "group_by": group_by,
        },
        "periods": labels, "period_keys": period_keys,
        # Cell/Total hiển thị DẠNG % (tỷ lệ đạt ngay lần đầu theo kỳ), không phải số mẻ thô.
        "rows": [{"label": category, "values": rate_values, "total": overall_rate}],
        "total_row": rate_values,
        "chart": {"categories": labels, "values": total_values, "rate_values": rate_values},
        "kpis": {
            "total_batches": len(total_batches),
            "ok_batches": len(ok_batches),
            "rate_pct": overall_rate,
        },
        "available_fabric_types": available_fabric_types, "available_brand_programs": available_brand_programs,
        "available_machine_types": available_machine_types,
        "other_stage_count": other_stage_count,
        "classification_ready": RFT_CLASSIFICATION_READY,
    }
