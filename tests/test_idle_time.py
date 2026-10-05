"""
tests/test_idle_time.py
-------------------------
2026-10-05 — Engine `idle_time` (báo cáo Idle Time). Kiểm tra trên DB tạm, dữ liệu dựng tay:

  1. Ngày không trọn: ngày đầu dữ liệu bắt đầu 18:00 -> chỉ tính 13h (18:00 -> 07:00), ngày
     cuối chỉ có 08:00-10:00 -> 2h; ngày KHÔNG có đoạn nào (khoảng hổng import) bị bỏ hẳn.
  2. Mẻ vắt qua 07:00 tách đúng; máy không chạy mẻ nào trong ngày = idle trọn giờ có dữ liệu;
     operating + idle = available ở mọi ô; tổng các khoảng idle = idle của ô.
  3. Filter Tank (J/O) + Capacity theo Machine Master.
  4. Note: lưu, Reason sai bị từ chối, import lại làm khoảng idle dịch chuyển -> note thành
     "stale" (không mất), xoá note.
  5. Target + Excel export: ô vượt Target được tô màu, sheet "Idle Gaps" có note.

Chạy: python tests/test_idle_time.py
"""
from __future__ import annotations

import io
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import Flask  # noqa: E402
from openpyxl import load_workbook  # noqa: E402

from core.database import close_db, get_db  # noqa: E402
from modules.dyeing.engines.batch_matrix import batch_day_trend  # noqa: E402
from modules.dyeing.engines.idle_time import service  # noqa: E402

# (dyelot, machine, start, end)
BATCHES = [
    ("C100000", "M1", "2026-09-01 18:00:00", "2026-09-01 22:00:00"),
    ("C100010", "M1", "2026-09-01 23:00:00", "2026-09-02 09:00:00"),  # vắt qua 07:00
    ("C100020", "M1", "2026-09-02 10:00:00", "2026-09-03 07:00:00"),  # kết thúc đúng 07:00
    ("C100030", "M2", "2026-09-02 08:00:00", "2026-09-02 20:00:00"),
    ("C100040", "M1", "2026-09-05 08:00:00", "2026-09-05 10:00:00"),  # 03-04/09 không có dữ liệu
]
DAYS = [date(2026, 9, d) for d in range(1, 6)]


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
    conn.execute("CREATE TABLE machines (machine_id TEXT, machine_code TEXT, tank_type TEXT, capacity_kg REAL, domain TEXT)")
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT)")
    conn.execute("INSERT INTO users (id, username) VALUES (1, 'tester')")
    conn.executemany(
        "INSERT INTO machines (machine_id, machine_code, tank_type, capacity_kg, domain) VALUES (?, ?, ?, ?, 'dyeing')",
        [("M1", "M1", "J tank", 600), ("M2", "M2", "O tank", 1200)],
    )
    conn.executemany(
        "INSERT INTO batch_details (dyelot, machine, start_time, end_time, fabric_type, sap_lot) VALUES (?, ?, ?, ?, 'Cotton', '1000000001')",
        BATCHES,
    )
    conn.commit()
    conn.close()


def _recompute() -> None:
    conn = get_db()
    batch_day_trend.recompute_all(DAYS, conn)
    conn.commit()


def _rows(data: dict) -> dict[str, dict]:
    return {row["machine"]: row for row in data["rows"]}


