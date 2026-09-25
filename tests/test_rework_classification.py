"""
tests/test_rework_classification.py
--------------------------------------
Verify quy tắc phân loại Batch Badge MỚI (2026-09-25, waterfall 4 bước — THAY THẾ HOÀN TOÀN
quy tắc CM/Rework trước đó) của `reports/cleaning_matrix.py::classify_batch_badge()`:

  1. Cleaning MC (CM): Dyelot chứa "-WA" HOẶC Dyelot BẮT ĐẦU bằng "CL".
  2. Mẻ mẫu (Sample, badge "S"): Dyelot chứa "-DU" HOẶC "-KN", HOẶC SapLot bắt đầu bằng "4".
     Loại HOÀN TOÀN khỏi Normal/Rework (không có màu, không hậu tố "R").
  3. Tông màu cơ bản B/D/M/L/W — KHÔNG đổi so với bản cũ.
  4. Normal (base) vs Rework (base + "R") — Normal khi ĐỦ CẢ: Dyelot kết thúc bằng "0", VÀ
     SapLot bắt đầu bằng "1" HOẶC "3", VÀ (nếu `require_redye_zero=True`, mặc định) ReDye = 0
     (cột số thô `batch_details.redye`, KHÔNG phải `batch_type`). Thiếu 1 trong 3 -> Rework.

`require_redye_zero=False` (checkbox "ReDye = 0" TẮT trên UI) bỏ điều kiện ReDye — dùng ở
READ TIME qua `_effective_badge_is_rework()`, KHÔNG đụng `classify_batch_badge()` (luôn ghi
với require_redye_zero=True cố định).

1. Test đơn vị THUẦN `classify_batch_badge()` (không cần DB) cho từng trường hợp.
2. Test tích hợp `recompute_daily()` trên DB tạm — xác nhận `sap_lot`/`redye` được SELECT +
   truyền đúng vào `classify_batch_badge()` qua đường thật (không chỉ unit test cô lập).
3. Test `_effective_badge_is_rework()` (read-time override khi checkbox "ReDye = 0" tắt).

Chạy: python tests/test_rework_classification.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.dyeing.engines.reports.cleaning_matrix import _effective_badge_is_rework, classify_batch_badge, recompute_daily  # noqa: E402


def _check(label: str, actual, expected, failures: list[str]) -> None:
    ok = actual == expected
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: actual={actual!r} expected={expected!r}")
    if not ok:
        failures.append(label)


def _scenario_unit_classify(failures: list[str]) -> None:
    print("\n=== Kịch bản 1: classify_batch_badge() — đơn vị thuần, không cần DB ===")
    base = {"shade": "Dark", "colour_no": "", "recipe_no": "", "customer_color": "", "batch_type": "Normal", "redye": 0}

    cases = [
        ("Dyelot kết thúc '0' + SapLot bắt đầu '1' + ReDye=0 -> Normal",
         {**base, "dyelot": "C260659920", "sap_lot": "1000092724"}, "D"),
        ("Dyelot kết thúc '0' + SapLot bắt đầu '3' (MỚI, trước đây SapLot đầu '3' là Rework) -> Normal",
         {**base, "dyelot": "C260659920", "sap_lot": "3000092724"}, "D"),
        ("Dyelot kết thúc '1' (không phải '0') -> Rework dù SapLot/ReDye đều hợp lệ",
         {**base, "dyelot": "C260659921", "sap_lot": "1000092724"}, "DR"),
        ("Dyelot kết thúc CHỮ CÁI lạ (KHÔNG phải WA/DU/KN) -> Rework (MỚI, trước đây mặc định Normal)",
         {**base, "dyelot": "C260659920-XY", "sap_lot": "1000092724"}, "DR"),
        ("SapLot bắt đầu '2' -> Rework (không thuộc {1,3})",
         {**base, "dyelot": "C260659920", "sap_lot": "2000092724"}, "DR"),
        ("SapLot rỗng -> Rework (thiếu điều kiện SapLot 1*/3*)",
         {**base, "dyelot": "C260659920", "sap_lot": ""}, "DR"),
        ("ReDye != 0 -> Rework dù Dyelot/SapLot đều hợp lệ (checkbox mặc định BẬT)",
         {**base, "dyelot": "C260659920", "sap_lot": "1000092724", "redye": 1}, "DR"),
        ("Dyelot kết thúc '-WA' (có dấu gạch) -> CM",
         {**base, "dyelot": "C260659920-WA", "sap_lot": "1000092724"}, "CM"),
        ("Dyelot kết thúc 'WA' THIẾU dấu gạch -> vẫn CM (2026-09-25 bản 2, raw data đôi khi thiếu dấu '-')",
         {**base, "dyelot": "C260659920WA", "sap_lot": "1000092724"}, "CM"),
        ("Dyelot chứa 'WA' ở GIỮA (không phải cuối chuỗi) -> KHÔNG phải CM (endswith, không phải substring)",
         {**base, "dyelot": "C260WA659920", "sap_lot": "1000092724"}, "D"),
        ("Dyelot BẮT ĐẦU bằng 'CL' -> CM (MỚI)",
         {**base, "dyelot": "CL0659920", "sap_lot": "1000092724"}, "CM"),
        ("Dyelot chứa 'CL' nhưng KHÔNG bắt đầu bằng 'CL' -> KHÔNG phải CM",
         {**base, "dyelot": "C260CL9920", "sap_lot": "1000092724"}, "D"),
        ("Dyelot kết thúc '-DU' (có dấu gạch) -> Sample 'S' (MỚI, trước đây mặc định Normal)",
         {**base, "dyelot": "C260659920-DU", "sap_lot": "1000092724"}, "S"),
        ("Dyelot kết thúc 'DU' THIẾU dấu gạch -> vẫn Sample 'S'",
         {**base, "dyelot": "C260659920DU", "sap_lot": "1000092724"}, "S"),
        ("Dyelot kết thúc '-KN' (có dấu gạch) -> Sample 'S' (MỚI, trước đây mặc định Normal)",
         {**base, "dyelot": "C260659920-KN", "sap_lot": "1000092724"}, "S"),
        ("Dyelot kết thúc 'KN' THIẾU dấu gạch -> vẫn Sample 'S'",
         {**base, "dyelot": "C260659920KN", "sap_lot": "1000092724"}, "S"),
        ("Dyelot chứa 'DU' ở GIỮA (không phải cuối chuỗi) -> KHÔNG phải Sample",
         {**base, "dyelot": "C260DU659920", "sap_lot": "1000092724"}, "D"),
        ("SapLot bắt đầu '4' -> Sample 'S' (MỚI) dù Dyelot hợp lệ Normal",
         {**base, "dyelot": "C260659920", "sap_lot": "4000092724"}, "S"),
        ("Sample ưu tiên TRƯỚC Normal/Rework (Dyelot kết thúc '1' + SapLot '4' vẫn là Sample, không phải Rework)",
         {**base, "dyelot": "C260659921", "sap_lot": "4000092724"}, "S"),
        ("CM ưu tiên TRƯỚC Sample (Dyelot kết thúc 'WA' -> CM dù SapLot cũng khớp điều kiện Sample '4*')",
         {**base, "dyelot": "C260659920-WA", "sap_lot": "4000092724"}, "CM"),
    ]
    for label, batch, expected in cases:
        _check(label, classify_batch_badge(batch), expected, failures)

    print("\n=== Kịch bản 1b: require_redye_zero=False (checkbox TẮT) truyền thẳng vào classify_batch_badge() ===")
    _check("ReDye != 0 nhưng require_redye_zero=False -> Normal (bỏ qua điều kiện ReDye)",
           classify_batch_badge({**base, "dyelot": "C260659920", "sap_lot": "1000092724", "redye": 1}, require_redye_zero=False), "D", failures)


def _scenario_effective_badge(failures: list[str]) -> None:
    print("\n=== Kịch bản 2: _effective_badge_is_rework() — read-time override khi checkbox tắt ===")
    # require_redye_zero=True khớp giá trị đã lưu -> trả nguyên, không tính lại.
    badge, is_rework = _effective_badge_is_rework("DR", "C260659920", "1000092724", 1, require_redye_zero=True)
    _check("require_redye_zero=True (mặc định) -> trả nguyên badge đã lưu 'DR'", (badge, is_rework), ("DR", True), failures)

    # require_redye_zero=False -> tính lại, ReDye không còn chặn Normal nữa.
    badge, is_rework = _effective_badge_is_rework("DR", "C260659920", "1000092724", 1, require_redye_zero=False)
    _check("require_redye_zero=False -> tính lại 'D' (ReDye không còn chặn)", (badge, is_rework), ("D", False), failures)

    # Dyelot/SapLot vẫn không đạt -> vẫn Rework dù tắt checkbox.
    badge, is_rework = _effective_badge_is_rework("DR", "C260659921", "2000092724", 1, require_redye_zero=False)
    _check("require_redye_zero=False nhưng Dyelot/SapLot vẫn không đạt -> vẫn 'DR'", (badge, is_rework), ("DR", True), failures)

    # CM/Sample không bị đụng tới bởi checkbox.
    badge, is_rework = _effective_badge_is_rework("CM", "C260659920-WA", "1000092724", 1, require_redye_zero=False)
    _check("badge 'CM' không đổi dù tắt checkbox", (badge, is_rework), ("CM", False), failures)
    badge, is_rework = _effective_badge_is_rework("S", "C260659920-DU", "1000092724", 1, require_redye_zero=False)
    _check("badge 'S' (Sample) không đổi dù tắt checkbox", (badge, is_rework), ("S", False), failures)


def _init_schema(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE availability_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch TEXT, batch_ref_no TEXT, machine TEXT, capacity_kg REAL, program TEXT,
            fabric_type TEXT, start_time TEXT, end_time TEXT, rework_hour REAL DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE batch_details (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dyelot TEXT NOT NULL, sap_lot TEXT, shade TEXT, colour_no TEXT, customer_color TEXT,
            batch_type TEXT, recipe_no TEXT, redye REAL DEFAULT 0, is_rework INTEGER DEFAULT 0,
            greige_code TEXT, machine TEXT, start_time TEXT, end_time TEXT
        )
    """)
    conn.execute("CREATE TABLE machines (machine_id TEXT, machine_code TEXT, mc_brand TEXT, tank_type TEXT, mc_quantity INTEGER, tube_no INTEGER, capacity_kg REAL, domain TEXT)")
    conn.commit()
    conn.close()


