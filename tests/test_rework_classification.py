from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.batch_source import dates_affected_by_batch, load_resolved_batches  # noqa: E402
from modules.dyeing.engines.reports.cleaning_matrix import badge_group, classify_batch_badge, is_scouring, recompute_daily  # noqa: E402


def _check(label: str, actual, expected, failures: list[str]) -> None:
    ok = actual == expected
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: actual={actual!r} expected={expected!r}")
    if not ok:
        failures.append(label)


def _scenario_unit_classify(failures: list[str]) -> None:
    print("\n=== Kịch bản 1: classify_batch_badge() — 7 bước ===")
    base = {"shade": "Dark", "colour_no": "", "recipe_no": "", "customer_color": "", "batch_type": "Normal", "dyelot": "C260659920", "sap_lot": "1000092724"}
    cases = [
        ("BatchType Normal -> Normal màu Dark", base, "D"),
        ("BatchType Rework -> Rework", {**base, "batch_type": "Rework"}, "DR"),
        ("Rework + Shade Light -> LR", {**base, "batch_type": "Rework", "shade": "Light"}, "LR"),
        ("Đuôi Dyelot không còn quyết định: Dyelot kết thúc '1' + BatchType Normal -> vẫn Normal", {**base, "dyelot": "C260659921"}, "D"),
        ("SapLot 2* không còn quyết định: BatchType Normal -> Normal", {**base, "sap_lot": "2000092724"}, "D"),
        ("ReDye không còn quyết định: cột redye bị bỏ qua", {**base, "redye": 3}, "D"),
        ("BatchType Redye -> RD", {**base, "batch_type": "Redye"}, "RD"),
        ("BatchType Redye + Dyelot *0 + SapLot 3* (C260512100) -> RD", {**base, "batch_type": "Redye", "sap_lot": "3000002146"}, "RD"),
        ("BatchType Unknown -> ?", {**base, "batch_type": "Unknown"}, "?"),
        ("BatchType trống -> ?", {**base, "batch_type": ""}, "?"),
        ("BatchType lạ -> ?", {**base, "batch_type": "R&D"}, "?"),
        ("Dyelot kết thúc '-WA' -> CM", {**base, "dyelot": "C260659920-WA"}, "CM"),
        ("Dyelot kết thúc 'WA' thiếu dấu gạch -> CM", {**base, "dyelot": "C260659920WA"}, "CM"),
        ("Dyelot chứa 'WA' ở giữa -> không phải CM", {**base, "dyelot": "C260WA659920"}, "D"),
        ("Dyelot bắt đầu 'CL' -> CM", {**base, "dyelot": "CL0659920"}, "CM"),
        ("CM ưu tiên khi BatchType Unknown", {**base, "dyelot": "11031527-WA", "batch_type": "Unknown"}, "CM"),
        ("Dyelot kết thúc 'DU' -> Sample", {**base, "dyelot": "C260659920-DU"}, "S"),
        ("Dyelot kết thúc 'KN' -> Sample", {**base, "dyelot": "C260659920KN"}, "S"),
        ("SapLot bắt đầu '4' -> Sample", {**base, "sap_lot": "4000092724"}, "S"),
        ("CM ưu tiên trước Sample", {**base, "dyelot": "C260659920-WA", "sap_lot": "4000092724"}, "CM"),
        ("Sample ưu tiên trước tinh luyện (đuôi DU, RecipeNo TINHLUYEN)", {**base, "dyelot": "2026110411-DU", "recipe_no": "TINHLUYEN-COTTON-02", "batch_type": "Unknown"}, "S"),
        ("RecipeNo TLDT-DG01 + BatchType Normal -> SC", {**base, "recipe_no": "TLDT-DG01"}, "SC"),
        ("RecipeNo DG01-NO-C26D2322 -> SC", {**base, "recipe_no": "DG01-NO-C26D2322-FY02"}, "SC"),
        ("RecipeNo 'TINH LUYEN-RD2' + Unknown -> SC", {**base, "recipe_no": "TINH LUYEN-RD2", "batch_type": "Unknown"}, "SC"),
        ("RecipeNo NC26E0401-DG01 -> SC", {**base, "recipe_no": "NC26E0401-DG01"}, "SC"),
        ("RecipeNo DG010 không phải tinh luyện", {**base, "recipe_no": "DG010-X"}, "D"),
        ("RecipeNo DG03 (nhuộm cotton) không phải tinh luyện", {**base, "recipe_no": "DG03-NO-C26F1301-FY18"}, "D"),
        ("RecipeNo DG08-01 (giặt) + Normal -> Normal", {**base, "recipe_no": "DG08-01"}, "D"),
        ("Tinh luyện ưu tiên trước Redye", {**base, "recipe_no": "DG01-X", "batch_type": "Redye"}, "SC"),
        ("ColourNo chứa BLACK -> màu B", {**base, "colour_no": "005-18-00-PUMA BLACK", "shade": "Dark"}, "B"),
        ("Shade Black (nhập tay) -> B", {**base, "shade": "Black"}, "B"),
        ("Shade White (nhập tay) -> W", {**base, "shade": "White"}, "W"),
        ("Không có thông tin màu -> M", {**base, "shade": ""}, "M"),
    ]
    for label, batch, expected in cases:
        _check(label, classify_batch_badge(batch), expected, failures)

    print("\n=== Kịch bản 1b: badge_group() / is_scouring() ===")
    groups = {"CM": "CM", "S": "S", "SC": "SC", "RD": "RD", "?": "PENDING", "B": "NORMAL", "D": "NORMAL", "M": "NORMAL", "L": "NORMAL", "W": "NORMAL", "BR": "REWORK", "DR": "REWORK", "MR": "REWORK", "LR": "REWORK", "WR": "REWORK"}
    for badge, expected in groups.items():
        _check(f"badge_group({badge!r})", badge_group(badge), expected, failures)
    _check("is_scouring(None)", is_scouring(None), False, failures)
    _check("is_scouring('TINHLUYEN-COTTON-01-DARK')", is_scouring("TINHLUYEN-COTTON-01-DARK"), True, failures)


