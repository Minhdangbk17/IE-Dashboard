"""
tests/test_batch_importer.py
------------------------------
Verify `core/batch_importer.py::sync_batch_details()` sau khi đổi khoá bảng `batch_details`
từ `dyelot TEXT PRIMARY KEY` sang `id` surrogate + UNIQUE(dyelot, machine, start_time) — cho
phép 1 Dyelot có NHIỀU dòng (mẻ gốc + mẻ redye chạy lại), thay vì dòng sau ghi đè mất dòng
trước (bug thật phát hiện qua mẻ C260659920, xem memory-bank/activeContext.md):

  1. Import file mẫu THẬT `Batch_202681092911.xlsx` (có 2 dòng cùng Dyelot C260659920 — mẻ gốc
     NG kết thúc 2026-08-01 + mẻ redye kết thúc 2026-08-08) -> `batch_details` PHẢI giữ ĐỦ CẢ 2
     dòng, mỗi dòng đúng weight/dye_cost/recipe_no riêng (KHÔNG bị ghi đè mất mẻ gốc).
  2. Dòng trùng THẬT 100% (cùng dyelot+machine+start_time xuất hiện 2 lần trong CÙNG 1 file,
     mô phỏng lỗi nhập liệu/export trùng dòng) vẫn phải khử trùng đúng — chỉ còn 1 dòng.
  3. Import LẶP LẠI cùng file (re-import) — UPSERT đúng theo (dyelot, machine, start_time):
     dòng khớp cả 3 khoá được CẬP NHẬT tại chỗ (không nhân đôi), không ảnh hưởng dòng khác
     dyelot.

Dùng DB TẠM (file SQLite tạm + Flask app context tạm, KHÔNG đụng DB thật) — cùng pattern
`tests/test_rft_classification.py`.

Chạy: python tests/test_batch_importer.py
"""
from __future__ import annotations

import io
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import Flask  # noqa: E402
from openpyxl import Workbook  # noqa: E402

from core.batch_importer import sync_batch_details  # noqa: E402
from core.database import close_db  # noqa: E402

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "sample_imports" / "Batch_202681092911.xlsx"

BATCH_HEADERS = [
    "Dyelot", "Customer", "OrderNo", "GreigeCode", "RecipeNo", "ColourNo", "Shade", "Machine",
    "MachineGroup", "TreatmentProgram", "BatchState", "FormulaCode", "FormulaType", "ReDye",
    "Weight", "ProcessType", "BatchType", "FabricType", "ScheduleTime", "StartTime", "EndTime",
]


def _make_temp_app(db_path: str) -> Flask:
    app = Flask(__name__)
    app.config["DATABASE_PATH"] = db_path
    app.config["SQLITE_PRAGMAS"] = {}
    return app


def _init_availability_logs(db_path: str) -> None:
    """`sync_batch_details()` JOIN `availability_logs` (đếm 'synced' + tính affected_dates cho
    Daily Rollup) — bảng này KHÔNG được `sync_batch_details()` tự tạo (thuộc luồng import
    Availability riêng), phải có sẵn trước khi gọi hàm trong DB tạm. Để RỖNG là đủ: `batch_details`
    trong các kịch bản dưới đây không cần khớp `availability_logs` nào cả (affected_dates rỗng
    -> `trigger_recompute()` return sớm, không đụng tới các bảng `*_daily_summary` khác)."""
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE availability_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, batch TEXT, end_time TEXT)")
    conn.commit()
    conn.close()


def _check(label: str, actual, expected, failures: list[str]) -> None:
    ok = actual == expected
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: actual={actual!r} expected={expected!r}")
    if not ok:
        failures.append(label)


def _build_batch_xlsx(rows: list[dict[str, object]]) -> bytes:
    """Dựng 1 file .xlsx Batch tối giản trong bộ nhớ (không cần fixture trên đĩa) — dùng cho
    kịch bản khử trùng dòng trùng thật, không phụ thuộc dữ liệu mẫu thật."""
    wb = Workbook()
    ws = wb.active
    ws.append(BATCH_HEADERS)
    for row in rows:
        ws.append([row.get(header, "") for header in BATCH_HEADERS])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _scenario_real_fixture_keeps_both_runs(failures: list[str]) -> None:
    """File mẫu THẬT có 2 dòng cùng Dyelot C260659920 (mẻ gốc NG + mẻ redye) — PHẢI giữ ĐỦ
    CẢ 2 dòng trong `batch_details` sau khi import, không còn dòng nào bị ghi đè mất."""
    print("\n=== Kịch bản 1: file mẫu thật (C260659920, mẻ gốc + redye) — giữ ĐỦ 2 dòng ===")
    if not FIXTURE_PATH.exists():
        print(f"  [SKIP] Không tìm thấy fixture {FIXTURE_PATH}")
        return
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        _init_availability_logs(db_path)
        file_bytes = FIXTURE_PATH.read_bytes()
        app = _make_temp_app(db_path)
        with app.app_context():
            result = sync_batch_details(file_bytes, imported_by="tester", filename="Batch_202681092911.xlsx")
            close_db()

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT weight, dye_cost, recipe_no, redye, start_time, end_time FROM batch_details "
            "WHERE dyelot='C260659920' ORDER BY end_time"
        ).fetchall()
        conn.close()

        _check("status = completed", result["status"], "completed", failures)
        _check("C260659920: đủ 2 dòng (mẻ gốc + redye)", len(rows), 2, failures)
        if len(rows) == 2:
            original, redye = rows[0], rows[1]
            _check("Mẻ gốc: weight=265", original["weight"], 265.0, failures)
            _check("Mẻ gốc: dye_cost ~ 94.65825", round(original["dye_cost"], 4), 94.6582, failures)
            _check("Mẻ gốc: redye=0", original["redye"], 0.0, failures)
            _check("Mẻ redye: weight=253", redye["weight"], 253.0, failures)
            _check("Mẻ redye: dye_cost ~ 5.116343", round(redye["dye_cost"], 4), 5.1163, failures)
            _check("Mẻ redye: redye=1", redye["redye"], 1.0, failures)
            _check("Mẻ redye: recipe_no chứa DG09 (recipe redye)", "DG09" in (redye["recipe_no"] or ""), True, failures)
    finally:
        os.unlink(db_path)


