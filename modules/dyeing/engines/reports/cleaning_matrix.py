from __future__ import annotations

import calendar
import io
import logging
import re
from collections import Counter, defaultdict
from datetime import date, datetime
from typing import Any, Iterable, Mapping

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from core.batch_source import (
    MANUAL_OVERRIDE_TABLE, OVERRIDE_BATCH_TYPES, OVERRIDE_FABRIC_TYPES, OVERRIDE_SHADES, dates_affected_by_batch, load_resolved_batches,
)
from core.brand_program_importer import ensure_brand_program_table
from core.database import execute_query, get_db, get_dialect

FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "dyelot": ("Dyelot", "dyelot"),
    "batch_type": ("BatchType", "batch_type", "Batch_Type"),
    "shade": ("Shade", "shade"),
    "colour_no": ("ColourNo", "colour_no", "Color", "color", "CustomerColor"),
    "recipe_no": ("RecipeNo", "recipe_no"),
    "customer_color": ("CustomerColor", "customer_color"),
    "sap_lot": ("SapLot", "sap_lot"),
}

ALL_BADGE_CODES = ("CM", "S", "SC", "RD", "?", "B", "D", "M", "L", "W", "BR", "DR", "MR", "LR", "WR")
PENDING_BADGE = "?"
SCOURING_PATTERN = re.compile(r"(?<![A-Z0-9])DG\s*-?\s*01(?!\d)")

COLOR_LABEL_ORDER = ("Dark", "Light", "Medium", "Black", "White")
BADGE_TO_COLOR_LABEL: dict[str, str] = {"D": "Dark", "L": "Light", "M": "Medium", "B": "Black", "W": "White"}
FABRIC_GROUP_ORDER = ("Cotton", "CVC", "Polyester")

BADGE_FILL_COLORS: dict[str, tuple[str, str]] = {
    "CM": ("4B7931", "FFFFFF"), "S": ("8250DF", "FFFFFF"),
    "SC": ("0F8B8D", "FFFFFF"), "RD": ("6E7781", "FFFFFF"), "?": ("FFFFFF", "BF5B04"),
    "B": ("000000", "FFFFFF"), "BR": ("000000", "FFFFFF"),
    "D": ("5A738E", "FFFFFF"), "DR": ("5A738E", "FFFFFF"),
    "M": ("F6A97A", "000000"), "MR": ("F6A97A", "000000"),
    "L": ("FFF5CD", "000000"), "LR": ("FFF5CD", "000000"),
    "W": ("FFFFFF", "000000"), "WR": ("FFFFFF", "000000"),
}
REWORK_BORDER_COLOR = "FF0000"
WHITE_BADGE_BORDER_COLOR = "CCCCCC"
PENDING_BADGE_BORDER_COLOR = "BF5B04"

DARK_KEYWORDS = ("DARK", "DEEP", "NAVY", "MARINE", "CHARCOAL", "MAROON", "BURGUNDY", "EBONY", "MIDNIGHT", "INDIGO", "SHADOW", "GRAPHITE", "ESPRESSO", "COFFEE")
LIGHT_KEYWORDS = ("LIGHT", "PALE", "PASTEL", "CREAM", "IVORY", "BEIGE", "BLUSH", "PEACH", "MINT", "SKY", "BABY", "POWDER", "LILAC", "ROSE", "LEMON", "PINK", "PEARL", "ECRU", "BLANCH")

logger = logging.getLogger(__name__)


def _get_field(batch: Mapping[str, Any], name: str) -> str:
    for key in FIELD_ALIASES.get(name, (name,)):
        try:
            value = batch[key]
        except (KeyError, IndexError, TypeError):
            continue
        if value not in (None, ""):
            return str(value)
    return ""


def _is_sample_batch(dyelot: str | None, sap_lot: str | None) -> bool:
    dyelot_upper = (dyelot or "").strip().upper()
    sap_lot_norm = (sap_lot or "").strip()
    return dyelot_upper.endswith("DU") or dyelot_upper.endswith("KN") or sap_lot_norm.startswith("4")


def is_scouring(recipe_no: str | None) -> bool:
    text = str(recipe_no or "").upper()
    squeezed = text.replace(" ", "")
    return bool(SCOURING_PATTERN.search(text)) or "TLDT" in squeezed or "TINHLUYEN" in squeezed


def badge_group(badge: str) -> str:
    if badge in ("CM", "S", "SC", "RD"):
        return badge
    if badge == PENDING_BADGE:
        return "PENDING"
    return "REWORK" if badge.endswith("R") else "NORMAL"


def _base_color_code(batch: Mapping[str, Any]) -> str:
    text_check = f"{_get_field(batch, 'colour_no')} {_get_field(batch, 'recipe_no')} {_get_field(batch, 'customer_color')}".upper()
    shade = _get_field(batch, "shade").upper()
    if "BLACK" in text_check or "BLK" in text_check:
        return "B"
    if "WHITE" in text_check or "WHT" in text_check or "BLANCH" in text_check:
        return "W"
    if shade == "DARK":
        return "D"
    if shade == "MEDIUM":
        return "M"
    if shade == "LIGHT":
        return "L"
    if shade == "BLACK":
        return "B"
    if shade == "WHITE":
        return "W"
    if any(keyword in text_check for keyword in LIGHT_KEYWORDS):
        return "L"
    if any(keyword in text_check for keyword in DARK_KEYWORDS):
        return "D"
    return "M"


def classify_batch_badge(batch: Mapping[str, Any]) -> str:
    dyelot = _get_field(batch, "dyelot").upper()
    if dyelot.endswith("WA") or dyelot.startswith("CL"):
        return "CM"
    if _is_sample_batch(dyelot, _get_field(batch, "sap_lot")):
        return "S"
    if is_scouring(_get_field(batch, "recipe_no")):
        return "SC"
    batch_type = _get_field(batch, "batch_type").strip().lower()
    if batch_type == "redye":
        return "RD"
    if batch_type not in ("normal", "rework"):
        return PENDING_BADGE
    base = _base_color_code(batch)
    return base if batch_type == "normal" else f"{base}R"


