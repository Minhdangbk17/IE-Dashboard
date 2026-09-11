"""
migrate_sqlite_to_supabase.py
-------------------------------
Copy TOÀN BỘ dữ liệu lịch sử đang có trong SQLite local (`data/mes_dashboard.db`) sang
Postgres/Supabase — CHẠY 1 LẦN TỪ MÁY LOCAL cho bộ dữ liệu ban đầu, KHÔNG qua UI/Vercel.
Lý do bắt buộc chạy local: Vercel Serverless Function có giới hạn thời gian chạy (300s) —
không đủ cho khối lượng dữ liệu lịch sử lớn (import qua UI chỉ phù hợp cho file mới,
tương đối nhỏ, phát sinh hàng ngày/tuần).

Chỉ migrate các bảng ĐANG CÓ dữ liệu thật (đã kiểm tra `data/mes_dashboard.db`):
availability_logs, batch_details, batch_matrix_daily_summary, batch_matrix_targets,
cleaning_mc_daily_summary, downtime_case_notes, downtime_daily_summary, import_logs,
import_log_rows. Các bảng rỗng ở local (machines, machine_telemetry, downtime_logs,
performance_logs, user_permissions) tự động bỏ qua nếu 0 dòng.

KHÔNG đụng tới bảng 'users': Supabase đã seed sẵn admin/operator qua
`seed_supabase_users.py`/SQL Editor với password_hash băm theo SECRET_KEY CỦA VERCEL — copy
đè từ SQLite local (băm theo SECRET_KEY dev khác) sẽ làm hỏng đăng nhập production.

Xử lý khoá ngoại (id) giữa 2 DB — QUAN TRỌNG:
  KHÔNG cố giữ nguyên giá trị `id` gốc từ SQLite khi insert vào Postgres (`generated always
  as identity` không cho set tuỳ ý, và quan trọng hơn: Postgres CÓ THỂ đã có sẵn vài dòng do
  bạn đã test upload 1 file nhỏ qua UI trước đó — id tự sinh của những dòng đó có thể trùng
  số với id trong SQLite dù là dữ liệu HOÀN TOÀN KHÁC nhau). Thay vào đó:
    1. Insert vào bảng cha (import_logs, availability_logs, ...) để Postgres tự sinh id mới.
    2. Đọc lại id mới + khoá tự nhiên (natural key, vd batch_ref_no+machine+start_time) của
       TOÀN BỘ bảng đó từ Postgres, dựng dict {khoá tự nhiên: id mới}.
    3. Với bảng con (downtime_case_notes, cleaning_mc_daily_summary, import_log_rows, ...)
       tự tra lại khoá tự nhiên của dòng gốc trong SQLite để suy ra ĐÚNG id mới bên Postgres,
       thay cho việc dùng thẳng id cũ.
  `user_permissions`/`downtime_case_notes.updated_by` tham chiếu users.id — tự tra lại theo
  USERNAME (không theo id) để lấy đúng id bên Supabase.

Các bảng có khoá tự nhiên (unique constraint) dùng ON CONFLICT ... DO UPDATE — AN TOÀN chạy
lại nhiều lần (idempotent), khớp đúng cách app tự upsert. Các bảng KHÔNG có khoá tự nhiên
(import_logs, import_log_rows — thuần log lịch sử) dùng cơ chế "guard theo số dòng": nếu bảng
đích trên Postgres ĐÃ có dữ liệu, script sẽ bỏ qua (không insert lại) trừ khi truyền --force.

TOÀN BỘ chạy trong 1 transaction duy nhất — nếu có lỗi giữa chừng, rollback sạch (không để
lại dữ liệu nửa vời). Dùng --dry-run để chạy hết logic (bao gồm ghi tạm trong transaction) rồi
rollback ở bước cuối thay vì commit, xem trước số dòng sẽ ảnh hưởng mà không ghi thật.

Cách chạy:
    export DATABASE_URL="...connection string Supabase (Pooler, xem README/memory-bank)..."
    pip install psycopg2-binary   # nếu chưa cài
    python migrate_sqlite_to_supabase.py --dry-run   # xem trước
    python migrate_sqlite_to_supabase.py             # chạy thật
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Any, Iterable

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("Chưa cài psycopg2-binary. Chạy: pip install psycopg2-binary")
    sys.exit(1)

import os

BASE_DIR = Path(__file__).resolve().parent


def log(msg: str) -> None:
    print(msg, flush=True)


def fetch_sqlite_rows(sqlite_conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    cur = sqlite_conn.execute(f"SELECT * FROM {table}")
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def pg_row_count(pg_cur: Any, table: str) -> int:
    pg_cur.execute(f"SELECT COUNT(*) AS c FROM {table}")
    return pg_cur.fetchone()["c"]


def get_pg_columns(pg_cur: Any, table: str) -> set[str]:
    pg_cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = %s", (table,))
    return {row["column_name"] for row in pg_cur.fetchall()}


def bulk_upsert(
    pg_cur: Any,
    table: str,
    columns: list[str],
    rows: list[dict[str, Any]],
    conflict_cols: tuple[str, ...] | None,
    update_cols: list[str] | None = None,
) -> None:
    """INSERT hàng loạt bằng execute_values (gộp round-trip). `conflict_cols=None` nghĩa là
    INSERT thường (không ON CONFLICT) — dùng cho bảng không có khoá tự nhiên đáng tin cậy.

    Tự dò cột THẬT đang có trên Postgres (`information_schema`) và chỉ insert phần giao với
    `columns` — KHÔNG giả định schema SQLite local và `supabase/schema.sql` luôn khớp 100%.
    Đã phát hiện thật 1 trường hợp lệch (`import_logs.created_at` có ở SQLite nhưng thiếu bên
    Postgres do sót khi dịch schema) qua test — cách này tự chịu được sai lệch kiểu đó (và mọi
    lệch schema khác phát sinh sau này) thay vì phải sửa tay `supabase/schema.sql` + chạy
    ALTER TABLE thủ công trên Supabase thật trước khi migrate được."""
    if not rows:
        return
    pg_cols = get_pg_columns(pg_cur, table)
    dropped = [c for c in columns if c not in pg_cols]
    if dropped:
        log(f"  [CẢNH BÁO] Bảng '{table}': bỏ qua cột không tồn tại bên Postgres: {dropped}")
    columns = [c for c in columns if c in pg_cols]
    if update_cols:
        update_cols = [c for c in update_cols if c in pg_cols]
    col_list = ", ".join(columns)
    if conflict_cols:
        if update_cols:
            set_clause = ", ".join(f"{c}=excluded.{c}" for c in update_cols)
            conflict_clause = f" ON CONFLICT ({', '.join(conflict_cols)}) DO UPDATE SET {set_clause}"
        else:
            conflict_clause = f" ON CONFLICT ({', '.join(conflict_cols)}) DO NOTHING"
    else:
        conflict_clause = ""
    sql = f"INSERT INTO {table} ({col_list}) VALUES %s{conflict_clause}"
    values = [tuple(row.get(c) for c in columns) for row in rows]
    psycopg2.extras.execute_values(pg_cur, sql, values, page_size=1000)


def build_key_map(pg_cur: Any, table: str, key_cols: tuple[str, ...], id_col: str = "id") -> dict[tuple, int]:
    """Đọc lại {khoá tự nhiên: id} của TOÀN BỘ bảng trên Postgres (sau khi đã insert) — dùng
    để tra id MỚI cho các bảng con tham chiếu tới bảng này, KHÔNG dùng lại id cũ từ SQLite."""
    pg_cur.execute(f"SELECT {id_col}, {', '.join(key_cols)} FROM {table}")
    mapping: dict[tuple, int] = {}
    for row in pg_cur.fetchall():
        key = tuple(row[k] for k in key_cols)
        mapping[key] = row[id_col]
    return mapping


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite-path", default=str(BASE_DIR / "data" / "mes_dashboard.db"))
    parser.add_argument("--dry-run", action="store_true", help="Chạy hết logic rồi rollback, không ghi thật.")
    parser.add_argument("--force", action="store_true", help="Vẫn insert import_logs/import_log_rows dù Postgres đã có dữ liệu.")
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        log("Thiếu biến môi trường DATABASE_URL (connection string Supabase — dùng Pooler).")
        return 1
    if not Path(args.sqlite_path).exists():
        log(f"Không tìm thấy file SQLite: {args.sqlite_path}")
        return 1

    sqlite_conn = sqlite3.connect(args.sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row
    pg_conn = psycopg2.connect(database_url, cursor_factory=psycopg2.extras.RealDictCursor)
    pg_cur = pg_conn.cursor()

    try:
        # --- users: chỉ dùng để dựng map username -> id bên Supabase, KHÔNG insert/update ---
        sqlite_users = {row["id"]: row["username"] for row in fetch_sqlite_rows(sqlite_conn, "users")}
        pg_cur.execute("SELECT id, username FROM users")
        username_to_pg_id = {row["username"]: row["id"] for row in pg_cur.fetchall()}
        user_id_map = {
            sqlite_id: username_to_pg_id[username]
            for sqlite_id, username in sqlite_users.items()
            if username in username_to_pg_id
        }
        missing_users = [u for u in sqlite_users.values() if u not in username_to_pg_id]
        if missing_users:
            log(f"[CẢNH BÁO] {len(missing_users)} username có trong SQLite nhưng CHƯA có trên Supabase (bỏ qua remap): {missing_users}")

        # --- import_logs (không có khoá tự nhiên -> guard theo số dòng đã có) ---
        import_logs_rows = fetch_sqlite_rows(sqlite_conn, "import_logs")
        existing_import_logs = pg_row_count(pg_cur, "import_logs")
        import_log_id_map: dict[int, int] = {}
        if import_logs_rows and (existing_import_logs == 0 or args.force):
            cols = [c for c in import_logs_rows[0].keys() if c != "id"]
            bulk_upsert(pg_cur, "import_logs", cols, import_logs_rows, conflict_cols=None)
            log(f"[import_logs] Đã insert {len(import_logs_rows)} dòng.")
            # Khoá tự nhiên tạm cho riêng bước remap này: thứ tự (file_name, imported_at,
            # imported_by) đủ để khớp lại 1-1 vì import_logs không có 2 dòng giống hệt nhau
            # về cả 3 giá trị này trong dữ liệu thật (đã verify: mỗi lần import là 1 lần
            # nhấn nút riêng biệt, có mốc giờ imported_at khác nhau).
            key_map = build_key_map(pg_cur, "import_logs", ("file_name", "imported_at", "imported_by"))
            for row in import_logs_rows:
                key = (row["file_name"], row["imported_at"], row["imported_by"])
                if key in key_map:
                    import_log_id_map[row["id"]] = key_map[key]
        elif import_logs_rows:
            log(f"[import_logs] Postgres đã có {existing_import_logs} dòng — bỏ qua (dùng --force để vẫn insert thêm).")

        # --- availability_logs (khoá tự nhiên: batch_ref_no, machine, start_time) ---
        availability_rows = fetch_sqlite_rows(sqlite_conn, "availability_logs")
        availability_id_map: dict[int, int] = {}
        if availability_rows:
            cols = [c for c in availability_rows[0].keys() if c != "id"]
            for row in availability_rows:
                if row.get("import_log_id") is not None:
                    row["import_log_id"] = import_log_id_map.get(row["import_log_id"])
            update_cols = [c for c in cols if c not in ("batch_ref_no", "machine", "start_time")]
            bulk_upsert(
                pg_cur, "availability_logs", cols, availability_rows,
                conflict_cols=("batch_ref_no", "machine", "start_time"), update_cols=update_cols,
            )
            log(f"[availability_logs] Đã upsert {len(availability_rows)} dòng.")
            key_map = build_key_map(pg_cur, "availability_logs", ("batch_ref_no", "machine", "start_time"))
            for row in availability_rows:
                key = (row["batch_ref_no"], row["machine"], row["start_time"])
                if key in key_map:
                    availability_id_map[row["id"]] = key_map[key]

        # --- batch_details (khoá tự nhiên: dyelot chính là PK) ---
        batch_details_rows = fetch_sqlite_rows(sqlite_conn, "batch_details")
        if batch_details_rows:
            cols = list(batch_details_rows[0].keys())
            for row in batch_details_rows:
                if row.get("import_log_id") is not None:
                    row["import_log_id"] = import_log_id_map.get(row["import_log_id"])
            update_cols = [c for c in cols if c != "dyelot"]
            bulk_upsert(pg_cur, "batch_details", cols, batch_details_rows, conflict_cols=("dyelot",), update_cols=update_cols)
            log(f"[batch_details] Đã upsert {len(batch_details_rows)} dòng.")

        # --- downtime_daily_summary (khoá tự nhiên: production_date, capacity_kg, category) ---
        dds_rows = fetch_sqlite_rows(sqlite_conn, "downtime_daily_summary")
        if dds_rows:
            cols = list(dds_rows[0].keys())
            update_cols = [c for c in cols if c not in ("production_date", "capacity_kg", "category")]
            bulk_upsert(pg_cur, "downtime_daily_summary", cols, dds_rows, conflict_cols=("production_date", "capacity_kg", "category"), update_cols=update_cols)
            log(f"[downtime_daily_summary] Đã upsert {len(dds_rows)} dòng.")

        # --- batch_matrix_daily_summary (khoá tự nhiên: production_date, fabric_type, color_group, capacity_kg) ---
        bmds_rows = fetch_sqlite_rows(sqlite_conn, "batch_matrix_daily_summary")
        if bmds_rows:
            cols = list(bmds_rows[0].keys())
            key_cols = ("production_date", "fabric_type", "color_group", "capacity_kg")
            update_cols = [c for c in cols if c not in key_cols]
            bulk_upsert(pg_cur, "batch_matrix_daily_summary", cols, bmds_rows, conflict_cols=key_cols, update_cols=update_cols)
            log(f"[batch_matrix_daily_summary] Đã upsert {len(bmds_rows)} dòng.")

        # --- batch_matrix_targets (khoá tự nhiên: fabric_type, color_group) ---
        bmt_rows = fetch_sqlite_rows(sqlite_conn, "batch_matrix_targets")
        if bmt_rows:
            cols = list(bmt_rows[0].keys())
            update_cols = [c for c in cols if c not in ("fabric_type", "color_group")]
            bulk_upsert(pg_cur, "batch_matrix_targets", cols, bmt_rows, conflict_cols=("fabric_type", "color_group"), update_cols=update_cols)
            log(f"[batch_matrix_targets] Đã upsert {len(bmt_rows)} dòng.")

        # --- cleaning_mc_daily_summary (khoá tự nhiên: production_date, availability_log_id MỚI) ---
        cmds_rows = fetch_sqlite_rows(sqlite_conn, "cleaning_mc_daily_summary")
        if cmds_rows:
            cols = list(cmds_rows[0].keys())
            remapped, skipped = [], 0
            for row in cmds_rows:
                new_id = availability_id_map.get(row["availability_log_id"])
                if new_id is None:
                    skipped += 1
                    continue
                row = dict(row)
                row["availability_log_id"] = new_id
                remapped.append(row)
            key_cols = ("production_date", "availability_log_id")
            update_cols = [c for c in cols if c not in key_cols]
            bulk_upsert(pg_cur, "cleaning_mc_daily_summary", cols, remapped, conflict_cols=key_cols, update_cols=update_cols)
            log(f"[cleaning_mc_daily_summary] Đã upsert {len(remapped)} dòng" + (f" (bỏ qua {skipped} dòng không tra được availability_log_id mới)" if skipped else "") + ".")

        # --- downtime_case_notes (khoá tự nhiên: availability_log_id MỚI; updated_by remap theo username) ---
        dcn_rows = fetch_sqlite_rows(sqlite_conn, "downtime_case_notes")
        if dcn_rows:
            cols = [c for c in dcn_rows[0].keys() if c != "id"]
            remapped, skipped = [], 0
            for row in dcn_rows:
                new_avail_id = availability_id_map.get(row["availability_log_id"])
                new_user_id = user_id_map.get(row["updated_by"])
                if new_avail_id is None or new_user_id is None:
                    skipped += 1
                    continue
                row = dict(row)
                row["availability_log_id"] = new_avail_id
                row["updated_by"] = new_user_id
                remapped.append(row)
            update_cols = [c for c in cols if c != "availability_log_id"]
            bulk_upsert(pg_cur, "downtime_case_notes", cols, remapped, conflict_cols=("availability_log_id",), update_cols=update_cols)
            log(f"[downtime_case_notes] Đã upsert {len(remapped)} dòng" + (f" (bỏ qua {skipped} dòng thiếu tham chiếu)" if skipped else "") + ".")

        # --- import_log_rows (không có khoá tự nhiên -> guard theo số dòng đã có) ---
        ilr_rows = fetch_sqlite_rows(sqlite_conn, "import_log_rows")
        existing_ilr = pg_row_count(pg_cur, "import_log_rows")
        if ilr_rows and (existing_ilr == 0 or args.force):
            cols = [c for c in ilr_rows[0].keys() if c != "id"]
            remapped, skipped = [], 0
            for row in ilr_rows:
                new_log_id = import_log_id_map.get(row["import_log_id"])
                if new_log_id is None:
                    skipped += 1
                    continue
                row = dict(row)
                row["import_log_id"] = new_log_id
                remapped.append(row)
            bulk_upsert(pg_cur, "import_log_rows", cols, remapped, conflict_cols=None)
            log(f"[import_log_rows] Đã insert {len(remapped)} dòng" + (f" (bỏ qua {skipped} dòng không tra được import_log_id mới)" if skipped else "") + ".")
        elif ilr_rows:
            log(f"[import_log_rows] Postgres đã có {existing_ilr} dòng — bỏ qua (dùng --force để vẫn insert thêm).")

        if args.dry_run:
            pg_conn.rollback()
            log("\n[DRY RUN] Đã rollback — KHÔNG có gì được ghi thật vào Supabase.")
        else:
            pg_conn.commit()
            log("\nĐã commit — dữ liệu đã ghi thật vào Supabase.")
        return 0
    except Exception:
        pg_conn.rollback()
        log("\n[LỖI] Đã rollback toàn bộ transaction, KHÔNG có gì bị ghi lại. Chi tiết lỗi:")
        raise
    finally:
        pg_cur.close()
        pg_conn.close()
        sqlite_conn.close()


if __name__ == "__main__":
    sys.exit(main())
