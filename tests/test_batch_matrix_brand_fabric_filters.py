from __future__ import annotations

import io
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import Flask  # noqa: E402
from openpyxl import load_workbook  # noqa: E402

from core.database import close_db  # noqa: E402
from modules.dyeing.engines.batch_matrix.service import build_matrix, export_matrix_excel, get_cell_batches  # noqa: E402

DAY1, DAY2 = "2026-09-01", "2026-09-02"


def _make_temp_app(db_path: str) -> Flask:
    app = Flask(__name__)
    app.config["DATABASE_PATH"] = db_path
    app.config["SQLITE_PRAGMAS"] = {}
    return app


def _init_db(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE availability_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch TEXT, batch_ref_no TEXT, fabric_type TEXT, machine TEXT, capacity_kg REAL,
            start_time TEXT, end_time TEXT
        )
    """)
    conn.execute(
        "CREATE TABLE batch_details (id INTEGER PRIMARY KEY AUTOINCREMENT, dyelot TEXT NOT NULL, shade TEXT, colour_no TEXT, "
        "batch_type TEXT, greige_code TEXT, fabric_type TEXT, machine TEXT, start_time TEXT, end_time TEXT, sap_lot TEXT, redye REAL DEFAULT 0)"
    )
    conn.execute("CREATE TABLE machines (machine_code TEXT, machine_id TEXT, capacity_kg REAL, tank_type TEXT)")
    conn.execute("INSERT INTO machines (machine_code, capacity_kg, tank_type) VALUES ('M1', 600, 'J tank'), ('M2', 300, NULL)")
    conn.executemany(
        "INSERT INTO availability_logs (batch, fabric_type, machine, capacity_kg, start_time, end_time) VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("M1-UQ0", "CVC", "M1", 600, "2026-09-01 07:00:00", "2026-09-01 11:00:00"),
            ("M1-NIKE0", "CVC", "M1", 600, "2026-09-01 11:00:00", "2026-09-01 16:00:00"),
            ("M2-UQ0", "CVC", "M2", 999, "2026-09-01 07:00:00", "2026-09-01 13:00:00"),
            ("M2-RD0", "CVC", "M2", 999, "2026-09-02 07:00:00", "2026-09-02 15:00:00"),
            ("M2-RW1", "CVC", "M2", 999, "2026-09-02 15:00:00", "2026-09-02 16:00:00"),
        ],
    )
    conn.executemany(
        "INSERT INTO batch_details (dyelot, shade, colour_no, batch_type, greige_code, sap_lot, redye) VALUES (?, 'Dark', '091-NAVY', ?, ?, '1000', ?)",
        [("M1-UQ0", "Normal", "G1", 0), ("M1-NIKE0", "Normal", "G2", 0), ("M2-UQ0", "Normal", "G1", 0), ("M2-RD0", "Rework", "G1", 1), ("M2-RW1", "Rework", "G1", 0)],
    )
    conn.execute(
        "UPDATE batch_details SET "
        "machine = (SELECT a.machine FROM availability_logs a WHERE a.batch = batch_details.dyelot), "
        "fabric_type = (SELECT a.fabric_type FROM availability_logs a WHERE a.batch = batch_details.dyelot), "
        "start_time = (SELECT a.start_time FROM availability_logs a WHERE a.batch = batch_details.dyelot), "
        "end_time = (SELECT a.end_time FROM availability_logs a WHERE a.batch = batch_details.dyelot)"
    )
    conn.commit()
    conn.close()


def _check(label: str, actual, expected, failures: list[str], tolerance: float = 0.0) -> None:
    ok = actual is not None and abs(actual - expected) <= tolerance if tolerance else actual == expected
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: actual={actual} expected={expected}")
    if not ok:
        failures.append(label)


def _cvc_dark(data: dict) -> dict:
    return next(r for r in data["rows"] if r["row_type"] == "data" and r["fabric_type"] == "CVC" and r["color_group"] == "Dark")


def main() -> int:
    failures: list[str] = []
    tmp_dir = tempfile.mkdtemp()
    try:
        db_path = os.path.join(tmp_dir, "test.db")
        _init_db(db_path)
        with _make_temp_app(db_path).app_context():
            from core.brand_program_importer import ensure_brand_program_table
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            ensure_brand_program_table(conn)
            conn.execute("INSERT INTO brand_program_mapping (greige_code, brand, brand_program) VALUES ('G1', 'UQ', 'Ht Fleece')")
            conn.execute("INSERT INTO brand_program_mapping (greige_code, brand, brand_program) VALUES ('G2', 'Nike', 'Performance')")
            conn.commit()
            conn.close()

            print("=== Kịch bản 1: không lọc (Group By Day, ReDye = 0 bật) ===")
            data = build_matrix(group_by="date")
            _check("ngày 1 CVC/Dark = 3*24/15", _cvc_dark(data)["values"][DAY1], 4.8, failures, tolerance=0.01)
            _check("ngày 2 = 0 (9h ReDye/Rework, không mẻ Normal)", _cvc_dark(data)["values"].get(DAY2), 0.0, failures)
            _check("available_brand_programs", data["available_brand_programs"], ["Nike - Performance", "UQ - Ht Fleece"], failures)
            _check("available_tank_types", data["available_tank_types"], ["J tank", "Unclassified"], failures)
            _check("available_capacities lấy từ Machine Master (không có 999)", data["available_capacities"], [300.0, 600.0], failures)
            _check("không còn Fabric Type filter", "available_fabric_types" in data, False, failures)

            print("\n=== Kịch bản 2: Brand Program — mẫu số = giờ các mẻ thuộc brand ===")
            _check("brand=UQ (2*24/10)", _cvc_dark(build_matrix(brand_programs="UQ - Ht Fleece"))["values"][DAY1], 4.8, failures, tolerance=0.01)
            _check("brand=Nike (1*24/5)", _cvc_dark(build_matrix(brand_programs="Nike - Performance"))["values"][DAY1], 4.8, failures, tolerance=0.01)

            print("\n=== Kịch bản 3: Tank Type + Capacity ===")
            _check("tank=J tank: chỉ M1 (2*24/9)", _cvc_dark(build_matrix(tank_types="J tank"))["values"][DAY1], 5.33, failures, tolerance=0.01)
            _check("capacity=300: chỉ M2 (1*24/6)", _cvc_dark(build_matrix(capacities="300"))["values"][DAY1], 4.0, failures, tolerance=0.01)

            print("\n=== Kịch bản 4: Group By Week ===")
            week = build_matrix(group_by="week")
            _check("week: 1 cột W36", week["period_keys"], ["2026-W36"], failures)
            _check("week (ReDye bật) = 3*24/(15+9), giờ ngày 2 vẫn tính", _cvc_dark(week)["values"]["2026-W36"], 3.0, failures, tolerance=0.01)

            print("\n=== Kịch bản 5: drill-down + Export ===")
            _check("ô ngày 1 brand=UQ -> 2 mẻ", len(get_cell_batches("CVC", "Dark", DAY1, brand_programs="UQ - Ht Fleece")), 2, failures)
            _check("ô Total (period rỗng) -> 3 mẻ", len(get_cell_batches("CVC", "Dark", None)), 3, failures)
            workbook = load_workbook(io.BytesIO(export_matrix_excel(group_by="date")))
            _check("Excel sheets", workbook.sheetnames, ["Matrix", "Batches", "Filters"], failures)
            _check("Excel Batches: 3 mẻ Normal", workbook["Batches"].max_row - 1, 3, failures)
            matrix_row = next(r for r in workbook["Matrix"].iter_rows(min_row=2, values_only=True) if r[1] == "Dark")
            _check("Excel Matrix ô ngày 1", matrix_row[4], 4.8, failures, tolerance=0.01)
            close_db()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    if failures:
        print(f"\n{len(failures)} FAILURE(S): {failures}")
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
