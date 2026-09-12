"""
tests/test_downtime_case_notes_context.py
------------------------------------------
Xác nhận fix bug thật: `downtime_case_notes` trước đây khoá UNIQUE(availability_log_id)
— 1 note dùng CHUNG cho MỌI category ("Downtime by Category") / field ("Data Quality")
mà 1 mẻ xuất hiện, nên sửa note ở category này làm lộ/đổi luôn note ở category khác của
CÙNG mẻ. Đã đổi khoá thành UNIQUE(availability_log_id, context).

3 điều cần verify (không phải giả định — build DB tạm mô phỏng ĐÚNG bảng cũ rồi để code
tự lazy-migrate, giống hệt tình huống DB thật đã có 27 note production):
1. Bảng SQLite cũ (chưa có cột `context`) được tự migrate, dữ liệu cũ giữ nguyên ở
   context='' — KHÔNG mất note đã nhập trước đây.
2. Note cũ (context='') hiển thị làm FALLBACK cho category CHƯA có note riêng.
3. Ghi note riêng cho 1 category KHÔNG ảnh hưởng tới note của category khác của CÙNG mẻ
   (kể cả note cũ context='' lẫn note context khác đã ghi trước đó) — đây chính là bug đã
   sửa, không phải hành vi phụ.

Dùng DB TẠM (file SQLite tạm + Flask app context tạm), KHÔNG đụng DB thật.
Chạy: python tests/test_downtime_case_notes_context.py
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
from modules.dyeing.engines.downtime import service  # noqa: E402


def _make_temp_app(db_path: str) -> Flask:
    app = Flask(__name__)
    app.config["DATABASE_PATH"] = db_path
    app.config["SQLITE_PRAGMAS"] = {}
    return app


def _init_schema_with_legacy_case_notes(db_path: str) -> None:
    """Dựng đúng bảng `downtime_case_notes` SCHEMA CŨ (trước khi có `context`) kèm 1 note
    thật đã nhập từ trước — mô phỏng chính xác tình huống DB production hiện có."""
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT)")
    conn.execute("CREATE TABLE availability_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, batch TEXT)")
    conn.execute("""
        CREATE TABLE downtime_case_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            availability_log_id INTEGER NOT NULL REFERENCES availability_logs (id) ON DELETE CASCADE,
            reason TEXT,
            detail TEXT,
            updated_by INTEGER NOT NULL REFERENCES users (id),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE (availability_log_id)
        )
    """)
    conn.execute("INSERT INTO users (id, username) VALUES (1, 'admin')")
    conn.execute("INSERT INTO availability_logs (id, batch) VALUES (1, 'B001')")
    conn.execute(
        "INSERT INTO downtime_case_notes (availability_log_id, reason, detail, updated_by, updated_at) "
        "VALUES (1, 'Old reason (legacy)', 'Old detail (legacy)', 1, '2026-01-01 00:00:00')"
    )
    conn.commit()
    conn.close()


def _check(label: str, actual, expected, failures: list[str]) -> None:
    ok = actual == expected
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: actual={actual!r} expected={expected!r}")
    if not ok:
        failures.append(label)


def run() -> bool:
    failures: list[str] = []
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        _init_schema_with_legacy_case_notes(db_path)
        app = _make_temp_app(db_path)

        with app.app_context():
            print("1. Lazy-migrate bảng cũ + fallback note legacy cho category CHƯA có note riêng")
            rework_batch = [{"availability_log_id": 1}]
            service._attach_case_notes(rework_batch, context="Rework")
            _check("Rework fallback về note legacy", rework_batch[0]["case_reason"], "Old reason (legacy)", failures)

            columns = {row[1] for row in sqlite3.connect(db_path).execute("PRAGMA table_info(downtime_case_notes)").fetchall()}
            _check("Cột context đã được thêm sau migrate", "context" in columns, True, failures)
            legacy_count = sqlite3.connect(db_path).execute("SELECT COUNT(*) FROM downtime_case_notes WHERE context = ''").fetchone()[0]
            _check("Note legacy vẫn còn đúng 1 dòng (context='')", legacy_count, 1, failures)

            print("2. Ghi note RIÊNG cho category 'Rework' — không được đụng note legacy")
            service.upsert_case_note(1, "Rework", "New Rework reason", "New Rework detail", user_id=1)
            rework_batch2 = [{"availability_log_id": 1}]
            service._attach_case_notes(rework_batch2, context="Rework")
            _check("Rework giờ đọc đúng note riêng vừa ghi", rework_batch2[0]["case_reason"], "New Rework reason", failures)

            print("3. Category KHÁC ('Color Adjustment') của CÙNG mẻ PHẢI vẫn thấy note legacy (chưa bị đổi theo Rework)")
            ca_batch = [{"availability_log_id": 1}]
            service._attach_case_notes(ca_batch, context="Color Adjustment")
            _check("Color Adjustment vẫn fallback về note legacy, KHÔNG lộ note Rework", ca_batch[0]["case_reason"], "Old reason (legacy)", failures)

            print("4. Ghi note RIÊNG cho 'Color Adjustment' — không được đụng note Rework lẫn note legacy")
            service.upsert_case_note(1, "Color Adjustment", "CA reason", "CA detail", user_id=1)
            ca_batch2 = [{"availability_log_id": 1}]
            service._attach_case_notes(ca_batch2, context="Color Adjustment")
            _check("Color Adjustment đọc đúng note riêng vừa ghi", ca_batch2[0]["case_reason"], "CA reason", failures)

            rework_batch3 = [{"availability_log_id": 1}]
            service._attach_case_notes(rework_batch3, context="Rework")
            _check("Rework KHÔNG bị đổi bởi lần ghi Color Adjustment (bug đã sửa)", rework_batch3[0]["case_reason"], "New Rework reason", failures)

            total_rows = sqlite3.connect(db_path).execute("SELECT COUNT(*) FROM downtime_case_notes").fetchone()[0]
            _check("Tổng 3 dòng độc lập trong DB (legacy + Rework + Color Adjustment, không ghi đè nhau)", total_rows, 3, failures)

            close_db()
    finally:
        try:
            os.remove(db_path)
        except OSError:
            pass

    print()
    if failures:
        print(f"FAILED ({len(failures)}): {failures}")
        return False
    print("ALL PASSED")
    return True


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
