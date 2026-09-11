"""
tests/test_postgres_shim_translation.py
------------------------------------------
Kiểm tra logic dịch SQL của `core/database.py::_PostgresConnCompat` (dual-mode
SQLite/Postgres shim) — `?` -> `%s`, `PRAGMA table_info(x)` -> truy vấn
`information_schema.columns`. Đây là phần MẤU CHỐT giúp ~16 file Engine không cần
sửa từng câu SQL khi chạy Postgres (xem memory-bank/systemPatterns.md).

Chỉ test hàm `_translate()` (staticmethod, thuần string) — KHÔNG cần Postgres thật
hay kết nối psycopg2 nào (môi trường phát triển không có Postgres cài sẵn).

Chạy: python tests/test_postgres_shim_translation.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.database import _PostgresConnCompat, get_dialect, sql_datetime  # noqa: E402


def _check(label: str, actual, expected, failures: list[str]) -> None:
    ok = actual == expected
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: actual={actual!r} expected={expected!r}")
    if not ok:
        failures.append(label)


def _test_placeholder_translation(failures: list[str]) -> None:
    print("=== '?' -> '%s' placeholder translation ===")
    _check(
        "1 placeholder đơn giản",
        _PostgresConnCompat._translate("SELECT * FROM users WHERE id = ?"),
        "SELECT * FROM users WHERE id = %s",
        failures,
    )
    _check(
        "Nhiều placeholder, thứ tự giữ nguyên",
        _PostgresConnCompat._translate("INSERT INTO t (a, b, c) VALUES (?, ?, ?)"),
        "INSERT INTO t (a, b, c) VALUES (%s, %s, %s)",
        failures,
    )
    # Pattern IN (?, ?, ?) động — build qua ",".join("?" for _ in items), xác nhận số lượng
    # placeholder giữ nguyên sau khi dịch (không đổi số lượng tham số cần truyền).
    dynamic_in = "SELECT * FROM t WHERE capacity_kg IN (" + ",".join("?" for _ in range(4)) + ")"
    translated = _PostgresConnCompat._translate(dynamic_in)
    _check(
        "IN (?, ?, ?, ?) động — đúng 4 placeholder sau khi dịch",
        translated.count("%s"),
        4,
        failures,
    )
    _check(
        "IN (?, ?, ?, ?) động — không còn '?' nào sót lại",
        "?" in translated,
        False,
        failures,
    )


def _test_pragma_translation(failures: list[str]) -> None:
    print()
    print("=== PRAGMA table_info(x) -> information_schema.columns ===")
    translated = _PostgresConnCompat._translate("PRAGMA table_info(availability_logs)")
    _check(
        "Dịch đúng sang SELECT information_schema.columns",
        translated,
        "SELECT column_name AS name FROM information_schema.columns "
        "WHERE table_name = 'availability_logs' ORDER BY ordinal_position",
        failures,
    )
    _check(
        "Kết quả vẫn có alias 'name' — call site {row['name'] for row in ...} không cần đổi",
        "AS name" in translated,
        True,
        failures,
    )
    # Case-insensitive + khoảng trắng thừa (đã thấy trong code thật: "PRAGMA table_info(x)"
    # luôn viết hoa PRAGMA, nhưng test thêm biến thể để chắc regex không quá chặt).
    translated_lower = _PostgresConnCompat._translate("pragma table_info( batch_details )")
    _check(
        "Case-insensitive + khoảng trắng trong ngoặc",
        "batch_details" in translated_lower and "information_schema" in translated_lower,
        True,
        failures,
    )


def _test_sql_datetime_dialect_aware(failures: list[str]) -> None:
    print()
    print("=== sql_datetime() — dialect-aware (chỉ test được nhánh SQLite ở đây, ===")
    print("=== không có Flask app context nên get_dialect() fallback qua env var) ===")
    _check("dialect mặc định (không DATABASE_URL) là sqlite", get_dialect(), "sqlite", failures)
    _check(
        "sql_datetime() giữ đúng hành vi datetime() của SQLite khi dialect=sqlite",
        sql_datetime("a.end_time"),
        "datetime(a.end_time)",
        failures,
    )


def _test_non_pragma_sql_not_affected(failures: list[str]) -> None:
    print()
    print("=== SQL thường (không phải PRAGMA) không bị đụng vào ngoài việc đổi placeholder ===")
    sql = "SELECT id, batch FROM availability_logs WHERE machine = ? AND capacity_kg IN (?, ?)"
    translated = _PostgresConnCompat._translate(sql)
    _check(
        "Giữ nguyên cấu trúc câu SELECT, chỉ đổi placeholder",
        translated,
        "SELECT id, batch FROM availability_logs WHERE machine = %s AND capacity_kg IN (%s, %s)",
        failures,
    )


def main() -> int:
    failures: list[str] = []
    _test_placeholder_translation(failures)
    _test_pragma_translation(failures)
    _test_sql_datetime_dialect_aware(failures)
    _test_non_pragma_sql_not_affected(failures)

    print()
    print("=" * 60)
    if failures:
        print(f"KẾT QUẢ: {len(failures)} CASE LỆCH: {failures}")
        return 1
    print("KẾT QUẢ: TẤT CẢ KHỚP")
    return 0


if __name__ == "__main__":
    sys.exit(main())