def _scenario_matrix(failures: list[str]) -> None:
    print("\n=== Kịch bản 1-2: ngày không trọn, mẻ vắt 07:00, máy không chạy ===")
    data = service.get_idle_matrix("2026-09-01", "2026-09-05")
    _check("ngày có dữ liệu (bỏ 03/09, 04/09)", data["days"], ["2026-09-01", "2026-09-02", "2026-09-05"], failures)
    _check("ngày không trọn", data["partial_days"], ["2026-09-01", "2026-09-05"], failures)
    _check("giờ có dữ liệu/ngày", data["day_available_hours"], {"2026-09-01": 13.0, "2026-09-02": 24.0, "2026-09-05": 2.0}, failures)
    rows = _rows(data)
    m1, m2 = rows["M1"]["cells"], rows["M2"]["cells"]
    _check("M1 01/09: chạy 4h + 8h, idle 22:00-23:00", (m1["2026-09-01"]["operating"], m1["2026-09-01"]["idle"]), (12.0, 1.0), failures)
    _check("M1 02/09: chạy 2h + 21h, idle 09:00-10:00", (m1["2026-09-02"]["operating"], m1["2026-09-02"]["idle"]), (23.0, 1.0), failures)
    _check("M2 01/09 không chạy mẻ -> idle trọn 13h", (m2["2026-09-01"]["operating"], m2["2026-09-01"]["idle"], m2["2026-09-01"]["idle_pct"]), (0.0, 13.0, 100.0), failures)
    _check("M2 02/09: 2 khoảng idle, 12h", (m2["2026-09-02"]["idle"], m2["2026-09-02"]["gap_count"]), (12.0, 2), failures)
    bad = [(row["machine"], day) for row in data["rows"] for day, cell in row["cells"].items() if abs(cell["operating"] + cell["idle"] - cell["available"]) > 0.01]
    _check("operating + idle = available ở mọi ô", bad, [], failures)
    _check("% Idle M1 cả kỳ = 2/39", rows["M1"]["idle_pct"], round(2 / 39 * 100, 2), failures)
    _check("tổng ngày 02/09", data["day_totals"]["2026-09-02"], {"operating": 35.0, "idle": 13.0, "available": 48.0, "idle_pct": round(13 / 48 * 100, 2)}, failures)

    gaps = service.get_idle_gaps("M2", "2026-09-02")
    _check("khoảng idle M2 02/09", [(g["gap_start"], g["gap_end"], g["prev_batch"], g["next_batch"]) for g in gaps["gaps"]], [
        ("2026-09-02 07:00:00", "2026-09-02 08:00:00", None, "C100030"),
        ("2026-09-02 20:00:00", "2026-09-03 07:00:00", "C100030", None),
    ], failures)
    _check("tổng khoảng idle = idle của ô", round(sum(g["hours"] for g in gaps["gaps"]), 2), m2["2026-09-02"]["idle"], failures)


def _scenario_filters(failures: list[str]) -> None:
    print("\n=== Kịch bản 3: filter Tank + Capacity ===")
    data = service.get_idle_matrix("2026-09-01", "2026-09-05")
    _check("available_tank_types", data["available_tank_types"], ["J tank", "O tank"], failures)
    _check("available_capacities", data["available_capacities"], [600.0, 1200.0], failures)
    _check("J tank -> M1", list(_rows(service.get_idle_matrix("2026-09-01", "2026-09-05", tank_types=["J tank"]))), ["M1"], failures)
    _check("Capacity 1200 -> M2", list(_rows(service.get_idle_matrix("2026-09-01", "2026-09-05", capacities=["1200"]))), ["M2"], failures)
    filtered = service.get_idle_matrix("2026-09-01", "2026-09-05", tank_types=["O tank"])
    _check("lọc không đổi giờ có dữ liệu của ngày", filtered["day_available_hours"]["2026-09-01"], 13.0, failures)


