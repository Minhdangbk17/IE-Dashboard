from __future__ import annotations

import io
from datetime import date, datetime, timedelta
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from core.batch_details_match import batch_details_join_sql
from core.batch_source import load_resolved_batches
from core.brand_program_importer import ensure_brand_program_table
from core.database import execute_query, get_db, get_dialect, sql_datetime
from core.production_time import get_production_date, normalize_production_date, production_bounds, production_date_sql_expr
from modules.dyeing.engines.reports.cleaning_matrix import UNCLASSIFIED_TANK_LABEL, classify_batch_badge

from .batch_day_trend import _TANK_ORDER, _brand_program_label, get_batch_day_trend, _is_normal_batch, _machine_capacities, _machine_tank_labels, _period


def _parse_text_filter(value: str | list[str] | None) -> list[str]:
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

_INVALID_FABRIC_TYPES = {"", "unknow", "unknown"}
UNCLASSIFIED_COLOR_GROUP = "Unclassified"


def _ensure_targets_table(conn: Any) -> None:
    if get_dialect() == "sqlite":
        conn.execute("""
            CREATE TABLE IF NOT EXISTS batch_matrix_targets (
                fabric_type TEXT NOT NULL,
                color_group TEXT NOT NULL,
                target_value REAL NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (fabric_type, color_group)
            )
        """)
    conn.commit()


