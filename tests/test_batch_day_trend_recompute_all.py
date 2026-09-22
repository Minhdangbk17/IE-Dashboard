"""
tests/test_batch_day_trend_recompute_all.py
---------------------------------------------
Verify `batch_day_trend.recompute_all()` (2026-09-18) cho kết quả GIỐNG HỆT gọi
`recompute_daily()` lần lượt cho từng ngày — chỉ khác ở hiệu năng (fetch + sort lịch sử
mỗi máy ĐÚNG 1 lần thay vì N lần, N = số ngày).

Bug thật đã phát hiện trên production: DB chỉ có dữ liệu Batch/Day Trend cho 6 ngày đầu
06/2026 dù `availability_logs` có dữ liệu tới ngày hiện tại — do `flask rebuild-summaries`
gọi `recompute_daily()` riêng lẻ cho hàng trăm ngày, mỗi lần fetch+sort lại NGUYÊN VẸN lịch
sử từng máy (rất chậm qua kết nối Postgres remote), khiến tiến trình bị coi là "treo" và bị
ngắt giữa chừng (chỉ xử lý xong vài ngày ĐẦU TIÊN theo thứ tự tăng dần).

Kịch bản test: máy M1 có chuỗi mẻ trải qua 3 ngày, XEN KẼ mẻ FabricType "Unknow" (carry giờ
sang mẻ thật kế tiếp) — đúng tình huống carry-forward XUYÊN NGÀY mà thuật toán phải xử lý
đúng. Verify `recompute_all({day1,day2,day3})` cho ra CÙNG kết quả với việc reset DB rồi gọi
`recompute_daily(day1)` + `recompute_daily(day2)` + `recompute_daily(day3)` liên tiếp.

Chạy: python tests/test_batch_day_trend_recompute_all.py
"""
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
from modules.dyeing.engines.batch_matrix.batch_day_trend import recompute_all, recompute_daily  # noqa: E402


def _make_temp_app(db_path: str) -> Flask:
    app = Flask(__name__)
    app.config["DATABASE_PATH"] = db_path
    app.config["SQLITE_PRAGMAS"] = {}
    return app


