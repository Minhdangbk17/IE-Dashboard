from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask  # noqa: E402

from core.database import close_db  # noqa: E402
from modules.dyeing.engines.batch_matrix.batch_day_trend import (  # noqa: E402
    get_batch_day_trend,
    recompute_all,
    recompute_daily,
)


def _make_temp_app(db_path: str) -> Flask:
    app = Flask(__name__)
    app.config["DATABASE_PATH"] = db_path
    app.config["SQLITE_PRAGMAS"] = {}
    return app


def _init_schema(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE batch_details (id INTEGER PRIMARY KEY AUTOINCREMENT, dyelot TEXT NOT NULL, sap_lot TEXT, "
        "redye REAL DEFAULT 0, greige_code TEXT, fabric_type TEXT, machine TEXT, start_time TEXT, end_time TEXT, "
        "run_time REAL, batch_type TEXT)"
    )
    conn.execute("CREATE TABLE machines (machine_code TEXT, machine_id TEXT, capacity_kg REAL, tank_type TEXT)")
    conn.execute("INSERT INTO machines (machine_code, capacity_kg, tank_type) VALUES ('M1', 500, ' j TANK '), ('M2', 300, NULL)")
    conn.commit()
    conn.close()


def _seed_rows(conn: sqlite3.Connection) -> None:
    rows = [
        ("CL001", "", 0, "", "M1", "2026-06-01 07:00:00", "2026-06-01 09:00:00"),
        ("D0010", "1000", 0, "CVC", "M1", "2026-06-01 09:00:00", "2026-06-01 13:00:00"),
        ("D0020", "3000", 0, "CVC", "M1", "2026-06-01 22:00:00", "2026-06-02 10:00:00"),
        ("D0021", "1000", 0, "CVC", "", "2026-06-02 10:00:00", "2026-06-02 12:00:00"),
        ("D0030", "1000", 1, "CVC", "M1", "2026-06-02 12:00:00", "2026-06-03 07:00:00"),
        ("D0040", "1000", 0, "", "M1", "2026-06-03 08:00:00", "2026-06-03 10:00:00"),
        ("D0050", "1000", 0, "Cotton", "M2", "2026-06-03 07:00:00", "2026-06-03 12:00:00"),
        ("D0060", "4000", 0, "Cotton", "M2", "2026-06-03 12:00:00", "2026-06-03 13:00:00"),
    ]
    conn.executemany(
        "INSERT INTO batch_details (dyelot, sap_lot, redye, fabric_type, machine, start_time, end_time, run_time, batch_type) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 99999, ?)",
        [(*row, "Normal" if row[0][-1] == "0" and not row[2] else "Rework") for row in rows],
    )
    conn.commit()


def _check(label: str, actual, expected, failures: list[str]) -> None:
    ok = actual == expected
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: actual={actual!r} expected={expected!r}")
    if not ok:
        failures.append(label)


def _snapshot(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT production_date, machine, start_time, fabric_type, capacity_kg, hours, is_valid "
        "FROM batch_day_trend_daily_summary ORDER BY production_date, machine, start_time"
    ).fetchall()
    keys = ("production_date", "machine", "start_time", "fabric_type", "capacity_kg", "hours", "is_valid")
    return [dict(zip(keys, row)) for row in rows]


def _run(tmp_dir: str, name: str, action) -> list[dict]:
    db_path = os.path.join(tmp_dir, f"{name}.db")
    _init_schema(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _seed_rows(conn)
    with _make_temp_app(db_path).app_context():
        action(conn)
        conn.commit()
        snapshot = _snapshot(conn)
        conn.close()
        close_db()
    return snapshot


def _day_totals(snapshot: list[dict], day: str, fabric: str) -> tuple[float, int]:
    hours = sum(r["hours"] for r in snapshot if r["production_date"] == day and r["fabric_type"] == fabric)
    count = sum(r["is_valid"] for r in snapshot if r["production_date"] == day and r["fabric_type"] == fabric)
    return round(hours, 4), count


def main() -> int:
    failures: list[str] = []
    tmp_dir = tempfile.mkdtemp()
    day1, day2, day3 = date(2026, 6, 1), date(2026, 6, 2), date(2026, 6, 3)
    try:
        def daily(conn):
            for d in (day1, day2, day3):
                recompute_daily(d, conn)

        snapshot_a = _run(tmp_dir, "a", daily)
        snapshot_b = _run(tmp_dir, "b", lambda conn: recompute_all({day1, day2, day3}, conn))
        snapshot_c = _run(tmp_dir, "c", lambda conn: recompute_all({day1, day3}, conn))

        print("=== recompute_all() vs recompute_daily() lặp từng ngày ===")
        _check("nội dung summary giống hệt", snapshot_b, snapshot_a, failures)

        print("\n=== Giá trị cụ thể ===")
        d1, d2, d3 = day1.isoformat(), day2.isoformat(), day3.isoformat()
        _check("Day1 CVC: 2h CM + 4h + 9h qua đêm = 15h, đếm 1", _day_totals(snapshot_b, d1, "CVC"), (15.0, 1), failures)
        _check("Day2 CVC: 3h + 2h rework + 19h redye = 24h, đếm 1 (mẻ qua đêm)", _day_totals(snapshot_b, d2, "CVC"), (24.0, 1), failures)
        _check("Day3 CVC: không còn đoạn nào (đoạn 0h bị bỏ)", _day_totals(snapshot_b, d3, "CVC"), (0.0, 0), failures)
        _check("Day3 Unknown: mẻ cuối M1 không có mẻ sau", _day_totals(snapshot_b, d3, "Unknown"), (2.0, 1), failures)
        _check("Day3 Cotton: 5h Normal + 1h Sample, đếm 1", _day_totals(snapshot_b, d3, "Cotton"), (6.0, 1), failures)
        machines_day2 = {r["machine"] for r in snapshot_b if r["production_date"] == d2}
        _check("Machine trống được fill-down thành M1", machines_day2, {"M1"}, failures)
        _check("capacity lấy từ bảng machines", {r["capacity_kg"] for r in snapshot_b if r["machine"] == "M2"}, {300.0}, failures)

        print("\n=== recompute_all() với subset ngày ({day1, day3}) ===")
        _check("chỉ có day1 và day3", {r["production_date"] for r in snapshot_c}, {d1, d3}, failures)

        print("\n=== get_batch_day_trend() đọc từ summary ===")
        db_path = os.path.join(tmp_dir, "b.db")
        with _make_temp_app(db_path).app_context():
            trend = get_batch_day_trend(group_by="month")
            trend_j = get_batch_day_trend(group_by="month", tank_types="J tank")
            trend_unclassified = get_batch_day_trend(group_by="month", tank_types="Unclassified")
            close_db()
        cvc = next(r for r in trend["rows"] if r["fabric_type"] == "CVC")
        _check("CVC tháng 6: 2 mẻ * 24 / 39h", cvc["total"], round(2 * 24 / 39, 2), failures)
        _check("KPI/Total số mẻ Normal (CVC 2 + Cotton 1 + Unknown 1: Total KHÔNG quan tâm Fabric Type)", trend["kpis"]["valid_batches"], 4, failures)
        _check("total_row khớp KPI (4 mẻ, 39+6+2=47h)", (trend["total_row"]["total_count"], trend["total_row"]["total_hours"]), (4, 47.0), failures)
        _check("total_row Batch/Day = 4*24/47", trend["total_row"]["total"], round(4 * 24 / 47, 2), failures)

        print("\n=== Bộ lọc Tank Type (tra machines.tank_type tại read time) ===")
        _check("available_tank_types", trend["available_tank_types"], ["J tank", "Unclassified"], failures)
        _check("J tank: chỉ M1 (CVC 2 mẻ + Unknown 1)", trend_j["kpis"]["valid_batches"], 3, failures)
        _check("J tank: Cotton (M2) bị loại", next(r for r in trend_j["rows"] if r["fabric_type"] == "Cotton")["total"], 0.0, failures)
        _check("Unclassified: chỉ M2 (Cotton 1 mẻ / 6h)", trend_unclassified["kpis"]["valid_batches"], 1, failures)
        _check("Unclassified: Cotton = 1*24/6", next(r for r in trend_unclassified["rows"] if r["fabric_type"] == "Cotton")["total"], 4.0, failures)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    if failures:
        print(f"\n{len(failures)} FAILURE(S): {failures}")
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