def _scenario_recompute_daily_integration(failures: list[str]) -> None:
    """Xác nhận `sap_lot`/`redye` được SELECT + truyền đúng vào `classify_batch_badge()` qua
    đường thật `recompute_daily()` (không chỉ unit test cô lập)."""
    print("\n=== Kịch bản 3: recompute_daily() end-to-end — sap_lot/redye đi đúng đường JOIN thật ===")
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        _init_schema(db_path)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        day = date(2026, 9, 1)
        conn.execute(
            "INSERT INTO availability_logs (batch, machine, capacity_kg, start_time, end_time) VALUES (?, ?, ?, ?, ?)",
            ("C900001", "D700", 600, "2026-09-01 08:00:00", "2026-09-01 10:00:00"),
        )
        conn.execute(
            "INSERT INTO batch_details (dyelot, sap_lot, shade, batch_type, redye) VALUES (?, ?, ?, ?, ?)",
            ("C900001", "1000011111", "Dark", "Normal", 2),
        )
        conn.commit()
        recompute_daily(day, conn)
        row = conn.execute(
            "SELECT badge, is_rework, redye FROM cleaning_mc_daily_summary WHERE production_date=? AND dyelot_ref='C900001'",
            (day.isoformat(),),
        ).fetchone()
        conn.close()

        _check("ReDye=2 (!=0) qua JOIN thật -> badge kết thúc 'R' (Dyelot/SapLot hợp lệ nhưng ReDye chặn)", row["badge"].endswith("R") if row else None, True, failures)
        _check("is_rework lưu trong summary = 1", row["is_rework"] if row else None, 1, failures)
        _check("redye lưu trong summary = 2.0 (để read-time override dùng lại)", row["redye"] if row else None, 2.0, failures)
    finally:
        os.unlink(db_path)


def main() -> int:
    failures: list[str] = []
    _scenario_unit_classify(failures)
    _scenario_effective_badge(failures)
    _scenario_recompute_daily_integration(failures)
    print(f"\n{'='*60}\nKẾT QUẢ: {'TẤT CẢ KHỚP' if not failures else f'{len(failures)} CASE LỆCH'}\n{'='*60}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
