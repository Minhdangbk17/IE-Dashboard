"""
tests/test_batch_matrix_shade_sap_target.py
--------------------------------------------------
Verify 3 thay đổi của Fabric/Color Matrix (2026-10-26):
  1. Mẻ THIẾU SapLot được tính Normal như SapLot 1*/3* (nhưng SapLot "2000" vẫn là Rework,
     "4*" vẫn là Sample).
  2. Shade nhập tay theo Dyelot: mẻ "Unclassified" chuyển sang đúng Color Group, xoá override
     thì quay lại Unclassified; Shade không hợp lệ bị từ chối.
  3. Target: lưu / sửa / xoá (None) cho 1 ô Fabric x Color.

Chạy: python tests/test_batch_matrix_shade_sap_target.py
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import Flask  # noqa: E402

from modules.dyeing.engines.batch_matrix.service import (  # noqa: E402
    build_matrix, get_cell_batches, get_targets, set_shade_override, set_target,
)
from modules.dyeing.engines.batch_matrix.batch_day_trend import get_batch_day_trend, recompute_all  # noqa: E402

DAY = "2026-09-01"


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
    conn.execute("INSERT INTO machines (machine_code, capacity_kg) VALUES ('M1', 600)")
    # (dyelot, shade, sap_lot): cùng M1 nối tiếp nhau, mỗi mẻ 2h.
    batches = [
        ("A0", "Dark", "1000"),     # Normal (SapLot 1*)
        ("B0", "", None),           # THIẾU SapLot, Shade rỗng -> Normal + Unclassified
        ("C0", "Light", "  "),      # SapLot toàn khoảng trắng -> coi là thiếu -> Normal
        ("D0", "Dark", "2000"),     # SapLot 2* -> Rework (không đếm)
        ("E0", "Dark", "4000"),     # SapLot 4* -> Sample (không đếm)
    ]
    for i, (dyelot, shade, sap_lot) in enumerate(batches):
        start, end = f"{DAY} {7 + 2 * i:02d}:00:00", f"{DAY} {9 + 2 * i:02d}:00:00"
        conn.execute(
            "INSERT INTO availability_logs (batch, fabric_type, machine, capacity_kg, start_time, end_time) VALUES (?, 'CVC', 'M1', 600, ?, ?)",
            (dyelot, start, end),
        )
        conn.execute(
            "INSERT INTO batch_details (dyelot, shade, colour_no, batch_type, sap_lot, redye) VALUES (?, ?, '091-NAVY', 'Normal', ?, 0)",
            (dyelot, shade, sap_lot),
        )
    # Matrix đọc batch_details (như Trend): đồng bộ Machine/Fabric/Start/End từ bảng availability của fixture.
    conn.execute(
        "UPDATE batch_details SET "
        "machine = (SELECT a.machine FROM availability_logs a WHERE a.batch = batch_details.dyelot), "
        "fabric_type = (SELECT a.fabric_type FROM availability_logs a WHERE a.batch = batch_details.dyelot), "
        "start_time = (SELECT a.start_time FROM availability_logs a WHERE a.batch = batch_details.dyelot), "
        "end_time = (SELECT a.end_time FROM availability_logs a WHERE a.batch = batch_details.dyelot)"
    )
    conn.commit()
    conn.close()


def _check(label: str, actual, expected, failures: list[str]) -> None:
    ok = actual == expected
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: actual={actual!r} expected={expected!r}")
    if not ok:
        failures.append(label)


def _groups(data: dict) -> dict[str, int | None]:
    """{color_group: tổng mẻ} suy từ drill-down cho tiện — dùng get_cell_batches()."""
    return {row["color_group"]: row for row in data["rows"] if row["row_type"] == "data"}


def main() -> int:
    failures: list[str] = []
    tmp_dir = tempfile.mkdtemp()
    try:
        db_path = os.path.join(tmp_dir, "test.db")
        _init_db(db_path)
        app = Flask(__name__)
        app.config["DATABASE_PATH"] = db_path
        app.config["SQLITE_PRAGMAS"] = {}
        with app.app_context():
            print("=== 1. Thiếu SapLot = Normal ===")
            data = build_matrix(group_by="date")
            groups = _groups(data)
            _check("các Color Group", sorted(groups), ["Dark", "Light", "Unclassified"], failures)
            unclassified = get_cell_batches("CVC", "Unclassified")
            _check("Unclassified = B0 (thiếu SapLot, Shade rỗng)", [b["dyelot"] for b in unclassified], ["B0"], failures)
            _check("Light = C0 (SapLot khoảng trắng)", [b["dyelot"] for b in get_cell_batches("CVC", "Light")], ["C0"], failures)
            _check("Dark chỉ A0 (D0 Rework, E0 Sample bị loại)", [b["dyelot"] for b in get_cell_batches("CVC", "Dark")], ["A0"], failures)

            print("\n=== 2. Shade nhập tay ===")
            set_shade_override("B0", "Medium", "tester")
            _check("B0 chuyển sang Medium", [b["dyelot"] for b in get_cell_batches("CVC", "Medium")], ["B0"], failures)
            _check("Unclassified hết mẻ", get_cell_batches("CVC", "Unclassified"), [], failures)
            _check("shade_override có trong drill-down", get_cell_batches("CVC", "Medium")[0]["shade_override"], "Medium", failures)
            set_shade_override("B0", "Dark", "tester")  # sửa lại -> UPSERT
            _check("sửa lại B0 -> Dark (A0 + B0)", sorted(b["dyelot"] for b in get_cell_batches("CVC", "Dark")), ["A0", "B0"], failures)
            set_shade_override("B0", "", "tester")  # xoá
            _check("xoá override -> quay lại Unclassified", [b["dyelot"] for b in get_cell_batches("CVC", "Unclassified")], ["B0"], failures)
            try:
                set_shade_override("B0", "Purple", "tester")
                _check("Shade lạ bị từ chối", "không lỗi", "ValueError", failures)
            except ValueError:
                _check("Shade lạ bị từ chối", "ValueError", "ValueError", failures)
            try:
                set_shade_override("  ", "Dark", "tester")
                _check("Dyelot rỗng bị từ chối", "không lỗi", "ValueError", failures)
            except ValueError:
                _check("Dyelot rỗng bị từ chối", "ValueError", "ValueError", failures)

            print("\n=== 3. Target ===")
            set_target("CVC", "Dark", 5.5)
            _check("lưu Target", [t["target_value"] for t in get_targets()], [5.5], failures)
            _check("Target lên ma trận", _groups(build_matrix(group_by="date"))["Dark"]["target"], 5.5, failures)
            set_target("CVC", "Dark", 6.0)
            _check("sửa Target", [t["target_value"] for t in get_targets()], [6.0], failures)
            set_target("CVC", "Dark", None)
            _check("xoá Target (để trống)", get_targets(), [], failures)
            _check("ma trận hết Target", _groups(build_matrix(group_by="date"))["Dark"]["target"], None, failures)

            print("\n=== 4. Matrix và Batch/Day Trend cùng tập mẻ Normal / cùng Total ===")
            from datetime import date
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            recompute_all({date(2026, 9, 1)}, conn)
            conn.commit()
            conn.close()
            trend = get_batch_day_trend(group_by="date")
            matrix = build_matrix(group_by="date")
            matrix_count = sum(len(get_cell_batches(r["fabric_type"], r["color_group"])) for r in matrix["rows"] if r["row_type"] == "data")
            _check("tổng số mẻ Normal Matrix == Trend", matrix_count, trend["total_row"]["total_count"], failures)
            grand = next(r for r in matrix["rows"] if r["row_type"] == "grand_total")
            _check("Grand Total Matrix == Total Trend", grand["total"], trend["total_row"]["total"], failures)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    if failures:
        print(f"\nFAILED ({len(failures)}): {failures}")
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
