"""
tests/test_production_date.py
-------------------------------
Unit test cho `core/production_time.py::get_production_date()` — đảm bảo công thức cắt
ca 07:00 sáng không bị lặp lại sai ở nơi khác (bài học từ bug hiển thị nhầm ngày ở báo cáo
Cleaning MC: tầng JS lấy StartTime thay vì production_date backend đã tính đúng từ EndTime,
xem memory-bank/systemPatterns.md mục 6.2). Không dùng pytest (dự án cố tình giữ dependency
tối giản, xem CLAUDE.md) — chạy trực tiếp: `python tests/test_production_date.py`.

Chạy: python tests/test_production_date.py
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.production_time import get_production_date  # noqa: E402


def _check(label: str, actual, expected, failures: list[str]) -> None:
    status = "PASS" if actual == expected else "FAIL"
    print(f"  [{status}] {label}: actual={actual} expected={expected}")
    if actual != expected:
        failures.append(label)


def main() -> int:
    failures: list[str] = []

    print("=== get_production_date(): mốc trước/sau 07:00 trong cùng ngày dương lịch ===")
    _check(
        "05:30 (trước 07:00) -> thuộc ngày hôm trước",
        get_production_date(datetime(2026, 9, 6, 5, 30)),
        datetime(2026, 9, 5).date(),
        failures,
    )
    _check(
        "08:00 (sau 07:00) -> thuộc đúng ngày dương lịch",
        get_production_date(datetime(2026, 9, 6, 8, 0)),
        datetime(2026, 9, 6).date(),
        failures,
    )
    _check(
        "07:00:00 đúng mốc cắt -> thuộc ngày dương lịch (không lùi)",
        get_production_date(datetime(2026, 9, 6, 7, 0, 0)),
        datetime(2026, 9, 6).date(),
        failures,
    )
    _check(
        "06:59:59 ngay trước mốc cắt -> thuộc ngày hôm trước",
        get_production_date(datetime(2026, 9, 6, 6, 59, 59)),
        datetime(2026, 9, 5).date(),
        failures,
    )

    print("\n=== Mẻ batch chạy qua đêm — PHẢI dùng EndTime, KHÔNG dùng StartTime ===")
    # Ca thực tế lấy từ bug đã phát hiện: mẻ C260638611, StartTime=2026-08-24 21:43:49,
    # EndTime=2026-08-25 09:19:55. Theo đặc tả gốc, production_date PHẢI tính từ EndTime.
    start_time = datetime(2026, 8, 24, 21, 43, 49)
    end_time = datetime(2026, 8, 25, 9, 19, 55)
    _check(
        "get_production_date(EndTime) -> ngày EndTime (ĐÚNG, đây là cách dùng bắt buộc)",
        get_production_date(end_time),
        datetime(2026, 8, 25).date(),
        failures,
    )
    _check(
        "get_production_date(StartTime) -> ngày khác EndTime (SAI nếu dùng nhầm làm nguồn chính)",
        get_production_date(start_time),
        datetime(2026, 8, 24).date(),
        failures,
    )
    if get_production_date(start_time) == get_production_date(end_time):
        failures.append("StartTime và EndTime phải cho production_date KHÁC NHAU ở ca này (test vô nghĩa nếu trùng)")
    else:
        print("  [PASS] StartTime và EndTime cho production_date khác nhau đúng như kỳ vọng của ca qua đêm này")

    print(f"\n{'='*60}\nKẾT QUẢ: {'TẤT CẢ KHỚP' if not failures else f'{len(failures)} CASE LỆCH'}\n{'='*60}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