def _init_schema(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE availability_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch TEXT, batch_ref_no TEXT, fabric_type TEXT, machine TEXT, capacity_kg REAL,
            start_time TEXT, end_time TEXT, planned_prd_time_hour REAL, rework_hour REAL DEFAULT 0
        )
    """)
    conn.execute("CREATE TABLE batch_details (id INTEGER PRIMARY KEY AUTOINCREMENT, dyelot TEXT NOT NULL, greige_code TEXT, fabric_type TEXT, shade TEXT, colour_no TEXT, batch_type TEXT, machine TEXT, start_time TEXT, end_time TEXT, run_time REAL, is_rework INTEGER)")
    conn.execute("CREATE UNIQUE INDEX uq_batch_details_dyelot_machine_start ON batch_details(dyelot, machine, start_time)")
    conn.execute("CREATE TABLE machines (machine_code TEXT, machine_id TEXT, mc_brand TEXT, tank_type TEXT, mc_quantity INTEGER, tube_no INTEGER, capacity_kg REAL)")
    conn.commit()
    conn.close()


def _seed_rows(conn: sqlite3.Connection) -> None:
    # M1: Unknown(carry 2h) -> Real A (day1, absorbs carry) -> Unknown(carry 3h) ->
    # Real B (day2, absorbs carry) -> Real C (day3, no carry).
    conn.executemany(
        "INSERT INTO availability_logs (batch, fabric_type, machine, capacity_kg, start_time, end_time, planned_prd_time_hour, rework_hour) VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
        [
            ("M1-U1", "Unknow", "M1", 500, "2026-06-01 07:00:00", "2026-06-01 09:00:00", 2),
            ("M1-A", "CVC", "M1", 500, "2026-06-01 09:00:00", "2026-06-01 13:00:00", 4),
            ("M1-U2", "Unknow", "M1", 500, "2026-06-02 07:00:00", "2026-06-02 10:00:00", 3),
            ("M1-B", "CVC", "M1", 500, "2026-06-02 10:00:00", "2026-06-02 14:00:00", 4),
            ("M1-C", "CVC", "M1", 500, "2026-06-03 07:00:00", "2026-06-03 12:00:00", 5),
        ],
    )
    conn.commit()


def _check(label: str, actual, expected, failures: list[str]) -> None:
    ok = actual == expected
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: actual={actual!r} expected={expected!r}")
    if not ok:
        failures.append(label)


def _snapshot(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT production_date, machine, start_time, fabric_type, hours, is_valid "
        "FROM batch_day_trend_daily_summary ORDER BY production_date, start_time"
    ).fetchall()
    return [dict(zip(("production_date", "machine", "start_time", "fabric_type", "hours", "is_valid"), row)) for row in rows]


def main() -> int:
    failures: list[str] = []
    tmp_dir = tempfile.mkdtemp()
    try:
        day1, day2, day3 = date(2026, 6, 1), date(2026, 6, 2), date(2026, 6, 3)

        # --- Bản A: gọi recompute_daily() lần lượt từng ngày (baseline cũ). ---
        db_a = os.path.join(tmp_dir, "a.db")
        _init_schema(db_a)
        conn_a = sqlite3.connect(db_a)
        conn_a.row_factory = sqlite3.Row
        _seed_rows(conn_a)
        app_a = _make_temp_app(db_a)
        with app_a.app_context():
            recompute_daily(day1, conn_a)
            recompute_daily(day2, conn_a)
            recompute_daily(day3, conn_a)
            conn_a.commit()
            snapshot_a = _snapshot(conn_a)
            conn_a.close()
            close_db()

        # --- Bản B: gọi recompute_all() 1 lần cho cả 3 ngày (đường mới). ---
        db_b = os.path.join(tmp_dir, "b.db")
        _init_schema(db_b)
        conn_b = sqlite3.connect(db_b)
        conn_b.row_factory = sqlite3.Row
        _seed_rows(conn_b)
        app_b = _make_temp_app(db_b)
        with app_b.app_context():
            recompute_all({day1, day2, day3}, conn_b)
            conn_b.commit()
            snapshot_b = _snapshot(conn_b)
            conn_b.close()
            close_db()

        print("=== So khớp recompute_all({3 ngày}) vs recompute_daily() lặp từng ngày ===")
        _check("số dòng summary bằng nhau", len(snapshot_b), len(snapshot_a), failures)
        _check("nội dung summary giống hệt", snapshot_b, snapshot_a, failures)

        print("\n=== Xác nhận carry-forward xuyên ngày tính đúng (giá trị cụ thể) ===")
        by_day = {row["production_date"]: row for row in snapshot_b}
        _check("Day1 (M1-A): 2h carry + 4h = 6h", by_day.get(day1.isoformat(), {}).get("hours"), 6.0, failures)
        _check("Day2 (M1-B): 3h carry + 4h = 7h", by_day.get(day2.isoformat(), {}).get("hours"), 7.0, failures)
        _check("Day3 (M1-C): không carry = 5h", by_day.get(day3.isoformat(), {}).get("hours"), 5.0, failures)

        # --- Bản C: recompute_all() chỉ với 1 SUBSET ngày ({day1, day3}, bỏ day2) — xác
        # nhận day2 không bị đưa vào (đúng ngữ nghĩa "chỉ tính các ngày được yêu cầu"). ---
        db_c = os.path.join(tmp_dir, "c.db")
        _init_schema(db_c)
        conn_c = sqlite3.connect(db_c)
        conn_c.row_factory = sqlite3.Row
        _seed_rows(conn_c)
        app_c = _make_temp_app(db_c)
        with app_c.app_context():
            recompute_all({day1, day3}, conn_c)
            conn_c.commit()
            snapshot_c = _snapshot(conn_c)
            conn_c.close()
            close_db()

        print("\n=== recompute_all() với subset ngày ({day1, day3}, bỏ day2) ===")
        days_present = {row["production_date"] for row in snapshot_c}
        _check("chỉ có day1 và day3, KHÔNG có day2", days_present, {day1.isoformat(), day3.isoformat()}, failures)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    if failures:
        print(f"\n{len(failures)} FAILURE(S): {failures}")
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
