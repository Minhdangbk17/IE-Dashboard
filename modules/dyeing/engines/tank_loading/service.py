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

from core.database import DatabaseError, execute_query
from core.production_time import get_production_date


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
    từ EndTime (fallback StartTime) — query TRỰC TIẾP (chưa có Daily Rollup)."""
    sql = """
        SELECT machine, capacity, output_kgh, output_max_load_kgh, start_time, end_time
        FROM performance_logs
        WHERE start_time IS NOT NULL OR end_time IS NOT NULL
    """
    params: list[Any] = []
    if selected_capacities:
        placeholders = ", ".join("?" for _ in selected_capacities)
        sql += f" AND CAST(capacity AS REAL) IN ({placeholders})"
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


def _empty_pivot(group_by: str) -> dict[str, Any]:
    return {
        "filters": {"capacities": [], "from_date": None, "to_date": None, "group_by": group_by},
        "periods": [], "period_keys": [],
        "rows": [{"label": "Tank Loading %", "values": [], "total": 0.0}],
        "total_row": [],
        "chart": {"categories": [], "values": []},
        "kpis": {"tank_loading_pct": 0.0, "total_output_kgh": 0.0, "total_max_load_kgh": 0.0},
    }


def get_tank_loading_pivot_data(
    capacities: str | list[str] | None = None,
    from_date: str | None = None, to_date: str | None = None, group_by: str = "date",
) -> dict[str, Any]:
    """Bảng + biểu đồ %Tank Loading theo Day/Week/Month — 1 dòng duy nhất (không phân
    loại thêm chiều nào khác), cùng cấu trúc pivot 1-dòng đã dùng cho `rft` để frontend
    tái dùng được UI/JS pattern tương tự."""
    group_by = group_by if group_by in {"date", "week", "month"} else "date"
    selected_capacities = _parse_capacities(capacities)
    rows = _performance_rows(selected_capacities, from_date, to_date)
    if not rows:
        return _empty_pivot(group_by)

    periods: dict[str, dict[str, Any]] = {}
    total_output_kgh = 0.0
    total_max_load_kgh = 0.0
    for row in rows:
        key, label = _period(row["production_date"], group_by)
        period = periods.setdefault(key, {"label": label, "output_kgh": 0.0, "max_load_kgh": 0.0})
        output_kgh = float(row["output_kgh"] or 0)
        max_load_kgh = float(row["output_max_load_kgh"] or 0)
        period["output_kgh"] += output_kgh
        period["max_load_kgh"] += max_load_kgh
        total_output_kgh += output_kgh
        total_max_load_kgh += max_load_kgh

    ordered = sorted(periods.items())
    labels = [value["label"] for _, value in ordered]
    period_keys = [key for key, _ in ordered]
    values = [
        round(value["output_kgh"] / value["max_load_kgh"] * 100, 1) if value["max_load_kgh"] else 0.0
        for _, value in ordered
    ]
    tank_loading_pct = round(total_output_kgh / total_max_load_kgh * 100, 1) if total_max_load_kgh else 0.0

    return {
        "filters": {"capacities": selected_capacities or "all", "from_date": from_date, "to_date": to_date, "group_by": group_by},
        "periods": labels, "period_keys": period_keys,
        "rows": [{"label": "Tank Loading %", "values": values, "total": tank_loading_pct}],
        "total_row": values,
        "chart": {"categories": labels, "values": values},
        "kpis": {
            "tank_loading_pct": tank_loading_pct,
            "total_output_kgh": round(total_output_kgh, 1),
            "total_max_load_kgh": round(total_max_load_kgh, 1),
        },
    }