def _ensure_summary_table(conn: Any) -> None:
    if get_dialect() == "sqlite":
        existing_columns = {row["name"] for row in conn.execute("PRAGMA table_info(batch_matrix_daily_summary)")}
        if existing_columns and "operating_hours" not in existing_columns:
            conn.execute("DROP TABLE batch_matrix_daily_summary")
        conn.execute("DROP TABLE IF EXISTS batch_matrix_capacity_hours_daily")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS batch_matrix_daily_summary (
                production_date TEXT NOT NULL,
                fabric_type TEXT NOT NULL,
                color_group TEXT NOT NULL,
                capacity_kg REAL NOT NULL,
                batch_count INTEGER NOT NULL DEFAULT 0,
                operating_hours REAL NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (production_date, fabric_type, color_group, capacity_kg)
            )
        """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_batch_matrix_daily_summary_date ON batch_matrix_daily_summary (production_date)")


def _operating_hours_by_machine_for_window(rows: Any, window_start_dt: datetime, window_end_dt: datetime) -> dict[str, float]:
    hours_by_machine: dict[str, float] = {}
    for row in rows:
        machine = (row["machine"] or "").strip()
        if not machine:
            continue
        try:
            start_dt = datetime.strptime(row["start_time"], "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            continue
        end_raw = row["end_time"] or row["start_time"]
        try:
            end_dt = datetime.strptime(end_raw, "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            end_dt = start_dt
        overlap_start = max(start_dt, window_start_dt)
        overlap_end = min(end_dt, window_end_dt)
        overlap_hours = (overlap_end - overlap_start).total_seconds() / 3600.0
        if overlap_hours <= 0:
            continue
        hours_by_machine[machine] = hours_by_machine.get(machine, 0.0) + overlap_hours
    return hours_by_machine


def _compute_operating_hours_by_machine(conn: Any, production_date: date) -> dict[str, float]:
    day_str = production_date.isoformat()
    window_start, window_end = production_bounds(day_str, day_str)
    rows = conn.execute(
        f"""
        SELECT machine, start_time, end_time
        FROM availability_logs
        WHERE machine IS NOT NULL AND machine != ''
          AND start_time IS NOT NULL AND start_time != ''
          AND {sql_datetime("COALESCE(end_time, start_time)")} > {sql_datetime("?")}
          AND {sql_datetime("start_time")} < {sql_datetime("?")}
        """,
        (window_start, window_end),
    ).fetchall()
    if not rows:
        return {}
    window_start_dt = datetime.strptime(window_start, "%Y-%m-%d %H:%M:%S")
    window_end_dt = datetime.strptime(window_end, "%Y-%m-%d %H:%M:%S")
    return _operating_hours_by_machine_for_window(rows, window_start_dt, window_end_dt)


def _parse_capacities(capacities: str | list[str] | None) -> list[float]:
    if not capacities:
        return []
    values = capacities if isinstance(capacities, list) else str(capacities).split(",")
    parsed: list[float] = []
    for value in values:
        text = str(value).strip()
        if not text:
            continue
        try:
            parsed.append(float(text))
        except ValueError:
            continue
    return parsed


_DARK_KEYWORDS: tuple[str, ...] = ("DARK", "DK ", "NAVY", "CHARCOAL")
_LIGHT_KEYWORDS: tuple[str, ...] = ("LIGHT", "LT ", "CREAM", "IVORY")


def _excel_number(text: str) -> float | None:
    try:
        value = float(text)
    except ValueError:
        return None
    return value if value == value and value not in (float("inf"), float("-inf")) else None


def _excel_trim(text: str) -> str:
    return " ".join(part for part in text.split(" ") if part)


def _color_from_pantone(colour_no: str) -> str | None:
    if len(colour_no) >= 7 and _excel_number(colour_no[:3]) is not None and colour_no[3] == "-" and colour_no[6] == "-":
        lightness = _excel_number(colour_no[4:6])
        if lightness is not None:
            return "Dark" if lightness <= 30 else "Medium" if lightness <= 50 else "Light"
    tcx_pos = colour_no.upper().find("TCX")
    if tcx_pos > 0:
        code = _excel_trim(colour_no[:tcx_pos])[-7:]
        if len(code) >= 3 and code[2] == "-":
            depth = _excel_number(code[:2])
            if depth is not None:
                return "Dark" if depth >= 19 else "Light"
    return None


def _shade_by_colour(batches: list[dict[str, Any]]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for batch in batches:
        shade = str(batch["shade"] or "").strip()
        if shade:
            lookup[str(batch["colour_no"] or "").upper()] = shade
    return lookup


def _classify_color_group(colour_no: Any, shade: Any, shade_by_colour: dict[str, str]) -> str:
    colour = str(colour_no or "")
    colour_upper = colour.upper()
    if "BLACK" in colour_upper:
        return "Black"
    if "WHITE" in colour_upper:
        return "White"
    shade_text = _excel_trim(str(shade or ""))
    if shade_text:
        return shade_text.title()
    if not _excel_trim(colour):
        return UNCLASSIFIED_COLOR_GROUP
    borrowed = shade_by_colour.get(colour_upper)
    if borrowed:
        return _excel_trim(borrowed).title()
    from_code = _color_from_pantone(colour)
    if from_code:
        return from_code
    if any(keyword in colour_upper for keyword in _DARK_KEYWORDS):
        return "Dark"
    if any(keyword in colour_upper for keyword in _LIGHT_KEYWORDS):
        return "Light"
    return UNCLASSIFIED_COLOR_GROUP


def get_targets() -> list[dict[str, Any]]:
    conn = get_db()
    _ensure_targets_table(conn)
    rows = execute_query("SELECT fabric_type, color_group, target_value FROM batch_matrix_targets ORDER BY fabric_type, color_group")
    return [dict(row) for row in rows]


def set_target(fabric_type: str, color_group: str, target_value: float | None) -> None:
    conn = get_db()
    _ensure_targets_table(conn)
    if target_value is None:
        conn.execute("DELETE FROM batch_matrix_targets WHERE fabric_type = ? AND color_group = ?", (fabric_type, color_group))
        conn.commit()
        return
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT INTO batch_matrix_targets (fabric_type, color_group, target_value, updated_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(fabric_type, color_group) DO UPDATE SET target_value=excluded.target_value, updated_at=excluded.updated_at",
        (fabric_type, color_group, target_value, now_str),
    )
    conn.commit()


SHADE_CHOICES: tuple[str, ...] = ("Black", "Dark", "Medium", "Light", "White")


def _ensure_shade_overrides_table(conn: Any) -> None:
    if get_dialect() == "sqlite":
        conn.execute("""
            CREATE TABLE IF NOT EXISTS batch_shade_overrides (
                dyelot TEXT PRIMARY KEY,
                shade TEXT NOT NULL,
                updated_by TEXT,
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
    conn.commit()


def _load_shade_overrides(conn: Any) -> dict[str, str]:
    _ensure_shade_overrides_table(conn)
    return {str(row["dyelot"]).strip(): row["shade"] for row in conn.execute("SELECT dyelot, shade FROM batch_shade_overrides").fetchall()}


def set_shade_override(dyelot: str, shade: str | None, updated_by: str | None = None) -> None:
    dyelot = dyelot.strip()
    if not dyelot:
        raise ValueError("Missing dyelot.")
    shade = (shade or "").strip()
    if shade and shade not in SHADE_CHOICES:
        raise ValueError(f"Shade must be one of: {', '.join(SHADE_CHOICES)}.")
    conn = get_db()
    _ensure_shade_overrides_table(conn)
    if not shade:
        conn.execute("DELETE FROM batch_shade_overrides WHERE dyelot = ?", (dyelot,))
    else:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "INSERT INTO batch_shade_overrides (dyelot, shade, updated_by, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(dyelot) DO UPDATE SET shade=excluded.shade, updated_by=excluded.updated_by, updated_at=excluded.updated_at",
            (dyelot, shade, updated_by, now_str),
        )
    conn.commit()


