"""
tests/test_batch_matrix_formula.py
------------------------------------
Đối chiếu công thức mẫu số THỨ 3 (2026-09-10) của `batch_matrix`: với 1 ô (fabric_type,
color_group, capacity_kg, ngày), mẫu số = tổng giờ hoạt động (prorate theo ranh giới 7h
sáng) của ĐÚNG TẬP MÁY đã chạy các mẻ được đếm ở tử số của ô đó — bao gồm cả giờ mẻ KHÁC
màu/vải mà chính các máy này cũng chạy hôm đó. Ở cấp Total(Fabric)/Grand Total, PHẢI khử
trùng máy (tập máy = hợp của mọi ColorGroup con) trước khi cộng giờ — nếu không sẽ đếm
trùng giờ của máy chạy đa màu/ngày (đúng loại bug COUNT DISTINCT đã bắt được trước đây, ở
"giờ" thay vì "đếm máy").

Dùng DB TẠM (file SQLite tạm + Flask app context tạm trỏ vào file đó, KHÔNG đụng DB thật)
để test được cả `recompute_daily()` (nhận `conn` trực tiếp) lẫn `build_matrix()` (cần
`get_db()`/`execute_query()` qua Flask app context).

Chạy: python tests/test_batch_matrix_formula.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import Flask  # noqa: E402

from core.database import close_db  # noqa: E402
from modules.dyeing.engines.batch_matrix.service import build_matrix, recompute_daily  # noqa: E402


def _make_temp_app(db_path: str) -> Flask:
    app = Flask(__name__)
    app.config["DATABASE_PATH"] = db_path
    app.config["SQLITE_PRAGMAS"] = {}
    return app


def _init_schema(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE availability_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch TEXT, fabric_type TEXT, machine TEXT, capacity_kg REAL,
            start_time TEXT, end_time TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE batch_details (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dyelot TEXT NOT NULL, shade TEXT, colour_no TEXT, batch_type TEXT, greige_code TEXT,
            machine TEXT, start_time TEXT, end_time TEXT
        )
    """)
    conn.execute("CREATE UNIQUE INDEX uq_batch_details_dyelot_machine_start ON batch_details(dyelot, machine, start_time)")
    conn.commit()
    conn.close()


def _check(label: str, actual, expected, failures: list[str], tolerance: float = 0.0) -> None:
    ok = abs(actual - expected) <= tolerance if tolerance else actual == expected
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: actual={actual} expected={expected}")
    if not ok:
        failures.append(label)


def _scenario_basic_cell(failures: list[str]) -> None:
    """Ví dụ số gốc: 1 ô (CVC/Dark/capacity=600) có ĐÚNG 2 máy D507, D511 trong toàn bộ DB
    tạm — tập máy của ô này = {D507, D511} = MỌI máy có trong DB, nên mẫu số bằng đúng tổng
    giờ 2 máy này (16h) như ví dụ gốc, không phân biệt được với thiết kế "giờ dùng chung"
    (đã đổi ở lần trước) khi chỉ có 1 ô duy nhất — case này XÁC NHẬN công thức verbatim
    không đổi khi không có giao thoa máy giữa các ô, còn case đa màu bên dưới mới bẫy đúng
    khác biệt giữa 2 thiết kế."""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        _init_schema(db_path)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        day = date(2026, 9, 1)
        conn.executemany(
            "INSERT INTO availability_logs (batch, fabric_type, machine, capacity_kg, start_time, end_time) VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("D507-B1", "CVC", "D507", 600, "2026-09-01 07:00:00", "2026-09-01 10:00:00"),
                ("D507-B2", "CVC", "D507", 600, "2026-09-01 10:00:00", "2026-09-01 14:00:00"),
                ("D507-B3", "Cotton", "D507", 600, "2026-09-01 14:00:00", "2026-09-01 17:00:00"),
                ("D511-B1", "CVC", "D511", 600, "2026-09-01 08:00:00", "2026-09-01 11:30:00"),
                ("D511-B2", "CVC", "D511", 600, "2026-09-01 11:30:00", "2026-09-01 14:00:00"),
            ],
        )
        conn.executemany(
            "INSERT INTO batch_details (dyelot, shade, colour_no, batch_type) VALUES (?, ?, ?, ?)",
            [
                ("D507-B1", "Dark", "091-NAVY", "Normal"),
                ("D507-B2", "Dark", "091-NAVY", "Normal"),
                ("D511-B1", "Dark", "091-NAVY", "Normal"),
                ("D511-B2", "Dark", "091-NAVY", "Normal"),
            ],
        )
        conn.commit()
        recompute_daily(day, conn)
        row = conn.execute(
            "SELECT batch_count, operating_hours FROM batch_matrix_daily_summary WHERE production_date=? AND fabric_type='CVC' AND color_group='Dark' AND capacity_kg=600",
            (day.isoformat(),),
        ).fetchone()
        conn.close()

        print("=== Kịch bản 1: ô đơn (CVC/Dark/600) — đối chiếu ví dụ số gốc ===")
        if row is None:
            print("  [FAIL] không tìm thấy dòng summary")
            failures.append("scenario1 missing row")
            return
        _check("batch_count (tử số)", row["batch_count"], 4, failures)
        _check("operating_hours (mẫu số)", round(row["operating_hours"], 2), 16.0, failures, tolerance=0.01)
        cell_value = round(row["batch_count"] / (row["operating_hours"] / 24), 2)
        _check("cell_value", cell_value, 6.0, failures, tolerance=0.01)
    finally:
        os.unlink(db_path)


