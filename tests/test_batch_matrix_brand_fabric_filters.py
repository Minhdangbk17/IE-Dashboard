"""
tests/test_batch_matrix_brand_fabric_filters.py
--------------------------------------------------
Verify 2 filter MỚI thêm vào báo cáo Batch/Day - Fabric/Color Matrix (2026-09-17):
Fabric Type + Brand Program.

Fabric Type filter: an toàn (chỉ loại bớt HẲN 1 nhóm fabric_type khỏi kết quả, không đổi
cách tính mẫu số của các fabric_type còn lại).

Brand Program filter: RỦI RO CAO — bảng rollup `batch_matrix_daily_summary` KHÔNG lưu theo
brand_program (xem lý do ở `_ensure_summary_table()` trong service.py: 1 máy có thể chạy
NHIỀU brand_program trong CÙNG 1 ngày, nên không thể lưu operating_hours theo từng nhóm
brand_program rồi cộng lại — sẽ tái diễn ĐÚNG bug COUNT DISTINCT đã tốn 3 lần sửa ở "Mẫu
số"). `build_matrix()` xử lý bằng đường tính TRỰC TIẾP riêng (`_raw_matrix_rows()` +
`_aggregate_raw_rows()`) khi có Brand Program filter. Test này bẫy ĐÚNG loại bug đó: 1 máy
(M1) chạy 2 mẻ CÙNG ngày, CÙNG Fabric/Color/Capacity, nhưng 2 Brand Program khác nhau.

Chạy: python tests/test_batch_matrix_brand_fabric_filters.py
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import Flask  # noqa: E402

from core.database import close_db  # noqa: E402
from modules.dyeing.engines.batch_matrix.service import build_matrix, get_day_batches, recompute_daily  # noqa: E402


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
    conn.execute("CREATE TABLE batch_details (id INTEGER PRIMARY KEY AUTOINCREMENT, dyelot TEXT NOT NULL, shade TEXT, colour_no TEXT, batch_type TEXT, greige_code TEXT, machine TEXT, start_time TEXT, end_time TEXT)")
    conn.execute("CREATE UNIQUE INDEX uq_batch_details_dyelot_machine_start ON batch_details(dyelot, machine, start_time)")
    conn.commit()
    conn.close()


def _check(label: str, actual, expected, failures: list[str], tolerance: float = 0.0) -> None:
    ok = abs(actual - expected) <= tolerance if tolerance else actual == expected
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: actual={actual} expected={expected}")
    if not ok:
        failures.append(label)


def main() -> int:
    failures: list[str] = []
    tmp_dir = tempfile.mkdtemp()
    try:
        db_path = os.path.join(tmp_dir, "test.db")
        _init_schema(db_path)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        day = date(2026, 9, 1)
        # M1: 2 mẻ CÙNG Fabric=CVC/Color=Dark/Capacity=600, khác Brand Program (G1 -> UQ, G2 -> Nike).
        # M2: 1 mẻ CÙNG cell, Brand Program G1 (UQ) — để "UQ" filter còn lại CẢ M1 lẫn M2.
        conn.executemany(
            "INSERT INTO availability_logs (batch, fabric_type, machine, capacity_kg, start_time, end_time) VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("M1-UQ", "CVC", "M1", 600, "2026-09-01 07:00:00", "2026-09-01 11:00:00"),   # 4h, Brand UQ
                ("M1-NIKE", "CVC", "M1", 600, "2026-09-01 11:00:00", "2026-09-01 16:00:00"),  # 5h, Brand Nike (M1 = 9h/ngày)
                ("M2-UQ", "CVC", "M2", 600, "2026-09-01 07:00:00", "2026-09-01 13:00:00"),    # 6h, Brand UQ
            ],
        )
        conn.executemany(
            "INSERT INTO batch_details (dyelot, shade, colour_no, batch_type, greige_code) VALUES (?, ?, ?, ?, ?)",
            [
                ("M1-UQ", "Dark", "091-NAVY", "Normal", "G1"),
                ("M1-NIKE", "Dark", "091-NAVY", "Normal", "G2"),
                ("M2-UQ", "Dark", "091-NAVY", "Normal", "G1"),
            ],
        )
        conn.commit()

        app = _make_temp_app(db_path)
        with app.app_context():
            recompute_daily(day, conn)
            conn.commit()
            conn.close()
            close_db()

            from core.brand_program_importer import ensure_brand_program_table
            conn2 = sqlite3.connect(db_path)
            conn2.row_factory = sqlite3.Row
            ensure_brand_program_table(conn2)
            conn2.execute("INSERT INTO brand_program_mapping (greige_code, brand, brand_program) VALUES ('G1', 'UQ', 'Ht Fleece')")
            conn2.execute("INSERT INTO brand_program_mapping (greige_code, brand, brand_program) VALUES ('G2', 'Nike', 'Performance')")
            conn2.commit()
            conn2.close()

            print("=== Kịch bản 1: KHÔNG lọc Brand Program (mặc định) -> giống hệt kết quả trước khi có filter ===")
            data_all = build_matrix()
            cvc_dark_all = next(r for r in data_all["rows"] if r["row_type"] == "data" and r["fabric_type"] == "CVC" and r["color_group"] == "Dark")
            # tử số=3 (M1x2 + M2x1), mẫu số = tập máy {M1,M2} = 9h(M1) + 6h(M2) = 15h -> 3*24/15=4.8
            _check("no-filter cell value (CVC/Dark)", cvc_dark_all["days"][day.isoformat()], 4.8, failures, tolerance=0.01)
            _check("no-filter available_brand_programs", sorted(data_all["available_brand_programs"]), ["Nike - Performance", "UQ - Ht Fleece"], failures)
            _check("no-filter available_fabric_types", data_all["available_fabric_types"], ["CVC"], failures)

            print("\n=== Kịch bản 2: Filter Brand Program = 'UQ - Ht Fleece' -> M1 tính CẢ NGÀY (9h), không phải chỉ 4h phần UQ ===")
            data_uq = build_matrix(brand_programs="UQ - Ht Fleece")
            cvc_dark_uq = next(r for r in data_uq["rows"] if r["row_type"] == "data" and r["fabric_type"] == "CVC" and r["color_group"] == "Dark")
            # tử số (mẻ có Brand=UQ) = 2 (M1-UQ, M2-UQ). Tập máy tham gia = {M1, M2} (cả 2 đều
            # có ÍT NHẤT 1 mẻ UQ trong cell này) -> mẫu số = giờ CẢ NGÀY của M1(9h)+M2(6h)=15h
            # (ĐÚNG theo quy tắc "mẫu số = giờ hoạt động CẢ NGÀY của tập máy", không phải chỉ
            # giờ của riêng mẻ UQ) -> value = 2*24/15 = 3.2
            _check("brand_program=UQ cell value (M1 tính đủ 9h/ngày, không chỉ 4h)", cvc_dark_uq["days"][day.isoformat()], 3.2, failures, tolerance=0.01)

            print("\n=== Kịch bản 3: Filter Brand Program = 'Nike - Performance' -> chỉ còn M1-NIKE ===")
            data_nike = build_matrix(brand_programs="Nike - Performance")
            cvc_dark_nike = next(r for r in data_nike["rows"] if r["row_type"] == "data" and r["fabric_type"] == "CVC" and r["color_group"] == "Dark")
            # tử số=1 (M1-NIKE). Tập máy={M1} (chỉ M1 có mẻ Nike) -> mẫu số = 9h (CẢ ngày M1) -> 1*24/9=2.67
            _check("brand_program=Nike cell value", round(cvc_dark_nike["days"][day.isoformat()], 2), 2.67, failures, tolerance=0.01)

            print("\n=== Kịch bản 4: Fabric Type filter loại hết CVC -> rows rỗng (chỉ có Fabric CVC trong data test) ===")
            data_other_fabric = build_matrix(fabric_types="Polyester")
            data_rows = [r for r in data_other_fabric["rows"] if r["row_type"] == "data"]
            _check("fabric_type=Polyester -> 0 data rows (chỉ có CVC trong DB test)", len(data_rows), 0, failures)

            print("\n=== Kịch bản 5: get_day_batches() với Brand Program filter ===")
            batches_uq = get_day_batches(day.isoformat(), "CVC", "Dark", brand_programs="UQ - Ht Fleece")
            _check("get_day_batches brand=UQ -> 2 batches (M1-UQ, M2-UQ)", len(batches_uq), 2, failures)
            batches_nike = get_day_batches(day.isoformat(), "CVC", "Dark", brand_programs="Nike - Performance")
            _check("get_day_batches brand=Nike -> 1 batch (M1-NIKE)", len(batches_nike), 1, failures)
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