def recompute_daily(production_date: date, conn: Any) -> None:
    _ensure_summary_table(conn)
    day_str = production_date.isoformat()
    conn.execute("DELETE FROM batch_matrix_daily_summary WHERE production_date = ?", (day_str,))

    shifted_date = production_date_sql_expr("a.end_time")
    sql = f"""
        SELECT a.fabric_type, a.machine, a.capacity_kg, b.shade, b.colour_no
        FROM availability_logs a
        {batch_details_join_sql("a.batch", "a.end_time")}
        WHERE a.end_time IS NOT NULL AND a.end_time != ''
          AND a.fabric_type IS NOT NULL AND lower(trim(a.fabric_type)) NOT IN (?, ?, ?)
          AND (b.batch_type IS NULL OR lower(trim(b.batch_type)) = 'normal')
          AND {shifted_date} = ?
    """
    rows = conn.execute(sql, [*_INVALID_FABRIC_TYPES, day_str]).fetchall()
    if not rows:
        return

    buckets: dict[tuple[str, str, float], dict[str, Any]] = {}
    for row in rows:
        fabric_type = row["fabric_type"].strip()
        color_group = _classify_color_group(row["colour_no"], row["shade"], {})
        capacity = round(float(row["capacity_kg"] or 0), 2)
        key = (fabric_type, color_group, capacity)
        bucket = buckets.setdefault(key, {"count": 0, "machines": set()})
        bucket["count"] += 1
        machine = (row["machine"] or "").strip()
        if machine:
            bucket["machines"].add(machine)

    hours_by_machine = _compute_operating_hours_by_machine(conn, production_date)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.executemany(
        "INSERT INTO batch_matrix_daily_summary (production_date, fabric_type, color_group, capacity_kg, batch_count, operating_hours, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (
                day_str, fabric_type, color_group, capacity, bucket["count"],
                sum(hours_by_machine.get(m, 0.0) for m in bucket["machines"]), now_str,
            )
            for (fabric_type, color_group, capacity), bucket in buckets.items()
        ],
    )


def _assign_color_groups(batches: list[dict[str, Any]], shade_overrides: dict[str, str]) -> None:
    shade_by_colour = _shade_by_colour(batches)
    by_machine: dict[str, list[dict[str, Any]]] = {}
    for batch in batches:
        override = shade_overrides.get(str(batch["dyelot"]).strip())
        batch["_shade_override"] = override
        batch["_is_cm"] = classify_batch_badge(batch) == "CM"
        batch["_color_group"] = override or _classify_color_group(batch["colour_no"], batch["shade"], shade_by_colour)
        by_machine.setdefault(batch["machine"], []).append(batch)
    for machine_batches in by_machine.values():
        machine_batches.sort(key=lambda b: b["_start_dt"])
        next_color = UNCLASSIFIED_COLOR_GROUP
        for batch in reversed(machine_batches):
            if batch["_is_cm"] and not batch["_shade_override"]:
                batch["_color_group"] = next_color
            elif batch["_color_group"] in SHADE_CHOICES:
                next_color = batch["_color_group"]


