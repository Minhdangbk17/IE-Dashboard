"""
tests/test_batch_source_consistency.py
---------------------------------------
2026-10-02 — báo cáo Batch (`batch_details`) là NGUỒN SỰ THẬT DUY NHẤT cho CẢ "Batch/Day Trend"
lẫn "Batch Per Day by Machine" (`core/batch_source.py`). Kiểm tra:

  1. Batch Per Day by Machine KHÔNG đọc `availability_logs` (dòng Availability mâu thuẫn bị bỏ qua).
  2. Machine trống -> Machine dòng phía trên; FabricType trống -> FabricType mẻ kế tiếp cùng máy.
  3. production_date = ngày kết thúc 07:00->07:00 (mẻ qua đêm -> ngày sau; kết thúc đúng
     07:00:00 -> ngày trước).
  4. Số mẻ Normal theo (ngày, loại vải) của 2 báo cáo KHỚP NHAU.

Chạy: python tests/test_batch_source_consistency.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.dyeing.engines.batch_matrix import batch_day_trend  # noqa: E402
from modules.dyeing.engines.reports import cleaning_matrix  # noqa: E402

# (dyelot, machine, fabric_type, sap_lot, redye, start, end)
BATCHES = [
    ("C100000", "M1", "Cotton", "1000000001", 0, "2026-09-01 08:00:00", "2026-09-01 10:00:00"),
    # Machine trống -> M1 (dòng trên); FabricType trống -> CVC (mẻ kế tiếp trên M1).
    ("C100010", "", "", "1000000002", 0, "2026-09-01 11:00:00", "2026-09-01 13:00:00"),
    # Rework (Dyelot không kết thúc bằng 0), kết thúc ĐÚNG 07:00:00 -> thuộc ngày 2026-09-01.
    ("C100021", "M1", "CVC", "1000000003", 0, "2026-09-01 14:00:00", "2026-09-02 07:00:00"),
    # Qua đêm -> ngày kết thúc 2026-09-02.
    ("C100030", "M2", "Polyester", "3000000004", 0, "2026-09-01 22:00:00", "2026-09-02 09:00:00"),
]


def _check(label: str, actual, expected, failures: list[str]) -> None:
    ok = actual == expected
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: actual={actual!r} expected={expected!r}")
    if not ok:
        failures.append(label)


def _init_db(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE batch_details (
            id INTEGER PRIMARY KEY AUTOINCREMENT, dyelot TEXT NOT NULL, sap_lot TEXT, redye REAL DEFAULT 0,
            shade TEXT, colour_no TEXT, recipe_no TEXT, customer_color TEXT, batch_type TEXT,
            is_rework INTEGER DEFAULT 0, run_time REAL DEFAULT 0, greige_code TEXT,
            machine TEXT, fabric_type TEXT, start_time TEXT, end_time TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE availability_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, batch TEXT, batch_ref_no TEXT, machine TEXT,
            capacity_kg REAL, fabric_type TEXT, start_time TEXT, end_time TEXT
        )
    """)
    conn.execute("CREATE TABLE machines (machine_id TEXT, machine_code TEXT, mc_brand TEXT, tank_type TEXT, mc_quantity INTEGER, tube_no INTEGER, capacity_kg REAL, domain TEXT)")
    conn.executemany(
        "INSERT INTO batch_details (dyelot, machine, fabric_type, sap_lot, redye, start_time, end_time, shade) VALUES (?, ?, ?, ?, ?, ?, ?, 'Dark')",
        BATCHES,
    )
    # Dòng Availability MÂU THUẪN (máy/loại vải/ngày khác) — phải bị bỏ qua hoàn toàn.
    conn.execute(
        "INSERT INTO availability_logs (batch, machine, capacity_kg, fabric_type, start_time, end_time) VALUES (?, ?, ?, ?, ?, ?)",
        ("C100000", "M9", 600, "Polyester", "2026-09-05 08:00:00", "2026-09-05 10:00:00"),
    )
    conn.commit()
    conn.close()


def main() -> int:
    failures: list[str] = []
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        _init_db(db_path)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        days = [date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 5)]
        cleaning_matrix.recompute_all(days, conn)
        batch_day_trend.recompute_all(days, conn)
        conn.commit()

        print("\n=== Batch Per Day by Machine: mẻ lấy từ batch_details ===")
        rows = {
            row["dyelot_ref"]: dict(row)
            for row in conn.execute("SELECT production_date, machine, fabric_type, badge, dyelot_ref FROM cleaning_mc_daily_summary")
        }
        _check("Đủ 4 mẻ (không thêm/bớt theo Availability)", sorted(rows), sorted(b[0] for b in BATCHES), failures)
        _check("Không có máy M9 / ngày 2026-09-05 từ Availability",
               any(r["machine"] == "M9" or r["production_date"] == "2026-09-05" for r in rows.values()), False, failures)
        _check("C100000: M1 / Cotton / 2026-09-01",
               (rows["C100000"]["machine"], rows["C100000"]["fabric_type"], rows["C100000"]["production_date"]),
               ("M1", "Cotton", "2026-09-01"), failures)
        _check("C100010: Machine fill-down M1, FabricType fill-up CVC",
               (rows["C100010"]["machine"], rows["C100010"]["fabric_type"]), ("M1", "CVC"), failures)
        _check("C100021: kết thúc đúng 07:00 -> 2026-09-01, Rework",
               (rows["C100021"]["production_date"], rows["C100021"]["badge"].endswith("R")), ("2026-09-01", True), failures)
        _check("C100030: qua đêm -> ngày kết thúc 2026-09-02", rows["C100030"]["production_date"], "2026-09-02", failures)

        print("\n=== Số mẻ Normal 2 báo cáo khớp nhau theo (ngày, loại vải) ===")
        cleaning_normal = Counter(
            (r["production_date"], r["fabric_type"]) for r in rows.values()
            if r["badge"] not in ("CM", "S") and not r["badge"].endswith("R")
        )
        trend_normal: Counter = Counter()
        for r in conn.execute("SELECT production_date, fabric_type, is_valid FROM batch_day_trend_daily_summary"):
            if r["is_valid"]:
                trend_normal[(r["production_date"], r["fabric_type"])] += r["is_valid"]
        _check("Normal Batch Per Day by Machine == Normal Batch/Day Trend", dict(cleaning_normal), dict(trend_normal), failures)
        _check("Normal đúng kỳ vọng", dict(trend_normal),
               {("2026-09-01", "Cotton"): 1, ("2026-09-01", "CVC"): 1, ("2026-09-02", "Polyester"): 1}, failures)
        conn.close()
    finally:
        os.unlink(db_path)

    print(f"\n{'=' * 60}\nKẾT QUẢ: {'TẤT CẢ KHỚP' if not failures else f'{len(failures)} CASE LỆCH'}\n{'=' * 60}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
