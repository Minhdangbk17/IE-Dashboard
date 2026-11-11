from __future__ import annotations

import io
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import Flask  # noqa: E402
from openpyxl import Workbook, load_workbook  # noqa: E402

import core.batch_importer as batch_importer  # noqa: E402
from core.batch_importer import sync_batch_details  # noqa: E402
from core.database import close_db  # noqa: E402
from core.excel_importer import _parse_raw_row, AVAILABILITY_COLUMNS, PERFORMANCE_COLUMNS, save_to_db  # noqa: E402
from modules.dyeing.engines.excel_import.service import export_data  # noqa: E402

HEADERS = [
    "Dyelot", "Machine", "TreatmentProgram", "Shade", "RecipeNo", "Weight", "ReDye", "RunTime",
    "BatchType", "FabricType", "ScheduleTime", "StartTime", "EndTime",
]


def _check(label: str, actual, expected, failures: list[str]) -> None:
    ok = actual == expected
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: actual={actual!r} expected={expected!r}")
    if not ok:
        failures.append(label)


def _batch_xlsx() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(HEADERS)
    sheet.append(["B-1", "D900", "P", "Dark", "R1", 100, None, 0, "Normal", "Cotton", "2026-09-01 08:00:00", "2026-09-01 08:00:00", "2026-09-01 12:00:00"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _scenario_batch_export(failures: list[str]) -> None:
    print("\n=== Batch: ReDye rỗng -> rỗng, RunTime = 0 thật -> 0, Weight = 100 ===")
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE availability_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, batch TEXT, end_time TEXT)")
        conn.commit()
        conn.close()
        app = Flask(__name__)
        app.config["DATABASE_PATH"] = db_path
        app.config["SQLITE_PRAGMAS"] = {}
        batch_importer.trigger_recompute = lambda *args, **kwargs: None
        with app.app_context():
            sync_batch_details(_batch_xlsx(), imported_by="tester", filename="b.xlsx")
            content, _ = export_data("batch", "2026-09-01", "2026-09-02")
            close_db()
        sheet = load_workbook(io.BytesIO(content)).active
        header = [cell.value for cell in sheet[1]]
        row = [cell.value for cell in sheet[2]]
        values = dict(zip(header, row))
        _check("Weight = 100", values["Weight"], 100, failures)
        _check("RunTime = 0 (số 0 thật)", values["RunTime"], 0, failures)
        _check("ReDye rỗng", values["ReDye"], None, failures)
        _check("LiquorRatio rỗng", values["LiquorRatio"], None, failures)
    finally:
        os.unlink(db_path)


def _scenario_raw_parse(failures: list[str]) -> None:
    print("\n=== Availability / Performance: blank_fields ===")
    fields = list(AVAILABILITY_COLUMNS.values())
    raw = {"batch": "B1", "machine": "M1", "start_time": "2026-09-01 08:00:00", "load_hour": 0, "unload_hour": None}
    record, error = _parse_raw_row("AVAILABILITY", fields, {"batch", "machine", "start_time"}, raw)
    _check("không lỗi", error, None, failures)
    blank = set(record["blank_fields"].split(","))
    _check("load_hour = 0 không bị coi là rỗng", "load_hour" in blank, False, failures)
    _check("unload_hour rỗng được ghi nhận", "unload_hour" in blank, True, failures)
    _check("giá trị lưu vẫn là 0.0", record["unload_hour"], 0.0, failures)

    performance_fields = list(PERFORMANCE_COLUMNS.values())
    raw_perf = {"dyelot": "B1", "machine": "M1", "start_time": "2026-09-01 08:00:00", "speed": 5}
    record, error = _parse_raw_row("PERFORMANCE", performance_fields, {"dyelot", "machine", "start_time"}, raw_perf)
    _check("Performance: speed không rỗng", "speed" in record["blank_fields"].split(","), False, failures)
    _check("Performance: loading rỗng", "loading" in record["blank_fields"].split(","), True, failures)

    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        app = Flask(__name__)
        app.config["DATABASE_PATH"] = db_path
        app.config["SQLITE_PRAGMAS"] = {}
        with app.app_context():
            from core.database import get_db
            connection = get_db()
            save_to_db({"rows": [record]}, "PERFORMANCE", connection)
            stored = connection.execute("SELECT blank_fields FROM performance_logs").fetchone()["blank_fields"]
            close_db()
        _check("blank_fields được lưu vào DB", "loading" in stored.split(","), True, failures)
    finally:
        os.unlink(db_path)


def main() -> int:
    failures: list[str] = []
    _scenario_batch_export(failures)
    _scenario_raw_parse(failures)
    print()
    if failures:
        print(f"FAIL: {len(failures)} kiểm tra lỗi: {failures}")
        return 1
    print("PASS: tất cả kiểm tra đạt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