def _scenario_true_duplicate_row_dedup(failures: list[str]) -> None:
    """Dòng trùng THẬT 100% (cùng dyelot+machine+start_time xuất hiện 2 LẦN trong CÙNG 1 file)
    vẫn PHẢI khử trùng đúng — chỉ giữ 1 dòng (giữ giá trị dòng CUỐI xuất hiện trong file, đúng
    hành vi dedupe cũ khi thực sự là CÙNG 1 lần chạy, KHÔNG phải 2 lần chạy khác nhau)."""
    print("\n=== Kịch bản 2: dòng trùng thật 100% (cùng dyelot+machine+start_time) — vẫn khử trùng ===")
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        _init_availability_logs(db_path)
        file_bytes = _build_batch_xlsx([
            {
                "Dyelot": "T-DUP-1", "Machine": "D900", "StartTime": "2026-09-01 08:00:00",
                "EndTime": "2026-09-01 10:00:00", "Weight": 100, "BatchType": "Normal",
            },
            {
                # Cùng dyelot+machine+start_time -> coi là CÙNG 1 lần chạy, dòng SAU ghi đè dòng trước.
                "Dyelot": "T-DUP-1", "Machine": "D900", "StartTime": "2026-09-01 08:00:00",
                "EndTime": "2026-09-01 10:05:00", "Weight": 105, "BatchType": "Normal",
            },
        ])
        app = _make_temp_app(db_path)
        with app.app_context():
            result = sync_batch_details(file_bytes, imported_by="tester", filename="dup_test.xlsx")
            close_db()

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT weight, end_time FROM batch_details WHERE dyelot='T-DUP-1'").fetchall()
        conn.close()

        _check("status = completed", result["status"], "completed", failures)
        _check("Chỉ còn 1 dòng (khử trùng đúng)", len(rows), 1, failures)
        if rows:
            _check("Giữ giá trị dòng CUỐI xuất hiện trong file (weight=105)", rows[0]["weight"], 105.0, failures)
    finally:
        os.unlink(db_path)


def _scenario_reimport_upserts_matching_run(failures: list[str]) -> None:
    """Import LẶP LẠI file có dyelot đã tồn tại — dòng khớp ĐÚNG (dyelot, machine, start_time)
    được CẬP NHẬT tại chỗ (không nhân đôi), dòng khác dyelot/thời gian KHÔNG bị đụng tới."""
    print("\n=== Kịch bản 3: import lặp lại — UPSERT đúng theo (dyelot, machine, start_time) ===")
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        _init_availability_logs(db_path)
        first_bytes = _build_batch_xlsx([
            {
                "Dyelot": "T-REIMPORT", "Machine": "D901", "StartTime": "2026-09-02 08:00:00",
                "EndTime": "2026-09-02 10:00:00", "Weight": 200, "BatchType": "Normal",
            },
        ])
        second_bytes = _build_batch_xlsx([
            {
                # Cùng (dyelot, machine, start_time) -> UPSERT cập nhật Weight, KHÔNG tạo dòng mới.
                "Dyelot": "T-REIMPORT", "Machine": "D901", "StartTime": "2026-09-02 08:00:00",
                "EndTime": "2026-09-02 10:30:00", "Weight": 210, "BatchType": "Normal",
            },
        ])
        app = _make_temp_app(db_path)
        with app.app_context():
            sync_batch_details(first_bytes, imported_by="tester", filename="reimport_1.xlsx")
            sync_batch_details(second_bytes, imported_by="tester", filename="reimport_2.xlsx")
            close_db()

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT weight, end_time FROM batch_details WHERE dyelot='T-REIMPORT'").fetchall()
        conn.close()

        _check("Vẫn CHỈ 1 dòng sau 2 lần import (UPSERT, không nhân đôi)", len(rows), 1, failures)
        if rows:
            _check("Weight đã được CẬP NHẬT (210, không phải 200 cũ)", rows[0]["weight"], 210.0, failures)
    finally:
        os.unlink(db_path)


def main() -> int:
    failures: list[str] = []
    _scenario_real_fixture_keeps_both_runs(failures)
    _scenario_true_duplicate_row_dedup(failures)
    _scenario_reimport_upserts_matching_run(failures)
    print(f"\n{'='*60}\nKẾT QUẢ: {'TẤT CẢ KHỚP' if not failures else f'{len(failures)} CASE LỆCH'}\n{'='*60}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
