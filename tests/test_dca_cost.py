"""
tests/test_dca_cost.py
------------------------
Verify Engine `dca_cost` (DCA Cost = Sum(DyeCost) / Sum(số dyelot), phân theo 3 loại vải
chính (Cotton/CVC/Polyester) x 5 nhóm màu (Dark/Light/Medium/Black/White)):
  1. `_classify_color()` phân loại đúng 5 nhóm màu (Black/White qua từ khoá, Dark/Medium/
     Light qua Shade rồi fallback qua từ khoá, mặc định Medium).
  2. `get_dca_cost_data()`: công thức Sum(dye_cost)/COUNT(dyelot) đúng ở CẢ cấp ô-theo-kỳ
     LẪN cấp Total (Sum/Sum, KHÔNG phải trung bình cộng các ô-theo-kỳ).
  3. Loại vải ngoài Cotton/CVC/Polyester bị loại khỏi báo cáo hoàn toàn.
  4. Filter Capacity (qua LEFT JOIN availability_logs) loại đúng dòng không khớp.
  5. Mẻ thiếu start_time/end_time rơi vào bucket "Unknown Date" khi không lọc ngày, bị loại
     khi lọc ngày tường minh.

Dùng DB TẠM (file SQLite tạm + Flask app context tạm), KHÔNG đụng DB thật — cùng pattern
`tests/test_rft_classification.py`.

Chạy: python tests/test_dca_cost.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import Flask  # noqa: E402

from core.database import close_db  # noqa: E402
from modules.dyeing.engines.dca_cost.service import _classify_color, get_dca_cost_data  # noqa: E402


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
            batch TEXT, capacity_kg REAL, start_time TEXT, end_time TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE batch_details (
            dyelot TEXT PRIMARY KEY, dye_cost REAL NOT NULL DEFAULT 0, fabric_type TEXT,
            shade TEXT, colour_no TEXT, recipe_no TEXT, customer_color TEXT, greige_code TEXT,
            start_time TEXT, end_time TEXT
        )
    """)
    conn.commit()
    conn.close()


def _check(label: str, actual, expected, failures: list[str]) -> None:
    ok = actual == expected
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: actual={actual!r} expected={expected!r}")
    if not ok:
        failures.append(label)


def _scenario_classify_color(failures: list[str]) -> None:
    print("\n=== Kịch bản 1: _classify_color() phân loại đúng 5 nhóm màu ===")
    cases = [
        ({"colour_no": "115-23-11-BLACK", "recipe_no": "", "customer_color": "", "shade": ""}, "Black"),
        ({"colour_no": "010-BLK-SOLID", "recipe_no": "", "customer_color": "", "shade": ""}, "Black"),
        ({"colour_no": "096-70-05-WHITE", "recipe_no": "", "customer_color": "", "shade": ""}, "White"),
        ({"colour_no": "", "recipe_no": "", "customer_color": "", "shade": "Dark"}, "Dark"),
        ({"colour_no": "", "recipe_no": "", "customer_color": "", "shade": "Medium"}, "Medium"),
        ({"colour_no": "", "recipe_no": "", "customer_color": "", "shade": "Light"}, "Light"),
        ({"colour_no": "115-23-11-MARINE BLUE", "recipe_no": "", "customer_color": "", "shade": ""}, "Dark"),
        ({"colour_no": "096-70-05-MORDEN MINT", "recipe_no": "", "customer_color": "", "shade": ""}, "Light"),
        ({"colour_no": "096-70-05-GREY HEATHER", "recipe_no": "", "customer_color": "", "shade": ""}, "Medium"),
        ({"colour_no": "", "recipe_no": "", "customer_color": "", "shade": ""}, "Medium"),
    ]
    for row, expected in cases:
        _check(f"colour_no={row['colour_no']!r} shade={row['shade']!r}", _classify_color(row), expected, failures)


def _insert_batch(conn: sqlite3.Connection, **overrides: object) -> None:
    record = {
        "dyelot": "", "dye_cost": 0, "fabric_type": "", "shade": "", "colour_no": "",
        "recipe_no": "", "customer_color": "", "greige_code": "", "start_time": "", "end_time": "",
    }
    record.update(overrides)
    columns = ",".join(record.keys())
    placeholders = ",".join("?" for _ in record)
    conn.execute(f"INSERT INTO batch_details ({columns}) VALUES ({placeholders})", tuple(record.values()))