def _scenario_overnight_split(failures: list[str]) -> None:
    """Mẻ chạy qua đêm — CHIA NHỎ operating_hours theo ranh giới 7h sáng. Máy D999 cần CÓ
    thêm 1 mẻ hoàn tất ngay trong từng ngày (Batch X ngày trước, Batch Z ngày sau) để tạo
    "neo" tử số cho cả 2 ngày — vì ở thiết kế mới, mẫu số CHỈ tồn tại cho ô nào tử số > 0
    (tập máy được xác định TỪ chính các mẻ đã đếm), nên 1 mẻ qua đêm ĐƠN LẺ không có mẻ nào
    khác hoàn tất cùng ngày sẽ không tạo ra ô nào để hiển thị — đây là hệ quả ĐÚNG của thiết
    kế (không phải bug): không có mẻ nào hoàn tất hôm đó nghĩa là không có gì để chia tỷ lệ.

    - Batch X: 07:00-12:00 ngày trước (5h, hoàn tất ngày trước -> neo tử số ngày trước).
    - Batch Y (qua đêm): 22:00 ngày trước -> 10:00 ngày sau (12h, tách 9h/3h theo ranh giới 7h).
    - Batch Z: 11:00-15:00 ngày sau (4h, hoàn tất ngày sau -> neo tử số ngày sau).
    - operating_hours ngày trước = X(5h) + phần Y trước 7h(9h) = 14h.
    - operating_hours ngày sau = phần Y từ 7h(3h) + Z(4h) = 7h.
    - Tổng 3 mẻ = 5+12+4 = 21h = 14+7 (không mất/thừa giờ khi chia theo 2 ngày)."""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        _init_schema(db_path)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        day_before = date(2026, 9, 5)
        day_of = date(2026, 9, 6)
        conn.executemany(
            "INSERT INTO availability_logs (batch, fabric_type, machine, capacity_kg, start_time, end_time) VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("D999-X", "CVC", "D999", 300, "2026-09-05 07:00:00", "2026-09-05 12:00:00"),
                ("D999-Y-OVERNIGHT", "CVC", "D999", 300, "2026-09-05 22:00:00", "2026-09-06 10:00:00"),
                ("D999-Z", "CVC", "D999", 300, "2026-09-06 11:00:00", "2026-09-06 15:00:00"),
            ],
        )
        conn.commit()
        recompute_daily(day_before, conn)
        recompute_daily(day_of, conn)
        row_before = conn.execute(
            "SELECT operating_hours FROM batch_matrix_daily_summary WHERE production_date=? AND capacity_kg=300", (day_before.isoformat(),)
        ).fetchone()
        row_of = conn.execute(
            "SELECT operating_hours FROM batch_matrix_daily_summary WHERE production_date=? AND capacity_kg=300", (day_of.isoformat(),)
        ).fetchone()
        conn.close()

        print("\n=== Kịch bản 2: mẻ chạy qua đêm — tách đúng theo ranh giới 7h sáng ===")
        _check("operating_hours ngày trước (Batch X 5h + phần Y trước 7h 9h = 14h)", round(row_before["operating_hours"], 2) if row_before else None, 14.0, failures, tolerance=0.01)
        _check("operating_hours ngày sau (phần Y từ 7h 3h + Batch Z 4h = 7h)", round(row_of["operating_hours"], 2) if row_of else None, 7.0, failures, tolerance=0.01)
        total_split = (row_before["operating_hours"] if row_before else 0) + (row_of["operating_hours"] if row_of else 0)
        _check("tổng 2 ngày = tổng thời lượng 3 mẻ gốc (5+12+4=21h, không mất/thừa giờ)", round(total_split, 2), 21.0, failures, tolerance=0.01)
    finally:
        os.unlink(db_path)


