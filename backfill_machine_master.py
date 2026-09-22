"""
backfill_machine_master.py
---------------------------
Nạp SẴN vào `machines` (Machine Master, xem systemPatterns.md mục 6.2 "Batch Per Day by
Machine") toàn bộ mã máy ĐÃ TỪNG xuất hiện trong dữ liệu thật (`availability_logs.machine`
HỢP `batch_details.machine`) nhưng CHƯA có dòng nào trong `machines`.

Vì sao cần: báo cáo "Batch Per Day by Machine" đổi thiết kế (2026-09-22) — danh sách máy
hiển thị giờ LUÔN xuất phát từ `machines` (Machine Master quản lý thủ công), không còn tự
phát hiện từ dữ liệu batch. Ngay sau khi đổi, `machines` gần như RỖNG (khảo sát DB dev thật
lúc viết script này: chỉ có 1 dòng), nghĩa là gần như TOÀN BỘ máy thật (~60 mã) sẽ rơi vào
nhóm "unmapped" cho tới khi được khai báo — chạy script này 1 LẦN để mồi sẵn danh sách máy
(group_mc/capacity_kg/... để trống, admin tự điền dần qua UI "Batch Per Day by Machine"),
thay vì phải bấm "+ Add Machine" ~60 lần thủ công.

An toàn chạy lại nhiều lần: chỉ INSERT mã máy CHƯA có trong `machines` (theo
lower(trim(COALESCE(machine_code, machine_id)))), KHÔNG đụng/ghi đè bất kỳ dòng nào đã có
sẵn (kể cả đã cấu hình đầy đủ hay chưa) — idempotent, không có --force vì không cần overwrite.

Cách chạy (từ máy local hoặc bất kỳ đâu có DATABASE_PATH/DATABASE_URL trỏ đúng DB muốn nạp):
    python backfill_machine_master.py            # chạy thật
    python backfill_machine_master.py --dry-run   # chỉ liệt kê mã máy sẽ thêm, không ghi DB
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import app as appmod  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Chỉ liệt kê, không ghi DB.")
    args = parser.parse_args()

    with appmod.app.app_context():
        from core.database import execute_query, get_db

        conn = get_db()
        existing_rows = execute_query(
            "SELECT lower(trim(COALESCE(machine_code, machine_id))) AS norm FROM machines WHERE domain = 'dyeing'",
            [],
        )
        existing = {row["norm"] for row in existing_rows if row["norm"]}

        raw_rows = execute_query(
            """
            SELECT DISTINCT TRIM(machine) AS code FROM availability_logs WHERE machine IS NOT NULL AND TRIM(machine) != ''
            UNION
            SELECT DISTINCT TRIM(machine) AS code FROM batch_details WHERE machine IS NOT NULL AND TRIM(machine) != ''
            """,
            [],
        )
        to_add = sorted({row["code"] for row in raw_rows if row["code"] and row["code"].strip().lower() not in existing})

        if not to_add:
            print("Không có mã máy mới nào cần thêm — Machine Master đã đủ.")
            return 0

        print(f"Sẽ thêm {len(to_add)} mã máy vào Machine Master: {', '.join(to_add)}")
        if args.dry_run:
            print("(--dry-run: chưa ghi gì vào DB)")
            return 0

        for code in to_add:
            conn.execute(
                "INSERT INTO machines (machine_id, machine_code, machine_name, domain) VALUES (?, ?, ?, 'dyeing')",
                (code, code, code),
            )
        conn.commit()
        print(f"Đã thêm {len(to_add)} máy. Vào /dyeing/reports/cleaning-matrix để điền Group MC/Capacity/... cho từng máy.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
