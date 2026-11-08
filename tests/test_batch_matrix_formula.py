from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import Flask  # noqa: E402

from core.database import close_db  # noqa: E402
from modules.dyeing.engines.batch_matrix.service import build_matrix, recompute_daily  # noqa: E402


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
            start_time TEXT, end_time TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE batch_details (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dyelot TEXT NOT NULL, shade TEXT, colour_no TEXT, batch_type TEXT, greige_code TEXT, fabric_type TEXT,
            machine TEXT, start_time TEXT, end_time TEXT, sap_lot TEXT, redye REAL DEFAULT 0
        )
    """)
    conn.execute("CREATE UNIQUE INDEX uq_batch_details_dyelot_machine_start ON batch_details(dyelot, machine, start_time)")
    conn.execute("CREATE TABLE machines (machine_code TEXT, machine_id TEXT, capacity_kg REAL, tank_type TEXT)")
    conn.commit()
    conn.close()


def _check(label: str, actual, expected, failures: list[str], tolerance: float = 0.0) -> None:
    ok = abs(actual - expected) <= tolerance if tolerance else actual == expected
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: actual={actual} expected={expected}")
    if not ok:
        failures.append(label)


def _scenario_basic_cell(failures: list[str]) -> None:
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        _init_schema(db_path)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        day = date(2026, 9, 1)
        conn.executemany(
            "INSERT INTO availability_logs (batch, fabric_type, machine, capacity_kg, start_time, end_time) VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("D507-B1", "CVC", "D507", 600, "2026-09-01 07:00:00", "2026-09-01 10:00:00"),
                ("D507-B2", "CVC", "D507", 600, "2026-09-01 10:00:00", "2026-09-01 14:00:00"),
                ("D507-B3", "Cotton", "D507", 600, "2026-09-01 14:00:00", "2026-09-01 17:00:00"),
                ("D511-B1", "CVC", "D511", 600, "2026-09-01 08:00:00", "2026-09-01 11:30:00"),
                ("D511-B2", "CVC", "D511", 600, "2026-09-01 11:30:00", "2026-09-01 14:00:00"),
            ],
        )
        conn.executemany(
            "INSERT INTO batch_details (dyelot, shade, colour_no, batch_type) VALUES (?, ?, ?, ?)",
            [
                ("D507-B1", "Dark", "091-NAVY", "Normal"),
                ("D507-B2", "Dark", "091-NAVY", "Normal"),
                ("D511-B1", "Dark", "091-NAVY", "Normal"),
                ("D511-B2", "Dark", "091-NAVY", "Normal"),
            ],
        )
        conn.commit()
        recompute_daily(day, conn)
        row = conn.execute(
            "SELECT batch_count, operating_hours FROM batch_matrix_daily_summary WHERE production_date=? AND fabric_type='CVC' AND color_group='Dark' AND capacity_kg=600",
            (day.isoformat(),),
        ).fetchone()
        conn.close()

        print("=== Kịch bản 1: ô đơn (CVC/Dark/600) — đối chiếu ví dụ số gốc ===")
        if row is None:
            print("  [FAIL] không tìm thấy dòng summary")
            failures.append("scenario1 missing row")
            return
        _check("batch_count (tử số)", row["batch_count"], 4, failures)
        _check("operating_hours (mẫu số)", round(row["operating_hours"], 2), 16.0, failures, tolerance=0.01)
        cell_value = round(row["batch_count"] / (row["operating_hours"] / 24), 2)
        _check("cell_value", cell_value, 6.0, failures, tolerance=0.01)
    finally:
        os.unlink(db_path)


def _scenario_overnight_split(failures: list[str]) -> None:
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        _init_schema(db_path)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        day_before = date(2026, 9, 5)
        day_of = date(2026, 9, 6)
        conn.executemany(
            "INSERT INTO availability_logs (batch, fabric_type, machine, capacity_kg, start_time, end_time) VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("D999-X", "CVC", "D999", 300, "2026-09-05 07:00:00", "2026-09-05 12:00:00"),
                ("D999-Y-OVERNIGHT", "CVC", "D999", 300, "2026-09-05 22:00:00", "2026-09-06 10:00:00"),
                ("D999-Z", "CVC", "D999", 300, "2026-09-06 11:00:00", "2026-09-06 15:00:00"),
            ],
        )
        conn.commit()
        recompute_daily(day_before, conn)
        recompute_daily(day_of, conn)
        row_before = conn.execute(
            "SELECT operating_hours FROM batch_matrix_daily_summary WHERE production_date=? AND capacity_kg=300", (day_before.isoformat(),)
        ).fetchone()
        row_of = conn.execute(
            "SELECT operating_hours FROM batch_matrix_daily_summary WHERE production_date=? AND capacity_kg=300", (day_of.isoformat(),)
        ).fetchone()
        conn.close()

        print("\n=== Kịch bản 2: mẻ chạy qua đêm — tách đúng theo ranh giới 7h sáng ===")
        _check("operating_hours ngày trước (Batch X 5h + phần Y trước 7h 9h = 14h)", round(row_before["operating_hours"], 2) if row_before else None, 14.0, failures, tolerance=0.01)
        _check("operating_hours ngày sau (phần Y từ 7h 3h + Batch Z 4h = 7h)", round(row_of["operating_hours"], 2) if row_of else None, 7.0, failures, tolerance=0.01)
        total_split = (row_before["operating_hours"] if row_before else 0) + (row_of["operating_hours"] if row_of else 0)
        _check("tổng 2 ngày = tổng thời lượng 3 mẻ gốc (5+12+4=21h, không mất/thừa giờ)", round(total_split, 2), 21.0, failures, tolerance=0.01)
    finally:
        os.unlink(db_path)


def _scenario_multicolor_dedup(failures: list[str]) -> None:
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        _init_schema(db_path)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        day = date(2026, 9, 10)
        conn.executemany(
            "INSERT INTO availability_logs (batch, fabric_type, machine, capacity_kg, start_time, end_time) VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("M1-DARK0", "CVC", "M1", 700, "2026-09-10 07:00:00", "2026-09-10 11:00:00"),
                ("M1-MED0", "CVC", "M1", 700, "2026-09-10 11:00:00", "2026-09-10 16:00:00"),
                ("M2-DARK0", "CVC", "M2", 700, "2026-09-10 07:00:00", "2026-09-10 13:00:00"),
            ],
        )
        conn.executemany(
            "INSERT INTO batch_details (dyelot, shade, colour_no, batch_type, sap_lot) VALUES (?, ?, ?, ?, '1000')",
            [
                ("M1-DARK0", "Dark", "091-NAVY", "Normal"),
                ("M1-MED0", "Medium", "500-GREY", "Normal"),
                ("M2-DARK0", "Dark", "091-NAVY", "Normal"),
            ],
        )
        conn.execute(
            "UPDATE batch_details SET "
            "machine = (SELECT a.machine FROM availability_logs a WHERE a.batch = batch_details.dyelot), "
            "fabric_type = (SELECT a.fabric_type FROM availability_logs a WHERE a.batch = batch_details.dyelot), "
            "start_time = (SELECT a.start_time FROM availability_logs a WHERE a.batch = batch_details.dyelot), "
            "end_time = (SELECT a.end_time FROM availability_logs a WHERE a.batch = batch_details.dyelot)"
        )
        conn.commit()
        recompute_daily(day, conn)
        conn.commit()

        dark_row = conn.execute(
            "SELECT batch_count, operating_hours FROM batch_matrix_daily_summary WHERE production_date=? AND fabric_type='CVC' AND color_group='Dark'", (day.isoformat(),)
        ).fetchone()
        medium_row = conn.execute(
            "SELECT batch_count, operating_hours FROM batch_matrix_daily_summary WHERE production_date=? AND fabric_type='CVC' AND color_group='Medium'", (day.isoformat(),)
        ).fetchone()
        from modules.dyeing.engines.batch_matrix.batch_day_trend import recompute_all
        recompute_all({day}, conn)
        conn.commit()
        conn.close()

        print("\n=== Kịch bản 3: máy chạy ĐA MÀU/ngày — bẫy lỗi cộng trùng giờ ở Total(Fabric) ===")
        _check("Dark: batch_count", dark_row["batch_count"], 2, failures)
        _check("Dark: operating_hours (tập máy {M1,M2}, M1 tính CẢ NGÀY)", round(dark_row["operating_hours"], 2), 15.0, failures, tolerance=0.01)
        _check("Medium: batch_count", medium_row["batch_count"], 1, failures)
        _check("Medium: operating_hours (tập máy {M1}, CẢ NGÀY)", round(medium_row["operating_hours"], 2), 9.0, failures, tolerance=0.01)

        naive_hours = dark_row["operating_hours"] + medium_row["operating_hours"]
        naive_value = round((dark_row["batch_count"] + medium_row["batch_count"]) * 24 / naive_hours, 2)
        print(f"  [THAM KHẢO] Nếu cộng THẲNG operating_hours 2 dòng con (SAI): {naive_hours:.2f}h -> giá trị SAI = {naive_value}")

        app = _make_temp_app(db_path)
        with app.app_context():
            data = build_matrix()
            fabric_total_row = next(r for r in data["rows"] if r["row_type"] == "fabric_total" and r["fabric_type"] == "CVC")
            total_cvc_value = fabric_total_row["values"].get(day.isoformat())
            week = build_matrix(group_by="week")
            week_total = next(r for r in week["rows"] if r["row_type"] == "fabric_total" and r["fabric_type"] == "CVC")
            close_db()
        _check("Group By Week: cột tuần = giá trị ngày duy nhất (4.8)", week_total["values"].get(week["period_keys"][0]), 4.8, failures, tolerance=0.01)

        _check("Total(CVC) từ build_matrix() (PHẢI khử trùng M1, ra 4.8 KHÔNG PHẢI 3.0)", total_cvc_value, 4.8, failures, tolerance=0.01)
        if total_cvc_value == naive_value:
            print("  [FAIL] Total(CVC) trùng với giá trị SAI (cộng thẳng) -> bug cộng trùng giờ ĐÃ TÁI DIỄN")
            failures.append("Total(CVC) matches naive (wrong) value")
    finally:
        os.unlink(db_path)


def _scenario_duplicate_dyelot_redye(failures: list[str]) -> None:
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        _init_schema(db_path)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        day = date(2026, 9, 12)
        conn.execute(
            "INSERT INTO availability_logs (batch, fabric_type, machine, capacity_kg, start_time, end_time) VALUES (?, ?, ?, ?, ?, ?)",
            ("C-REDYE", "CVC", "D600", 600, "2026-09-12 06:00:00", "2026-09-12 10:00:00"),
        )
        conn.executemany(
            "INSERT INTO batch_details (dyelot, shade, colour_no, batch_type, machine, start_time, end_time) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                ("C-REDYE", "Medium", "500-GREY", "Normal", "D600", "2026-09-01 06:00:00", "2026-09-01 08:00:00"),
                ("C-REDYE", "Dark", "091-NAVY", "Normal", "D600", "2026-09-12 06:00:00", "2026-09-12 10:00:00"),
            ],
        )
        conn.commit()
        recompute_daily(day, conn)
        dark_row = conn.execute(
            "SELECT batch_count FROM batch_matrix_daily_summary WHERE production_date=? AND fabric_type='CVC' AND color_group='Dark'", (day.isoformat(),)
        ).fetchone()
        medium_row = conn.execute(
            "SELECT batch_count FROM batch_matrix_daily_summary WHERE production_date=? AND fabric_type='CVC' AND color_group='Medium'", (day.isoformat(),)
        ).fetchone()
        conn.close()

        print("\n=== Kịch bản 4: 1 Dyelot có 2 dòng batch_details (mẻ gốc + redye) — KHÔNG đếm trùng ===")
        _check("Dark (mẻ redye, end_time khớp): batch_count = 1 (không bị nhân đôi)", dark_row["batch_count"] if dark_row else 0, 1, failures)
        _check("Medium (mẻ gốc NG, end_time KHÔNG khớp): không xuất hiện (0 dòng)", medium_row["batch_count"] if medium_row else 0, 0, failures)
    finally:
        os.unlink(db_path)


def _scenario_color_formula(failures: list[str]) -> None:
    from modules.dyeing.engines.batch_matrix.service import _classify_color_group

    print("\n=== Kịch bản 5: phân màu theo công thức `Color` (ColourNo, Shade; không có nhóm Non-dyed) ===")
    lookup = {"RED 123": "Dark"}
    cases = [
        (("PUMA BLACK", "Medium"), "Black", "1. ColourNo BLACK thắng Shade Medium"),
        (("BLACK/WHITE", ""), "Black", "1. chứa cả BLACK lẫn WHITE -> Black"),
        (("OFF WHITE", "Light"), "White", "2. ColourNo WHITE"),
        (("RED 123", "medium"), "Medium", "3. Shade (Proper)"),
        (("  ", ""), "Unclassified", "4. ColourNo trống"),
        (("red 123", ""), "Dark", "5. mượn Shade mẻ khác cùng ColourNo (không phân biệt hoa/thường)"),
        (("005-18-00 PUMA RED", ""), "Dark", "6. mã số: 18 <= 30 -> Dark"),
        (("123-45-67", ""), "Medium", "6. mã số: 45 <= 50 -> Medium"),
        (("123-60-00", ""), "Light", "6. mã số: 60 -> Light"),
        (("NAVY 19-4052 TCX", ""), "Dark", "7. Pantone TCX 19 -> Dark"),
        (("CORAL 16-1546  TCX", ""), "Light", "7. Pantone TCX 16 -> Light (TRIM gộp khoảng trắng)"),
        (("DK GREEN", ""), "Dark", "8. từ khoá DK"),
        (("CREAM", ""), "Light", "8. từ khoá CREAM"),
        (("RED", ""), "Unclassified", "8. không khớp gì"),
    ]
    for (colour, shade), expected, label in cases:
        _check(label, _classify_color_group(colour, shade, lookup), expected, failures)


def _scenario_formula_v4_cm_next_color(failures: list[str]) -> None:
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        _init_schema(db_path)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.executemany(
            "INSERT INTO batch_details (dyelot, shade, colour_no, fabric_type, machine, start_time, end_time, sap_lot, batch_type) "
            "VALUES (?, ?, ?, 'CVC', ?, ?, ?, '1000', ?)",
            [
                ("M1-WA", "", "", "M1", "2026-09-15 07:00:00", "2026-09-15 08:00:00", "Unknown"),
                ("M1-L0", "Light", "SKY", "M1", "2026-09-15 08:00:00", "2026-09-15 12:00:00", "Normal"),
                ("M1-D0", "Dark", "RED", "M1", "2026-09-15 12:00:00", "2026-09-15 17:00:00", "Normal"),
                ("M2-D1", "Dark", "RED", "M2", "2026-09-15 07:00:00", "2026-09-15 13:00:00", "Rework"),
                ("M2-WA", "", "", "M2", "2026-09-15 13:00:00", "2026-09-15 14:00:00", "Unknown"),
            ],
        )
        conn.commit()
        from modules.dyeing.engines.batch_matrix.batch_day_trend import recompute_all
        recompute_all({date(2026, 9, 15)}, conn)
        conn.commit()
        conn.close()

        app = _make_temp_app(db_path)
        with app.app_context():
            data = build_matrix()
            close_db()
        cells = {r["color_group"]: r for r in data["rows"] if r["row_type"] == "data" and r["fabric_type"] == "CVC"}
        fabric_total = next(r for r in data["rows"] if r["row_type"] == "fabric_total" and r["fabric_type"] == "CVC")

        print("\n=== Kịch bản 6: công thức bản 4 + CM lấy màu mẻ kế tiếp ===")
        _check("Light = 1*24/(CM 1h + 4h)", cells["Light"]["total"], 4.8, failures, tolerance=0.01)
        _check("Dark = 1*24/(5h + Rework 6h)", cells["Dark"]["total"], 2.18, failures, tolerance=0.01)
        _check("Unclassified (CM cuối máy) = 0", cells["Unclassified"]["total"], 0.0, failures)
        _check("tổng giờ các ô = 17h", round(sum(r["hours"] for r in cells.values()), 2), 17.0, failures, tolerance=0.01)
        _check("Total(CVC) từ Trend = 2*24/17", fabric_total["total"], 2.82, failures, tolerance=0.01)
    finally:
        os.unlink(db_path)


def main() -> int:
    failures: list[str] = []
    _scenario_basic_cell(failures)
    _scenario_overnight_split(failures)
    _scenario_multicolor_dedup(failures)
    _scenario_duplicate_dyelot_redye(failures)
    _scenario_color_formula(failures)
    _scenario_formula_v4_cm_next_color(failures)
    print(f"\n{'='*60}\nKẾT QUẢ: {'TẤT CẢ KHỚP' if not failures else f'{len(failures)} CASE LỆCH'}\n{'='*60}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
