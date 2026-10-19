"""
tests/test_availability_text_numbers.py
----------------------------------------
2026-10-19 — File Availability xuất từ hệ thống đổi Load/Unload (hour) sang dạng TEXT ("0.11",
ô trống thay cho 0). Kiểm tra importer ép về số như cũ:

  1. `_raw_float` với các biến thể text (dấu chấm/phẩy thập phân, phẩy hàng nghìn, NBSP, ' ở đầu).
  2. Parse file mẫu thật `Availability_20261016-19.xlsx` -> load_hour/unload_hour là float.

Chạy: python tests/test_availability_text_numbers.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import excel_importer  # noqa: E402
from core.excel_importer import STANDARD_HOURS, _raw_float, detect_and_parse_file  # noqa: E402

SAMPLE = Path(__file__).resolve().parent / "fixtures" / "sample_imports" / "Availability_20261016-19.xlsx"


def _check(label: str, actual, expected, failures: list[str]) -> None:
    ok = actual == expected
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: actual={actual!r} expected={expected!r}")
    if not ok:
        failures.append(label)


def main() -> int:
    failures: list[str] = []

    print("1. _raw_float với giá trị text")
    cases = [
        ("0.11", 0.11), ("0.10", 0.1), ("'0.09", 0.09), ("0,11", 0.11), ("1,234", 1234.0),
        ("1,234.5", 1234.5), (" 0.07 ", 0.07), ("", 0.0), (None, 0.0), (0, 0.0), (3.92, 3.92),
    ]
    for value, expected in cases:
        _check(f"_raw_float({value!r})", _raw_float(value), expected, failures)
    try:
        _raw_float("abc")
        failures.append("_raw_float('abc') phải báo lỗi")
        print("  [FAIL] _raw_float('abc') không báo lỗi")
    except ValueError:
        print("  [PASS] _raw_float('abc') báo lỗi")

    print("2. File mẫu Availability_20261016-19.xlsx (Load/Unload dạng text)")
    # Không cần DB: dùng Standard mặc định thay cho bảng downtime_achievement_standards.
    with patch.object(excel_importer, "get_achievement_standard_hours_by_field", return_value=dict(STANDARD_HOURS)):
        parsed = detect_and_parse_file(str(SAMPLE))
    rows = parsed["rows"]
    _check("Số dòng hợp lệ", len(rows), 239, failures)
    _check("load_hour toàn bộ là float", all(isinstance(r["load_hour"], float) for r in rows), True, failures)
    _check("unload_hour toàn bộ là float", all(isinstance(r["unload_hour"], float) for r in rows), True, failures)
    _check("Σ load_hour", round(sum(r["load_hour"] for r in rows), 2), 21.86, failures)
    _check("Σ unload_hour", round(sum(r["unload_hour"] for r in rows), 2), 17.02, failures)
    _check("Ô trống -> 0 (số dòng load_hour = 0)", sum(1 for r in rows if r["load_hour"] == 0), 24, failures)

    print("=" * 60)
    print("All checks passed." if not failures else f"{len(failures)} check(s) FAILED: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