def _scenario_multicolor_dedup(failures: list[str]) -> None:
    """BẪY LỖI CỘNG TRÙNG: máy M1 chạy CẢ 2 màu (Dark + Medium) cùng ngày. Nếu Total(Fabric)
    cộng THẲNG operating_hours của 2 dòng ColorGroup con, giờ của M1 sẽ bị cộng 2 LẦN.

    - M1: mẻ Dark 4h (07:00-11:00) + mẻ Medium 5h (11:00-16:00) = 9h/ngày.
    - M2: mẻ Dark 6h (07:00-13:00) = 6h/ngày.
    - Dòng Dark: tử số=2 (M1+M2), tập máy={M1,M2}, operating_hours = 9+6 = 15h (LƯU Ý: giờ
      CỦA M1 Ở ĐÂY LÀ TOÀN BỘ 9h trong ngày, không phải chỉ 4h phần Dark).
    - Dòng Medium: tử số=1 (M1), tập máy={M1}, operating_hours = 9h (toàn bộ ngày của M1).
    - Total(CVC) SAI (cộng thẳng 2 dòng trên) = 15 + 9 = 24h -> giá trị SAI = 3*24/24 = 3.0.
    - Total(CVC) ĐÚNG (khử trùng M1, chỉ cộng 1 lần) = tập máy hợp {M1,M2} = 9+6 = 15h
      -> giá trị ĐÚNG = 3*24/15 = 4.8.
    `build_matrix()` PHẢI trả về 4.8 (không phải 3.0) để xác nhận không cộng trùng."""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        _init_schema(db_path)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        day = date(2026, 9, 10)
        conn.executemany(
            "INSERT INTO availability_logs (batch, fabric_type, machine, capacity_kg, start_time, end_time) VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("M1-DARK", "CVC", "M1", 700, "2026-09-10 07:00:00", "2026-09-10 11:00:00"),
                ("M1-MED", "CVC", "M1", 700, "2026-09-10 11:00:00", "2026-09-10 16:00:00"),
                ("M2-DARK", "CVC", "M2", 700, "2026-09-10 07:00:00", "2026-09-10 13:00:00"),
            ],
        )
        conn.executemany(
            "INSERT INTO batch_details (dyelot, shade, colour_no, batch_type) VALUES (?, ?, ?, ?)",
            [
                ("M1-DARK", "Dark", "091-NAVY", "Normal"),
                ("M1-MED", "Medium", "500-GREY", "Normal"),
                ("M2-DARK", "Dark", "091-NAVY", "Normal"),
            ],
        )
        conn.commit()
        recompute_daily(day, conn)
        conn.commit()  # PHẢI commit trước khi Flask app mở connection RIÊNG tới cùng file

        dark_row = conn.execute(
            "SELECT batch_count, operating_hours FROM batch_matrix_daily_summary WHERE production_date=? AND fabric_type='CVC' AND color_group='Dark'", (day.isoformat(),)
        ).fetchone()
        medium_row = conn.execute(
            "SELECT batch_count, operating_hours FROM batch_matrix_daily_summary WHERE production_date=? AND fabric_type='CVC' AND color_group='Medium'", (day.isoformat(),)
        ).fetchone()
        conn.close()

        print("\n=== Kịch bản 3: máy chạy ĐA MÀU/ngày — bẫy lỗi cộng trùng giờ ở Total(Fabric) ===")
        _check("Dark: batch_count", dark_row["batch_count"], 2, failures)
        _check("Dark: operating_hours (tập máy {M1,M2}, M1 tính CẢ NGÀY)", round(dark_row["operating_hours"], 2), 15.0, failures, tolerance=0.01)
        _check("Medium: batch_count", medium_row["batch_count"], 1, failures)
        _check("Medium: operating_hours (tập máy {M1}, CẢ NGÀY)", round(medium_row["operating_hours"], 2), 9.0, failures, tolerance=0.01)

        naive_hours = dark_row["operating_hours"] + medium_row["operating_hours"]
        naive_value = round((dark_row["batch_count"] + medium_row["batch_count"]) * 24 / naive_hours, 2)
        print(f"  [THAM KHẢO] Nếu cộng THẲNG operating_hours 2 dòng con (SAI): {naive_hours:.2f}h -> giá trị SAI = {naive_value}")

        app = _make_temp_app(db_path)
        with app.app_context():
            data = build_matrix()
            fabric_total_row = next(r for r in data["rows"] if r["row_type"] == "fabric_total" and r["fabric_type"] == "CVC")
            total_cvc_value = fabric_total_row["days"].get(day.isoformat())
            close_db()

        _check("Total(CVC) từ build_matrix() (PHẢI khử trùng M1, ra 4.8 KHÔNG PHẢI 3.0)", total_cvc_value, 4.8, failures, tolerance=0.01)
        if total_cvc_value == naive_value:
            print("  [FAIL] Total(CVC) trùng với giá trị SAI (cộng thẳng) -> bug cộng trùng giờ ĐÃ TÁI DIỄN")
            failures.append("Total(CVC) matches naive (wrong) value")
    finally:
        os.unlink(db_path)


