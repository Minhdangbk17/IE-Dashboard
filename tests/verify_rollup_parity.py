"""
tests/verify_rollup_parity.py
-------------------------------
Đối chiếu kết quả đọc từ Daily Rollup summary table (`downtime_daily_summary`,
`batch_matrix_daily_summary`) với kết quả tính TRỰC TIẾP từ raw data theo đúng
công thức cũ (trước khi có rollup) — PHẢI khớp tuyệt đối trước khi coi việc
chuyển sang Daily Rollup Pattern là an toàn (xem mục 7, yêu cầu gốc).

Logic "cũ" (_legacy_*) dựng lại NGUYÊN VẸN từ code trước khi refactor (đã đọc/lưu
lại trong quá trình implement) — script này tự chạy được, không phụ thuộc code cũ
còn tồn tại hay không trong service.py hiện tại.

Chạy: python tests/verify_rollup_parity.py
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app as appmod  # noqa: E402
from core.database import execute_query  # noqa: E402

_INVALID_FABRIC_TYPES_BM = {"", "unknow", "unknown"}
UNCLASSIFIED_COLOR_GROUP = "Unclassified"


def _legacy_classify_color_group(shade: Any, colour_no: Any) -> str:
    shade_norm = str(shade or "").strip()
    if not shade_norm:
        return UNCLASSIFIED_COLOR_GROUP
    colour_upper = str(colour_no or "").upper()
    shade_upper = shade_norm.upper()
    if shade_upper == "DARK":
        return "Black" if "BLACK" in colour_upper else "Dark"
    if shade_upper == "LIGHT":
        return "White" if "WHITE" in colour_upper else "Light"
    if shade_upper == "MEDIUM":
        return "Medium"
    return shade_norm


def _direct_machine_hours_by_day(days: list[str]) -> dict[str, dict[str, float]]:
    """Dựng ĐỘC LẬP giờ hoạt động của TỪNG MÁY theo TỪNG NGÀY — cùng logic với
    `batch_matrix/service.py::_machine_hours_by_day_for_range()` nhưng viết LẠI riêng ở đây
    (không import từ service.py) để giữ tính độc lập kiểm chứng."""
    from core.production_time import get_production_date, production_bounds

    if not days:
        return {}
    range_start, _ = production_bounds(days[0], days[0])
    _, range_end = production_bounds(days[-1], days[-1])
    rows = execute_query(
        """
        SELECT machine, start_time, end_time
        FROM availability_logs
        WHERE machine IS NOT NULL AND machine != ''
          AND start_time IS NOT NULL AND start_time != ''
          AND datetime(COALESCE(end_time, start_time)) > datetime(?)
          AND datetime(start_time) < datetime(?)
        """,
        (range_start, range_end),
    )
    day_set = set(days)
    day_windows: dict[str, tuple[datetime, datetime]] = {}
    for day in days:
        window_start, window_end = production_bounds(day, day)
        day_windows[day] = (datetime.strptime(window_start, "%Y-%m-%d %H:%M:%S"), datetime.strptime(window_end, "%Y-%m-%d %H:%M:%S"))

    result: dict[str, dict[str, float]] = {}
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
        current = get_production_date(start_dt)
        last_day = get_production_date(end_dt)
        while current <= last_day:
            day_str = current.isoformat()
            if day_str in day_set:
                window_start_dt, window_end_dt = day_windows[day_str]
                overlap = (min(end_dt, window_end_dt) - max(start_dt, window_start_dt)).total_seconds() / 3600.0
                if overlap > 0:
                    bucket = result.setdefault(day_str, {})
                    bucket[machine] = bucket.get(machine, 0.0) + overlap
            current += timedelta(days=1)
    return result


def direct_build_matrix(date_from: str | None, date_to: str | None, capacities: list[str] | None) -> dict[str, Any]:
    """Dựng lại ĐỘC LẬP build_matrix() bản JOIN trực tiếp trên raw data, đúng công thức
    HIỆN TẠI (bản THỨ 3, 2026-09-10): tử số = đếm mẻ theo (fabric_type, color_group,
    capacity, ngày) KHÔNG đổi; mẫu số = giờ hoạt động của ĐÚNG TẬP MÁY đã chạy các mẻ được
    đếm ở ô đó (bao gồm cả giờ mẻ khác màu/vải của chính các máy này) — Total(Fabric)/Grand
    Total PHẢI khử trùng máy (union qua các ColorGroup con) trước khi cộng giờ, KHÔNG cộng
    thẳng operating_hours của từng dòng con (đúng bug COUNT DISTINCT dạng "giờ")."""
    sql = """
        SELECT date(datetime(a.end_time), '-7 hours') AS production_date,
               a.fabric_type, a.machine, a.capacity_kg, b.shade, b.colour_no
        FROM availability_logs a
        LEFT JOIN batch_details b ON lower(trim(a.batch)) = lower(trim(b.dyelot))
        WHERE a.end_time IS NOT NULL AND a.end_time != ''
          AND a.fabric_type IS NOT NULL AND lower(trim(a.fabric_type)) NOT IN (?, ?, ?)
          AND (b.batch_type IS NULL OR lower(trim(b.batch_type)) = 'normal')
    """
    params: list[Any] = list(_INVALID_FABRIC_TYPES_BM)
    all_rows = execute_query(sql, params)
    if not all_rows:
        return {"days": [], "results": {}, "grand_total": None}

    all_days_sorted = sorted({row["production_date"] for row in all_rows if row["production_date"]})
    start_day = datetime.strptime(date_from, "%Y-%m-%d").date() if date_from else datetime.strptime(all_days_sorted[0], "%Y-%m-%d").date()
    end_day = datetime.strptime(date_to, "%Y-%m-%d").date() if date_to else datetime.strptime(all_days_sorted[-1], "%Y-%m-%d").date()
    days: list[str] = []
    current = start_day
    while current <= end_day:
        days.append(current.isoformat())
        current += timedelta(days=1)
    day_set = set(days)

    selected_capacities = [float(c) for c in capacities] if capacities else []
    capacity_filter = {round(v, 2) for v in selected_capacities} if selected_capacities else None

    # Tập máy theo TỪNG ô (fabric,color,day) — cho dòng "data".
    by_cell: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    by_fabric_count: dict[str, dict[str, int]] = {}
    # Tập máy đã khử trùng theo (day,fabric) và theo day — cho Total(Fabric)/Grand Total.
    fabric_machines: dict[tuple[str, str], set[str]] = {}
    grand_machines: dict[str, set[str]] = {}
    grand_count: dict[str, int] = {}

    for row in all_rows:
        day = row["production_date"]
        if day not in day_set:
            continue
        if capacity_filter is not None:
            row_capacity = round(float(row["capacity_kg"]), 2) if row["capacity_kg"] not in (None, "") else None
            if row_capacity not in capacity_filter:
                continue
        fabric_type = row["fabric_type"].strip()
        color_group = _legacy_classify_color_group(row["shade"], row["colour_no"])
        machine = (row["machine"] or "").strip()

        cell_bucket = by_cell.setdefault((fabric_type, color_group), {}).setdefault(day, {"count": 0, "machines": set()})
        cell_bucket["count"] += 1
        if machine:
            cell_bucket["machines"].add(machine)

        by_fabric_count.setdefault(fabric_type, {})
        by_fabric_count[fabric_type][day] = by_fabric_count[fabric_type].get(day, 0) + 1
        grand_count[day] = grand_count.get(day, 0) + 1
        if machine:
            fabric_machines.setdefault((day, fabric_type), set()).add(machine)
            grand_machines.setdefault(day, set()).add(machine)

    machine_hours_by_day = _direct_machine_hours_by_day(days)

    def _hours_of(machines: set[str], day: str) -> float:
        day_hours = machine_hours_by_day.get(day, {})
        return sum(day_hours.get(m, 0.0) for m in machines)

    def cell_value_from(count: int | None, hours: float) -> float | None:
        if count is None or not hours:
            return None
        return round(count / (hours / 24), 2)

    def cell_value(day: str, cell_bucket_by_day: dict[str, dict[str, Any]]) -> float | None:
        bucket = cell_bucket_by_day.get(day)
        if not bucket:
            return None
        return cell_value_from(bucket["count"], _hours_of(bucket["machines"], day))

    def total_value(cell_bucket_by_day: dict[str, dict[str, Any]]) -> float | None:
        numerator = sum(b["count"] for b in cell_bucket_by_day.values())
        denominator_hours = sum(_hours_of(b["machines"], day) for day, b in cell_bucket_by_day.items())
        return round(numerator / (denominator_hours / 24), 2) if denominator_hours else None

    def cell_value_dedup(day: str, count_by_day: dict[str, int], machines_by_day: dict[str, set[str]]) -> float | None:
        return cell_value_from(count_by_day.get(day), _hours_of(machines_by_day.get(day, set()), day))

    def total_value_dedup(count_by_day: dict[str, int], machines_by_day: dict[str, set[str]]) -> float | None:
        numerator = sum(count_by_day.values())
        denominator_hours = sum(_hours_of(machines_by_day.get(day, set()), day) for day in count_by_day)
        return round(numerator / (denominator_hours / 24), 2) if denominator_hours else None

    results: dict[tuple[str, str | None], dict[str, Any]] = {}
    for fabric_type in sorted(by_fabric_count.keys()):
        color_groups = sorted({cg for (ft, cg) in by_cell if ft == fabric_type})
        for color_group in color_groups:
            cell_bucket_by_day = by_cell[(fabric_type, color_group)]
            results[(fabric_type, color_group)] = {
                "days": {d: cell_value(d, cell_bucket_by_day) for d in days},
                "total": total_value(cell_bucket_by_day),
            }
        fabric_count_by_day = by_fabric_count[fabric_type]
        fabric_machines_by_day = {d: fabric_machines.get((d, fabric_type), set()) for d in days}
        results[(fabric_type, None)] = {
            "days": {d: cell_value_dedup(d, fabric_count_by_day, fabric_machines_by_day) for d in days},
            "total": total_value_dedup(fabric_count_by_day, fabric_machines_by_day),
        }
    grand_machines_by_day = {d: grand_machines.get(d, set()) for d in days}
    results[(None, None)] = {
        "days": {d: cell_value_dedup(d, grand_count, grand_machines_by_day) for d in days},
        "total": total_value_dedup(grand_count, grand_machines_by_day),
    }
    return {"days": days, "results": results, "grand_total": total_value_dedup(grand_count, grand_machines_by_day)}


CATEGORY_COLUMNS = {
    "Rework": ("rework_hour",), "Color Adjustment": ("adjust_color_hour",),
    "Sample checking": ("sample_checking_hour",), "Fabric loading": ("load_hour",),
    "Fabric unloading": ("unload_hour",), "Bleaching/Washing": ("bleaching_hour",),
    "PH checking": ("ph_checking_hour",), "Chemical load": ("wait_chemical_load_hour", "wait_color_load_hour"),
    "Others": ("wait_fabric_hour", "wait_water_hour", "wait_steam_hour", "cleaning_hour", "maintenance_hour", "others_hour", "no_order_hour"),
}


def legacy_category_hours(date_from: str | None, date_to: str | None, capacities: list[str] | None) -> dict[str, float]:
    """Dựng lại phần cộng dồn giờ theo CATEGORY (phần đã chuyển sang rollup) — trực tiếp
    từ availability_logs, không qua downtime_daily_summary."""
    record_time = 'COALESCE("end_time", "start_time")'
    shifted_date = f"date(datetime({record_time}), '-7 hours')"
    cols = [col for cols in CATEGORY_COLUMNS.values() for col in cols]
    sql = f"SELECT {shifted_date} AS production_date, capacity_kg, {', '.join(cols)} FROM availability_logs WHERE 1=1"
    params: list[Any] = []
    if date_from:
        sql += f" AND {shifted_date} >= ?"
        params.append(date_from)
    if date_to:
        sql += f" AND {shifted_date} <= ?"
        params.append(date_to)
    if capacities:
        placeholders = ",".join("?" for _ in capacities)
        sql += f" AND CAST(capacity_kg AS REAL) IN ({placeholders})"
        params.extend(float(c) for c in capacities)
    rows = execute_query(sql, params)
    totals = dict.fromkeys(CATEGORY_COLUMNS, 0.0)
    for row in rows:
        for category, cat_cols in CATEGORY_COLUMNS.items():
            totals[category] += sum(float(row[c] or 0) for c in cat_cols)
    return {k: round(v, 4) for k, v in totals.items()}


def new_category_hours_from_summary(date_from: str | None, date_to: str | None, capacities: list[str] | None) -> dict[str, float]:
    sql = "SELECT category, SUM(hours) AS hours FROM downtime_daily_summary WHERE 1=1"
    params: list[Any] = []
    if date_from:
        sql += " AND production_date >= ?"
        params.append(date_from)
    if date_to:
        sql += " AND production_date <= ?"
        params.append(date_to)
    if capacities:
        placeholders = ",".join("?" for _ in capacities)
        sql += f" AND capacity_kg IN ({placeholders})"
        params.extend(float(c) for c in capacities)
    sql += " GROUP BY category"
    rows = execute_query(sql, params)
    totals = dict.fromkeys(CATEGORY_COLUMNS, 0.0)
    for row in rows:
        if row["category"] in totals:
            totals[row["category"]] = float(row["hours"] or 0)
    return {k: round(v, 4) for k, v in totals.items()}


def legacy_get_cleaning_matrix(date_from: str | None, date_to: str | None, capacities: list[str] | None) -> dict[str, Any]:
    """Dựng lại NGUYÊN VẸN get_cleaning_matrix() bản JOIN trực tiếp (trước rollup) —
    JOIN availability_logs x batch_details + classify_batch_badge() NGAY LÚC ĐỌC, không qua
    cleaning_mc_daily_summary. Chỉ khác cách lọc ngày operational_bounds() gốc (mốc datetime
    [07:00, next-day 07:00)) bằng lọc trực tiếp trên production_date đã shift — hai cách
    tương đương vì production_date được ĐỊNH NGHĨA từ đúng mốc cắt 07:00 đó.

    Danh sách machine (2026-09-22, sau khi đổi thiết kế Machine Master) dùng LẠI ĐÚNG
    `_normalize_code()`/`_blank_machine_item()` thật từ cleaning_matrix.py thay vì viết lại
    lần 2 — script này CHỈ còn cần kiểm tra rollup fidelity ở TẦNG PHÂN LOẠI BADGE/ngày cắt
    ca (classify_batch_badge() chạy trên raw JOIN vs chạy trong recompute_daily()), việc chọn
    machine nào hiển thị đã là logic CHUNG (đọc Machine Master), không còn khác biệt cần dò
    lại giữa 2 đường."""
    from modules.dyeing.engines.reports.cleaning_matrix import _blank_machine_item, _normalize_code, classify_batch_badge

    availability_columns = {row["name"] for row in execute_query("PRAGMA table_info(availability_logs)")}
    batch_columns = {row["name"] for row in execute_query("PRAGMA table_info(batch_details)")}
    sequence_expression = 'a."sequence_order"' if "sequence_order" in availability_columns else 'a."start_time"'
    shifted_date = "date(datetime(COALESCE(a.end_time, a.start_time)), '-7 hours')"

    sql = f"""
         SELECT {shifted_date} AS production_date,
             a.machine, a.capacity_kg, a.program, a.start_time, a.end_time, a.rework_hour AS log_rework_minutes,
             a.batch_ref_no, a.batch, {sequence_expression} AS sequence_order, COALESCE(b.shade, '') AS shade,
             COALESCE(b.colour_no, '') AS colour_no, COALESCE(b.customer_color, '') AS customer_color, COALESCE(b.batch_type, '') AS batch_type,
             COALESCE(b.recipe_no, '') AS recipe_no,
             {('COALESCE(b.redye, 0)' if 'redye' in batch_columns else '0')} AS redye,
             COALESCE(b.is_rework, 0) AS is_rework, COALESCE(b.dyelot, '') AS dyelot_ref
        FROM availability_logs a
        LEFT JOIN batch_details b ON lower(trim(b.dyelot)) = lower(trim(a.batch_ref_no)) OR lower(trim(b.dyelot)) = lower(trim(a.batch))
        WHERE 1=1
    """
    params: list[Any] = []
    if date_from:
        sql += f" AND {shifted_date} >= ?"
        params.append(date_from)
    if date_to:
        sql += f" AND {shifted_date} <= ?"
        params.append(date_to)
    sql += f" ORDER BY production_date, a.machine, {sequence_expression}, a.start_time, a.end_time"
    rows = execute_query(sql, params)

    master_rows = execute_query(
        "SELECT machine_id, machine_code, group_mc, mc_brand, tank_type, mc_quantity, tube_no, capacity_kg, "
        "status, production_status, orgatex FROM machines WHERE domain = 'dyeing'",
        [],
    )
    available_capacities = sorted({round(float(m["capacity_kg"]), 2) for m in master_rows if m["capacity_kg"] not in (None, "")})
    capacity_filter = {round(float(value), 2) for value in capacities} if capacities else None

    machines: dict[str, dict[str, Any]] = {}
    master_by_norm: dict[str, Any] = {}
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
        machines[norm] = _blank_machine_item(machine_code_value, machine_code_value, master)

    unmapped: dict[str, dict[str, Any]] = {}
    normal = cleaning_count = rework = 0
    color_source_missing = color_source_present = 0
    for row in rows:
        raw_machine = (row["machine"] or "").strip()
        norm = _normalize_code(raw_machine)
        item = machines.get(norm)
        if item is None:
            master = master_by_norm.get(norm)
            if master is not None:
                continue
            item = unmapped.setdefault(norm, _blank_machine_item(raw_machine or "(unknown)", None, None))
        normalized_batch_type = str(row["batch_type"] or "").strip().lower()
        if not normalized_batch_type:
            normalized_batch_type = "normal"
        if row["dyelot_ref"] or row["colour_no"] or row["shade"]:
            color_source_present += 1
        else:
            color_source_missing += 1
        batch_no = "|".join(value for value in (row["batch_ref_no"], row["batch"]) if value)
        batch_record = {
            "dyelot": row["dyelot_ref"] or batch_no,
            "batch_type": row["batch_type"],
            "redye": row["redye"],
            "shade": row["shade"],
            "colour_no": row["colour_no"],
            "recipe_no": row["recipe_no"],
            "customer_color": row["customer_color"],
            "log_rework_minutes": row["log_rework_minutes"],
        }
        code = classify_batch_badge(batch_record)
        is_rework_badge = code.endswith("R")
        day = row["production_date"] or "Unknown"
        item["days"].setdefault(day, []).append(code)
        if code == "CM":
            item["cleaning_count"] += 1
            cleaning_count += 1
        elif not is_rework_badge and normalized_batch_type in {"normal", "unknown", ""}:
            item["normal_batches"] += 1
            normal += 1
        if normalized_batch_type in {"r&d", "rd", "research", "development"}:
            item["rd_batches"] += 1
        if is_rework_badge:
            item["rework_batches"] += 1
            rework += 1
    matrix = []
    for item in list(machines.values()) + list(unmapped.values()):
        item["cleaning_ratio"] = round(item["normal_batches"] / item["cleaning_count"], 2) if item["cleaning_count"] else None
        matrix.append(item)
    return {
        "kpis": {"normal_batches": normal, "cleaning_count": cleaning_count, "cleaning_ratio": round(normal / cleaning_count, 2) if cleaning_count else 0.0, "rework_batches": rework},
        "matrix": matrix,
        "available_capacities": available_capacities,
        "color_data_coverage": {
            "present": color_source_present,
            "missing": color_source_missing,
            "missing_pct": round(100.0 * color_source_missing / len(rows), 1) if rows else 0.0,
        },
    }


def main() -> int:
    with appmod.app.app_context():
        from core.rollup import rebuild_all_summaries
        from modules.dyeing.engines.batch_matrix.service import build_matrix as new_build_matrix
        from modules.dyeing.engines.downtime.service import get_downtime_pivot_data as new_downtime
        from modules.dyeing.engines.reports.cleaning_matrix import get_cleaning_matrix as new_cleaning_matrix

        n_days = rebuild_all_summaries()
        print(f"[setup] Đã rebuild summary cho {n_days} production_date.\n")

        failures = 0
        scenarios = [
            (None, None, None),
            ("2026-09-01", "2026-09-08", None),
            (None, None, ["600"]),
            ("2026-09-03", "2026-09-05", ["300", "600"]),
        ]

        print("=== batch_matrix: build_matrix() (rollup) vs direct_build_matrix() (raw JOIN, công thức operating_hours/24) ===")
        for date_from, date_to, capacities in scenarios:
            legacy = direct_build_matrix(date_from, date_to, capacities)
            new = new_build_matrix(date_from, date_to, capacities)
            new_results = {(row["fabric_type"], row["color_group"]): row for row in new["rows"]}
            label = f"date_from={date_from} date_to={date_to} capacities={capacities}"
            ok = True
            if legacy["days"] != new["days"]:
                ok = False
                print(f"  [FAIL] {label}: days mismatch legacy={legacy['days'][:3]}... new={new['days'][:3]}...")
            for key, legacy_cell in legacy.get("results", {}).items():
                new_cell = new_results.get(key)
                if new_cell is None:
                    ok = False
                    print(f"  [FAIL] {label}: thiếu dòng {key} trong kết quả mới")
                    continue
                if legacy_cell["total"] != new_cell["total"]:
                    ok = False
                    print(f"  [FAIL] {label}: {key} total legacy={legacy_cell['total']} new={new_cell['total']}")
                for day, legacy_value in legacy_cell["days"].items():
                    new_value = new_cell["days"].get(day)
                    if legacy_value != new_value:
                        ok = False
                        print(f"  [FAIL] {label}: {key} day={day} legacy={legacy_value} new={new_value}")
            if legacy["grand_total"] != new["grand_total"]:
                ok = False
                print(f"  [FAIL] {label}: grand_total legacy={legacy['grand_total']} new={new['grand_total']}")
            print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
            failures += 0 if ok else 1

        print("\n=== downtime: category hours (rollup) vs legacy (raw scan) ===")
        for date_from, date_to, capacities in scenarios:
            legacy = legacy_category_hours(date_from, date_to, capacities)
            new = new_category_hours_from_summary(date_from, date_to, capacities)
            label = f"date_from={date_from} date_to={date_to} capacities={capacities}"
            ok = legacy == new
            if not ok:
                print(f"  [FAIL] {label}: legacy={legacy} new={new}")
            print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
            failures += 0 if ok else 1

        print("\n=== downtime: get_downtime_pivot_data() KPI sanity (rollup read path chạy được, không lỗi) ===")
        for date_from, date_to, capacities in scenarios:
            result = new_downtime(from_date=date_from, to_date=date_to, capacities=capacities, group_by="date")
            ok = "error" not in result and isinstance(result["kpis"]["downtime_hours"], float)
            print(f"  [{'PASS' if ok else 'FAIL'}] date_from={date_from} date_to={date_to} capacities={capacities} -> downtime_hours={result['kpis']['downtime_hours']}")
            failures += 0 if ok else 1

        print("\n=== reports/cleaning_matrix: get_cleaning_matrix() (rollup) vs legacy (raw JOIN + classify) ===")
        for date_from, date_to, capacities in scenarios:
            legacy = legacy_get_cleaning_matrix(date_from, date_to, capacities)
            new = new_cleaning_matrix(date_from, date_to, [float(c) for c in capacities] if capacities else None)
            label = f"date_from={date_from} date_to={date_to} capacities={capacities}"
            ok = True
            if legacy["kpis"] != new["kpis"]:
                ok = False
                print(f"  [FAIL] {label}: kpis legacy={legacy['kpis']} new={new['kpis']}")
            if legacy["available_capacities"] != new["available_capacities"]:
                ok = False
                print(f"  [FAIL] {label}: available_capacities legacy={legacy['available_capacities']} new={new['available_capacities']}")
            if legacy["color_data_coverage"] != new["color_data_coverage"]:
                ok = False
                print(f"  [FAIL] {label}: color_data_coverage legacy={legacy['color_data_coverage']} new={new['color_data_coverage']}")
            # Khoá theo machine_code hoặc machine (raw name) cho dòng 'unmapped' —
            # machine_code=None với MỌI dòng unmapped nên không dùng trực tiếp làm khoá được.
            legacy_by_machine = {(item["machine_code"] or item["machine"]): item for item in legacy["matrix"]}
            new_by_machine = {(item["machine_code"] or item["machine"]): item for item in new["matrix"]}
            if set(legacy_by_machine) != set(new_by_machine):
                ok = False
                print(f"  [FAIL] {label}: bộ máy khác nhau legacy_only={set(legacy_by_machine) - set(new_by_machine)} new_only={set(new_by_machine) - set(legacy_by_machine)}")
            for machine_code, legacy_item in legacy_by_machine.items():
                new_item = new_by_machine.get(machine_code)
                if new_item is None:
                    continue
                for field in ("cleaning_count", "normal_batches", "rd_batches", "rework_batches", "cleaning_ratio", "days"):
                    if legacy_item[field] != new_item[field]:
                        ok = False
                        print(f"  [FAIL] {label}: machine={machine_code} field={field} legacy={legacy_item[field]} new={new_item[field]}")
            print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
            failures += 0 if ok else 1

        print(f"\n{'='*60}\nKẾT QUẢ: {'TẤT CẢ KHỚP' if failures == 0 else f'{failures} SCENARIO LỆCH'}\n{'='*60}")
        return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
