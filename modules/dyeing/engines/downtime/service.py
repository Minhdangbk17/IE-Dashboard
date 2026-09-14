"""Truy vấn và tổng hợp báo cáo Downtime từ bảng ``availability_logs``.

Daily Rollup Pattern (xem `memory-bank/systemPatterns.md`): phần tốn kém nhất của
báo cáo này — cộng dồn giờ dừng máy theo 9 CATEGORY qua TOÀN BỘ dòng `availability_logs`
khớp bộ lọc — được tính TRƯỚC theo từng ngày và lưu vào `downtime_daily_summary`
(`recompute_daily()`, gọi từ `core/rollup.py` ngay sau mỗi lần import). Đọc báo cáo
(`get_downtime_pivot_data()`) chỉ SELECT từ bảng đã tổng hợp sẵn cho phần category-hours.

`planned_hours`/Achievement (SUM/COUNT cờ 0-1, cộng dồn tuyến tính an toàn qua nhiều
ngày) và `valid_batches` (COUNT DISTINCT batch — ĐÃ XÁC MINH KHÔNG an toàn khi cộng dồn
qua nhiều ngày: 290 mã batch trong dữ liệu thật xuất hiện ở >1 production_date, vd các
mẻ rửa máy "-WA" lặp lại nhiều ngày) vẫn dùng query nhẹ trực tiếp trên `availability_logs`
— đây là SQL aggregate đã rẻ sẵn (SUM/COUNT DISTINCT có index), không phải phần vòng lặp
Python 9-category từng gây chậm, và với `valid_batches` bắt buộc phải giữ trực tiếp để
không tính sai (không thể cộng dồn distinct-count theo ngày).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from core.database import DatabaseError, execute_query, get_db, get_dialect, sql_datetime
from core.production_time import normalize_production_date, production_date_sql_expr

CATEGORIES = (
    "Rework", "Color Adjustment", "Sample checking", "Fabric loading",
    "Fabric unloading", "Bleaching/Washing", "PH checking", "Chemical load", "Others",
)
CATEGORY_COLUMNS = {
    "Rework": ("rework_hour",),
    "Color Adjustment": ("adjust_color_hour",),
    "Sample checking": ("sample_checking_hour",),
    "Fabric loading": ("load_hour",),
    "Fabric unloading": ("unload_hour",),
    "Bleaching/Washing": ("bleaching_hour",),
    "PH checking": ("ph_checking_hour",),
    "Chemical load": ("wait_chemical_load_hour", "wait_color_load_hour"),
    "Others": (
        "wait_fabric_hour", "wait_water_hour", "wait_steam_hour", "cleaning_hour", "maintenance_hour", "others_hour", "no_order_hour",
    ),
}
ACHIEVEMENT_COLUMNS = {
    "Load": "ach_load", "Unload": "ach_unload", "Sample Check": "ach_sample_check",
    "pH Check": "ach_ph", "Chemical": "ach_chemical", "Color": "ach_color",
}
INVALID_FABRIC_TYPES = ("Unknow", "Unknown", "All", "")


def _ensure_targets_table(conn: Any) -> None:
    """CHỈ chạy CREATE TABLE ở SQLite — ở Postgres bảng đã có sẵn qua `supabase/schema.sql`
    (cùng pattern `batch_matrix/service.py::_ensure_targets_table()`)."""
    if get_dialect() == "sqlite":
        conn.execute("""
            CREATE TABLE IF NOT EXISTS downtime_targets (
                category TEXT PRIMARY KEY,
                target_pct REAL NOT NULL DEFAULT 0,
                target_hours REAL NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
    conn.commit()


def get_targets() -> list[dict[str, Any]]:
    conn = get_db()
    _ensure_targets_table(conn)
    rows = execute_query("SELECT category, target_pct, target_hours FROM downtime_targets ORDER BY category")
    return [dict(row) for row in rows]


def set_target(category: str, target_pct: float, target_hours: float) -> None:
    if category not in CATEGORIES:
        raise ValueError(f"Category không hợp lệ: {category!r}")
    conn = get_db()
    _ensure_targets_table(conn)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT INTO downtime_targets (category, target_pct, target_hours, updated_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(category) DO UPDATE SET target_pct=excluded.target_pct, target_hours=excluded.target_hours, updated_at=excluded.updated_at",
        (category, target_pct, target_hours, now_str),
    )
    conn.commit()


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _parse_capacities(capacities: str | list[str] | None) -> list[float]:
    """Parse capacities=25,50; ALL/empty means no capacity filter."""
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


def operational_bounds(from_date: str | None, to_date: str | None) -> tuple[str | None, str | None]:
    """Return the half-open operational-day window [07:00, next-day 07:00).

    Giữ hàm này (delegate sang `core/production_time.py::production_bounds`) để không
    phải sửa lại mọi nơi đã import `operational_bounds` từ module này (`batch_matrix`,
    `reports/cleaning_matrix`).
    """
    from core.production_time import production_bounds

    return production_bounds(from_date, to_date)


def _availability_columns() -> dict[str, str] | None:
    """Tìm tên cột không phân biệt hoa thường để tương thích file Excel."""
    try:
        rows = execute_query("PRAGMA table_info(availability_logs)")
    except DatabaseError:
        return None
    available = {str(row["name"]).strip().lower(): str(row["name"]) for row in rows}
    if not available:
        return None

    def find(*names: str) -> str | None:
        for name in names:
            if name.lower() in available:
                return available[name.lower()]
        return None

    resolved = {
        "date": find("production_date", "Production Date", "Date", "date"),
        "capacity": find("capacity_kg", "Capacity (Kg)", "Capacity"),
        "batch": find("batch", "Batch"),
        "fabric_type": find("fabric_type", "Fabric Type"),
        "planned": find("planned_prd_time_hour", "planned_prd_time", "Planned PRD time (hour)", "Planned PRD time"),
    }
    if not all(resolved.values()):
        return None
    for columns in CATEGORY_COLUMNS.values():
        if any(find(column) is None for column in columns):
            return None
    return {key: value for key, value in resolved.items() if value is not None} | {
        column: find(column) or column for columns in CATEGORY_COLUMNS.values() for column in columns
    }


def _parse_day(value: Any) -> date | None:
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d/%m/%Y", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(text[:19], fmt).date()
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


def _valid_fabric_type(value: Any) -> bool:
    normalized = str(value or "").strip().lower()
    return normalized not in {"", "unknown", "unknow", "all"}


def _empty_result(group_by: str) -> dict[str, Any]:
    rows = [{"category": category, "values": [], "values_hours": [], "total_pct": 0.0, "total_hours": 0.0} for category in CATEGORIES]
    datasets = {category: [] for category in CATEGORIES}
    datasets["Total Rate"] = []
    datasets_hours = {category: [] for category in CATEGORIES}
    datasets_hours["Total Rate"] = []
    return {
        "filters": {"capacity": None, "from_date": None, "to_date": None, "group_by": group_by},
        "periods": [], "period_keys": [], "time_labels": [], "rows": rows, "rows_hours": rows, "total_row": [], "total_row_hours": [], "chart": {"categories": [], "series": []},
        "labels": [], "datasets": datasets, "datasets_hours": datasets_hours,
        "kpis": {"planned_hours": 0.0, "downtime_hours": 0.0, "downtime_rate_pct": 0.0, "valid_batches": 0, "achievement_rate_pct": 0.0},
        "achievement": {"periods": [], "breakdown": [], "overall_rate_pct": 0.0},
    }


# ---------------------------------------------------------------------------
# Daily Rollup: recompute_daily() + đọc bảng summary
# ---------------------------------------------------------------------------


def _ensure_summary_table(conn: Any) -> None:
    """Tự tạo bảng nếu chưa có — CHỈ chạy DDL này ở SQLite (cú pháp `datetime('now')` là
    SQLite-only). Ở Postgres, bảng đã được tạo trước qua `supabase/schema.sql` (migration
    quản lý riêng, không lazy-create như SQLite) — chỉ cần đảm bảo index tồn tại, và
    `CREATE INDEX IF NOT EXISTS` hợp lệ ở cả 2 dialect."""
    if get_dialect() == "sqlite":
        conn.execute("""
            CREATE TABLE IF NOT EXISTS downtime_daily_summary (
                production_date TEXT NOT NULL,
                capacity_kg REAL NOT NULL,
                category TEXT NOT NULL,
                hours REAL NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (production_date, capacity_kg, category)
            )
        """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_downtime_daily_summary_date ON downtime_daily_summary (production_date)")


def recompute_daily(production_date: date, conn: Any) -> None:
    """Tính lại `downtime_daily_summary` cho ĐÚNG 1 production_date — idempotent
    (DELETE dòng cũ của ngày này rồi INSERT lại từ raw data)."""
    _ensure_summary_table(conn)
    day_str = production_date.isoformat()
    conn.execute("DELETE FROM downtime_daily_summary WHERE production_date = ?", (day_str,))

    columns = _availability_columns()
    if columns is None:
        return

    record_time = 'COALESCE("end_time", "start_time")'
    shifted_date = production_date_sql_expr(record_time)
    select_parts = [_quote(columns["capacity"]) + " AS capacity"]
    for category_columns in CATEGORY_COLUMNS.values():
        for column in category_columns:
            select_parts.append(_quote(columns[column]) + " AS " + _quote(column))
    sql = f"SELECT {', '.join(select_parts)} FROM availability_logs WHERE {shifted_date} = ?"
    rows = conn.execute(sql, (day_str,)).fetchall()
    if not rows:
        return

    totals: dict[tuple[float, str], float] = {}
    for row in rows:
        capacity = round(float(row["capacity"] or 0), 2)
        for category, category_columns in CATEGORY_COLUMNS.items():
            key = (capacity, category)
            totals[key] = totals.get(key, 0.0) + sum(float(row[column] or 0) for column in category_columns)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.executemany(
        "INSERT INTO downtime_daily_summary (production_date, capacity_kg, category, hours, updated_at) VALUES (?, ?, ?, ?, ?)",
        [(day_str, capacity, category, hours, now_str) for (capacity, category), hours in totals.items() if hours],
    )


def _hours_by_period_from_summary(
    selected_capacities: list[float], from_date: str | None, to_date: str | None,
) -> dict[str, dict[str, float]]:
    """{production_date: {category: hours}} từ bảng đã tổng hợp sẵn — KHÔNG quét raw data."""
    sql = "SELECT production_date, category, SUM(hours) AS hours FROM downtime_daily_summary WHERE 1=1"
    params: list[Any] = []
    if from_date:
        sql += " AND production_date >= ?"
        params.append(from_date)
    if to_date:
        sql += " AND production_date <= ?"
        params.append(to_date)
    if selected_capacities:
        placeholders = ", ".join("?" for _ in selected_capacities)
        sql += f" AND capacity_kg IN ({placeholders})"
        params.extend(selected_capacities)
    sql += " GROUP BY production_date, category"
    try:
        rows = execute_query(sql, params)
    except DatabaseError:
        return {}
    result: dict[str, dict[str, float]] = {}
    for row in rows:
        result.setdefault(row["production_date"], {})[row["category"]] = float(row["hours"] or 0)
    return result


def _daily_planned_and_achievement(
    columns: dict[str, str], selected_capacities: list[float], start_timestamp: str | None, end_timestamp: str | None,
) -> dict[str, dict[str, Any]]:
    """{production_date: {"planned": float, "achievement": {name: [evaluated, passed]}}}.

    SUM/COUNT cờ 0-1 cộng dồn tuyến tính AN TOÀN qua nhiều ngày — query nhẹ trực tiếp
    trên `availability_logs`, KHÔNG cần bảng rollup riêng (đã rẻ sẵn nhờ GROUP BY SQL).
    """
    record_time = 'COALESCE("end_time", "start_time")'
    shifted_date = production_date_sql_expr(record_time)
    achievement_select = ", ".join(
        f"SUM(CASE WHEN {_quote(field)} IS NOT NULL THEN 1 ELSE 0 END) AS evaluated_{index}, "
        f"SUM(COALESCE({_quote(field)}, 0)) AS passed_{index}"
        for index, field in enumerate(ACHIEVEMENT_COLUMNS.values())
    )
    sql = f"""
        SELECT {shifted_date} AS production_date, SUM({_quote(columns['planned'])}) AS planned, {achievement_select}
        FROM availability_logs WHERE 1=1
    """
    params: list[Any] = []
    if selected_capacities:
        placeholders = ", ".join("?" for _ in selected_capacities)
        sql += f" AND CAST({_quote(columns['capacity'])} AS REAL) IN ({placeholders})"
        params.extend(selected_capacities)
    if start_timestamp:
        sql += f" AND {sql_datetime(record_time)} >= {sql_datetime('?')}"
        params.append(start_timestamp)
    if end_timestamp:
        sql += f" AND {sql_datetime(record_time)} < {sql_datetime('?')}"
        params.append(end_timestamp)
    sql += f" GROUP BY {shifted_date}"
    try:
        rows = execute_query(sql, params)
    except DatabaseError:
        return {}
    names = list(ACHIEVEMENT_COLUMNS.keys())
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        achievement = {names[i]: [int(row[f"evaluated_{i}"] or 0), int(row[f"passed_{i}"] or 0)] for i in range(len(names))}
        result[normalize_production_date(row["production_date"])] = {"planned": float(row["planned"] or 0), "achievement": achievement}
    return result


def _daily_batches(
    columns: dict[str, str], selected_capacities: list[float], start_timestamp: str | None, end_timestamp: str | None,
) -> dict[str, set[str]]:
    """{production_date: {batch, ...}} — CHỈ lấy batch có FabricType hợp lệ, dùng để đếm
    DISTINCT theo từng kỳ (date/week/month) ở tầng Python. KHÔNG cộng dồn số lượng theo
    ngày (đã xác minh: 290 mã batch thật xuất hiện ở nhiều production_date khác nhau —
    cộng dồn distinct-count theo ngày sẽ đếm dư)."""
    record_time = 'COALESCE("end_time", "start_time")'
    shifted_date = production_date_sql_expr(record_time)
    sql = f"""
        SELECT DISTINCT {shifted_date} AS production_date, {_quote(columns['batch'])} AS batch
        FROM availability_logs
        WHERE {_quote(columns['batch'])} IS NOT NULL AND TRIM(CAST({_quote(columns['batch'])} AS TEXT)) <> ''
          AND {_quote(columns['fabric_type'])} IS NOT NULL
          AND LOWER(TRIM(CAST({_quote(columns['fabric_type'])} AS TEXT))) NOT IN (?, ?, ?, ?)
    """
    params: list[Any] = [value.lower() for value in INVALID_FABRIC_TYPES]
    if selected_capacities:
        placeholders = ", ".join("?" for _ in selected_capacities)
        sql += f" AND CAST({_quote(columns['capacity'])} AS REAL) IN ({placeholders})"
        params.extend(selected_capacities)
    if start_timestamp:
        sql += f" AND {sql_datetime(record_time)} >= {sql_datetime('?')}"
        params.append(start_timestamp)
    if end_timestamp:
        sql += f" AND {sql_datetime(record_time)} < {sql_datetime('?')}"
        params.append(end_timestamp)
    try:
        rows = execute_query(sql, params)
    except DatabaseError:
        return {}
    result: dict[str, set[str]] = {}
    for row in rows:
        result.setdefault(normalize_production_date(row["production_date"]), set()).add(str(row["batch"]).strip())
    return result


def get_downtime_pivot_data(
    capacity: str | None = None, from_date: str | None = None,
    to_date: str | None = None, group_by: str = "date",
    capacities: str | list[str] | None = None,
) -> dict[str, Any]:
    """Tính tỷ lệ Downtime theo nhóm, kỳ thời gian và bộ lọc đã chọn.

    Đọc `hours` theo CATEGORY từ `downtime_daily_summary` (Daily Rollup — xem module
    docstring); `planned`/achievement/valid_batches vẫn query nhẹ trực tiếp trên
    `availability_logs` (lý do: xem docstring đầu file)."""
    group_by = group_by if group_by in {"date", "week", "month"} else "date"
    columns = _availability_columns()
    if columns is None:
        return _empty_result(group_by)

    selected_capacities = _parse_capacities(capacities if capacities is not None else capacity)
    start_timestamp, end_timestamp = operational_bounds(from_date, to_date)

    hours_by_day = _hours_by_period_from_summary(selected_capacities, from_date, to_date)
    daily_extra = _daily_planned_and_achievement(columns, selected_capacities, start_timestamp, end_timestamp)
    daily_batches = _daily_batches(columns, selected_capacities, start_timestamp, end_timestamp)

    all_days = set(hours_by_day) | set(daily_extra) | set(daily_batches)
    if not all_days:
        return _empty_result(group_by)

    periods: dict[str, dict[str, Any]] = {}
    for day_str in all_days:
        day = _parse_day(day_str)
        if day is None:
            continue
        key, label = _period(day, group_by)
        period = periods.setdefault(key, {"label": label, "planned": 0.0, "categories": dict.fromkeys(CATEGORIES, 0.0), "achievement": {name: [0, 0] for name in ACHIEVEMENT_COLUMNS}, "valid_batches": set()})

        for category, hours in hours_by_day.get(day_str, {}).items():
            if category in period["categories"]:
                period["categories"][category] += hours

        extra = daily_extra.get(day_str)
        if extra:
            period["planned"] += extra["planned"]
            for name, (evaluated, passed) in extra["achievement"].items():
                period["achievement"][name][0] += evaluated
                period["achievement"][name][1] += passed

        period["valid_batches"] |= daily_batches.get(day_str, set())

    ordered = sorted(periods.items())
    period_keys = [key for key, _ in ordered]
    labels = [value["label"] for _, value in ordered]
    totals = {category: sum(value["categories"][category] for _, value in ordered) for category in CATEGORIES}
    planned_total = sum(value["planned"] for _, value in ordered)
    downtime_total = sum(totals.values())
    percentages = {
        category: [round(value["categories"][category] / value["planned"] * 100, 1) if value["planned"] else 0.0 for _, value in ordered]
        for category in CATEGORIES
    }
    total_rates = [round(sum(value["categories"].values()) / value["planned"] * 100, 1) if value["planned"] else 0.0 for _, value in ordered]
    category_hours = {category: [value["categories"][category] / len(value["valid_batches"]) if value["valid_batches"] else None for _, value in ordered] for category in CATEGORIES}
    total_hours = [sum(category_hours[category][index] or 0 for category in CATEGORIES) if any(category_hours[category][index] is not None for category in CATEGORIES) else None for index in range(len(ordered))]
    datasets = {category: percentages[category] for category in CATEGORIES}
    datasets["Total Rate"] = total_rates
    datasets_hours = {category: category_hours[category] for category in CATEGORIES}
    datasets_hours["Total Rate"] = total_hours
    targets_by_category = {row["category"]: row for row in get_targets()}
    rows = [
        {
            "category": category, "values": percentages[category], "values_hours": category_hours[category],
            "total_pct": round(totals[category] / planned_total * 100, 1) if planned_total else 0.0,
            "total_hours": sum(category_hours[category][index] or 0 for index in range(len(category_hours[category]))) if category_hours[category] else 0.0,
            "target_pct": targets_by_category.get(category, {}).get("target_pct"),
            "target_hours": targets_by_category.get(category, {}).get("target_hours"),
        }
        for category in CATEGORIES
    ]
    achievement_breakdown = []
    achievement_periods = [value["label"] for _, value in ordered]
    for name in ACHIEVEMENT_COLUMNS:
        evaluated = sum(value["achievement"][name][0] for _, value in ordered)
        passed = sum(value["achievement"][name][1] for _, value in ordered)
        achievement_breakdown.append({"stage": name, "values": [round(value["achievement"][name][1] / value["achievement"][name][0] * 100, 1) if value["achievement"][name][0] else None for _, value in ordered], "rate_pct": round(passed / evaluated * 100, 1) if evaluated else None})
    all_evaluated = sum(value["achievement"][name][0] for _, value in ordered for name in ACHIEVEMENT_COLUMNS)
    all_passed = sum(value["achievement"][name][1] for _, value in ordered for name in ACHIEVEMENT_COLUMNS)
    achievement_rate = round(all_passed / all_evaluated * 100, 1) if all_evaluated else 0.0
    valid_batches = get_daily_batch_count(capacity, from_date, to_date, capacities=selected_capacities)
    return {
        "filters": {"capacities": selected_capacities or "all", "from_date": from_date, "to_date": to_date, "group_by": group_by},
        "periods": labels, "period_keys": period_keys, "time_labels": labels, "rows": rows, "rows_hours": [{"category": category, "values": category_hours[category]} for category in CATEGORIES], "total_row": total_rates, "total_row_hours": total_hours,
        "chart": {"categories": labels, "series": [{"name": category, "data": percentages[category]} for category in CATEGORIES]},
        "labels": labels, "datasets": datasets, "datasets_hours": datasets_hours,
        "kpis": {"planned_hours": round(planned_total, 1), "downtime_hours": round(downtime_total, 1), "downtime_rate_pct": round(downtime_total / planned_total * 100, 1) if planned_total else 0.0, "valid_batches": valid_batches, "achievement_rate_pct": achievement_rate},
        "achievement": {"periods": achievement_periods, "breakdown": achievement_breakdown, "overall_rate_pct": achievement_rate},
    }


def get_daily_batch_count(capacity: str | None = None, from_date: str | None = None, to_date: str | None = None, capacities: str | list[str] | None = None) -> int:
    """Đếm Batch duy nhất, loại Fabric Type không hợp lệ."""
    columns = _availability_columns()
    if columns is None:
        return 0
    sql = "SELECT COUNT(DISTINCT " + _quote(columns["batch"]) + ") AS total FROM availability_logs WHERE " + _quote(columns["batch"]) + " IS NOT NULL AND TRIM(CAST(" + _quote(columns["batch"]) + " AS TEXT)) <> '' AND " + _quote(columns["fabric_type"]) + " IS NOT NULL AND LOWER(TRIM(CAST(" + _quote(columns["fabric_type"]) + " AS TEXT))) NOT IN (?, ?, ?, ?)"
    params: list[Any] = [value.lower() for value in INVALID_FABRIC_TYPES]
    selected_capacities = _parse_capacities(capacities if capacities is not None else capacity)
    if selected_capacities:
        placeholders = ", ".join("?" for _ in selected_capacities)
        sql += " AND CAST(" + _quote(columns["capacity"]) + f" AS REAL) IN ({placeholders})"
        params.extend(selected_capacities)
    start_timestamp, end_timestamp = operational_bounds(from_date, to_date)
    record_time = 'COALESCE("end_time", "start_time")'
    if start_timestamp:
        sql += " AND " + sql_datetime(record_time) + " >= " + sql_datetime("?")
        params.append(start_timestamp)
    if end_timestamp:
        sql += " AND " + sql_datetime(record_time) + " < " + sql_datetime("?")
        params.append(end_timestamp)
    try:
        row = execute_query(sql, params)
    except DatabaseError:
        return 0
    return int(row[0]["total"] or 0) if row else 0


# ---------------------------------------------------------------------------
# Drill-down: Top N batch có giờ Downtime CATEGORY lớn nhất trong 1 kỳ
# (double-check số liệu, tương tự day-batches của batch_matrix)
# ---------------------------------------------------------------------------


def _period_date_range(period: str, group_by: str) -> tuple[str | None, str | None]:
    """Quy đổi 1 nhãn kỳ (period, xem `_period()`) ngược lại thành khoảng
    [date_from, date_to] theo production_date — để truy vấn drill-down đúng đúng
    kỳ người dùng đã bấm trên bảng pivot (Day/Week/Month)."""
    if group_by == "week":
        try:
            year_str, week_str = period.split("-W")
            start = date.fromisocalendar(int(year_str), int(week_str), 1)
            end = date.fromisocalendar(int(year_str), int(week_str), 7)
        except (ValueError, IndexError):
            return None, None
        return start.isoformat(), end.isoformat()
    if group_by == "month":
        try:
            year_str, month_str = period.split("-")
            year, month = int(year_str), int(month_str)
        except (ValueError, IndexError):
            return None, None
        start = date(year, month, 1)
        end = date(year, month + 1, 1) - timedelta(days=1) if month < 12 else date(year, 12, 31)
        return start.isoformat(), end.isoformat()
    day = _parse_day(period)
    if day is None:
        return None, None
    return day.isoformat(), day.isoformat()


def get_top_batches_for_category(
    period: str, group_by: str, category: str, capacities: str | list[str] | None = None, limit: int = 10,
) -> list[dict[str, Any]]:
    """Top N mẻ (mặc định 10) có giờ Downtime CATEGORY lớn nhất trong 1 kỳ (Day/Week/Month),
    sắp xếp giảm dần — dùng để double-check khi bấm vào 1 ô số trên bảng pivot Downtime.
    Query TRỰC TIẾP `availability_logs` (không qua `downtime_daily_summary` — bảng đó chỉ
    lưu TỔNG giờ theo ngày/category, không giữ chi tiết từng mẻ) vì đây là truy vấn hẹp/hiếm,
    chỉ chạy khi bấm xem chi tiết — không phải đường đọc tần suất cao."""
    if category not in CATEGORY_COLUMNS:
        raise ValueError(f"Category không hợp lệ: {category}")
    columns = _availability_columns()
    if columns is None:
        return []
    date_from, date_to = _period_date_range(period, group_by)
    if date_from is None:
        return []

    start_timestamp, end_timestamp = operational_bounds(date_from, date_to)
    record_time = 'COALESCE("end_time", "start_time")'
    category_sum = " + ".join(f"COALESCE({_quote(columns[col])}, 0)" for col in CATEGORY_COLUMNS[category])
    sql = f"""
        SELECT "id" AS availability_log_id, {_quote(columns['batch'])} AS batch, "machine" AS machine,
               {_quote(columns['capacity'])} AS capacity_kg, "start_time" AS start_time, "end_time" AS end_time,
               ({category_sum}) AS category_hours
        FROM availability_logs
        WHERE 1=1
    """
    params: list[Any] = []
    selected_capacities = _parse_capacities(capacities)
    if selected_capacities:
        placeholders = ", ".join("?" for _ in selected_capacities)
        sql += f" AND CAST({_quote(columns['capacity'])} AS REAL) IN ({placeholders})"
        params.extend(selected_capacities)
    if start_timestamp:
        sql += f" AND {sql_datetime(record_time)} >= {sql_datetime('?')}"
        params.append(start_timestamp)
    if end_timestamp:
        sql += f" AND {sql_datetime(record_time)} < {sql_datetime('?')}"
        params.append(end_timestamp)
    sql += f" AND ({category_sum}) > 0 ORDER BY ({category_sum}) DESC LIMIT ?"
    params.append(limit)
    try:
        rows = execute_query(sql, params)
    except DatabaseError:
        return []
    result = [
        {
            "availability_log_id": row["availability_log_id"],
            "batch": row["batch"], "machine": row["machine"], "capacity_kg": row["capacity_kg"],
            "start_time": row["start_time"], "end_time": row["end_time"],
            "category_hours": round(float(row["category_hours"] or 0), 2),
        }
        for row in rows
    ]
    _attach_case_notes(result, context=category)
    return result


# ---------------------------------------------------------------------------
# Downtime Case Notes: annotation THỦ CÔNG riêng (Reason/Detail người dùng tự
# nhập cho 1 mẻ trong danh sách drill-down "Downtime by Category" VÀ "Data
# Quality") — KHÔNG ghi đè `availability_logs` gốc. Khoá theo `availability_logs.id`
# — danh sách drill-down lấy từ bảng này, KHÔNG phải `downtime_logs` (bảng đó
# chưa nối vào pipeline báo cáo thật).
#
# `context` (2026-09-12, thêm sau khi phát hiện bug thật): 1 mẻ (availability_log_id)
# có thể xuất hiện ở NHIỀU category khác nhau trong "Downtime by Category" (vd vừa có
# Rework vừa có Color Adjustment) HOẶC cả 2 field của "Data Quality" (loading/unloading)
# — bản đầu chỉ khoá theo `availability_log_id` nên 1 note bị DÙNG CHUNG nhầm cho MỌI
# category/field của mẻ đó (sửa note ở category này thì category khác của CÙNG mẻ cũng
# đổi theo). Khoá UNIQUE đổi thành (availability_log_id, context): context = tên category
# (`CATEGORIES`) khi ghi từ "Downtime by Category", hoặc "loading"/"unloading"
# (`ABNORMAL_POINT_FIELDS`) khi ghi từ "Data Quality" — 2 note của CÙNG 1 mẻ ở 2 ngữ
# cảnh khác nhau giờ độc lập hoàn toàn. Note CŨ (tạo trước khi có `context`) được giữ ở
# context='' và dùng làm FALLBACK hiển thị cho MỌI category/field CHƯA có note riêng của
# mẻ đó — không mất dữ liệu đã nhập, chỉ tách dần khi người dùng sửa lại theo từng
# category cụ thể (xem `_attach_case_notes()`).
# ---------------------------------------------------------------------------


def _ensure_case_notes_table(conn: Any) -> None:
    """Tự tạo bảng nếu chưa có — CHỈ chạy DDL này ở SQLite (`AUTOINCREMENT`/`datetime('now')`
    là cú pháp SQLite-only). Ở Postgres, bảng đã được tạo trước qua `supabase/schema.sql`
    (cột `context` + constraint mới áp qua `supabase/migrate_case_notes_context.sql` —
    KHÔNG lazy-migrate như SQLite vì app không có quyền ALTER TABLE trên Postgres theo
    quy ước dự án)."""
    if get_dialect() == "sqlite":
        conn.execute("""
            CREATE TABLE IF NOT EXISTS downtime_case_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                availability_log_id INTEGER NOT NULL REFERENCES availability_logs (id) ON DELETE CASCADE,
                context TEXT NOT NULL DEFAULT '',
                reason TEXT,
                detail TEXT,
                updated_by INTEGER NOT NULL REFERENCES users (id),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE (availability_log_id, context)
            )
        """)
        _migrate_case_notes_context_column(conn)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_downtime_case_notes_log ON downtime_case_notes (availability_log_id)")


def _migrate_case_notes_context_column(conn: Any) -> None:
    """Bổ sung cột `context` cho bảng SQLite ĐÃ TỒN TẠI TỪ TRƯỚC (tạo lúc `context` chưa
    có, `UNIQUE(availability_log_id)` cũ). SQLite không cho ALTER đổi UNIQUE constraint tại
    chỗ -> dựng lại bảng: đổi tên bảng cũ, tạo bảng mới đúng schema, copy dữ liệu cũ với
    context='' (coi là note "chung", vẫn hiển thị lại đúng nội dung qua fallback ở
    `_attach_case_notes()`), xoá bảng cũ. Idempotent: return ngay nếu bảng chưa tồn tại
    (lần tạo mới hoàn toàn, không có gì để migrate) hoặc đã có cột `context` rồi."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(downtime_case_notes)").fetchall()}
    if not columns or "context" in columns:
        return
    conn.execute("ALTER TABLE downtime_case_notes RENAME TO downtime_case_notes_pre_context")
    conn.execute("""
        CREATE TABLE downtime_case_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            availability_log_id INTEGER NOT NULL REFERENCES availability_logs (id) ON DELETE CASCADE,
            context TEXT NOT NULL DEFAULT '',
            reason TEXT,
            detail TEXT,
            updated_by INTEGER NOT NULL REFERENCES users (id),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE (availability_log_id, context)
        )
    """)
    conn.execute("""
        INSERT INTO downtime_case_notes (id, availability_log_id, context, reason, detail, updated_by, updated_at)
        SELECT id, availability_log_id, '', reason, detail, updated_by, updated_at FROM downtime_case_notes_pre_context
    """)
    conn.execute("DROP TABLE downtime_case_notes_pre_context")
    conn.commit()


def _attach_case_notes(batches: list[dict[str, Any]], context: str) -> None:
    """Ghép note (Reason/Detail thủ công + ai/lúc nào sửa lần cuối) từ `downtime_case_notes`
    vào TỪNG mẻ trong danh sách drill-down — 1 query cho CẢ danh sách (không N+1).
    `context` = category ("Downtime by Category") hoặc field ("Data Quality") ĐANG XEM —
    ưu tiên note ghi ĐÚNG context này; nếu mẻ chưa có note riêng cho context, fallback về
    note "chung" cũ (context='', tạo trước khi tách theo category) nếu có."""
    log_ids = [batch["availability_log_id"] for batch in batches if batch.get("availability_log_id") is not None]
    for batch in batches:
        batch["case_reason"] = None
        batch["case_detail"] = None
        batch["case_updated_by"] = None
        batch["case_updated_at"] = None
    if not log_ids:
        return
    conn = get_db()
    _ensure_case_notes_table(conn)
    placeholders = ", ".join("?" for _ in log_ids)
    sql = f"""
        SELECT n.availability_log_id, n.context, n.reason, n.detail, n.updated_at, u.username AS updated_by_username
        FROM downtime_case_notes n
        LEFT JOIN users u ON u.id = n.updated_by
        WHERE n.availability_log_id IN ({placeholders}) AND n.context IN (?, '')
    """
    try:
        rows = execute_query(sql, [*log_ids, context])
    except DatabaseError:
        return
    notes_by_log: dict[Any, Any] = {}
    for row in rows:
        log_id = row["availability_log_id"]
        # Note đúng context LUÔN thắng note "chung" (context=''), bất kể thứ tự trả về.
        if log_id not in notes_by_log or row["context"] == context:
            notes_by_log[log_id] = row
    for batch in batches:
        note = notes_by_log.get(batch.get("availability_log_id"))
        if note is None:
            continue
        batch["case_reason"] = note["reason"]
        batch["case_detail"] = note["detail"]
        batch["case_updated_by"] = note["updated_by_username"]
        batch["case_updated_at"] = note["updated_at"]


def upsert_case_note(availability_log_id: int, context: str, reason: str | None, detail: str | None, user_id: int) -> dict[str, Any]:
    """Lưu (UPSERT) Reason/Detail thủ công cho 1 mẻ TRONG ĐÚNG 1 context (category/field) —
    tối đa 1 note/(mẻ, context) (`UNIQUE(availability_log_id, context)`), sửa lại thì ghi
    đè CHÍNH dòng đó, KHÔNG lưu lịch sử nhiều phiên bản, KHÔNG ảnh hưởng note của context
    khác cho CÙNG mẻ. KHÔNG đụng `availability_logs` gốc."""
    conn = get_db()
    _ensure_case_notes_table(conn)
    exists = conn.execute("SELECT 1 FROM availability_logs WHERE id = ?", (availability_log_id,)).fetchone()
    if exists is None:
        raise ValueError(f"Không tìm thấy mẻ với availability_log_id={availability_log_id}")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """
        INSERT INTO downtime_case_notes (availability_log_id, context, reason, detail, updated_by, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(availability_log_id, context)
        DO UPDATE SET reason = excluded.reason, detail = excluded.detail,
                      updated_by = excluded.updated_by, updated_at = excluded.updated_at
        """,
        (availability_log_id, context, reason, detail, user_id, now_str),
    )
    conn.commit()
    row = conn.execute(
        """
        SELECT n.reason, n.detail, n.updated_at, u.username AS updated_by_username
        FROM downtime_case_notes n LEFT JOIN users u ON u.id = n.updated_by
        WHERE n.availability_log_id = ? AND n.context = ?
        """,
        (availability_log_id, context),
    ).fetchone()
    return {
        "availability_log_id": availability_log_id,
        "context": context,
        "reason": row["reason"] if row else reason,
        "detail": row["detail"] if row else detail,
        "updated_by": row["updated_by_username"] if row else None,
        "updated_at": row["updated_at"] if row else None,
    }


# ---------------------------------------------------------------------------
# Abnormal Point: bảng pivot đếm mẻ có giờ Loading/Unloading ghi nhận = 0 theo
# Day/Week/Month (cùng cấu trúc bảng "Downtime by category" — cột ngoài cùng là
# tên chỉ số Abnormal Point, cột bên phải là period theo group_by đang chọn).
# Loại các mẻ FabricType không hợp lệ (rỗng/"Unknow"/"Unknown"/"All", cùng
# `INVALID_FABRIC_TYPES` đã dùng cho `valid_batches`) — 1 mẻ có thể vừa
# Loading=0 vừa Unloading=0, 2 chỉ số KHÔNG loại trừ lẫn nhau.
# ---------------------------------------------------------------------------

ABNORMAL_POINT_FIELDS = {"loading": "load_hour", "unloading": "unload_hour"}
ABNORMAL_POINT_LABELS = {"loading": "Cases Loading = 0", "unloading": "Cases Unloading = 0"}


def _abnormal_point_filters(
    columns: dict[str, str], selected_capacities: list[float], start_timestamp: str | None, end_timestamp: str | None,
) -> tuple[str, list[Any]]:
    """SQL điều kiện dùng chung capacity + operational_bounds — ĐÚNG bộ lọc đang áp dụng
    trên trang Downtime (dùng chung `record_time` có alias `a.` vì hàm gọi có JOIN sang
    `batch_details`, bảng này cũng có cột `start_time`/`end_time`/`machine` trùng tên, nếu
    không alias sẽ bị SQLite báo lỗi ambiguous column)."""
    record_time = 'COALESCE(a."end_time", a."start_time")'
    clause = ""
    params: list[Any] = []
    if selected_capacities:
        placeholders = ", ".join("?" for _ in selected_capacities)
        clause += f" AND CAST(a.{_quote(columns['capacity'])} AS REAL) IN ({placeholders})"
        params.extend(selected_capacities)
    if start_timestamp:
        clause += f" AND {sql_datetime(record_time)} >= {sql_datetime('?')}"
        params.append(start_timestamp)
    if end_timestamp:
        clause += f" AND {sql_datetime(record_time)} < {sql_datetime('?')}"
        params.append(end_timestamp)
    return clause, params


def _abnormal_point_fabric_filter(fabric_col: str) -> tuple[str, list[Any]]:
    """Loại mẻ FabricType không hợp lệ — dùng CHUNG `INVALID_FABRIC_TYPES` đã áp dụng cho
    `valid_batches` (`_daily_batches()`/`get_daily_batch_count()`), theo yêu cầu người dùng
    2026-09-11 ("không tính các mẻ có fabric type = unknow")."""
    clause = f" AND a.{fabric_col} IS NOT NULL AND LOWER(TRIM(CAST(a.{fabric_col} AS TEXT))) NOT IN (?, ?, ?, ?)"
    return clause, [value.lower() for value in INVALID_FABRIC_TYPES]


def get_abnormal_point_pivot(
    capacities: str | list[str] | None = None, from_date: str | None = None, to_date: str | None = None, group_by: str = "date",
) -> dict[str, Any]:
    """Bảng Abnormal Point theo Day/Week/Month — CÙNG bộ lọc capacity/date range/group_by
    như bảng "Downtime by category". Query nhẹ trực tiếp `availability_logs`
    (SUM CASE WHEN = 0, cộng dồn tuyến tính an toàn — không phải COUNT DISTINCT nên không
    dính bài học rủi ro cộng trùng ở systemPatterns.md mục 6.2), group theo ngày ở SQL rồi
    gộp lại theo Day/Week/Month ở Python (cùng cách `_daily_planned_and_achievement()` làm).
    KHÔNG qua `downtime_daily_summary` — bảng rollup không lưu chi tiết = 0 theo mẻ."""
    group_by = group_by if group_by in {"date", "week", "month"} else "date"
    columns = _availability_columns()
    if columns is None:
        return {"periods": [], "period_keys": [], "rows": [], "total_row": []}
    selected_capacities = _parse_capacities(capacities)
    start_timestamp, end_timestamp = operational_bounds(from_date, to_date)
    filter_clause, filter_params = _abnormal_point_filters(columns, selected_capacities, start_timestamp, end_timestamp)
    fabric_col = _quote(columns["fabric_type"])
    fabric_clause, fabric_params = _abnormal_point_fabric_filter(fabric_col)
    record_time = 'COALESCE(a."end_time", a."start_time")'
    shifted_date = production_date_sql_expr(record_time)
    load_col = _quote(columns["load_hour"])
    unload_col = _quote(columns["unload_hour"])

    sql = f"""
        SELECT {shifted_date} AS production_date,
               SUM(CASE WHEN a.{load_col} = 0 THEN 1 ELSE 0 END) AS loading_zero,
               SUM(CASE WHEN a.{unload_col} = 0 THEN 1 ELSE 0 END) AS unloading_zero
        FROM availability_logs a
        WHERE 1=1{fabric_clause}{filter_clause}
        GROUP BY {shifted_date}
    """
    params = [*fabric_params, *filter_params]
    try:
        rows = execute_query(sql, params)
    except DatabaseError:
        return {"periods": [], "period_keys": [], "rows": [], "total_row": []}

    periods: dict[str, dict[str, Any]] = {}
    for row in rows:
        day = _parse_day(row["production_date"])
        if day is None:
            continue
        key, label = _period(day, group_by)
        period = periods.setdefault(key, {"label": label, "loading": 0, "unloading": 0})
        period["loading"] += int(row["loading_zero"] or 0)
        period["unloading"] += int(row["unloading_zero"] or 0)

    ordered = sorted(periods.items())
    labels = [value["label"] for _, value in ordered]
    period_keys = [key for key, _ in ordered]
    loading_values = [value["loading"] for _, value in ordered]
    unloading_values = [value["unloading"] for _, value in ordered]
    rows_out = [
        {"field": "loading", "label": ABNORMAL_POINT_LABELS["loading"], "values": loading_values, "total": sum(loading_values)},
        {"field": "unloading", "label": ABNORMAL_POINT_LABELS["unloading"], "values": unloading_values, "total": sum(unloading_values)},
    ]
    return {
        "periods": labels, "period_keys": period_keys, "rows": rows_out,
        "total_row": [loading_values[i] + unloading_values[i] for i in range(len(ordered))],
    }


def get_abnormal_point_batches(
    field: str, capacities: str | list[str] | None = None, from_date: str | None = None, to_date: str | None = None,
    period: str | None = None, group_by: str = "date", limit: int | None = None,
) -> list[dict[str, Any]]:
    """Danh sách mẻ có `load_hour`/`unload_hour` = 0 (drill-down khi bấm vào 1 ô trên bảng
    Data Quality) — `field` in {"loading", "unloading"}. Truyền `period` (+ `group_by`)
    để giới hạn đúng 1 cột (Day/Week/Month) đã bấm — quy đổi ngược nhãn kỳ sang khoảng ngày
    bằng `_period_date_range()` (dùng CHUNG với `get_top_batches_for_category()`); không
    truyền `period` thì áp dụng nguyên `from_date`/`to_date` (toàn bộ giai đoạn đang filter).
    Query TRỰC TIẾP `availability_logs` (cấp MẺ, không qua `downtime_daily_summary`) LEFT
    JOIN `batch_details` (khoá `lower(trim(batch)) = lower(trim(dyelot))`, cùng pattern đã
    dùng ở `batch_matrix/service.py::get_day_batches()`) để lấy thêm Customer/ColourNo khi
    có. Loại mẻ FabricType không hợp lệ — CÙNG điều kiện với `get_abnormal_point_pivot()`
    để con số trên bảng khớp CHÍNH XÁC số dòng trả về ở đây (đối chiếu tay được). KHÔNG
    giới hạn số dòng theo mặc định (`limit=None`) vì lý do tương tự. Reason/Detail ghép qua
    `_attach_case_notes()` — DÙNG CHUNG bảng `downtime_case_notes` với "Downtime by
    Category" (annotation thủ công theo `availability_log_id`, KHÔNG còn auto-match từ
    `downtime_logs` như bản đầu — xem systemPatterns.md mục 6.2)."""
    if field not in ABNORMAL_POINT_FIELDS:
        raise ValueError(f"field không hợp lệ: {field}")
    zero_column = ABNORMAL_POINT_FIELDS[field]
    columns = _availability_columns()
    if columns is None:
        return []
    if period:
        period_from, period_to = _period_date_range(period, group_by)
        if period_from is None:
            return []
        from_date, to_date = period_from, period_to
    selected_capacities = _parse_capacities(capacities)
    start_timestamp, end_timestamp = operational_bounds(from_date, to_date)
    filter_clause, filter_params = _abnormal_point_filters(columns, selected_capacities, start_timestamp, end_timestamp)
    record_time = 'COALESCE(a."end_time", a."start_time")'
    shifted_date = production_date_sql_expr(record_time)
    batch_col = _quote(columns["batch"])
    fabric_col = _quote(columns["fabric_type"])
    capacity_col = _quote(columns["capacity"])
    zero_col = _quote(columns[zero_column])
    load_col = _quote(columns["load_hour"])
    unload_col = _quote(columns["unload_hour"])
    fabric_clause, fabric_params = _abnormal_point_fabric_filter(fabric_col)

    sql = f"""
        SELECT a."id" AS availability_log_id, a.{batch_col} AS batch, a."batch_ref_no" AS batch_ref_no, a."machine" AS machine,
               a.{fabric_col} AS fabric_type, a.{capacity_col} AS capacity_kg,
               a."start_time" AS start_time, a."end_time" AS end_time,
               {shifted_date} AS production_date,
               a.{load_col} AS load_hour, a.{unload_col} AS unload_hour,
               b.customer AS customer, b.colour_no AS colour_no
        FROM availability_logs a
        LEFT JOIN batch_details b ON lower(trim(a.{batch_col})) = lower(trim(b.dyelot))
        WHERE a.{zero_col} = 0{fabric_clause}{filter_clause}
        ORDER BY {shifted_date} DESC, a."machine"
    """
    params = [*fabric_params, *filter_params]
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    try:
        rows = execute_query(sql, params)
    except DatabaseError:
        return []
    result = [
        {
            "availability_log_id": row["availability_log_id"],
            "batch": row["batch"], "batch_ref_no": row["batch_ref_no"], "machine": row["machine"],
            "fabric_type": row["fabric_type"], "capacity_kg": row["capacity_kg"],
            "production_date": normalize_production_date(row["production_date"]),
            "start_time": row["start_time"], "end_time": row["end_time"],
            "load_hour": row["load_hour"], "unload_hour": row["unload_hour"],
            "customer": row["customer"] or None, "colour_no": row["colour_no"] or None,
        }
        for row in rows
    ]
    _attach_case_notes(result, context=field)
    return result
