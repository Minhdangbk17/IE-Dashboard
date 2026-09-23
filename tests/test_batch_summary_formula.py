"""
tests/test_batch_summary_formula.py
--------------------------------------
Verify công thức MỚI (2026-09-23) của tab "Summary" — báo cáo "Batch Per Day by Machine"
(`reports/cleaning_matrix.py::get_batch_summary()`). Người dùng yêu cầu Summary dùng ĐÚNG
NGUYÊN định nghĩa "Normal"/"Cleaning MC Ratio"/"R&D"/"Rework" đã có sẵn ở tab "Detail"
(`get_cleaning_matrix()`), không tự đặt tiêu chí riêng — vì Summary chỉ là cộng dồn theo
tháng của cùng 1 nguồn dữ liệu:

CẬP NHẬT 2026-09-24: bảng Summary đổi thành 3 tầng Group Machine x Tank Type x Category
(trước đó chỉ 2 tầng Group Machine x Category) — mỗi Group giờ có `["tanks"]` (danh sách
khối "Subtotal"/"J tank"/"O tank"/"Unclassified"), KHÔNG còn `["rows"]` phẳng ở cấp Group.
3 mức Group Machine cũng đổi ranh giới/nhãn: ">=500Kg"/">=300 to <500Kg"/"<300Kg" (trước đó
"<300Kg"/"300 to 500 Kg"/"600kg or above"). Công thức 9 Category KHÔNG đổi — test này chỉ
cập nhật cách ĐI TỚI đúng dòng dữ liệu (qua khối "Subtotal" của group, gộp mọi Tank).

  - "No. of normal dyeing batch" = đếm mẻ badge != CM, KHÔNG Rework, VÀ batch_type thuộc
    {normal, unknown, rỗng} (loại CẢ R&D).
  - "Cleaning MC Ratio" = No. of normal dyeing batch / No. of time Cleaning MC (KHÔNG PHẢI
    (Normal+Rework)/Cleaning MC như bản cũ).
  - "No. of R&D batch" = đếm mẻ batch_type thuộc {r&d, rd, research, development} — cờ RIÊNG,
    không loại trừ Rework (1 mẻ có thể vừa Rework vừa R&D).
  - "Rework batch" = đếm mẻ is_rework (badge kết thúc "R") — không đổi.
  - "Rework ratio" = No. of normal dyeing batch / Rework batch (người dùng xác nhận đảo
    ngược so với bản cũ Rework/Normal+Rework).
  - "Daily batch/day" = No. of normal dyeing batch / (No. total day x No. Dyeing machine).
  - "No. Dyeing machine" KHÔNG đổi — vẫn đếm máy có >=1 mẻ THẬT (Normal/Rework/R&D, loại CM).

Dùng DB TẠM (file SQLite tạm + Flask app context tạm), KHÔNG đụng DB thật — cùng pattern
`tests/test_batch_matrix_formula.py`.

Chạy: python tests/test_batch_summary_formula.py
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
from modules.dyeing.engines.reports.cleaning_matrix import get_batch_summary  # noqa: E402


def _make_temp_app(db_path: str) -> Flask:
    app = Flask(__name__)
    app.config["DATABASE_PATH"] = db_path
    app.config["SQLITE_PRAGMAS"] = {}
    return app


def _check(label: str, actual, expected, failures: list[str]) -> None:
    ok = actual == expected
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: actual={actual!r} expected={expected!r}")
    if not ok:
        failures.append(label)


def _init_schema(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE cleaning_mc_daily_summary (
            production_date TEXT NOT NULL, availability_log_id INTEGER NOT NULL,
            machine TEXT NOT NULL, batch_type TEXT, badge TEXT NOT NULL,
            is_rework INTEGER NOT NULL DEFAULT 0, dyelot_ref TEXT,
            PRIMARY KEY (production_date, availability_log_id)
        )
    """)
    conn.execute("""
        CREATE TABLE machines (
            machine_id TEXT, machine_code TEXT, group_mc TEXT, tank_type TEXT, domain TEXT
        )
    """)
    conn.execute("CREATE TABLE availability_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, batch TEXT, batch_ref_no TEXT, end_time TEXT)")
    conn.execute("CREATE TABLE batch_details (id INTEGER PRIMARY KEY AUTOINCREMENT, dyelot TEXT NOT NULL, machine TEXT, start_time TEXT, end_time TEXT, greige_code TEXT)")
    conn.execute("INSERT INTO machines (machine_id, machine_code, group_mc, tank_type, domain) VALUES ('M1', 'M1', '>=300 to <500Kg', 'J tank', 'dyeing')")
    conn.commit()
    conn.close()


