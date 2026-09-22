"""
tests/test_rework_classification.py
--------------------------------------
Verify quy tắc phân loại Rework MỚI (2026-09-22, bản 3) của
`reports/cleaning_matrix.py::classify_batch_badge()` — THAY THẾ hoàn toàn cách cũ
(batch_type='Rework' HOẶC log_rework_minutes>0) bằng 2 điều kiện dựa trên MÃ:

  (a) CHỈ xét khi chữ số CUỐI CÙNG của Dyelot là CHỮ SỐ: khác '0' -> Rework; bằng '0' ->
      Normal. Dyelot kết thúc bằng CHỮ CÁI (hậu tố như "-WA"/"-KN"/"-DU" — mẻ rửa máy/mẻ thử
      nghiệm "experiment" hay bị loại khỏi tính toán khác) KHÔNG tính là tín hiệu Rework từ
      điều kiện này — mặc định Normal (kể cả hậu tố lạ chưa từng gặp), riêng "-WA" đã trả
      "CM" ngay ở Bước 1, không bao giờ chạm quy tắc Rework.
  (b) Chữ số ĐẦU TIÊN của SapLot > 1 -> Rework; = 1 -> Normal. SapLot rỗng/không bắt đầu
      bằng chữ số -> KHÔNG tính là tín hiệu Rework từ điều kiện này (an toàn, không bịa).
  2 điều kiện nối HOẶC — chỉ cần 1 trong 2 báo Rework là đủ.

1. Test đơn vị THUẦN `classify_batch_badge()` (không cần DB) cho từng trường hợp.
2. Test tích hợp `recompute_daily()` trên DB tạm — xác nhận cột `sap_lot` được SELECT +
   truyền đúng vào `classify_batch_badge()` qua đường thật (không chỉ unit test cô lập).

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

from modules.dyeing.engines.reports.cleaning_matrix import classify_batch_badge, recompute_daily  # noqa: E402


def _check(label: str, actual, expected, failures: list[str]) -> None:
    ok = actual == expected
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: actual={actual!r} expected={expected!r}")
    if not ok:
        failures.append(label)


def _scenario_unit_classify(failures: list[str]) -> None:
    print("\n=== Kịch bản 1: classify_batch_badge() — đơn vị thuần, không cần DB ===")
    base = {"shade": "Dark", "colour_no": "", "recipe_no": "", "customer_color": "", "batch_type": "Normal", "log_rework_minutes": 0}

    cases = [
        ("Dyelot kết thúc '0' + SapLot bắt đầu '1' -> Normal (khớp mẻ C260659920 thật)",
         {**base, "dyelot": "C260659920", "sap_lot": "1000092724"}, "D"),
        ("Dyelot kết thúc '1' -> Rework (dù SapLot Normal)",
         {**base, "dyelot": "C260659921", "sap_lot": "1000092724"}, "DR"),
        ("Dyelot kết thúc '2' -> Rework",
         {**base, "dyelot": "C260659922", "sap_lot": ""}, "DR"),
        ("Dyelot kết thúc CHỮ CÁI (hậu tố '-KN', mẻ experiment) -> Normal (KHÔNG phải Rework)",
         {**base, "dyelot": "C260659920-KN", "sap_lot": "1000092724"}, "D"),
        ("Dyelot kết thúc CHỮ CÁI (hậu tố '-DU', mẻ experiment) -> Normal (KHÔNG phải Rework)",
         {**base, "dyelot": "C260659920-DU", "sap_lot": "1000092724"}, "D"),
        ("Dyelot kết thúc CHỮ CÁI lạ chưa từng gặp -> mặc định Normal (không bịa Rework)",
         {**base, "dyelot": "C260659920-XY", "sap_lot": "1000092724"}, "D"),
        ("Dyelot kết thúc '-WA' -> CM (Bước 1 short-circuit, KHÔNG áp quy tắc Rework)",
         {**base, "dyelot": "C260659920-WA", "sap_lot": "1000092724"}, "CM"),
        ("SapLot bắt đầu '2' (>1) -> Rework (dù Dyelot kết thúc '0')",
         {**base, "dyelot": "C260659920", "sap_lot": "2000092724"}, "DR"),
        ("SapLot bắt đầu '9' (>1) -> Rework",
         {**base, "dyelot": "C260659920", "sap_lot": "9000092724"}, "DR"),
        ("SapLot rỗng + Dyelot kết thúc '0' -> Normal (không bịa Rework khi thiếu căn cứ)",
         {**base, "dyelot": "C260659920", "sap_lot": ""}, "D"),
        ("SapLot không bắt đầu bằng chữ số -> KHÔNG tính là tín hiệu Rework từ SapLot",
         {**base, "dyelot": "C260659920", "sap_lot": "ABC123"}, "D"),
        ("CẢ 2 điều kiện đều báo Rework -> vẫn chỉ 1 hậu tố 'R' (không nhân đôi)",
         {**base, "dyelot": "C260659921", "sap_lot": "2000092724"}, "DR"),
        ("batch_type='Rework' cũ + log_rework_minutes>0 KHÔNG còn tác dụng (đã thay thế hoàn toàn)",
         {**base, "dyelot": "C260659920", "sap_lot": "1000092724", "batch_type": "Rework", "log_rework_minutes": 99}, "D"),
    ]
    for label, batch, expected in cases:
        _check(label, classify_batch_badge(batch), expected, failures)


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
    """Xác nhận `sap_lot` được SELECT + truyền đúng vào `classify_batch_badge()` qua đường
    thật `recompute_daily()` (không chỉ unit test cô lập `classify_batch_badge()`)."""
    print("\n=== Kịch bản 2: recompute_daily() end-to-end — sap_lot đi đúng đường JOIN thật ===")
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
            "INSERT INTO batch_details (dyelot, sap_lot, shade, batch_type) VALUES (?, ?, ?, ?)",
            ("C900001", "2000011111", "Dark", "Normal"),
        )
        conn.commit()
        recompute_daily(day, conn)
        row = conn.execute(
            "SELECT badge, is_rework FROM cleaning_mc_daily_summary WHERE production_date=? AND dyelot_ref='C900001'",
            (day.isoformat(),),
        ).fetchone()
        conn.close()

        _check("Đọc SapLot='20...' (đầu >1) qua JOIN thật -> badge kết thúc 'R'", row["badge"].endswith("R") if row else None, True, failures)
        _check("is_rework lưu trong summary = 1", row["is_rework"] if row else None, 1, failures)
    finally:
        os.unlink(db_path)


def main() -> int:
    failures: list[str] = []
    _scenario_unit_classify(failures)
    _scenario_recompute_daily_integration(failures)
    print(f"\n{'='*60}\nKẾT QUẢ: {'TẤT CẢ KHỚP' if not failures else f'{len(failures)} CASE LỆCH'}\n{'='*60}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
