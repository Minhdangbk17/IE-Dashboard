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
"<300Kg"/"300 to 500 Kg"/"600kg or above"). Test này cập nhật cách ĐI TỚI đúng dòng dữ liệu
(qua khối "Subtotal" của group, gộp mọi Tank).

CẬP NHẬT 2026-09-25 (thay thế mục "bộ lọc SapLot 1*/3*" cũ — TÍNH NĂNG ĐÓ ĐÃ BỊ GỠ BỎ) —
công thức CM/Normal/Rework đổi HOÀN TOÀN theo `classify_batch_badge()` waterfall 4 bước mới
(xem `tests/test_rework_classification.py` cho chi tiết đơn vị): CM = Dyelot chứa "-WA" hoặc
bắt đầu "CL"; Sample (badge "S") = Dyelot chứa "-DU"/"-KN" hoặc SapLot bắt đầu "4", loại HOÀN
TOÀN khỏi mọi Category; Normal = Dyelot kết thúc "0" + SapLot bắt đầu "1"/"3" + (tuỳ chọn qua
checkbox "ReDye = 0" trên UI, mặc định BẬT) ReDye = 0. Checkbox tắt -> `get_batch_summary(
require_redye_zero=False)` tính lại ranh giới Normal/Rework NGAY TẠI READ TIME (không
recompute lại) qua `_effective_badge_is_rework()`. Test thêm cột `sap_lot`/`redye` cho từng mẻ
mẫu, 1 kịch bản riêng cho Sample + checkbox "ReDye = 0" ở cuối file.