def _scenario_notes(failures: list[str]) -> None:
    print("\n=== Kịch bản 4: note nguyên nhân ===")
    gap_start = "2026-09-01 22:00:00"
    saved = service.upsert_idle_note("M1", "2026-09-01", gap_start, "Waiting for fabric", "no greige", 1)
    _check("lưu note", (saved["note"]["reason"], saved["note"]["detail"], saved["note"]["updated_by"]), ("Waiting for fabric", "no greige", "tester"), failures)
    try:
        service.upsert_idle_note("M1", "2026-09-01", gap_start, "Lunch", None, 1)
        _check("Reason ngoài danh sách bị từ chối", "accepted", "ValueError", failures)
    except ValueError:
        _check("Reason ngoài danh sách bị từ chối", "ValueError", "ValueError", failures)
    try:
        service.upsert_idle_note("M1", "2026-09-01", "2026-09-01 19:00:00", "No order", None, 1)
        _check("khoảng idle không tồn tại bị từ chối", "accepted", "ValueError", failures)
    except ValueError:
        _check("khoảng idle không tồn tại bị từ chối", "ValueError", "ValueError", failures)
    _check("ô đếm note", _rows(service.get_idle_matrix("2026-09-01", "2026-09-05"))["M1"]["cells"]["2026-09-01"]["noted_count"], 1, failures)

    # Import lại: mẻ C100000 kết thúc 22:30 -> khoảng idle giờ bắt đầu 22:30, note cũ thành stale.
    conn = get_db()
    conn.execute("UPDATE batch_details SET end_time = '2026-09-01 22:30:00' WHERE dyelot = 'C100000'")
    conn.commit()
    _recompute()
    gaps = service.get_idle_gaps("M1", "2026-09-01")
    _check("khoảng idle dịch sang 22:30", [g["gap_start"] for g in gaps["gaps"]], ["2026-09-01 22:30:00"], failures)
    _check("note cũ hiện ở stale_notes", [(n["gap_start"], n["reason"]) for n in gaps["stale_notes"]], [(gap_start, "Waiting for fabric")], failures)
    _check("ô không còn đếm note stale", _rows(service.get_idle_matrix("2026-09-01", "2026-09-05"))["M1"]["cells"]["2026-09-01"]["noted_count"], 0, failures)
    service.upsert_idle_note("M1", "2026-09-01", gap_start, None, None, 1)
    _check("xoá note stale", service.get_idle_gaps("M1", "2026-09-01")["stale_notes"], [], failures)
    service.upsert_idle_note("M1", "2026-09-01", "2026-09-01 22:30:00", "Maintenance", None, 1)


def _scenario_target_excel(failures: list[str]) -> None:
    print("\n=== Kịch bản 5: Target + Excel ===")
    _check("Target chưa đặt", service.get_target(), None, failures)
    service.set_target(10)
    _check("Target = 10", service.get_target(), 10.0, failures)
    try:
        service.set_target(120)
        _check("Target > 100 bị từ chối", "accepted", "ValueError", failures)
    except ValueError:
        _check("Target > 100 bị từ chối", "ValueError", "ValueError", failures)

    book = load_workbook(io.BytesIO(service.export_idle_excel("2026-09-01", "2026-09-05")))
    sheet = book["Idle Time"]
    header = [cell.value for cell in sheet[1]]
    _check("header", header, ["Machine", "Tank", "Capacity (Kg)", "2026-09-01", "2026-09-02", "2026-09-05", "Total (h)", "% Idle", "Target % Idle"], failures)
    m1 = [cell.value for cell in sheet[2]]
    _check("dòng M1 (giờ idle)", m1, ["M1", "J tank", 600, 0.5, 1.0, 0.0, 1.5, round(1.5 / 39 * 100, 2), 10.0], failures)
    _check("M2 01/09 (100% idle) tô màu vượt Target", sheet.cell(row=3, column=4).fill.start_color.rgb[-6:], "FFC7CE", failures)
    _check("M1 02/09 (4.2%) không tô màu", sheet.cell(row=2, column=5).fill.fill_type, None, failures)
    gaps = [[cell.value for cell in row] for row in book["Idle Gaps"].iter_rows(min_row=2)]
    _check("sheet Idle Gaps có note", [g[:6] for g in gaps if g[5]], [["M1", "2026-09-01", "2026-09-01 22:30:00", "2026-09-01 23:00:00", 0.5, "Maintenance"]], failures)
    operating = load_workbook(io.BytesIO(service.export_idle_excel("2026-09-01", "2026-09-05", mode="operating")))["Idle Time"]
    _check("mode operating: M1 01/09 = 4.5h + 8h", operating.cell(row=2, column=4).value, 12.5, failures)


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
            get_db().row_factory = sqlite3.Row
            _recompute()
            _scenario_matrix(failures)
            _scenario_filters(failures)
            _scenario_notes(failures)
            _scenario_target_excel(failures)
            close_db()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print(f"\n{'=' * 60}\nKẾT QUẢ: {'TẤT CẢ KHỚP' if not failures else f'{len(failures)} CASE LỆCH'}\n{'=' * 60}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