def _ensure_batch_details_columns(conn: Any) -> None:
    if get_dialect() == "sqlite":
        conn.execute("""
            CREATE TABLE IF NOT EXISTS batch_details (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dyelot TEXT NOT NULL, shade TEXT, colour_no TEXT, batch_type TEXT, is_rework INTEGER DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
    batch_columns = {row["name"] for row in conn.execute("PRAGMA table_info(batch_details)")}
    for column, definition in (("colour_no", "TEXT"), ("is_rework", "INTEGER NOT NULL DEFAULT 0"), ("recipe_no", "TEXT"), ("customer_color", "TEXT"), ("sap_lot", "TEXT"), ("run_time", "REAL NOT NULL DEFAULT 0")):
        if column not in batch_columns:
            conn.execute(f"ALTER TABLE batch_details ADD COLUMN {column} {definition}")
    machine_columns = {row["name"] for row in conn.execute("PRAGMA table_info(machines)")}
    for column, definition in (("machine_code", "TEXT"), ("mc_brand", "TEXT"), ("tank_type", "TEXT"), ("mc_quantity", "INTEGER"), ("tube_no", "INTEGER"), ("capacity_kg", "REAL"), ("group_mc", "TEXT"), ("status", "TEXT"), ("production_status", "TEXT"), ("orgatex", "INTEGER NOT NULL DEFAULT 0")):
        if column not in machine_columns:
            conn.execute(f"ALTER TABLE machines ADD COLUMN {column} {definition}")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_batch_details_dyelot_norm ON batch_details (LOWER(TRIM(dyelot)))")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_batch_details_greige_code_norm ON batch_details (LOWER(TRIM(greige_code)))")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_machines_code_norm ON machines (LOWER(TRIM(COALESCE(machine_code, machine_id))))")
    conn.commit()


def _ensure_summary_table(conn: Any) -> None:
    if get_dialect() == "sqlite":
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cleaning_mc_daily_summary (
                production_date TEXT NOT NULL,
                availability_log_id INTEGER NOT NULL,
                machine TEXT NOT NULL,
                capacity_kg REAL NOT NULL DEFAULT 0,
                configured_capacity_kg REAL,
                machine_code TEXT,
                mc_brand TEXT,
                tank_type TEXT,
                mc_quantity INTEGER,
                tube_no TEXT,
                sequence_order TEXT,
                batch_no TEXT,
                dyelot_ref TEXT,
                shade_raw TEXT,
                colour_no TEXT,
                batch_type TEXT,
                start_time TEXT,
                end_time TEXT,
                program TEXT,
                brand_program TEXT,
                brand TEXT,
                fabric_type TEXT,
                badge TEXT NOT NULL,
                is_rework INTEGER NOT NULL DEFAULT 0,
                run_time REAL NOT NULL DEFAULT 0,
                sap_lot TEXT,
                redye REAL NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (production_date, availability_log_id)
            )
        """)
        existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(cleaning_mc_daily_summary)")}
        for column, definition in (("brand_program", "TEXT"), ("brand", "TEXT"), ("fabric_type", "TEXT"), ("run_time", "REAL NOT NULL DEFAULT 0"), ("sap_lot", "TEXT"), ("redye", "REAL NOT NULL DEFAULT 0")):
            if column not in existing_cols:
                conn.execute(f"ALTER TABLE cleaning_mc_daily_summary ADD COLUMN {column} {definition}")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cleaning_mc_daily_summary_date ON cleaning_mc_daily_summary (production_date)")


def _machine_master_by_code(conn: Any) -> dict[str, Mapping[str, Any]]:
    masters: dict[str, Mapping[str, Any]] = {}
    for row in conn.execute(
        "SELECT machine_id, machine_code, mc_brand, tank_type, mc_quantity, tube_no, capacity_kg FROM machines"
    ).fetchall():
        code = str(row["machine_code"] or row["machine_id"] or "").strip().lower()
        if code and code not in masters:
            masters[code] = row
    return masters


def recompute_daily(production_date: date, conn: Any) -> None:
    recompute_all([production_date], conn)