def main() -> int:
    failures: list[str] = []
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        _init_schema(db_path)
        conn = sqlite3.connect(db_path)
        # Tháng 01/2026, máy M1: 2 mẻ Normal, 1 mẻ Rework (batch_type Normal + is_rework=1),
        # 1 mẻ R&D (badge D, KHÔNG rework), 1 mẻ CM.
        rows = [
            ("2026-01-05", 1, "M1", "Normal", "D", 0),
            ("2026-01-06", 2, "M1", "Normal", "M", 0),
            ("2026-01-07", 3, "M1", "Normal", "DR", 1),
            ("2026-01-08", 4, "M1", "R&D", "L", 0),
            ("2026-01-09", 5, "M1", "", "CM", 0),
        ]
        conn.executemany(
            "INSERT INTO cleaning_mc_daily_summary (production_date, availability_log_id, machine, batch_type, badge, is_rework) VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
        conn.close()

        app = _make_temp_app(db_path)
        with app.app_context():
            data = get_batch_summary(2026)
            close_db()

        group = next(g for g in data["groups"] if g["group"] == ">=300 to <500Kg")
        tanks_by_label = {t["tank"]: t for t in group["tanks"]}
        jan = 0  # index 0 = January

        print("=== Kịch bản 0: cấu trúc 3 tầng (chỉ có M1 -> Tank 'J tank') ===")
        _check("group có đúng 2 khối Tank: Subtotal + J tank (không có O tank/Unclassified)", set(tanks_by_label.keys()), {"Subtotal", "J tank"}, failures)

        # "Subtotal" gộp mọi Tank trong group — vì chỉ có 1 máy/1 Tank nên bằng hệt "J tank".
        by_category = {row["category"]: row["values"] for row in tanks_by_label["Subtotal"]["rows"]}

        print("=== Kịch bản 1: Group '>=300 to <500Kg' / Subtotal, tháng 01/2026 ===")
        _check("No. of time Cleaning MC = 1", by_category["No. of time Cleaning MC"][jan], 1, failures)
        _check("No. of normal dyeing batch = 2 (loại Rework + R&D)", by_category["No. of normal dyeing batch"][jan], 2, failures)
        _check("Cleaning MC Ratio = Normal/CleaningMC = 2/1 = 2.0", by_category["Cleaning MC Ratio"][jan], 2.0, failures)
        _check("No. of R&D batch = 1", by_category["No. of R&D batch"][jan], 1, failures)
        _check("Rework batch = 1", by_category["Rework batch"][jan], 1, failures)
        _check("Rework ratio = Normal/Rework = 2/1 = 2.0 (đảo ngược so với bản cũ)", by_category["Rework ratio"][jan], 2.0, failures)
        _check("No. Dyeing machine = 1 (M1 có mẻ thật)", by_category["No. Dyeing machine"][jan], 1, failures)
        _check("No. total day = 31 (tháng 1)", by_category["No. total day"][jan], 31, failures)
        _check("Daily batch/day = Normal/(days*machines) = 2/31", by_category["Daily batch/day"][jan], round(2 / 31, 2), failures)

        all_groups = next(g for g in data["groups"] if g["group"] == "All Groups")
        check_no_tank_split = all_groups["tanks"][0]["tank"] is None and len(all_groups["tanks"]) == 1
        _check("'All Groups' không tách theo Tank (1 khối duy nhất, tank=None)", check_no_tank_split, True, failures)
        all_by_category = {row["category"]: row["values"] for row in all_groups["tanks"][0]["rows"]}
        print("\n=== Kịch bản 2: 'All Groups' cộng dồn đúng (chỉ 1 group nên bằng group con) ===")
        _check("All Groups: No. of normal dyeing batch = 2", all_by_category["No. of normal dyeing batch"][jan], 2, failures)
        _check("All Groups: No. of R&D batch = 1", all_by_category["No. of R&D batch"][jan], 1, failures)
        _check("All Groups: Cleaning MC Ratio = 2.0", all_by_category["Cleaning MC Ratio"][jan], 2.0, failures)
    finally:
        os.unlink(db_path)

    print(f"\n{'='*60}\nKẾT QUẢ: {'TẤT CẢ KHỚP' if not failures else f'{len(failures)} CASE LỆCH'}\n{'='*60}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
