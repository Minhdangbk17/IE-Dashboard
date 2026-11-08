from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import Flask  # noqa: E402

from core.database import close_db  # noqa: E402
from modules.dyeing.engines.reports.cleaning_matrix import get_batch_summary  # noqa: E402


def _make_temp_app(db_path: str) -> Flask:
    app = Flask(__name__)
    app.config["DATABASE_PATH"] = db_path
    app.config["SQLITE_PRAGMAS"] = {}
    return app


def _check(label: str, actual, expected, failures: list[str]) -> None:
    ok = actual == expected
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: actual={actual!r} expected={expected!r}")
    if not ok:
        failures.append(label)


def _init_schema(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE cleaning_mc_daily_summary (
            production_date TEXT NOT NULL, availability_log_id INTEGER NOT NULL,
            machine TEXT NOT NULL, batch_type TEXT, badge TEXT NOT NULL,
            is_rework INTEGER NOT NULL DEFAULT 0, dyelot_ref TEXT, sap_lot TEXT,
            redye REAL NOT NULL DEFAULT 0,
            PRIMARY KEY (production_date, availability_log_id)
        )
    """)
    conn.execute("""
        CREATE TABLE machines (
            machine_id TEXT, machine_code TEXT, group_mc TEXT, tank_type TEXT, domain TEXT
        )
    """)
    conn.execute("CREATE TABLE availability_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, batch TEXT, batch_ref_no TEXT, end_time TEXT)")
    conn.execute("CREATE TABLE batch_details (id INTEGER PRIMARY KEY AUTOINCREMENT, dyelot TEXT NOT NULL, machine TEXT, start_time TEXT, end_time TEXT, greige_code TEXT)")
    conn.execute("INSERT INTO machines (machine_id, machine_code, group_mc, tank_type, domain) VALUES ('M1', 'M1', '>=300 to <500Kg', 'J tank', 'dyeing')")
    conn.commit()
    conn.close()


def main() -> int:
    failures: list[str] = []
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        _init_schema(db_path)
        conn = sqlite3.connect(db_path)
        rows = [
            ("2026-01-05", 1, "M1", "Normal", "D", 0, "10011"),
            ("2026-01-06", 2, "M1", "Normal", "M", 0, "20022"),
            ("2026-01-07", 3, "M1", "Normal", "DR", 1, "10033"),
            ("2026-01-08", 4, "M1", "R&D", "L", 0, "30044"),
            ("2026-01-09", 5, "M1", "", "CM", 0, "20055"),
        ]
        conn.executemany(
            "INSERT INTO cleaning_mc_daily_summary (production_date, availability_log_id, machine, batch_type, badge, is_rework, sap_lot) VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
        conn.close()

        app = _make_temp_app(db_path)
        with app.app_context():
            data = get_batch_summary(2026)
            close_db()

        group = next(g for g in data["groups"] if g["group"] == ">=300 to <500Kg")
        tanks_by_label = {t["tank"]: t for t in group["tanks"]}
        jan = 0

        print("=== Kịch bản 0: cấu trúc 3 tầng (chỉ có M1 -> Tank 'J tank') ===")
        _check("group có đúng 2 khối Tank: Subtotal + J tank (không có O tank/Unclassified)", set(tanks_by_label.keys()), {"Subtotal", "J tank"}, failures)

        by_category = {row["category"]: row["values"] for row in tanks_by_label["Subtotal"]["rows"]}

        print("=== Kịch bản 1: Group '>=300 to <500Kg' / Subtotal, tháng 01/2026 ===")
        _check("No. of time Cleaning MC = 1", by_category["No. of time Cleaning MC"][jan], 1, failures)
        _check("No. of normal dyeing batch = 3 (loại Rework, KHÔNG loại R&D nữa)", by_category["No. of normal dyeing batch"][jan], 3, failures)
        _check("Cleaning MC Ratio = Normal/CleaningMC = 3/1 = 3.0", by_category["Cleaning MC Ratio"][jan], 3.0, failures)
        _check("No. of R&D batch = 1 (vẫn đếm riêng, không loại trừ Normal)", by_category["No. of R&D batch"][jan], 1, failures)
        _check("Rework batch = 1", by_category["Rework batch"][jan], 1, failures)
        _check("Rework ratio = Normal/Rework = 3/1 = 3.0", by_category["Rework ratio"][jan], 3.0, failures)
        _check("No. Dyeing machine = 1 (M1 có mẻ thật)", by_category["No. Dyeing machine"][jan], 1, failures)
        _check("No. total day = 31 (tháng 1)", by_category["No. total day"][jan], 31, failures)
        _check("Daily batch/day = Normal/(days*machines) = 3/31", by_category["Daily batch/day"][jan], round(3 / 31, 2), failures)

        all_groups = next(g for g in data["groups"] if g["group"] == "All Groups")
        check_no_tank_split = all_groups["tanks"][0]["tank"] is None and len(all_groups["tanks"]) == 1
        _check("'All Groups' không tách theo Tank (1 khối duy nhất, tank=None)", check_no_tank_split, True, failures)
        all_by_category = {row["category"]: row["values"] for row in all_groups["tanks"][0]["rows"]}
        print("\n=== Kịch bản 2: 'All Groups' cộng dồn đúng (chỉ 1 group nên bằng group con) ===")
        _check("All Groups: No. of normal dyeing batch = 3", all_by_category["No. of normal dyeing batch"][jan], 3, failures)
        _check("All Groups: No. of R&D batch = 1", all_by_category["No. of R&D batch"][jan], 1, failures)
        _check("All Groups: Cleaning MC Ratio = 3.0", all_by_category["Cleaning MC Ratio"][jan], 3.0, failures)

        print("\n=== Kịch bản 3: Sample, tinh luyện, Redye, chờ nhập tay loại hoàn toàn khỏi số đếm ===")
        conn2 = sqlite3.connect(db_path)
        feb_rows = [
            ("2026-02-05", 10, "M1", "Rework", "MR", 1, "C002001", "10077", 3),
            ("2026-02-06", 11, "M1", "Rework", "LR", 1, "C002011", "10088", 0),
            ("2026-02-07", 12, "M1", "", "S", 0, "C002020-DU", "10099", 0),
            ("2026-02-08", 13, "M1", "", "CM", 0, "C002030-WA", "", 0),
            ("2026-02-09", 14, "M1", "Normal", "SC", 0, "C002040", "10011", 0),
            ("2026-02-10", 15, "M1", "Redye", "RD", 0, "C002050", "30011", 0),
            ("2026-02-11", 16, "M1", "Unknown", "?", 0, "C002060", "", 0),
        ]
        conn2.executemany(
            "INSERT INTO cleaning_mc_daily_summary (production_date, availability_log_id, machine, batch_type, badge, is_rework, dyelot_ref, sap_lot, redye) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            feb_rows,
        )
        conn2.commit()
        conn2.close()
        feb = 1

        app2 = _make_temp_app(db_path)
        with app2.app_context():
            february = get_batch_summary(2026)
            close_db()

        group = next(g for g in february["groups"] if g["group"] == ">=300 to <500Kg")
        tanks = {t["tank"]: t for t in group["tanks"]}
        feb_cat = {row["category"]: row["values"] for row in tanks["Subtotal"]["rows"]}

        _check("No. of time Cleaning MC = 1 (chỉ CM)", feb_cat["No. of time Cleaning MC"][feb], 1, failures)
        _check("No. of normal dyeing batch = 0 (SC, RD, ?, S không đếm)", feb_cat["No. of normal dyeing batch"][feb], 0, failures)
        _check("Rework batch = 2", feb_cat["Rework batch"][feb], 2, failures)
        _check("No. Dyeing machine = 1 (chỉ máy có Rework)", feb_cat["No. Dyeing machine"][feb], 1, failures)
    finally:
        try:
            os.unlink(db_path)
        except PermissionError:
            pass

    print(f"\n{'='*60}\nKẾT QUẢ: {'TẤT CẢ KHỚP' if not failures else f'{len(failures)} CASE LỆCH'}\n{'='*60}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