def recompute_all(dates: Iterable[date], conn: Any) -> None:
    _ensure_batch_details_columns(conn)
    _ensure_summary_table(conn)
    ensure_brand_program_table(conn)
    date_strs = {d.isoformat() for d in dates}
    if not date_strs:
        return

    masters = _machine_master_by_code(conn)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    inserts = []
    for batch in load_resolved_batches(conn):
        day_str = batch["production_date"].isoformat()
        if day_str not in date_strs:
            continue
        badge = classify_batch_badge({
            "dyelot": batch["dyelot"],
            "batch_type": batch["batch_type"],
            "shade": batch["shade"],
            "colour_no": batch["colour_no"],
            "recipe_no": batch["recipe_no"],
            "customer_color": batch["customer_color"],
            "sap_lot": batch["sap_lot"],
        })
        master = masters.get(batch["machine"].lower())
        configured_capacity = master["capacity_kg"] if master else None
        start_time = str(batch["start_time"] or "") or None
        end_time = str(batch["end_time"] or "") or None
        inserts.append((
            day_str, batch["id"], batch["machine"], float(configured_capacity or 0), configured_capacity,
            (master["machine_code"] if master else None) or batch["machine"],
            master["mc_brand"] if master else None, master["tank_type"] if master else None,
            master["mc_quantity"] if master else None, master["tube_no"] if master else None,
            start_time, batch["dyelot"], batch["dyelot"], batch["shade"] or "", batch["colour_no"] or "",
            batch["batch_type"] or "", start_time, end_time, None,
            str(batch["brand_program"] or ""), str(batch["brand"] or ""), batch["fabric_type"],
            badge, int(badge_group(badge) == "REWORK"), float(batch["run_time"] or 0), batch["sap_lot"] or "",
            float(batch["redye"] or 0), now_str,
        ))

    for day_str in date_strs:
        conn.execute("DELETE FROM cleaning_mc_daily_summary WHERE production_date = ?", (day_str,))
    if inserts:
        conn.executemany(
            """
            INSERT INTO cleaning_mc_daily_summary (
                production_date, availability_log_id, machine, capacity_kg, configured_capacity_kg,
                machine_code, mc_brand, tank_type, mc_quantity, tube_no,
                sequence_order, batch_no, dyelot_ref, shade_raw, colour_no, batch_type,
                start_time, end_time, program, brand_program, brand, fabric_type, badge, is_rework, run_time, sap_lot, redye, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            inserts,
        )


def _normalize_code(value: Any) -> str:
    return str(value or "").strip().lower()


def _blank_machine_item(machine_label: str, machine_code: str | None, master: Mapping[str, Any] | None) -> dict[str, Any]:
    return {
        "machine": machine_label,
        "machine_code": machine_code,
        "group_mc": ((master["group_mc"] if master else None) or "-"),
        "mc_brand": ((master["mc_brand"] if master else None) or "-"),
        "tank_type": ((master["tank_type"] if master else None) or "-"),
        "mc_quantity": ((master["mc_quantity"] if master else None) or 1),
        "tube_no": ((master["tube_no"] if master else None) or "-"),
        "capacity": (master["capacity_kg"] if master else None),
        "status": ((master["status"] if master else None) or "-"),
        "production_status": ((master["production_status"] if master else None) or "-"),
        "orgatex": bool(master["orgatex"]) if master and master["orgatex"] is not None else False,
        "is_unmapped": master is None,
        "cleaning_count": 0, "normal_batches": 0, "rd_batches": 0, "rework_batches": 0, "pending_batches": 0, "days": {}, "batches": [],
    }


def get_cleaning_matrix(
    from_date: str | None = None, to_date: str | None = None, capacities: list[float] | None = None,
    brand_programs: list[str] | None = None, fabric_types: list[str] | None = None,
    tank_types: list[str] | None = None,
) -> dict[str, Any]:
    conn = get_db()
    _ensure_batch_details_columns(conn)
    _ensure_summary_table(conn)

    sql = "SELECT * FROM cleaning_mc_daily_summary WHERE 1=1"
    params: list[Any] = []
    if from_date:
        sql += " AND production_date >= ?"
        params.append(from_date)
    if to_date:
        sql += " AND production_date <= ?"
        params.append(to_date)
    sql += " ORDER BY production_date, machine, sequence_order, start_time, end_time"
    empty_result = {"time_labels": [], "daily_sequence": {}, "kpis": {"normal_batches": 0, "cleaning_count": 0, "cleaning_ratio": 0.0, "rework_batches": 0, "pending_batches": 0}, "matrix": [], "available_capacities": [], "available_brand_programs": [], "available_fabric_types": [], "available_tank_types": [], "color_summary": {"labels": list(COLOR_LABEL_ORDER), "by_day": {}, "fabric_groups": []}, "unmapped_machines": []}
    try:
        rows = execute_query(sql, params)
        master_rows = execute_query(
            "SELECT machine_id, machine_code, group_mc, mc_brand, tank_type, mc_quantity, tube_no, capacity_kg, "
            "status, production_status, orgatex FROM machines WHERE domain = 'dyeing' "
            "ORDER BY COALESCE(group_mc, ''), COALESCE(machine_code, machine_id)",
            [],
        )
    except Exception as exc:
        return {**empty_result, "error": str(exc)}

    available_capacities = sorted({round(float(m["capacity_kg"]), 2) for m in master_rows if m["capacity_kg"] not in (None, "")})
    capacity_filter = {round(float(value), 2) for value in capacities} if capacities else None
    available_brand_programs = sorted({f"{row['brand']} - {row['brand_program']}" for row in rows if row["brand"] and row["brand_program"]})
    brand_program_filter = set(brand_programs) if brand_programs else None
    available_fabric_types = sorted({row["fabric_type"] for row in rows if row["fabric_type"]})
    fabric_type_filter = set(fabric_types) if fabric_types else None
    tank_filter = set(tank_types) if tank_types else None

    machines: dict[str, dict[str, Any]] = {}
    master_by_norm: dict[str, Mapping[str, Any]] = {}
    for master in master_rows:
        machine_code_value = master["machine_code"] or master["machine_id"]
        if not machine_code_value:
            continue
        norm = _normalize_code(machine_code_value)
        master_by_norm[norm] = master
        if capacity_filter is not None:
            row_capacity = round(float(master["capacity_kg"]), 2) if master["capacity_kg"] not in (None, "") else None
            if row_capacity not in capacity_filter:
                continue
        if tank_filter is not None and _normalize_tank_label(master["tank_type"]) not in tank_filter:
            continue
        machines[norm] = _blank_machine_item(machine_code_value, machine_code_value, master)
    present_tanks = {_normalize_tank_label(master["tank_type"]) for master in master_by_norm.values()}
    if any(_normalize_code((row["machine"] or "").strip()) not in master_by_norm for row in rows):
        present_tanks.add(UNCLASSIFIED_TANK_LABEL)
    available_tank_types = [label for label in (*CANONICAL_TANK_ORDER, UNCLASSIFIED_TANK_LABEL) if label in present_tanks]

    unmapped: dict[str, dict[str, Any]] = {}
    normal = cleaning_count = rework = pending = 0
    badge_counter: Counter[str] = Counter()
    color_by_day: dict[str, Counter[str]] = defaultdict(Counter)
    color_by_day_fabric: dict[str, Counter[tuple[str, str]]] = defaultdict(Counter)
    ungrouped_normal_dyelots: list[str] = []
    color_source_missing = color_source_present = 0
    for row in rows:
        if brand_program_filter is not None:
            row_brand_program = f"{row['brand']} - {row['brand_program']}" if row["brand"] and row["brand_program"] else None
            if row_brand_program not in brand_program_filter:
                continue
        if fabric_type_filter is not None and row["fabric_type"] not in fabric_type_filter:
            continue
        raw_machine = (row["machine"] or "").strip()
        norm = _normalize_code(raw_machine)
        item = machines.get(norm)
        if item is None:
            master = master_by_norm.get(norm)
            if master is not None:
                continue
            if tank_filter is not None and UNCLASSIFIED_TANK_LABEL not in tank_filter:
                continue
            item = unmapped.setdefault(norm, _blank_machine_item(raw_machine or "(unknown)", None, None))
        normalized_batch_type = str(row["batch_type"] or "").strip().lower()
        if not normalized_batch_type:
            normalized_batch_type = "normal"
        if row["dyelot_ref"] or row["colour_no"] or row["shade_raw"]:
            color_source_present += 1
        else:
            color_source_missing += 1
        code = row["badge"]
        group = badge_group(code)
        is_rework_badge = group == "REWORK"
        badge_counter[code] += 1
        day = row["production_date"] or "Unknown"
        item["days"].setdefault(day, []).append(code)
        item["batches"].append({"batch_no": row["batch_no"], "machine_code": row["machine_code"], "mc_brand": row["mc_brand"], "tank_type": row["tank_type"], "capacity_kg": row["configured_capacity_kg"], "shade_raw": row["shade_raw"], "colour_no": row["colour_no"], "batch_type": normalized_batch_type, "sequence_order": row["sequence_order"], "production_date": day, "start_time": row["start_time"], "end_time": row["end_time"], "duration_minutes": round((datetime.fromisoformat(row["end_time"]) - datetime.fromisoformat(row["start_time"])).total_seconds() / 60, 1) if row["start_time"] and row["end_time"] else None, "program": row["program"], "brand_program": row["brand_program"] or None, "brand": row["brand"] or None, "color_code_display": code, "is_rework": is_rework_badge, "fabric_type": row["fabric_type"] or ""})
        if group == "CM":
            item["cleaning_count"] += 1
            cleaning_count += 1
        elif group == "NORMAL":
            item["normal_batches"] += 1
            normal += 1
            color_label = BADGE_TO_COLOR_LABEL.get(code)
            if color_label:
                color_by_day[day][color_label] += 1
                fabric = row["fabric_type"] or ""
                if fabric in FABRIC_GROUP_ORDER:
                    color_by_day_fabric[day][(fabric, color_label)] += 1
                else:
                    ungrouped_normal_dyelots.append(f"{row['dyelot_ref']} ({fabric or 'blank'})")
        elif group == "PENDING":
            item["pending_batches"] += 1
            pending += 1
        if normalized_batch_type in {"r&d", "rd", "research", "development"}:
            item["rd_batches"] += 1
        if is_rework_badge:
            item["rework_batches"] += 1
            rework += 1
    matrix = []
    for item in list(machines.values()) + list(unmapped.values()):
        item["cleaning_ratio"] = round(item["normal_batches"] / item["cleaning_count"], 2) if item["cleaning_count"] else None
        matrix.append(item)
    unmapped_machines = [{"machine": item["machine"], "batch_count": len(item["batches"])} for item in unmapped.values()]
    time_labels = sorted({day for item in matrix for day in item["days"]})
    color_summary = {
        "labels": list(COLOR_LABEL_ORDER),
        "by_day": {day: [color_by_day.get(day, Counter()).get(label, 0) for label in COLOR_LABEL_ORDER] for day in time_labels},
        "fabric_groups": [
            {
                "fabric": fabric,
                "by_day": {day: [color_by_day_fabric.get(day, Counter()).get((fabric, label), 0) for label in COLOR_LABEL_ORDER] for day in time_labels},
            }
            for fabric in FABRIC_GROUP_ORDER
            if fabric_type_filter is None or fabric in fabric_type_filter
        ],
    }
    if ungrouped_normal_dyelots:
        logger.warning(
            "Normal Dyeing Batches by Colour: %d mẻ Normal có FabricType ngoài %s -> không vào nhóm nào, tổng nhóm sẽ lệch KPI: %s",
            len(ungrouped_normal_dyelots), FABRIC_GROUP_ORDER, ungrouped_normal_dyelots[:20],
        )
    logger.info(
        "Machine Scheduling Matrix badge check: found=%s missing=%s counts=%s | batch_details join coverage: co_du_lieu_mau=%d thieu_du_lieu_mau=%d (%.0f%% thiếu -> cần bổ sung file Batch Detail nếu tỷ lệ cao)",
        sorted(badge_counter),
        [code for code in ALL_BADGE_CODES if code not in badge_counter],
        dict(badge_counter),
        color_source_present,
        color_source_missing,
        (100.0 * color_source_missing / len(rows)) if rows else 0.0,
    )
    return {
        "time_labels": time_labels,
        "daily_sequence": {(item["machine_code"] or item["machine"]): item["days"] for item in matrix},
        "kpis": {"normal_batches": normal, "cleaning_count": cleaning_count, "cleaning_ratio": round(normal / cleaning_count, 2) if cleaning_count else 0.0, "rework_batches": rework, "pending_batches": pending},
        "matrix": matrix,
        "available_capacities": available_capacities,
        "available_brand_programs": available_brand_programs,
        "available_fabric_types": available_fabric_types,
        "available_tank_types": available_tank_types,
        "color_summary": color_summary,
        "unmapped_machines": unmapped_machines,
        "color_data_coverage": {
            "present": color_source_present,
            "missing": color_source_missing,
            "missing_pct": round(100.0 * color_source_missing / len(rows), 1) if rows else 0.0,
        },
    }


def export_cleaning_matrix_excel(
    from_date: str | None = None, to_date: str | None = None, capacities: list[float] | None = None,
    brand_programs: list[str] | None = None, fabric_types: list[str] | None = None,
    tank_types: list[str] | None = None,
) -> bytes:
    data = get_cleaning_matrix(from_date, to_date, capacities, brand_programs, fabric_types, tank_types)

    workbook = Workbook()
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="24292F", end_color="24292F", fill_type="solid")

    detail_sheet = workbook.active
    detail_sheet.title = "Detail"
    fixed_headers = ["Machine", "Group MC", "MC brand", "Tank", "MC quantity", "Tube no", "Capacity (Kg)", "Status", "Production Status", "Orgatex", "No. of time Cleaning MC", "No. of normal dyeing batch", "Cleaning MC Ratio", "No. of R&D batch", "Rework batch"]
    for col_idx, header in enumerate(fixed_headers, start=1):
        cell = detail_sheet.cell(row=1, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        detail_sheet.column_dimensions[cell.column_letter].width = 16

    day_slot_counts: dict[str, int] = {
        day: max((sum(1 for batch in item["batches"] if batch["production_date"] == day) for item in data["matrix"]), default=1) or 1
        for day in data["time_labels"]
    }
    day_start_col: dict[str, int] = {}
    col_idx = len(fixed_headers) + 1
    for day in data["time_labels"]:
        day_start_col[day] = col_idx
        slot_count = day_slot_counts[day]
        header_cell = detail_sheet.cell(row=1, column=col_idx, value=day)
        header_cell.font = header_font
        header_cell.fill = header_fill
        for offset in range(slot_count):
            detail_sheet.column_dimensions[detail_sheet.cell(row=1, column=col_idx + offset).column_letter].width = 7
            if offset > 0:
                detail_sheet.cell(row=1, column=col_idx + offset).fill = header_fill
        if slot_count > 1:
            detail_sheet.merge_cells(start_row=1, start_column=col_idx, end_row=1, end_column=col_idx + slot_count - 1)
        col_idx += slot_count

    for row_idx, item in enumerate(data["matrix"], start=2):
        machine_label = item["machine_code"] or item["machine"] or "-"
        if item["is_unmapped"]:
            machine_label += " (unmapped)"
        fixed_values = [
            machine_label, item["group_mc"], item["mc_brand"], item["tank_type"], item["mc_quantity"], item["tube_no"],
            item["capacity"], item["status"], item["production_status"], "Yes" if item["orgatex"] else "No",
            item["cleaning_count"], item["normal_batches"], item["cleaning_ratio"], item["rd_batches"], item["rework_batches"],
        ]
        for fixed_col_idx, value in enumerate(fixed_values, start=1):
            detail_sheet.cell(row=row_idx, column=fixed_col_idx, value=value)
        for day in data["time_labels"]:
            day_batches = [batch for batch in item["batches"] if batch["production_date"] == day]
            for slot, batch in enumerate(day_batches):
                code = batch["color_code_display"]
                cell = detail_sheet.cell(row=row_idx, column=day_start_col[day] + slot, value=code)
                bg_color, fg_color = BADGE_FILL_COLORS.get(code, (None, None))
                if bg_color:
                    cell.fill = PatternFill(start_color=bg_color, end_color=bg_color, fill_type="solid")
                    cell.font = Font(color=fg_color)
                    if code.endswith("R"):
                        side = Side(style="medium", color=REWORK_BORDER_COLOR)
                        cell.border = Border(left=side, right=side, top=side, bottom=side)
                    elif code == "W":
                        side = Side(style="thin", color=WHITE_BADGE_BORDER_COLOR)
                        cell.border = Border(left=side, right=side, top=side, bottom=side)
                    elif code == "?":
                        side = Side(style="dashed", color=PENDING_BADGE_BORDER_COLOR)
                        cell.border = Border(left=side, right=side, top=side, bottom=side)
    detail_sheet.freeze_panes = "B2"

    color_sheet = workbook.create_sheet("Color Summary")
    summary = data["color_summary"]
    labels = summary["labels"]
    days = data["time_labels"]
    color_headers = ["Fabric", "Colour", *days, "Total"]
    for col_idx, header in enumerate(color_headers, start=1):
        cell = color_sheet.cell(row=1, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
    for col_idx in range(1, len(color_headers) + 1):
        color_sheet.column_dimensions[color_sheet.cell(row=1, column=col_idx).column_letter].width = 14
    total_font = Font(bold=True)
    total_col = len(color_headers)

    def _write_counts_row(row_idx: int, counts: list[int], font: Font | None = None) -> None:
        for col_offset, count in enumerate(counts):
            cell = color_sheet.cell(row=row_idx, column=3 + col_offset, value=count)
            if font:
                cell.font = font
        cell = color_sheet.cell(row=row_idx, column=total_col, value=sum(counts))
        if font:
            cell.font = font

    row_idx = 2
    for group in summary.get("fabric_groups", []):
        group_start = row_idx
        fabric_cell = color_sheet.cell(row=row_idx, column=1, value=group["fabric"])
        fabric_cell.font = total_font
        fabric_cell.alignment = Alignment(vertical="center")
        subtotal = [0] * len(days)
        for label_index, label in enumerate(labels):
            color_sheet.cell(row=row_idx, column=2, value=label)
            counts = [(group["by_day"].get(day) or [0] * len(labels))[label_index] for day in days]
            subtotal = [a + b for a, b in zip(subtotal, counts)]
            _write_counts_row(row_idx, counts)
            row_idx += 1
        color_sheet.cell(row=row_idx, column=2, value="Subtotal").font = total_font
        _write_counts_row(row_idx, subtotal, total_font)
        color_sheet.merge_cells(start_row=group_start, start_column=1, end_row=row_idx, end_column=1)
        row_idx += 1
    color_sheet.cell(row=row_idx, column=1, value="Total").font = total_font
    _write_counts_row(row_idx, [sum(summary["by_day"].get(day) or []) for day in days], total_font)
    color_sheet.freeze_panes = "C2"

    data_sheet = workbook.create_sheet("Data")
    data_headers = ["Production Date", "Machine", "Dyelot", "Batch Type", "Fabric Type", "Shade", "Badge", "Normal_Cnt", "RW_Cnt", "CM_Cnt", "Start", "End", "Hours"]
    for col_idx, header in enumerate(data_headers, start=1):
        cell = data_sheet.cell(row=1, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        data_sheet.column_dimensions[cell.column_letter].width = 16
    data_row = 2
    for item in data["matrix"]:
        machine_label = item["machine_code"] or item["machine"] or "-"
        for batch in sorted(item["batches"], key=lambda b: (b["production_date"], b["start_time"] or "")):
            group = badge_group(batch["color_code_display"])
            hours = round(batch["duration_minutes"] / 60, 2) if batch["duration_minutes"] is not None else None
            values = [
                batch["production_date"], machine_label, batch["batch_no"], batch["batch_type"], batch["fabric_type"], batch["shade_raw"],
                batch["color_code_display"], int(group == "NORMAL"), int(group == "REWORK"), int(group == "CM"),
                batch["start_time"], batch["end_time"], hours,
            ]
            for col_idx, value in enumerate(values, start=1):
                data_sheet.cell(row=data_row, column=col_idx, value=value)
            data_row += 1
    data_sheet.freeze_panes = "A2"
    data_sheet.auto_filter.ref = f"A1:{data_sheet.cell(row=1, column=len(data_headers)).column_letter}{max(data_row - 1, 1)}"

    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()


PRODUCTION_STATUS_VALUES = ("Sample", "Bulk", "No production")


def list_machine_configs() -> list[dict[str, Any]]:
    conn = get_db()
    _ensure_batch_details_columns(conn)
    sql = """
        SELECT machine_id, COALESCE(machine_code, machine_id) AS machine_code, group_mc, mc_brand, tank_type,
               mc_quantity, tube_no, capacity_kg, status, production_status, orgatex
        FROM machines
        WHERE domain = 'dyeing'
        ORDER BY COALESCE(group_mc, ''), COALESCE(machine_code, machine_id)
    """
    rows = execute_query(sql, [])
    return [dict(row) for row in rows]


def upsert_machine_config(machine_code: str, fields: Mapping[str, Any]) -> dict[str, Any]:
    machine_code = machine_code.strip()
    if not machine_code:
        raise ValueError("Machine code không được rỗng.")
    allowed = {"group_mc", "mc_brand", "tank_type", "mc_quantity", "tube_no", "capacity_kg", "status", "production_status", "orgatex"}
    updates = {key: value for key, value in fields.items() if key in allowed}
    if not updates:
        raise ValueError("Không có field hợp lệ để cập nhật.")
    if "production_status" in updates and updates["production_status"] not in (None, "") and updates["production_status"] not in PRODUCTION_STATUS_VALUES:
        raise ValueError(f"Production Status phải là một trong: {', '.join(PRODUCTION_STATUS_VALUES)}.")
    if "orgatex" in updates:
        updates["orgatex"] = 1 if updates["orgatex"] in (True, 1, "1", "true", "True", "yes", "Yes") else 0

    conn = get_db()
    _ensure_batch_details_columns(conn)
    columns = ["machine_id", "machine_code", "machine_name", "domain", *updates.keys()]
    placeholders = ",".join("?" for _ in columns)
    set_clause = ", ".join(f"{key} = excluded.{key}" for key in updates)
    conn.execute(
        f"""
        INSERT INTO machines ({','.join(columns)}) VALUES ({placeholders})
        ON CONFLICT (machine_id) DO UPDATE SET {set_clause}
        """,
        (machine_code, machine_code, machine_code, "dyeing", *updates.values()),
    )
    conn.commit()

    affected_dates_rows = conn.execute(
        "SELECT DISTINCT production_date FROM cleaning_mc_daily_summary WHERE lower(trim(machine)) = lower(trim(?))",
        (machine_code,),
    ).fetchall()
    affected_dates = {datetime.strptime(row["production_date"], "%Y-%m-%d").date() for row in affected_dates_rows}
    if affected_dates:
        from core.rollup import trigger_recompute

        trigger_recompute(affected_dates)

    row = conn.execute(
        "SELECT machine_code, mc_brand, tank_type, mc_quantity, tube_no, capacity_kg FROM machines WHERE lower(trim(COALESCE(machine_code, machine_id))) = lower(trim(?))",
        (machine_code,),
    ).fetchone()
    return dict(row) if row else {"machine_code": machine_code, **updates}


CANONICAL_GROUP_MC_ORDER = (">=500Kg", ">=300 to <500Kg", "<300Kg")
UNCLASSIFIED_GROUP_LABEL = "Unclassified"
ALL_GROUPS_LABEL = "All Groups"

CANONICAL_TANK_ORDER = ("J tank", "O tank")
UNCLASSIFIED_TANK_LABEL = "Unclassified"
SUBTOTAL_TANK_LABEL = "Subtotal"

SUMMARY_CATEGORIES = (
    "No. total day",
    "No. Dyeing machine",
    "No. of time Cleaning MC",
    "No. of normal dyeing batch",
    "Cleaning MC Ratio",
    "No. of R&D batch",
    "Rework batch",
    "Rework ratio",
    "Daily batch/day",
    "Plan PRD time",
    "Batch/day (Plan PRD)",
)


def _empty_summary_bucket() -> dict[str, Any]:
    return {"cm": 0, "normal": 0, "rd": 0, "rework": 0, "machines": set(), "run_time_sec": 0.0}


def _normalize_tank_label(raw: str | None) -> str:
    normalized = (raw or "").strip().lower()
    if not normalized:
        return UNCLASSIFIED_TANK_LABEL
    for canonical in CANONICAL_TANK_ORDER:
        if normalized == canonical.lower():
            return canonical
    return UNCLASSIFIED_TANK_LABEL


def _merge_summary_buckets(month_data_list: list[dict[int, dict[str, Any]]]) -> dict[int, dict[str, Any]]:
    merged: dict[int, dict[str, Any]] = {}
    for month_data in month_data_list:
        for month, bucket in month_data.items():
            target = merged.setdefault(month, _empty_summary_bucket())
            target["cm"] += bucket["cm"]
            target["normal"] += bucket["normal"]
            target["rd"] += bucket["rd"]
            target["rework"] += bucket["rework"]
            target["machines"] |= bucket["machines"]
            target["run_time_sec"] += bucket["run_time_sec"]
    return merged


def _build_summary_category_rows(year: int, month_data: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    values: dict[str, list[Any]] = {category: [] for category in SUMMARY_CATEGORIES}
    for month in range(1, 13):
        bucket = month_data.get(month) or _empty_summary_bucket()
        days = calendar.monthrange(year, month)[1]
        n_machines = len(bucket["machines"])
        cm = bucket["cm"]
        normal = bucket["normal"]
        rd = bucket["rd"]
        rework = bucket["rework"]
        plan_prd_time_hours = bucket["run_time_sec"] / 3600
        values["No. total day"].append(days)
        values["No. Dyeing machine"].append(n_machines)
        values["No. of time Cleaning MC"].append(cm)
        values["No. of normal dyeing batch"].append(normal)
        values["Cleaning MC Ratio"].append(round(normal / cm, 2) if cm else None)
        values["No. of R&D batch"].append(rd)
        values["Rework batch"].append(rework)
        values["Rework ratio"].append(round(normal / rework, 2) if rework else None)
        values["Daily batch/day"].append(round(normal / (days * n_machines), 2) if (days and n_machines) else None)
        values["Plan PRD time"].append(round(plan_prd_time_hours, 2))
        values["Batch/day (Plan PRD)"].append(round(normal * 24 / plan_prd_time_hours, 2) if plan_prd_time_hours else None)
    return [{"category": category, "values": values[category]} for category in SUMMARY_CATEGORIES]


def get_batch_summary(year: int) -> dict[str, Any]:
    conn = get_db()
    _ensure_batch_details_columns(conn)
    _ensure_summary_table(conn)

    from_date = f"{year:04d}-01-01"
    to_date = f"{year:04d}-12-31"
    rows = execute_query(
        "SELECT production_date, machine, badge, batch_type, run_time FROM cleaning_mc_daily_summary WHERE production_date >= ? AND production_date <= ?",
        [from_date, to_date],
    )
    master_rows = execute_query("SELECT machine_id, machine_code, group_mc, tank_type FROM machines WHERE domain = 'dyeing'", [])
    machine_meta_by_norm: dict[str, dict[str, str | None]] = {}
    for master in master_rows:
        code = master["machine_code"] or master["machine_id"]
        if not code:
            continue
        machine_meta_by_norm[_normalize_code(code)] = {
            "group": (master["group_mc"] or "").strip() or None,
            "tank": master["tank_type"],
        }

    accumulators: dict[str, dict[str, dict[int, dict[str, Any]]]] = defaultdict(lambda: defaultdict(dict))
    distinct_groups: set[str] = set()
    for row in rows:
        production_date = row["production_date"] or ""
        if len(production_date) < 7:
            continue
        try:
            month = int(production_date[5:7])
        except ValueError:
            continue
        if not (1 <= month <= 12):
            continue
        norm = _normalize_code(row["machine"])
        meta = machine_meta_by_norm.get(norm)
        group_label = (meta["group"] if meta else None) or UNCLASSIFIED_GROUP_LABEL
        tank_label = _normalize_tank_label(meta["tank"] if meta else None)
        distinct_groups.add(group_label)
        bucket = accumulators[group_label][tank_label].setdefault(month, _empty_summary_bucket())
        normalized_batch_type = str(row["batch_type"] or "").strip().lower() or "normal"
        code = row["badge"]
        group = badge_group(code)
        bucket["run_time_sec"] += float(row["run_time"] or 0)
        if group == "CM":
            bucket["cm"] += 1
        elif group in ("NORMAL", "REWORK"):
            bucket["machines"].add(norm)
            if group == "NORMAL":
                bucket["normal"] += 1
            else:
                bucket["rework"] += 1
            if normalized_batch_type in {"r&d", "rd", "research", "development"}:
                bucket["rd"] += 1

    ordered_groups = [g for g in CANONICAL_GROUP_MC_ORDER if g in distinct_groups]
    ordered_groups += sorted(g for g in distinct_groups if g not in CANONICAL_GROUP_MC_ORDER and g != UNCLASSIFIED_GROUP_LABEL)
    if UNCLASSIFIED_GROUP_LABEL in distinct_groups:
        ordered_groups.append(UNCLASSIFIED_GROUP_LABEL)

    groups_output = []
    for group_label in ordered_groups:
        tank_buckets = accumulators[group_label]
        present_tanks = set(tank_buckets.keys())
        ordered_tanks = [t for t in CANONICAL_TANK_ORDER if t in present_tanks]
        if UNCLASSIFIED_TANK_LABEL in present_tanks:
            ordered_tanks.append(UNCLASSIFIED_TANK_LABEL)

        tanks_output = [{"tank": SUBTOTAL_TANK_LABEL, "rows": _build_summary_category_rows(year, _merge_summary_buckets(list(tank_buckets.values())))}]
        for tank_label in ordered_tanks:
            tanks_output.append({"tank": tank_label, "rows": _build_summary_category_rows(year, tank_buckets[tank_label])})
        groups_output.append({"group": group_label, "tanks": tanks_output})

    all_groups_month_data = [accumulators[group_label][tank_label] for group_label in ordered_groups for tank_label in accumulators[group_label]]
    all_groups_data = _merge_summary_buckets(all_groups_month_data)
    groups_output.append({"group": ALL_GROUPS_LABEL, "tanks": [{"tank": None, "rows": _build_summary_category_rows(year, all_groups_data)}]})

    month_labels = [date(year, month, 1).strftime("%b-%y") for month in range(1, 13)]
    year_rows = execute_query("SELECT DISTINCT substr(production_date, 1, 4) AS y FROM cleaning_mc_daily_summary WHERE production_date IS NOT NULL", [])
    available_years = sorted({int(r["y"]) for r in year_rows if r["y"] and r["y"].isdigit()})
    if year not in available_years:
        available_years = sorted({*available_years, year})

    return {
        "year": year,
        "available_years": available_years,
        "months": month_labels,
        "groups": groups_output,
    }


def export_batch_summary_excel(year: int) -> bytes:
    data = get_batch_summary(year)

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = f"Summary {year}"[:31]

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="24292F", end_color="24292F", fill_type="solid")
    group_font = Font(bold=True)
    subtotal_font = Font(bold=True, italic=True)
    total_font = Font(bold=True)

    headers = ["Group Machine", "Tank", "Category", *data["months"]]
    for col_idx, header in enumerate(headers, start=1):
        cell = sheet.cell(row=1, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
    sheet.column_dimensions["A"].width = 18
    sheet.column_dimensions["B"].width = 14
    sheet.column_dimensions["C"].width = 26
    for col_idx in range(4, len(headers) + 1):
        sheet.column_dimensions[sheet.cell(row=1, column=col_idx).column_letter].width = 12

    current_row = 2
    for group in data["groups"]:
        is_total_group = group["group"] == ALL_GROUPS_LABEL
        group_start_row = current_row
        for tank_block in group["tanks"]:
            is_subtotal = tank_block["tank"] == SUBTOTAL_TANK_LABEL
            emphasize = is_total_group or is_subtotal
            tank_start_row = current_row
            for row in tank_block["rows"]:
                sheet.cell(row=current_row, column=1, value=group["group"] if current_row == group_start_row else None)
                sheet.cell(row=current_row, column=2, value=(tank_block["tank"] or "-") if current_row == tank_start_row else None)
                category_cell = sheet.cell(row=current_row, column=3, value=row["category"])
                if emphasize:
                    category_cell.font = total_font if is_total_group else subtotal_font
                for col_offset, value in enumerate(row["values"]):
                    value_cell = sheet.cell(row=current_row, column=4 + col_offset, value=value)
                    if emphasize:
                        value_cell.font = total_font if is_total_group else subtotal_font
                current_row += 1
            sheet.merge_cells(start_row=tank_start_row, start_column=2, end_row=current_row - 1, end_column=2)
            sheet.cell(row=tank_start_row, column=2).font = total_font if is_total_group else (subtotal_font if is_subtotal else group_font)
        sheet.merge_cells(start_row=group_start_row, start_column=1, end_row=current_row - 1, end_column=1)
        sheet.cell(row=group_start_row, column=1).font = total_font if is_total_group else group_font

    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()


def _pending_batch_row(batch: dict[str, Any]) -> dict[str, Any]:
    return {
        "batch_id": batch["id"],
        "override_id": batch["_override_id"],
        "production_date": batch["production_date"].isoformat(),
        "machine": batch["machine"],
        "dyelot": batch["dyelot"],
        "start_time": str(batch["start_time"] or ""),
        "end_time": str(batch["end_time"] or ""),
        "recipe_no": batch["recipe_no"] or "",
        "colour_no": batch["colour_no"] or "",
        "sap_lot": batch["sap_lot"] or "",
        "original_batch_type": batch["_original_batch_type"] or "",
        "batch_type": batch["batch_type"] or "",
        "fabric_type": batch["fabric_type"] or "",
        "shade": batch["shade"] or "",
        "status": "manual" if batch["_override_id"] else "pending",
    }


def _batch_classification_input(batch: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "dyelot": batch["dyelot"], "batch_type": batch["batch_type"], "shade": batch["shade"], "colour_no": batch["colour_no"],
        "recipe_no": batch["recipe_no"], "customer_color": batch["customer_color"], "sap_lot": batch["sap_lot"],
    }


def get_data_quality(from_date: str | None = None, to_date: str | None = None) -> dict[str, Any]:
    conn = get_db()
    ensure_brand_program_table(conn)
    batches = load_resolved_batches(conn)
    groups = [badge_group(classify_batch_badge(_batch_classification_input(batch))) for batch in batches]

    def in_range(batch: Mapping[str, Any]) -> bool:
        day = batch["production_date"].isoformat()
        return not ((from_date and day < from_date) or (to_date and day > to_date))

    pending: list[dict[str, Any]] = []
    scouring_normal: list[dict[str, Any]] = []
    normal_runs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for batch, group in zip(batches, groups):
        if group == "NORMAL":
            normal_runs[str(batch["dyelot"]).strip()].append(batch)
        if not in_range(batch):
            continue
        if group == "PENDING" or batch["_override_id"]:
            pending.append(_pending_batch_row(batch))
        elif group == "SC" and str(batch["_original_batch_type"] or "").strip().lower() == "normal":
            scouring_normal.append(_pending_batch_row(batch))
    multi_normal = []
    for dyelot, runs in normal_runs.items():
        if len(runs) < 2 or not any(in_range(run) for run in runs):
            continue
        multi_normal.append({
            "dyelot": dyelot,
            "runs": [
                {"production_date": run["production_date"].isoformat(), "machine": run["machine"], "start_time": str(run["start_time"] or ""), "recipe_no": run["recipe_no"] or "", "redye": run["redye"]}
                for run in sorted(runs, key=lambda r: r["_start_dt"])
            ],
        })
    pending.sort(key=lambda row: (row["production_date"], row["machine"], row["start_time"]))
    scouring_normal.sort(key=lambda row: (row["production_date"], row["machine"], row["start_time"]))
    multi_normal.sort(key=lambda row: row["dyelot"])
    return {
        "pending": pending,
        "scouring_normal": scouring_normal,
        "multi_normal": multi_normal,
        "options": {"batch_types": list(OVERRIDE_BATCH_TYPES), "fabric_types": list(OVERRIDE_FABRIC_TYPES), "shades": list(OVERRIDE_SHADES)},
    }


def _validated_override_fields(batch_type: Any, fabric_type: Any, shade: Any) -> tuple[str, str, str]:
    values = []
    for label, value, allowed in (("Batch type", batch_type, OVERRIDE_BATCH_TYPES), ("Fabric type", fabric_type, OVERRIDE_FABRIC_TYPES), ("Shade", shade, OVERRIDE_SHADES)):
        text = str(value or "").strip()
        match = next((option for option in allowed if option.lower() == text.lower()), None)
        if match is None:
            raise ValueError(f"{label} must be one of: {', '.join(allowed)}.")
        values.append(match)
    return values[0], values[1], values[2]


def save_manual_override(batch_id: int, batch_type: Any, fabric_type: Any, shade: Any, username: str | None) -> set[date]:
    batch_type_value, fabric_type_value, shade_value = _validated_override_fields(batch_type, fabric_type, shade)
    conn = get_db()
    ensure_brand_program_table(conn)
    batches = load_resolved_batches(conn)
    target = next((batch for batch in batches if batch["id"] == batch_id), None)
    if target is None:
        raise ValueError("Batch not found.")
    group = badge_group(classify_batch_badge(_batch_classification_input(target)))
    if group != "PENDING" and not target["_override_id"]:
        raise ValueError("Only batches with a missing batch type can be entered manually.")
    key_values = (str(target["dyelot"]).strip(), target["machine"], target["_start_dt"].strftime("%Y-%m-%d %H:%M:%S"))
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        f"""
        INSERT INTO {MANUAL_OVERRIDE_TABLE} (dyelot, machine, start_time, batch_type, fabric_type, shade, updated_by, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (dyelot, machine, start_time) DO UPDATE SET
            batch_type = excluded.batch_type, fabric_type = excluded.fabric_type, shade = excluded.shade,
            updated_by = excluded.updated_by, updated_at = excluded.updated_at
        """,
        (*key_values, batch_type_value, fabric_type_value, shade_value, username, now_str),
    )
    conn.commit()
    return dates_affected_by_batch(load_resolved_batches(conn), batch_id)


def delete_manual_override(override_id: int) -> set[date]:
    conn = get_db()
    ensure_brand_program_table(conn)
    batches = load_resolved_batches(conn)
    target = next((batch for batch in batches if batch["_override_id"] == override_id), None)
    if target is None:
        raise ValueError("Manual entry not found.")
    affected = dates_affected_by_batch(batches, target["id"])
    conn.execute(f"DELETE FROM {MANUAL_OVERRIDE_TABLE} WHERE id = ?", (override_id,))
    conn.commit()
    return affected
