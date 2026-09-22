"""
backfill_batch_details_lost_rows.py
-------------------------------------
Khôi phục các dòng `batch_details` đã bị MẤT do bug thiết kế cũ (`dyelot TEXT PRIMARY KEY` —
đã sửa, xem `core/batch_importer.py::_migrate_batch_details_primary_key()`): trước bản sửa,
khi 1 Dyelot chạy lại thật (mẻ gốc bị NG rồi redye, VD mẻ C260659920 — xem
memory-bank/activeContext.md), lần import SAU ghi đè MẤT dữ liệu lần chạy TRƯỚC trong
`batch_details`, dù snapshot RAW của MỌI dòng từng import vẫn còn nguyên trong
`import_log_rows` (bảng này lưu theo `row_number`, KHÔNG dedupe theo dyelot — xem
`core/excel_importer.py::record_import_rows()`).

Script này quét lại `import_log_rows` của MỌI lần import Batch Detail (`import_type='batch'`),
dòng nào `status='valid'` mà khoá tự nhiên (dyelot, machine, start_time) của nó CHƯA có trong
`batch_details` hiện tại thì chèn lại — dùng ĐÚNG hàm parse/validate của luồng import thật
(`core.batch_importer.revalidate_batch_row()`, cùng hàm Raw Data Viewer dùng để sửa 1 dòng) để
không viết lại logic parse lần 2.

An toàn chạy lại nhiều lần: CHỈ INSERT dòng CHƯA có (idempotent, `ON CONFLICT ... DO NOTHING`),
TUYỆT ĐỐI KHÔNG ghi đè dòng nào đã có sẵn trong `batch_details` (kể cả nếu giá trị khác nhau —
ưu tiên giữ dữ liệu hiện tại, không đoán bên nào "đúng hơn").

Cách chạy (từ máy local hoặc bất kỳ đâu có DATABASE_PATH/DATABASE_URL trỏ đúng DB muốn khôi
phục — với Supabase production, set biến môi trường DATABASE_URL trỏ connection string Pooler
TRƯỚC khi chạy, xem `.env.example`):
    python backfill_batch_details_lost_rows.py            # mặc định CHỈ liệt kê, không ghi
    python backfill_batch_details_lost_rows.py --apply     # ghi thật vào DB
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import app as appmod  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Ghi thật vào DB (mặc định chỉ liệt kê, KHÔNG ghi).")
    args = parser.parse_args()

    with appmod.app.app_context():
        from core.batch_importer import NUMERIC_FIELDS, revalidate_batch_row
        from core.database import execute_query, get_db
        from models.dyeing import BATCH_DETAIL_FIELDS

        conn = get_db()

        # Tự đảm bảo đủ cột trước khi ghi (phòng khi batch_details chưa từng nhận đủ
        # BATCH_DETAIL_FIELDS — cùng vòng lặp ALTER dùng trong sync_batch_details()).
        existing_columns = {row["name"] for row in conn.execute("PRAGMA table_info(batch_details)")}
        for field in BATCH_DETAIL_FIELDS:
            if field not in existing_columns:
                definition = "REAL NOT NULL DEFAULT 0" if field in NUMERIC_FIELDS else "TEXT"
                conn.execute(f"ALTER TABLE batch_details ADD COLUMN {field} {definition}")
        conn.commit()

        raw_rows = execute_query(
            """
            SELECT r.id AS row_id, r.import_log_id, r.row_data
            FROM import_log_rows r
            JOIN import_logs l ON l.id = r.import_log_id
            WHERE l.import_type = 'batch' AND r.status = 'valid'
            ORDER BY r.import_log_id, r.row_number
            """,
            [],
        )
        print(f"Quét {len(raw_rows)} dòng raw đã import qua Batch Detail (mọi lần import, mọi thời điểm)...")

        existing_keys = {
            (row["dyelot"], row["machine"] or "", row["start_time"] or "")
            for row in execute_query("SELECT dyelot, machine, start_time FROM batch_details", [])
        }
        print(f"batch_details hiện có {len(existing_keys)} dòng.")

        to_insert: list[tuple[dict, int]] = []
        parse_errors = 0
        for row in raw_rows:
            raw = json.loads(row["row_data"])
            record, error = revalidate_batch_row(raw)
            if error is not None or record is None:
                parse_errors += 1
                continue
            key = (record["dyelot"], record.get("machine") or "", record.get("start_time") or "")
            if key in existing_keys:
                continue
            to_insert.append((record, row["import_log_id"]))
            existing_keys.add(key)  # tránh chèn trùng nếu 2 dòng import_log_rows khác nhau cùng khoá

        print(f"Tìm thấy {len(to_insert)} dòng ĐÃ MẤT cần khôi phục (bỏ qua {parse_errors} dòng lỗi parse lại).")
        for record, _ in to_insert[:30]:
            print(f"  - dyelot={record['dyelot']} machine={record.get('machine')} start_time={record.get('start_time')} weight={record.get('weight')} dye_cost={record.get('dye_cost')}")
        if len(to_insert) > 30:
            print(f"  ... và {len(to_insert) - 30} dòng khác.")

        if not to_insert:
            print("Không có gì cần khôi phục.")
            return 0

        if not args.apply:
            print("\n(chế độ liệt kê — chạy lại kèm --apply để ghi thật vào DB)")
            return 0

        key_fields = ("dyelot", "machine", "start_time")
        columns_with_log = BATCH_DETAIL_FIELDS + ("import_log_id",)
        placeholders = ",".join("?" for _ in columns_with_log)
        sql = (
            f"INSERT INTO batch_details ({','.join(columns_with_log)}) VALUES ({placeholders}) "
            f"ON CONFLICT({','.join(key_fields)}) DO NOTHING"
        )
        conn.execute("BEGIN")
        for record, import_log_id in to_insert:
            conn.execute(sql, tuple(record[field] for field in BATCH_DETAIL_FIELDS) + (import_log_id,))
        conn.commit()
        print(f"Đã khôi phục {len(to_insert)} dòng vào batch_details.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
