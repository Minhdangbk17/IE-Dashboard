"""%Tank Loading report — Sum(OutputKgH) / Sum(MaxOutputKgH) từ dữ liệu Performance.

Nguồn dữ liệu: `performance_logs` (import qua Modal Import Data, loại "Performance") —
CHƯA có Engine nào đọc bảng này trước đây (chỉ dùng cho Import/Raw Data Viewer, xem
`modules/dyeing/engines/excel_import/service.py`). Dòng "Tổng kết" (Dyelot/Machine='All')
ở cuối file Excel đã bị loại bỏ NGAY LÚC IMPORT (xem `core/excel_importer.py::_parse_raw_row()`),
nên KHÔNG cần lọc lại ở đây.

Công thức Sum/Sum (không phải trung bình cộng %Loading của từng dòng) — cùng nguyên tắc
gộp đã áp dụng cho `batch_matrix` (Sum tử/Sum mẫu ở MỌI cấp gộp, xem
`memory-bank/systemPatterns.md` mục 6.2) để không bị lệch khi các dòng có RunningTime
khác nhau nhiều.

Bộ lọc Capacity (Kg) đọc từ `performance_logs.capacity` (header Excel gốc "Capacity") —
CÙNG khái niệm "dung tích máy" như `availability_logs.capacity_kg`, chỉ khác tên cột vì 2
bảng import độc lập nhau.

CHƯA có Daily Rollup (query trực tiếp mỗi request) — cùng quyết định "tạm hoãn rollup tới
khi có dữ liệu thật đủ lớn để đo được chậm" đã áp dụng cho `oee`/`rft`.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from core.brand_program_importer import ensure_brand_program_table
from core.database import DatabaseError, execute_query, get_db, get_dialect
from core.production_time import get_production_date

# Báo cáo LUÔN thể hiện ĐÚNG 3 loại vải chính này (theo yêu cầu người dùng, cùng quyết định
# đã áp dụng cho "Batch/Day Trend" — `modules/dyeing/engines/batch_matrix/batch_day_trend.py::
# MAIN_FABRIC_TYPES`). Định nghĩa RIÊNG ở đây (không import cross-engine từ batch_matrix) để
# giữ đúng Vertical Slice Architecture — mỗi Engine tự đóng gói đầy đủ, không phụ thuộc lẫn
# nhau (xem CLAUDE.md mục 3-4). Loại KHÁC 3 loại này (VD Nylon) bị loại khỏi báo cáo hoàn
# toàn. So khớp không phân biệt hoa/thường — CHƯA xác nhận dữ liệu thật có biến thể viết
# khác (VD viết tắt) hay không.
MAIN_FABRIC_TYPES: tuple[str, ...] = ("Cotton", "CVC", "Polyester")
_MAIN_FABRIC_TYPE_BY_NORM: dict[str, str] = {name.lower(): name for name in MAIN_FABRIC_TYPES}


def _normalize_main_fabric_type(value: str | None) -> str | None:
    return _MAIN_FABRIC_TYPE_BY_NORM.get(str(value or "").strip().lower())

# Nhãn "Brand - Program" suy từ dyelot -> greige_code -> brand_program_mapping — cùng cơ
# chế `downtime/service.py`/`batch_matrix/service.py`. `performance_logs.dyelot` khớp
# THẲNG `batch_details.dyelot` (không qua alias batch/batch_ref_no như availability_logs).
_BRAND_PROGRAM_LABEL_SQL = "CASE WHEN COALESCE(bpm.brand, '') <> '' AND COALESCE(bpm.brand_program, '') <> '' THEN bpm.brand || ' - ' || bpm.brand_program ELSE '' END"
_BRAND_PROGRAM_JOIN_SQL = (
    "LEFT JOIN batch_details bd ON lower(trim(bd.dyelot)) = lower(trim(p.dyelot)) "
    "LEFT JOIN brand_program_mapping bpm ON lower(trim(bpm.greige_code)) = lower(trim(bd.greige_code))"
)


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


def _performance_rows(selected_capacities: list[float], from_date: str | None, to_date: str | None) -> list[dict[str, Any]]:
    """Lấy toàn bộ dòng `performance_logs` khớp bộ lọc Capacity, kèm production_date tính
    từ EndTime (fallback StartTime) + Fabric Type/nhãn Brand Program — query TRỰC TIẾP
    (chưa có Daily Rollup). KHÔNG lọc theo Fabric Type/Brand Program ở đây — lọc theo 3
    loại vải chính (`_normalize_main_fabric_type()`) và Brand Program ở Python trong
    `get_tank_loading_pivot_data()`, để tính được `available_brand_programs` từ CÙNG 1 lần
    query (độc lập với filter Brand Program)."""
    ensure_brand_program_table(get_db())
    sql = f"""
        SELECT p.machine, p.capacity, p.output_kgh, p.output_max_load_kgh, p.start_time, p.end_time,
               p.fabric_type AS fabric_type, {_BRAND_PROGRAM_LABEL_SQL} AS brand_program
        FROM performance_logs p
        {_BRAND_PROGRAM_JOIN_SQL}
        WHERE p.start_time IS NOT NULL OR p.end_time IS NOT NULL
    """
    params: list[Any] = []
    if selected_capacities:
        placeholders = ", ".join("?" for _ in selected_capacities)
        sql += f" AND CAST(p.capacity AS REAL) IN ({placeholders})"
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


# ---------------------------------------------------------------------------
# Target — bảng cấu hình `tank_loading_targets`, khoá theo `fabric_type` (CHỈ 3 giá trị
# `MAIN_FABRIC_TYPES`). Cùng pattern `downtime_targets`/`batch_matrix_targets`/
# `batch_day_trend_targets` đã có sẵn trong dự án — mỗi báo cáo 1 bảng riêng.
# ---------------------------------------------------------------------------


def _ensure_targets_table(conn: Any) -> None:
    """CHỈ chạy CREATE TABLE ở SQLite — Postgres tạo qua `supabase/schema.sql`."""
    if get_dialect() == "sqlite":
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tank_loading_targets (
                fabric_type TEXT PRIMARY KEY,
                target_value REAL NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
    conn.commit()


def get_targets() -> dict[str, float | None]:
    """{fabric_type: target_value} cho ĐÚNG 3 loại `MAIN_FABRIC_TYPES` — loại CHƯA từng
    được cấu hình trả `None` (hiển thị "-" trên UI, phân biệt với target THẬT SỰ = 0)."""
    conn = get_db()
    _ensure_targets_table(conn)
    rows = execute_query("SELECT fabric_type, target_value FROM tank_loading_targets")
    result: dict[str, float | None] = {row["fabric_type"]: float(row["target_value"]) for row in rows}
    for name in MAIN_FABRIC_TYPES:
        result.setdefault(name, None)
    return result


def set_target(fabric_type: str, target_value: float) -> dict[str, Any]:
    if fabric_type not in MAIN_FABRIC_TYPES:
        raise ValueError(f"Fabric type không hợp lệ: {fabric_type}")
    conn = get_db()
    _ensure_targets_table(conn)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT INTO tank_loading_targets (fabric_type, target_value, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(fabric_type) DO UPDATE SET target_value = excluded.target_value, updated_at = excluded.updated_at",
        (fabric_type, target_value, now_str),
    )
    conn.commit()
    return {"fabric_type": fabric_type, "target_value": target_value, "updated_at": now_str}


def _empty_pivot(group_by: str, targets: dict[str, float | None] | None = None) -> dict[str, Any]:
    targets = targets or {}
    return {
        "filters": {"capacities": [], "brand_programs": [], "from_date": None, "to_date": None, "group_by": group_by},
        "periods": [], "period_keys": [],
        "rows": [{"fabric_type": name, "target": targets.get(name), "values": [], "total": 0.0} for name in MAIN_FABRIC_TYPES],
        "chart": {"categories": [], "series": []},
        "kpis": {"tank_loading_pct": 0.0, "total_output_kgh": 0.0, "total_max_load_kgh": 0.0},
        "available_brand_programs": [],
    }


def get_tank_loading_pivot_data(
    capacities: str | list[str] | None = None,
    brand_programs: str | list[str] | None = None,
    from_date: str | None = None, to_date: str | None = None, group_by: str = "date",
) -> dict[str, Any]:
    """Bảng + biểu đồ %Tank Loading theo Day/Week/Month — LUÔN 3 dòng/3 đường cố định
    Cotton/CVC/Polyester (mỗi loại có tử số/mẫu số Sum(OutputKgH)/Sum(MaxOutputKgH) RIÊNG,
    tính ĐỘC LẬP — không dùng chung mẫu số). Loại khác 3 loại chính bị loại khỏi báo cáo."""
    group_by = group_by if group_by in {"date", "week", "month"} else "date"
    targets = get_targets()
    selected_capacities = _parse_capacities(capacities)
    selected_brand_programs = _parse_text_filter(brand_programs)
    all_rows = _performance_rows(selected_capacities, from_date, to_date)
    available_brand_programs = sorted({row["brand_program"] for row in all_rows if row["brand_program"]})

    brand_filter = set(selected_brand_programs) if selected_brand_programs else None
    rows = [
        row for row in all_rows
        if _normalize_main_fabric_type(row["fabric_type"]) is not None
        and (brand_filter is None or row["brand_program"] in brand_filter)
    ]
    if not rows:
        empty = _empty_pivot(group_by, targets)
        empty["available_brand_programs"] = available_brand_programs
        return empty

    # Mỗi loại vải chính có tử số/mẫu số RIÊNG — tính ĐỘC LẬP theo đúng công thức gốc
    # Sum(OutputKgH)/Sum(MaxOutputKgH), không dùng chung mẫu số như bản 1-đường-gộp cũ.
    periods_by_fabric: dict[str, dict[str, dict[str, Any]]] = {name: {} for name in MAIN_FABRIC_TYPES}
    period_labels: dict[str, str] = {}
    total_output_all = 0.0
    total_max_load_all = 0.0
    for row in rows:
        fabric_type = _normalize_main_fabric_type(row["fabric_type"])
        key, label = _period(row["production_date"], group_by)
        period_labels[key] = label
        period = periods_by_fabric[fabric_type].setdefault(key, {"output_kgh": 0.0, "max_load_kgh": 0.0})
        output_kgh = float(row["output_kgh"] or 0)
        max_load_kgh = float(row["output_max_load_kgh"] or 0)
        period["output_kgh"] += output_kgh
        period["max_load_kgh"] += max_load_kgh
        total_output_all += output_kgh
        total_max_load_all += max_load_kgh

    ordered_keys = sorted(period_labels.keys())
    labels = [period_labels[key] for key in ordered_keys]

    rows_out: list[dict[str, Any]] = []
    for name in MAIN_FABRIC_TYPES:
        periods = periods_by_fabric[name]
        values = [
            round(periods[key]["output_kgh"] / periods[key]["max_load_kgh"] * 100, 1) if periods.get(key) and periods[key]["max_load_kgh"] else 0.0
            for key in ordered_keys
        ]
        total_output = sum(period["output_kgh"] for period in periods.values())
        total_max_load = sum(period["max_load_kgh"] for period in periods.values())
        total_value = round(total_output / total_max_load * 100, 1) if total_max_load else 0.0
        rows_out.append({"fabric_type": name, "target": targets.get(name), "values": values, "total": total_value})

    overall_pct = round(total_output_all / total_max_load_all * 100, 1) if total_max_load_all else 0.0

    return {
        "filters": {
            "capacities": selected_capacities or "all",
            "brand_programs": selected_brand_programs or "all", "from_date": from_date, "to_date": to_date, "group_by": group_by,
        },
        "periods": labels, "period_keys": ordered_keys,
        "rows": rows_out,
        "chart": {"categories": labels, "series": [{"name": row["fabric_type"], "data": row["values"]} for row in rows_out]},
        "kpis": {
            "tank_loading_pct": overall_pct,
            "total_output_kgh": round(total_output_all, 1),
            "total_max_load_kgh": round(total_max_load_all, 1),
        },
        "available_brand_programs": available_brand_programs,
    }
