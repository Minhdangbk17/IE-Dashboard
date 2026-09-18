"""
tests/test_downtime_brand_fabric_filters.py
--------------------------------------------
Verify 2 filter MỚI thêm vào báo cáo Downtime (2026-09-17): Fabric Type + Brand Program.

Brand Program suy từ availability_logs.batch -> batch_details.dyelot (khoá greige_code) ->
brand_program_mapping.greige_code -> "Brand - Program". Grain của `downtime_daily_summary`
đã mở rộng từ (production_date, capacity_kg, category) sang (production_date, capacity_kg,
fabric_type, brand_program, category) — test này xác nhận:
1. Không filter (mặc định "All") -> tổng giờ Downtime GIỐNG HỆT trước khi có 2 cột mới
   (backward-compat, không đổi hành vi mặc định).
2. Filter Fabric Type -> chỉ cộng đúng giờ của các mẻ thuộc Fabric Type đã chọn.
3. Filter Brand Program -> chỉ cộng đúng giờ của các mẻ có Brand Program khớp (qua JOIN
   batch_details/brand_program_mapping).
4. available_fabric_types/available_brand_programs trả đúng danh sách thực có trong dữ liệu.

Dùng DB tạm SQLite (cùng pattern `tests/test_batch_matrix_formula.py`).
Chạy: python tests/test_downtime_brand_fabric_filters.py
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
from modules.dyeing.engines.downtime.service import get_downtime_pivot_data, recompute_daily  # noqa: E402


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
            batch TEXT, fabric_type TEXT, machine TEXT, capacity_kg REAL, production_date TEXT,
            start_time TEXT, end_time TEXT, planned_prd_time_hour REAL,
            rework_hour REAL DEFAULT 0, adjust_color_hour REAL DEFAULT 0, sample_checking_hour REAL DEFAULT 0,
            load_hour REAL DEFAULT 0, unload_hour REAL DEFAULT 0, bleaching_hour REAL DEFAULT 0,
            ph_checking_hour REAL DEFAULT 0, wait_chemical_load_hour REAL DEFAULT 0, wait_color_load_hour REAL DEFAULT 0,
            wait_fabric_hour REAL DEFAULT 0, wait_water_hour REAL DEFAULT 0, wait_steam_hour REAL DEFAULT 0,
            cleaning_hour REAL DEFAULT 0, maintenance_hour REAL DEFAULT 0, others_hour REAL DEFAULT 0, no_order_hour REAL DEFAULT 0,
            ach_load INTEGER, ach_unload INTEGER, ach_sample_check INTEGER, ach_ph INTEGER, ach_chemical INTEGER, ach_color INTEGER
        )
    """)
    conn.execute("CREATE TABLE batch_details (dyelot TEXT PRIMARY KEY, greige_code TEXT)")
    conn.execute("CREATE TABLE brand_program_mapping (greige_code TEXT PRIMARY KEY, brand TEXT, brand_program TEXT, fabric_type TEXT, item_code TEXT, import_log_id INTEGER, updated_at TEXT)")
    conn.commit()
    conn.close()


def _check(label: str, actual, expected, failures: list[str]) -> None:
    ok = abs(actual - expected) < 1e-6 if isinstance(expected, (int, float)) else actual == expected
    status = "OK" if ok else "FAIL"
    print(f"[{status}] {label}: actual={actual!r} expected={expected!r}")
    if not ok:
        failures.append(label)


def main() -> int:
    failures: list[str] = []
    tmp_dir = tempfile.mkdtemp()
    try:
        db_path = os.path.join(tmp_dir, "test.db")
        _init_schema(db_path)
        app = _make_temp_app(db_path)

        with app.app_context():
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            # 2 batch cùng ngày/capacity, khác Fabric Type + Brand Program.
            # B001: CVC, greige G1 -> Brand "UQ - Ht Fleece", rework_hour=2
            # B002: Polyester, greige G2 -> Brand "Nike - Performance", rework_hour=5
            conn.execute(
                "INSERT INTO availability_logs (batch, fabric_type, machine, capacity_kg, start_time, end_time, planned_prd_time_hour, rework_hour) "
                "VALUES ('B001', 'CVC', 'D001', 500, '2026-09-01 08:00:00', '2026-09-01 12:00:00', 4, 2)"
            )
            conn.execute(
                "INSERT INTO availability_logs (batch, fabric_type, machine, capacity_kg, start_time, end_time, planned_prd_time_hour, rework_hour) "
                "VALUES ('B002', 'Polyester', 'D002', 500, '2026-09-01 08:00:00', '2026-09-01 12:00:00', 4, 5)"
            )
            conn.execute("INSERT INTO batch_details (dyelot, greige_code) VALUES ('B001', 'G1')")
            conn.execute("INSERT INTO batch_details (dyelot, greige_code) VALUES ('B002', 'G2')")
            conn.execute("INSERT INTO brand_program_mapping (greige_code, brand, brand_program) VALUES ('G1', 'UQ', 'Ht Fleece')")
            conn.execute("INSERT INTO brand_program_mapping (greige_code, brand, brand_program) VALUES ('G2', 'Nike', 'Performance')")
            conn.commit()

            recompute_daily(date(2026, 9, 1), conn)
            conn.commit()
            conn.close()
            close_db()

            # 1) Không filter -> tổng Rework = 2 + 5 = 7
            data_all = get_downtime_pivot_data(from_date="2026-09-01", to_date="2026-09-01", group_by="date")
            rework_row = next(r for r in data_all["rows"] if r["category"] == "Rework")
            _check("no-filter total Rework hours", rework_row["total_hours"], round(7 / 2, 2), failures)  # total_hours = raw/valid_batches (2)
            _check("no-filter available_fabric_types", sorted(data_all["available_fabric_types"]), ["CVC", "Polyester"], failures)
            _check("no-filter available_brand_programs", sorted(data_all["available_brand_programs"]), ["Nike - Performance", "UQ - Ht Fleece"], failures)

            # 2) Filter Fabric Type = CVC -> chỉ còn B001 (rework=2, valid_batches=1)
            data_cvc = get_downtime_pivot_data(from_date="2026-09-01", to_date="2026-09-01", group_by="date", fabric_types="CVC")
            rework_cvc = next(r for r in data_cvc["rows"] if r["category"] == "Rework")
            _check("fabric_type=CVC total Rework hours", rework_cvc["total_hours"], 2.0, failures)
            _check("fabric_type=CVC valid_batches", data_cvc["kpis"]["valid_batches"], 1, failures)

            # 3) Filter Brand Program = "Nike - Performance" -> chỉ còn B002 (rework=5)
            data_nike = get_downtime_pivot_data(from_date="2026-09-01", to_date="2026-09-01", group_by="date", brand_programs="Nike - Performance")
            rework_nike = next(r for r in data_nike["rows"] if r["category"] == "Rework")
            _check("brand_program=Nike total Rework hours", rework_nike["total_hours"], 5.0, failures)
            _check("brand_program=Nike valid_batches", data_nike["kpis"]["valid_batches"], 1, failures)

            # 4) Kết hợp cả 2 filter, không khớp batch nào -> rỗng
            data_none = get_downtime_pivot_data(from_date="2026-09-01", to_date="2026-09-01", group_by="date", fabric_types="CVC", brand_programs="Nike - Performance")
            _check("mismatched combo -> empty rows total", data_none["kpis"]["downtime_hours"], 0.0, failures)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    if failures:
        print(f"\n{len(failures)} FAILURE(S): {failures}")
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