def _scenario_formula_and_fabric_scope(failures: list[str]) -> None:
    print("\n=== Kịch bản 2: công thức Sum/Sum + loại vải ngoài 3 loại chính ===")
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        _init_schema(db_path)
        conn = sqlite3.connect(db_path)

        # Cotton/Dark: kỳ 1 (2 mẻ: 100 + 200), kỳ 2 (1 mẻ: 300) -> Total PHẢI = (100+200+300)/3
        # = 200, KHÔNG PHẢI trung bình cộng 2 ô-theo-kỳ (150 và 300 -> 225, SAI).
        conn.execute(
            "INSERT INTO availability_logs (batch, capacity_kg, start_time, end_time) VALUES (?, ?, ?, ?)",
            ("CT-DARK-1", 600, "2026-09-01 08:00:00", "2026-09-01 10:00:00"),
        )
        _insert_batch(conn, dyelot="CT-DARK-1", dye_cost=100, fabric_type="Cotton", shade="Dark", start_time="2026-09-01 08:00:00", end_time="2026-09-01 10:00:00")
        conn.execute(
            "INSERT INTO availability_logs (batch, capacity_kg, start_time, end_time) VALUES (?, ?, ?, ?)",
            ("CT-DARK-2", 600, "2026-09-02 08:00:00", "2026-09-02 10:00:00"),
        )
        _insert_batch(conn, dyelot="CT-DARK-2", dye_cost=200, fabric_type="Cotton", shade="Dark", start_time="2026-09-02 08:00:00", end_time="2026-09-02 10:00:00")
        conn.execute(
            "INSERT INTO availability_logs (batch, capacity_kg, start_time, end_time) VALUES (?, ?, ?, ?)",
            ("CT-DARK-3", 600, "2026-09-08 08:00:00", "2026-09-08 10:00:00"),
        )
        _insert_batch(conn, dyelot="CT-DARK-3", dye_cost=300, fabric_type="Cotton", shade="Dark", start_time="2026-09-08 08:00:00", end_time="2026-09-08 10:00:00")

        # 1 mẻ CVC/White (kỳ 1) — dùng để verify tab "Overview" gộp ĐÚNG cả Cotton lẫn CVC.
        conn.execute(
            "INSERT INTO availability_logs (batch, capacity_kg, start_time, end_time) VALUES (?, ?, ?, ?)",
            ("CVC-WHITE-1", 600, "2026-09-01 08:00:00", "2026-09-01 10:00:00"),
        )
        _insert_batch(conn, dyelot="CVC-WHITE-1", dye_cost=50, fabric_type="CVC", colour_no="WHITE SOLID", start_time="2026-09-01 08:00:00", end_time="2026-09-01 10:00:00")

        # Nylon: PHẢI bị loại hoàn toàn khỏi báo cáo (không phải 1 trong 3 loại chính, kể cả
        # tab "Overview").
        conn.execute(
            "INSERT INTO availability_logs (batch, capacity_kg, start_time, end_time) VALUES (?, ?, ?, ?)",
            ("NY-1", 600, "2026-09-01 08:00:00", "2026-09-01 10:00:00"),
        )
        _insert_batch(conn, dyelot="NY-1", dye_cost=999, fabric_type="Nylon", shade="Dark", start_time="2026-09-01 08:00:00", end_time="2026-09-01 10:00:00")
        conn.commit()
        conn.close()

        app = _make_temp_app(db_path)
        with app.app_context():
            data = get_dca_cost_data(capacities="600", from_date="2026-09-01", to_date="2026-09-14", group_by="week")
            close_db()

        cotton_rows = {row["color"]: row for row in data["fabrics"]["Cotton"]["rows"]}
        _check("Cotton/Dark: 2 kỳ (week 1 có 2 mẻ, week 2 có 1 mẻ)", len(data["periods"]), 2, failures)
        _check("Cotton/Dark: giá trị kỳ 1 = (100+200)/2 = 150.0", cotton_rows["Dark"]["values"][0], 150.0, failures)
        _check("Cotton/Dark: giá trị kỳ 2 = 300.0", cotton_rows["Dark"]["values"][1], 300.0, failures)
        _check("Cotton/Dark: Total = Sum/Sum = (100+200+300)/3 = 200.0 (KHÔNG PHẢI TB cộng 150/300)", cotton_rows["Dark"]["total"], 200.0, failures)
        _check("Cotton KPI: total_dye_cost = 600.0", data["fabrics"]["Cotton"]["kpis"]["total_dye_cost"], 600.0, failures)
        _check("Cotton KPI: total_batches = 3", data["fabrics"]["Cotton"]["kpis"]["total_batches"], 3, failures)
        _check("Cotton KPI: dca_cost = 600/3 = 200.0", data["fabrics"]["Cotton"]["kpis"]["dca_cost"], 200.0, failures)
        _check("CVC KPI: total_batches = 1 (mẻ CVC-WHITE-1)", data["fabrics"]["CVC"]["kpis"]["total_batches"], 1, failures)
        _check("Chỉ có đúng 4 tab Overview/Cotton/CVC/Polyester (Nylon không có tab riêng)", sorted(data["fabrics"].keys()), ["CVC", "Cotton", "Overview", "Polyester"], failures)

        overview_kpis = data["fabrics"]["Overview"]["kpis"]
        _check("Overview: total_batches = 4 (3 Cotton + 1 CVC, KHÔNG tính Nylon)", overview_kpis["total_batches"], 4, failures)
        _check("Overview: total_dye_cost = 650.0 (600 Cotton + 50 CVC)", overview_kpis["total_dye_cost"], 650.0, failures)
        _check("Overview: dca_cost = 650/4 = 162.5", overview_kpis["dca_cost"], 162.5, failures)
        overview_rows = {row["color"]: row for row in data["fabrics"]["Overview"]["rows"]}
        _check("Overview/Dark: total = 200.0 (chỉ Cotton có màu Dark)", overview_rows["Dark"]["total"], 200.0, failures)
        _check("Overview/White: total = 50.0 (chỉ CVC có màu White)", overview_rows["White"]["total"], 50.0, failures)
    finally:
        os.unlink(db_path)