def _load_matrix_source(
    date_from: str | None, date_to: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    conn = get_db()
    batches = load_resolved_batches(conn)
    _assign_color_groups(batches, _load_shade_overrides(conn))
    rows: list[dict[str, Any]] = []
    segments: list[dict[str, Any]] = []
    for batch in batches:
        if not batch["_segments"]:
            continue
        machine = batch["machine"]
        brand_program = _brand_program_label(batch)
        for seg_day, seg_hours in batch["_segments"]:
            seg_day_str = seg_day.isoformat()
            if (date_from and seg_day_str < date_from) or (date_to and seg_day_str > date_to):
                continue
            segments.append({
                "day": seg_day_str, "fabric_type": batch["fabric_type"], "color_group": batch["_color_group"],
                "machine": machine, "brand_program": brand_program, "hours": seg_hours,
            })
        day = batch["_segments"][-1][0].isoformat()
        if (date_from and day < date_from) or (date_to and day > date_to):
            continue
        if not _is_normal_batch(batch):
            continue
        override = batch["_shade_override"]
        shade = override or batch["shade"]
        rows.append({
            "day": day,
            "fabric_type": batch["fabric_type"],
            "color_group": batch["_color_group"],
            "shade_override": override,
            "capacity": None,
            "machine": machine,
            "brand_program": brand_program,
            "batch_no": batch["dyelot"],
            "dyelot": batch["dyelot"], "sap_lot": batch["sap_lot"], "redye": batch["redye"],
            "shade": shade, "colour_no": batch["colour_no"],
            "start_time": batch["start_time"], "end_time": batch["end_time"],
        })
    return rows, segments


def _empty_result(date_from: str | None = None, date_to: str | None = None, group_by: str = "date", error: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "date_from": date_from, "date_to": date_to, "group_by": group_by,
        "periods": [], "period_keys": [], "day_count": 0,
        "available_capacities": [], "available_brand_programs": [], "available_tank_types": [],
        "rows": [], "grand_total": None,
    }
    if error:
        result["error"] = error
    return result


def _build_core(
    date_from: str | None, date_to: str | None, capacities: str | list[str] | None,
    brand_programs: str | list[str] | None, tank_types: str | list[str] | None,
    group_by: str,
) -> dict[str, Any] | None:
    conn = get_db()
    ensure_brand_program_table(conn)
    raw_rows, raw_segments = _load_matrix_source(date_from, date_to)
    if not raw_rows:
        return None
    tank_by_machine = _machine_tank_labels(conn)
    capacity_by_machine = _machine_capacities(conn)
    for row in (*raw_rows, *raw_segments):
        code = row["machine"].lower()
        row["tank"] = tank_by_machine.get(code, UNCLASSIFIED_TANK_LABEL)
        row["capacity"] = capacity_by_machine.get(code)

    selected_capacities = _parse_capacities(capacities)
    capacity_filter = {round(value, 2) for value in selected_capacities} if selected_capacities else None
    selected_brand_programs = _parse_text_filter(brand_programs)
    brand_program_filter = set(selected_brand_programs) if selected_brand_programs else None
    selected_tank_types = [value for value in _parse_text_filter(tank_types) if value in _TANK_ORDER]
    tank_filter = set(selected_tank_types) if selected_tank_types else None

    def passes(row: dict[str, Any]) -> bool:
        return (
            (capacity_filter is None or row["capacity"] in capacity_filter)
            and (brand_program_filter is None or row["brand_program"] in brand_program_filter)
            and (tank_filter is None or row["tank"] in tank_filter)
        )

    rows = [row for row in raw_rows if passes(row)]
    segments = [segment for segment in raw_segments if passes(segment)]

    all_days = sorted({row["day"] for row in (*raw_rows, *raw_segments)})
    start_day = datetime.strptime(date_from or all_days[0], "%Y-%m-%d").date()
    end_day = datetime.strptime(date_to or all_days[-1], "%Y-%m-%d").date()
    if end_day < start_day:
        start_day, end_day = end_day, start_day
    days: list[str] = []
    period_of_day: dict[str, str] = {}
    period_labels: dict[str, str] = {}
    current = start_day
    while current <= end_day:
        key, label = _period(current, group_by)
        days.append(current.isoformat())
        period_of_day[current.isoformat()] = key
        period_labels[key] = label
        current += timedelta(days=1)
    for row in (*rows, *segments):
        row["period_key"] = period_of_day.get(row["day"])
    period_keys = sorted(period_labels)
    return {
        "rows": [row for row in rows if row["period_key"] is not None],
        "segments": [segment for segment in segments if segment["period_key"] is not None],
        "days": days,
        "period_of_day": period_of_day,
        "period_keys": period_keys,
        "periods": [period_labels[key] for key in period_keys],
        "period_labels": period_labels,
        "available_capacities": sorted({row["capacity"] for row in raw_rows if row["capacity"] is not None}),
        "available_brand_programs": sorted({row["brand_program"] for row in raw_rows if row["brand_program"]}),
        "available_tank_types": [label for label in _TANK_ORDER if label in {row["tank"] for row in raw_rows}],
        "selected_capacities": selected_capacities,
        "selected_brand_programs": selected_brand_programs,
        "selected_tank_types": selected_tank_types,
    }


def build_matrix(
    date_from: str | None = None, date_to: str | None = None, capacities: str | list[str] | None = None,
    brand_programs: str | list[str] | None = None, tank_types: str | list[str] | None = None,
    group_by: str = "date",
) -> dict[str, Any]:
    conn = get_db()
    _ensure_targets_table(conn)
    group_by = group_by if group_by in {"date", "week", "month"} else "date"
    try:
        core = _build_core(date_from, date_to, capacities, brand_programs, tank_types, group_by)
    except Exception as exc:
        return _empty_result(date_from, date_to, group_by, error=str(exc))
    if core is None:
        return _empty_result(date_from, date_to, group_by)

    days, period_keys = core["days"], core["period_keys"]

    cell_count: dict[tuple[str, str], dict[str, int]] = {}
    cell_hours: dict[tuple[str, str], dict[str, float]] = {}
    fabric_count: dict[str, dict[str, int]] = {}
    fabric_hours: dict[str, dict[str, float]] = {}
    for row in core["rows"]:
        period_key, fabric_type = row["period_key"], row["fabric_type"]
        cell_bucket = cell_count.setdefault((fabric_type, row["color_group"]), {})
        cell_bucket[period_key] = cell_bucket.get(period_key, 0) + 1
        fabric_bucket = fabric_count.setdefault(fabric_type, {})
        fabric_bucket[period_key] = fabric_bucket.get(period_key, 0) + 1
    for segment in core["segments"]:
        period_key, fabric_type = segment["period_key"], segment["fabric_type"]
        hours_bucket = cell_hours.setdefault((fabric_type, segment["color_group"]), {})
        hours_bucket[period_key] = hours_bucket.get(period_key, 0.0) + segment["hours"]
        fabric_bucket_hours = fabric_hours.setdefault(fabric_type, {})
        fabric_bucket_hours[period_key] = fabric_bucket_hours.get(period_key, 0.0) + segment["hours"]

    def ratio(count_by_period: dict[str, int], hours_by_period: dict[str, float], period_key: str | None) -> float | None:
        selected = period_keys if period_key is None else [period_key]
        hours = sum(hours_by_period.get(key, 0.0) for key in selected)
        numerator = sum(count_by_period.get(key, 0) for key in selected)
        return round(numerator * 24 / hours, 2) if hours > 0 else None

    def values(count_by_period: dict[str, int], hours_by_period: dict[str, float]) -> dict[str, float | None]:
        return {key: ratio(count_by_period, hours_by_period, key) for key in period_keys}

    targets = {(row["fabric_type"], row["color_group"]): row["target_value"] for row in execute_query("SELECT fabric_type, color_group, target_value FROM batch_matrix_targets")}

    def color_group_sort_key(name: str) -> tuple[int, str]:
        return (1, name) if name == UNCLASSIFIED_COLOR_GROUP else (0, name)

    trend = get_batch_day_trend(
        capacities=capacities, brand_programs=brand_programs, tank_types=tank_types,
        from_date=date_from, to_date=date_to, group_by=group_by,
    )
    trend_total = trend["total_row"]
    trend_by_key = {
        key: value for key, value, hours in zip(trend["period_keys"], trend_total["values"], trend_total["hours"]) if hours
    }
    trend_fabric = {row["fabric_type"]: row for row in trend["rows"]}
    trend_fabric.update(trend["other_fabrics"])

    def trend_fabric_values(fabric_type: str) -> tuple[dict[str, float | None], float | None] | None:
        source = trend_fabric.get(fabric_type)
        if source is None:
            return None
        by_key = {key: value for key, value, hours in zip(trend["period_keys"], source["values"], source["hours"]) if hours}
        return {key: by_key.get(key) for key in period_keys}, (source["total"] if source.get("total_hours", 1) else None)

    rows: list[dict[str, Any]] = []
    for fabric_type in sorted(fabric_count):
        color_groups = sorted(
            {color_group for (ft, color_group) in (*cell_count, *cell_hours) if ft == fabric_type}, key=color_group_sort_key,
        )
        for color_group in color_groups:
            cell_key = (fabric_type, color_group)
            count_by_period, hours_by_period = cell_count.get(cell_key, {}), cell_hours.get(cell_key, {})
            rows.append({
                "row_type": "data", "fabric_type": fabric_type, "color_group": color_group,
                "target": targets.get(cell_key),
                "values": values(count_by_period, hours_by_period),
                "total": ratio(count_by_period, hours_by_period, None),
                "batch_count": sum(count_by_period.values()), "hours": round(sum(hours_by_period.values()), 4),
            })
        from_trend = trend_fabric_values(fabric_type)
        own_hours = fabric_hours.get(fabric_type, {})
        rows.append({
            "row_type": "fabric_total", "fabric_type": fabric_type, "color_group": None, "target": None,
            "values": from_trend[0] if from_trend else values(fabric_count[fabric_type], own_hours),
            "total": from_trend[1] if from_trend else ratio(fabric_count[fabric_type], own_hours, None),
            "batch_count": sum(fabric_count[fabric_type].values()), "hours": round(sum(own_hours.values()), 4),
        })
    grand_total = trend_total["total"] if trend_total["total_hours"] else None
    rows.append({
        "row_type": "grand_total", "fabric_type": None, "color_group": None, "target": None,
        "values": {key: trend_by_key.get(key) for key in period_keys}, "total": grand_total,
    })

    return {
        "date_from": date_from, "date_to": date_to, "group_by": group_by,
        "periods": core["periods"], "period_keys": period_keys, "day_count": len(days),
        "capacities": core["selected_capacities"], "available_capacities": core["available_capacities"],
        "brand_programs": core["selected_brand_programs"], "available_brand_programs": core["available_brand_programs"],
        "tank_types": core["selected_tank_types"], "available_tank_types": core["available_tank_types"],
        "rows": rows, "grand_total": grand_total,
    }


_BATCH_FIELDS: tuple[tuple[str, str], ...] = (
    ("day", "Production Date"), ("machine", "Machine"), ("capacity", "Capacity (Kg)"), ("tank", "Tank"),
    ("fabric_type", "Fabric Type"), ("color_group", "Color Group"), ("brand_program", "Brand Program"),
    ("batch_no", "Batch No"), ("dyelot", "Dyelot"), ("sap_lot", "SapLot"), ("redye", "ReDye"),
    ("shade", "Shade"), ("colour_no", "ColourNo"), ("start_time", "Start"), ("end_time", "End"),
)


def _public_batch(row: dict[str, Any]) -> dict[str, Any]:
    return {**{key: row[key] for key, _ in _BATCH_FIELDS}, "shade_override": row.get("shade_override")}


def get_cell_batches(
    fabric_type: str, color_group: str, period_key: str | None = None,
    date_from: str | None = None, date_to: str | None = None, capacities: str | list[str] | None = None,
    brand_programs: str | list[str] | None = None, tank_types: str | list[str] | None = None,
    group_by: str = "date",
) -> list[dict[str, Any]]:
    group_by = group_by if group_by in {"date", "week", "month"} else "date"
    core = _build_core(date_from, date_to, capacities, brand_programs, tank_types, group_by)
    if core is None:
        return []
    batches = [
        _public_batch(row) for row in core["rows"]
        if row["fabric_type"] == fabric_type and row["color_group"] == color_group
        and (not period_key or row["period_key"] == period_key)
    ]
    batches.sort(key=lambda b: (b["day"], str(b["machine"]).lower(), str(b["start_time"])))
    return batches


def export_matrix_excel(
    date_from: str | None = None, date_to: str | None = None, capacities: str | list[str] | None = None,
    brand_programs: str | list[str] | None = None, tank_types: str | list[str] | None = None,
    group_by: str = "date",
) -> bytes:
    group_by = group_by if group_by in {"date", "week", "month"} else "date"
    data = build_matrix(date_from, date_to, capacities, brand_programs, tank_types, group_by)
    core = _build_core(date_from, date_to, capacities, brand_programs, tank_types, group_by)
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="24292F", end_color="24292F", fill_type="solid")
    bold = Font(bold=True)

    def write_header(sheet: Any, headers: list[str]) -> None:
        for col, header in enumerate(headers, start=1):
            cell = sheet.cell(row=1, column=col, value=header)
            cell.font, cell.fill = header_font, header_fill
            sheet.column_dimensions[cell.column_letter].width = 14

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Matrix"
    write_header(sheet, ["Fabric Type", "Color Group", "Target", "Total", *data["periods"]])
    for row_idx, row in enumerate(data["rows"], start=2):
        if row["row_type"] == "data":
            label = (row["fabric_type"], row["color_group"])
        elif row["row_type"] == "fabric_total":
            label = (row["fabric_type"], f"Total ({row['fabric_type']})")
        else:
            label = ("Grand Total", None)
        values = [*label, row["target"], row["total"], *(row["values"].get(key) for key in data["period_keys"])]
        for col, value in enumerate(values, start=1):
            cell = sheet.cell(row=row_idx, column=col, value=value)
            if row["row_type"] != "data":
                cell.font = bold
    sheet.freeze_panes = "E2"

    batches_sheet = workbook.create_sheet("Batches")
    write_header(batches_sheet, [label for _, label in _BATCH_FIELDS])
    batches = sorted((_public_batch(row) for row in (core or {}).get("rows", [])), key=lambda b: (b["day"], str(b["machine"]).lower(), str(b["start_time"])))
    for row_idx, batch in enumerate(batches, start=2):
        for col, (key, _) in enumerate(_BATCH_FIELDS, start=1):
            batches_sheet.cell(row=row_idx, column=col, value=batch[key])
    batches_sheet.auto_filter.ref = f"A1:{batches_sheet.cell(row=1, column=len(_BATCH_FIELDS)).column_letter}{len(batches) + 1}"
    batches_sheet.freeze_panes = "A2"

    filters_sheet = workbook.create_sheet("Filters")
    write_header(filters_sheet, ["Filter", "Value"])
    filters_sheet.column_dimensions["B"].width = 40
    filters = [
        ("From Date", date_from or "All"), ("To Date", date_to or "All"),
        ("Group By", {"date": "Day", "week": "Week", "month": "Month"}[group_by]),
        ("Capacity (Kg)", ", ".join(str(value) for value in _parse_capacities(capacities)) or "All"),
        ("Brand Program", ", ".join(_parse_text_filter(brand_programs)) or "All"),
        ("Tank Type", ", ".join(_parse_text_filter(tank_types)) or "All"),
    ]
    for row_idx, (label, value) in enumerate(filters, start=2):
        filters_sheet.cell(row=row_idx, column=1, value=label)
        filters_sheet.cell(row=row_idx, column=2, value=value)

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
