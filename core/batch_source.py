from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from core.database import get_dialect
from core.production_time import PRODUCTION_SHIFT_START_HOUR, get_production_date

INVALID_FABRIC_TYPES = {"", "unknow", "unknown"}
UNKNOWN_FABRIC_TYPE = "Unknown"
MANUAL_OVERRIDE_TABLE = "batch_manual_overrides"
OVERRIDE_BATCH_TYPES = ("Normal", "Rework")
OVERRIDE_FABRIC_TYPES = ("Cotton", "CVC", "Polyester")
OVERRIDE_SHADES = ("Dark", "Medium", "Light", "Black", "White")
_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

_OPTIONAL_COLUMNS: tuple[tuple[str, str], ...] = (
    ("shade", "''"), ("colour_no", "''"), ("recipe_no", "''"), ("customer_color", "''"),
    ("batch_type", "''"), ("is_rework", "0"), ("run_time", "0"),
)


def parse_batch_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
    return None


def split_production_days(start: datetime, end: datetime) -> list[tuple[date, float]]:
    segments: list[tuple[date, float]] = []
    day = get_production_date(start)
    last_day = get_production_date(end)
    while day <= last_day:
        window_start = datetime(day.year, day.month, day.day, PRODUCTION_SHIFT_START_HOUR)
        window_end = window_start + timedelta(days=1)
        hours = (min(end, window_end) - max(start, window_start)).total_seconds() / 3600.0
        if hours > 0:
            segments.append((day, hours))
        day += timedelta(days=1)
    return segments


def ensure_manual_overrides_table(conn: Any) -> None:
    if get_dialect() != "sqlite":
        return
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {MANUAL_OVERRIDE_TABLE} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dyelot TEXT NOT NULL,
            machine TEXT NOT NULL,
            start_time TEXT NOT NULL,
            batch_type TEXT NOT NULL,
            fabric_type TEXT NOT NULL,
            shade TEXT NOT NULL,
            updated_by TEXT,
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE (dyelot, machine, start_time)
        )
        """
    )
    conn.commit()


def override_key(dyelot: Any, machine: Any, start_dt: datetime) -> tuple[str, str, str]:
    return (str(dyelot or "").strip().lower(), str(machine or "").strip().lower(), start_dt.strftime(_TIME_FORMAT))


def _load_overrides(conn: Any) -> dict[tuple[str, str, str], dict[str, Any]]:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({MANUAL_OVERRIDE_TABLE})").fetchall()}
    if not columns:
        return {}
    overrides: dict[tuple[str, str, str], dict[str, Any]] = {}
    for raw in conn.execute(
        f"SELECT id, dyelot, machine, start_time, batch_type, fabric_type, shade FROM {MANUAL_OVERRIDE_TABLE}"
    ).fetchall():
        row = dict(raw)
        start_dt = parse_batch_datetime(row["start_time"])
        if start_dt is not None:
            overrides[override_key(row["dyelot"], row["machine"], start_dt)] = row
    return overrides


def load_resolved_batches(conn: Any) -> list[dict[str, Any]]:
    ensure_manual_overrides_table(conn)
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(batch_details)").fetchall()}
    optional_columns = ", ".join(
        f"b.{name}" if name in existing else f"{default} AS {name}"
        for name, default in _OPTIONAL_COLUMNS
    )
    rows = conn.execute(
        f"""
        SELECT b.id, b.dyelot, b.sap_lot, b.redye, b.machine, b.fabric_type, b.start_time, b.end_time,
               {optional_columns},
               COALESCE(bpm.brand, '') AS brand, COALESCE(bpm.brand_program, '') AS brand_program
        FROM batch_details b
        LEFT JOIN brand_program_mapping bpm ON lower(trim(bpm.greige_code)) = lower(trim(b.greige_code))
        ORDER BY b.id
        """
    ).fetchall()
    overrides = _load_overrides(conn)

    batches: list[dict[str, Any]] = []
    last_machine = ""
    for raw in rows:
        row = dict(raw)
        machine = str(row["machine"] or "").strip() or last_machine
        last_machine = machine
        start_dt = parse_batch_datetime(row["start_time"])
        if not machine or start_dt is None:
            continue
        fabric = str(row["fabric_type"] or "").strip()
        override = overrides.get(override_key(row["dyelot"], machine, start_dt))
        row["_original_batch_type"] = row["batch_type"]
        row["_override_id"] = override["id"] if override else None
        if override:
            row["batch_type"] = override["batch_type"]
            row["shade"] = override["shade"]
            fabric = override["fabric_type"]
        row.update({
            "machine": machine,
            "fabric_type": "" if fabric.lower() in INVALID_FABRIC_TYPES else fabric,
            "_start_dt": start_dt,
            "_end_dt": parse_batch_datetime(row["end_time"]),
        })
        batches.append(row)

    by_machine: dict[str, list[dict[str, Any]]] = {}
    for batch in batches:
        by_machine.setdefault(batch["machine"], []).append(batch)
    for machine_batches in by_machine.values():
        machine_batches.sort(key=lambda b: b["_start_dt"])
        next_fabric = UNKNOWN_FABRIC_TYPE
        for batch in reversed(machine_batches):
            if batch["fabric_type"]:
                next_fabric = batch["fabric_type"]
                batch["_fabric_filled"] = False
            else:
                batch["fabric_type"] = next_fabric
                batch["_fabric_filled"] = True

    for batch in batches:
        segments = split_production_days(batch["_start_dt"], batch["_end_dt"]) if batch["_end_dt"] else []
        batch["_segments"] = segments
        batch["production_date"] = segments[-1][0] if segments else get_production_date(batch["_start_dt"])
    return batches


def dates_affected_by_batch(batches: list[dict[str, Any]], batch_id: int) -> set[date]:
    target = next((batch for batch in batches if batch["id"] == batch_id), None)
    if target is None:
        return set()
    affected = {target["production_date"]}
    machine_batches = sorted((b for b in batches if b["machine"] == target["machine"]), key=lambda b: b["_start_dt"])
    index = next(i for i, b in enumerate(machine_batches) if b["id"] == batch_id)
    for previous in reversed(machine_batches[:index]):
        if not previous["_fabric_filled"]:
            break
        affected.add(previous["production_date"])
    return affected