def _init_schema(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE batch_details (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dyelot TEXT NOT NULL, sap_lot TEXT, shade TEXT, colour_no TEXT, customer_color TEXT,
            batch_type TEXT, recipe_no TEXT, redye REAL DEFAULT 0, is_rework INTEGER DEFAULT 0,
            greige_code TEXT, machine TEXT, fabric_type TEXT, start_time TEXT, end_time TEXT, run_time REAL DEFAULT 0
        )
    """)
    conn.execute("CREATE TABLE machines (machine_id TEXT, machine_code TEXT, mc_brand TEXT, tank_type TEXT, mc_quantity INTEGER, tube_no INTEGER, capacity_kg REAL, domain TEXT)")
    conn.commit()
    conn.close()


def _scenario_recompute_daily_integration(failures: list[str]) -> None:
    print("\n=== Kịch bản 2: recompute_daily() end-to-end ===")
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = None
    try:
        _init_schema(db_path)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        day = date(2026, 9, 1)
        rows = [
            ("C900001", "1000011111", "Dark", "Normal", 2, "D700", "Cotton", "2026-09-01 08:00:00", "2026-09-01 10:00:00", ""),
            ("C900002", "1000011112", "Dark", "Rework", 0, "D700", "Cotton", "2026-09-01 10:30:00", "2026-09-01 12:00:00", ""),
            ("C900003", "3000011113", "Dark", "Redye", 0, "D700", "Cotton", "2026-09-01 12:30:00", "2026-09-01 14:00:00", ""),
            ("C900004", "1000011114", "Dark", "Normal", 0, "D700", "Cotton", "2026-09-01 14:30:00", "2026-09-01 15:00:00", "TLDT-DG01"),
            ("C900005-WA", "", "", "Unknown", 0, "D700", "", "2026-09-01 15:10:00", "2026-09-01 15:40:00", ""),
            ("C900006", "", "", "Unknown", 0, "D700", "", "2026-09-01 16:00:00", "2026-09-01 18:00:00", "NO-T26E1518-RD"),
        ]
        for dyelot, sap_lot, shade, batch_type, redye, machine, fabric, start, end, recipe in rows:
            conn.execute(
                "INSERT INTO batch_details (dyelot, sap_lot, shade, batch_type, redye, machine, fabric_type, start_time, end_time, recipe_no) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (dyelot, sap_lot, shade, batch_type, redye, machine, fabric, start, end, recipe),
            )
        conn.commit()
        recompute_daily(day, conn)

        def badge_of(dyelot: str) -> tuple[str, int]:
            row = conn.execute("SELECT badge, is_rework FROM cleaning_mc_daily_summary WHERE production_date=? AND dyelot_ref=?", (day.isoformat(), dyelot)).fetchone()
            return (row["badge"], row["is_rework"]) if row else (None, None)

        _check("Normal có ReDye=2 vẫn là Normal", badge_of("C900001"), ("D", 0), failures)
        _check("BatchType Rework", badge_of("C900002"), ("DR", 1), failures)
        _check("BatchType Redye -> RD, is_rework=0", badge_of("C900003"), ("RD", 0), failures)
        _check("Tinh luyện mang BatchType Normal -> SC", badge_of("C900004"), ("SC", 0), failures)
        _check("Dyelot -WA + Unknown -> CM", badge_of("C900005-WA"), ("CM", 0), failures)
        _check("Unknown không CM/Sample -> ?", badge_of("C900006"), ("?", 0), failures)

        print("\n=== Kịch bản 3: nhập tay cho mẻ Pending ===")
        batches = load_resolved_batches(conn)
        pending = next(b for b in batches if b["dyelot"] == "C900006")
        conn.execute(
            "INSERT INTO batch_manual_overrides (dyelot, machine, start_time, batch_type, fabric_type, shade) VALUES (?, ?, ?, ?, ?, ?)",
            ("c900006", "d700", "2026-09-01 16:00:00", "Normal", "CVC", "Light"),
        )
        conn.commit()
        batches = load_resolved_batches(conn)
        manual = next(b for b in batches if b["dyelot"] == "C900006")
        _check("Ghép nhập tay không phân biệt hoa thường: batch_type", manual["batch_type"], "Normal", failures)
        _check("Nhập tay ghi đè FabricType", manual["fabric_type"], "CVC", failures)
        _check("Nhập tay ghi đè Shade", manual["shade"], "Light", failures)
        _check("Có _override_id", manual["_override_id"] is not None, True, failures)
        _check("Giữ BatchType gốc", manual["_original_batch_type"], "Unknown", failures)
        recompute_daily(day, conn)
        _check("Sau nhập tay -> badge L", badge_of("C900006"), ("L", 0), failures)
        _check("Mẻ CM liền trước không lấy FabricType từ mẻ trống nữa (đã điền) ", next(b for b in batches if b["dyelot"] == "C900005-WA")["fabric_type"], "CVC", failures)
        affected = dates_affected_by_batch(batches, pending["id"])
        _check("Ngày cần tính lại gồm ngày của mẻ", day in affected, True, failures)
    finally:
        if conn is not None:
            conn.close()
        try:
            os.unlink(db_path)
        except PermissionError:
            pass


def main() -> int:
    failures: list[str] = []
    _scenario_unit_classify(failures)
    _scenario_recompute_daily_integration(failures)
    print(f"\n{'=' * 60}\nKẾT QUẢ: {'TẤT CẢ KHỚP' if not failures else f'{len(failures)} CASE LỆCH'}\n{'=' * 60}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