CẬP NHẬT 2026-09-24 (tiếp, cùng ngày) — ĐỔI CÔNG THỨC "Normal": người dùng tự tải file Batch
Detail thật (`batch_2026-08-01_to_2026-08-31.xlsx`) về pivot tay, đối chiếu với nút "Ignore
SapLot" trên UI, phát hiện "No. of normal dyeing batch" tính RA THẤP HƠN THỰC TẾ đáng kể
(1717 so với pivot tay ~1811) — nguyên nhân: bản cũ loại bỏ CẢ mẻ có `batch_type`='Rework'/
'ReDye' khỏi "Normal" (không chỉ dựa vào is_rework suy từ Dyelot/SapLot), trong khi pivot tay
của người dùng CHỈ dựa THUẦN vào quy tắc Dyelot/SapLot. Người dùng xác nhận rõ: bỏ HẲN điều
kiện lọc theo `batch_type` gốc, áp dụng CẢ 2 tab Detail VÀ Summary (giữ 2 tab đồng bộ, không
lệch số nhau) — xem comment chi tiết ở `get_cleaning_matrix()`/`get_batch_summary()`.

  - "No. of normal dyeing batch" = đếm mẻ badge != CM VÀ KHÔNG Rework (theo Dyelot/SapLot) —
    KHÔNG còn lọc thêm theo `batch_type` gốc (ĐỔI, xem trên). Hệ quả: 1 mẻ batch_type='R&D'
    nhưng KHÔNG rework giờ tính vào CẢ "Normal" LẪN "R&D" (2 cờ độc lập, không loại trừ nhau).
  - "Cleaning MC Ratio" = No. of normal dyeing batch / No. of time Cleaning MC (KHÔNG PHẢI
    (Normal+Rework)/Cleaning MC như bản cũ).
  - "No. of R&D batch" = đếm mẻ batch_type thuộc {r&d, rd, research, development} — cờ RIÊNG,
    không loại trừ Rework/Normal (1 mẻ có thể vừa Rework vừa R&D, hoặc vừa Normal vừa R&D).
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
            is_rework INTEGER NOT NULL DEFAULT 0, dyelot_ref TEXT, sap_lot TEXT,
            redye REAL NOT NULL DEFAULT 0,
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
        # 1 mẻ batch_type='R&D' KHÔNG rework (giờ tính CẢ Normal LẪN R&D, xem đổi công thức ở
        # đầu file), 1 mẻ CM.
        # sap_lot: 2 mẻ bắt đầu "1", 1 mẻ bắt đầu "3", 2 mẻ bắt đầu "2" (không khớp bộ lọc 1*/3*).
        rows = [
            ("2026-01-05", 1, "M1", "Normal", "D", 0, "10011"),
            ("2026-01-06", 2, "M1", "Normal", "M", 0, "20022"),
            ("2026-01-07", 3, "M1", "Normal", "DR", 1, "10033"),
            ("2026-01-08", 4, "M1", "R&D", "L", 0, "30044"),
            ("2026-01-09", 5, "M1", "", "CM", 0, "20055"),
        ]
        conn.executemany(
            "INSERT INTO cleaning_mc_daily_summary (production_date, availability_log_id, machine, batch_type, badge, is_rework, sap_lot) VALUES (?, ?, ?, ?, ?, ?, ?)",
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
        _check("No. of normal dyeing batch = 3 (loại Rework, KHÔNG loại R&D nữa)", by_category["No. of normal dyeing batch"][jan], 3, failures)
        _check("Cleaning MC Ratio = Normal/CleaningMC = 3/1 = 3.0", by_category["Cleaning MC Ratio"][jan], 3.0, failures)
        _check("No. of R&D batch = 1 (vẫn đếm riêng, không loại trừ Normal)", by_category["No. of R&D batch"][jan], 1, failures)
        _check("Rework batch = 1", by_category["Rework batch"][jan], 1, failures)
        _check("Rework ratio = Normal/Rework = 3/1 = 3.0", by_category["Rework ratio"][jan], 3.0, failures)
        _check("No. Dyeing machine = 1 (M1 có mẻ thật)", by_category["No. Dyeing machine"][jan], 1, failures)
        _check("No. total day = 31 (tháng 1)", by_category["No. total day"][jan], 31, failures)
        _check("Daily batch/day = Normal/(days*machines) = 3/31", by_category["Daily batch/day"][jan], round(3 / 31, 2), failures)

        all_groups = next(g for g in data["groups"] if g["group"] == "All Groups")
        check_no_tank_split = all_groups["tanks"][0]["tank"] is None and len(all_groups["tanks"]) == 1
        _check("'All Groups' không tách theo Tank (1 khối duy nhất, tank=None)", check_no_tank_split, True, failures)
        all_by_category = {row["category"]: row["values"] for row in all_groups["tanks"][0]["rows"]}
        print("\n=== Kịch bản 2: 'All Groups' cộng dồn đúng (chỉ 1 group nên bằng group con) ===")
        _check("All Groups: No. of normal dyeing batch = 3", all_by_category["No. of normal dyeing batch"][jan], 3, failures)
        _check("All Groups: No. of R&D batch = 1", all_by_category["No. of R&D batch"][jan], 1, failures)
        _check("All Groups: Cleaning MC Ratio = 3.0", all_by_category["Cleaning MC Ratio"][jan], 3.0, failures)

        print("\n=== Kịch bản 3: Sample (badge 'S') loại hoàn toàn + checkbox 'ReDye = 0' ===")
        # Tháng 02/2026 (month index 1), máy M1, dữ liệu MỚI tách riêng khỏi Kịch bản 0-2 để
        # không lẫn số liệu. G: Dyelot/SapLot hợp lệ Normal nhưng ReDye=3 (!=0) -> lưu sẵn
        # "MR" (Rework, vì recompute_daily() LUÔN dùng require_redye_zero=True). H: Dyelot
        # KHÔNG kết thúc '0' -> Rework THẬT SỰ (không đổi dù tắt checkbox). I: Sample (Dyelot
        # chứa '-DU'). J: CM (Dyelot chứa '-WA').
        conn2 = sqlite3.connect(db_path)
        feb_rows = [
            ("2026-02-05", 10, "M1", "Normal", "MR", 1, "C002000", "10077", 3),
            ("2026-02-06", 11, "M1", "Normal", "LR", 1, "C002011", "10088", 0),
            ("2026-02-07", 12, "M1", "Normal", "S", 0, "C002020-DU", "10099", 0),
            ("2026-02-08", 13, "M1", "", "CM", 0, "C002030-WA", "", 0),
        ]
        conn2.executemany(
            "INSERT INTO cleaning_mc_daily_summary (production_date, availability_log_id, machine, batch_type, badge, is_rework, dyelot_ref, sap_lot, redye) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            feb_rows,
        )
        conn2.commit()
        conn2.close()
        feb = 1  # index 1 = February

        app2 = _make_temp_app(db_path)
        with app2.app_context():
            default_on = get_batch_summary(2026)
            toggled_off = get_batch_summary(2026, require_redye_zero=False)
            close_db()

        def _feb_by_category(data):
            group = next(g for g in data["groups"] if g["group"] == ">=300 to <500Kg")
            tanks = {t["tank"]: t for t in group["tanks"]}
            return {row["category"]: row["values"] for row in tanks["Subtotal"]["rows"]}

        on_cat = _feb_by_category(default_on)
        off_cat = _feb_by_category(toggled_off)

        _check("Mặc định BẬT: No. of time Cleaning MC = 1 (Sample 'S' KHÔNG tính vào đây)", on_cat["No. of time Cleaning MC"][feb], 1, failures)
        _check("Mặc định BẬT: No. of normal dyeing batch = 0 (G bị chặn bởi ReDye!=0, Sample loại hẳn)", on_cat["No. of normal dyeing batch"][feb], 0, failures)
        _check("Mặc định BẬT: Rework batch = 2 (G + H)", on_cat["Rework batch"][feb], 2, failures)

        _check("Tắt checkbox: No. of normal dyeing batch = 1 (G hết bị ReDye chặn -> Normal)", off_cat["No. of normal dyeing batch"][feb], 1, failures)
        _check("Tắt checkbox: Rework batch = 1 (chỉ còn H — Dyelot không kết thúc '0', KHÔNG liên quan ReDye)", off_cat["Rework batch"][feb], 1, failures)
        _check("Tắt checkbox: No. of time Cleaning MC vẫn = 1 (không đổi)", off_cat["No. of time Cleaning MC"][feb], 1, failures)
        _check("Sample 'S' không lọt vào 'No. Dyeing machine' (chỉ tính máy có mẻ thật khác)", off_cat["No. Dyeing machine"][feb], 1, failures)
    finally:
        os.unlink(db_path)

    print(f"\n{'='*60}\nKẾT QUẢ: {'TẤT CẢ KHỚP' if not failures else f'{len(failures)} CASE LỆCH'}\n{'='*60}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