def _scenario_duplicate_dyelot_redye(failures: list[str]) -> None:
    """BẪY LỖI ĐẾM TRÙNG: 1 Dyelot có 2 dòng batch_details (mẻ gốc bị NG + mẻ redye chạy lại,
    xem điều tra mẻ C260659920 trong memory-bank/activeContext.md) — availability_logs CHỈ có
    1 dòng lịch máy, khớp lần chạy REDYE (end_time khớp chính xác dòng redye). JOIN theo dyelot
    ĐƠN THUẦN sẽ khớp CẢ 2 dòng batch_details, nhân đôi dòng availability_logs này -> batch_count
    của ô đó bị đếm 2 thay vì 1. `batch_details_join_sql()` phải chọn ĐÚNG dòng redye (end_time
    khớp chính xác) — không chỉ tránh đếm trùng mà còn gán ĐÚNG màu (Dark, của mẻ redye) chứ
    không phải màu của mẻ gốc (Medium)."""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        _init_schema(db_path)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        day = date(2026, 9, 12)
        conn.execute(
            "INSERT INTO availability_logs (batch, fabric_type, machine, capacity_kg, start_time, end_time) VALUES (?, ?, ?, ?, ?, ?)",
            ("C-REDYE", "CVC", "D600", 600, "2026-09-12 06:00:00", "2026-09-12 10:00:00"),
        )
        conn.executemany(
            "INSERT INTO batch_details (dyelot, shade, colour_no, batch_type, machine, start_time, end_time) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                # Mẻ gốc NG — kết thúc SỚM HƠN, KHÔNG khớp end_time của dòng availability_logs.
                ("C-REDYE", "Medium", "500-GREY", "Normal", "D600", "2026-09-01 06:00:00", "2026-09-01 08:00:00"),
                # Mẻ redye — end_time KHỚP CHÍNH XÁC dòng availability_logs.
                ("C-REDYE", "Dark", "091-NAVY", "Normal", "D600", "2026-09-12 06:00:00", "2026-09-12 10:00:00"),
            ],
        )
        conn.commit()
        recompute_daily(day, conn)
        dark_row = conn.execute(
            "SELECT batch_count FROM batch_matrix_daily_summary WHERE production_date=? AND fabric_type='CVC' AND color_group='Dark'", (day.isoformat(),)
        ).fetchone()
        medium_row = conn.execute(
            "SELECT batch_count FROM batch_matrix_daily_summary WHERE production_date=? AND fabric_type='CVC' AND color_group='Medium'", (day.isoformat(),)
        ).fetchone()
        conn.close()

        print("\n=== Kịch bản 4: 1 Dyelot có 2 dòng batch_details (mẻ gốc + redye) — KHÔNG đếm trùng ===")
        _check("Dark (mẻ redye, end_time khớp): batch_count = 1 (không bị nhân đôi)", dark_row["batch_count"] if dark_row else 0, 1, failures)
        _check("Medium (mẻ gốc NG, end_time KHÔNG khớp): không xuất hiện (0 dòng)", medium_row["batch_count"] if medium_row else 0, 0, failures)
    finally:
        os.unlink(db_path)


def main() -> int:
    failures: list[str] = []
    _scenario_basic_cell(failures)
    _scenario_overnight_split(failures)
    _scenario_multicolor_dedup(failures)
    _scenario_duplicate_dyelot_redye(failures)
    print(f"\n{'='*60}\nKẾT QUẢ: {'TẤT CẢ KHỚP' if not failures else f'{len(failures)} CASE LỆCH'}\n{'='*60}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