def _scenario_capacity_filter(failures: list[str]) -> None:
    print("\n=== Kịch bản 3: filter Capacity loại đúng dòng không khớp availability_logs ===")
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        _init_schema(db_path)
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO availability_logs (batch, capacity_kg, start_time, end_time) VALUES (?, ?, ?, ?)",
            ("CAP-MATCH", 600, "2026-09-05 08:00:00", "2026-09-05 10:00:00"),
        )
        _insert_batch(conn, dyelot="CAP-MATCH", dye_cost=100, fabric_type="Polyester", shade="Medium", start_time="2026-09-05 08:00:00", end_time="2026-09-05 10:00:00")
        # Khớp availability_logs nhưng capacity KHÁC 600 -> bị loại khi filter capacities=600.
        conn.execute(
            "INSERT INTO availability_logs (batch, capacity_kg, start_time, end_time) VALUES (?, ?, ?, ?)",
            ("CAP-OTHER", 1200, "2026-09-05 08:00:00", "2026-09-05 10:00:00"),
        )
        _insert_batch(conn, dyelot="CAP-OTHER", dye_cost=999, fabric_type="Polyester", shade="Medium", start_time="2026-09-05 08:00:00", end_time="2026-09-05 10:00:00")
        conn.commit()
        conn.close()

        app = _make_temp_app(db_path)
        with app.app_context():
            filtered = get_dca_cost_data(capacities="600", group_by="week")
            unfiltered = get_dca_cost_data(group_by="week")
            close_db()

        _check("Lọc capacities=600: chỉ đếm CAP-MATCH (total_batches=1)", filtered["fabrics"]["Polyester"]["kpis"]["total_batches"], 1, failures)
        _check("Lọc capacities=600: dca_cost = 100.0 (loại CAP-OTHER)", filtered["fabrics"]["Polyester"]["kpis"]["dca_cost"], 100.0, failures)
        _check("Không lọc Capacity: đếm CẢ 2 mẻ (total_batches=2)", unfiltered["fabrics"]["Polyester"]["kpis"]["total_batches"], 2, failures)
    finally:
        os.unlink(db_path)


def _scenario_unknown_date_bucket(failures: list[str]) -> None:
    print("\n=== Kịch bản 4: mẻ thiếu start/end time -> bucket 'Unknown Date' ===")
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        _init_schema(db_path)
        conn = sqlite3.connect(db_path)
        _insert_batch(conn, dyelot="NO-DATE", dye_cost=50, fabric_type="CVC", shade="Light", start_time="", end_time="")
        conn.execute(
            "INSERT INTO availability_logs (batch, capacity_kg, start_time, end_time) VALUES (?, ?, ?, ?)",
            ("HAS-DATE", 600, "2026-09-05 08:00:00", "2026-09-05 10:00:00"),
        )
        _insert_batch(conn, dyelot="HAS-DATE", dye_cost=150, fabric_type="CVC", shade="Light", start_time="2026-09-05 08:00:00", end_time="2026-09-05 10:00:00")
        conn.commit()
        conn.close()

        app = _make_temp_app(db_path)
        with app.app_context():
            no_date_filter = get_dca_cost_data(group_by="date")
            with_date_filter = get_dca_cost_data(from_date="2026-09-05", to_date="2026-09-05", group_by="date")
            close_db()

        _check("Không lọc ngày: total_batches = 2 (giữ cả mẻ thiếu ngày)", no_date_filter["fabrics"]["CVC"]["kpis"]["total_batches"], 2, failures)
        _check("Không lọc ngày: có period 'Unknown Date'", "Unknown Date" in no_date_filter["periods"], True, failures)
        _check("Có lọc ngày tường minh: total_batches = 1 (loại mẻ thiếu ngày)", with_date_filter["fabrics"]["CVC"]["kpis"]["total_batches"], 1, failures)
    finally:
        os.unlink(db_path)


def main() -> int:
    failures: list[str] = []
    _scenario_classify_color(failures)
    _scenario_formula_and_fabric_scope(failures)
    _scenario_capacity_filter(failures)
    _scenario_unknown_date_bucket(failures)
    print(f"\n{'='*60}\nKẾT QUẢ: {'TẤT CẢ KHỚP' if not failures else f'{len(failures)} CASE LỆCH'}\n{'='*60}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
