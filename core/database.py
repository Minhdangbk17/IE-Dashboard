"""
core/database.py
-----------------
Quản lý kết nối DB — DUAL-MODE:

- MẶC ĐỊNH (không set biến môi trường `DATABASE_URL`): SQLite cục bộ, hành vi Y HỆT trước
  đây (WAL mode, `sqlite3.Row`, connection cache trong `flask.g`). Local dev KHÔNG cần
  Postgres thật để chạy app.
- KHI CÓ `DATABASE_URL` (vd deploy Vercel trỏ Supabase Postgres): `get_db()` mở kết nối
  `psycopg2`, bọc trong `_PostgresConnCompat` — lớp này mô phỏng lại đúng bề mặt API mà
  gần 20 nơi trong codebase đang dựa vào (`conn.execute(sql, params)` kiểu shorthand của
  `sqlite3.Connection`, placeholder `?`, `PRAGMA table_info(x)` để dò cột động), để tuyệt
  đại đa số câu SQL hiện có KHÔNG cần sửa khi chạy Postgres.

  Dịch trong suốt (xem `_PostgresConnCompat._translate`):
    - `?` -> `%s` (placeholder style của psycopg2). AN TOÀN vì SQL trong dự án không có `?`
      literal trong chuỗi; các `IN (?, ?, ?)` động đều build qua `",".join("?" for _ in x)`
      nên số lượng khớp tham số 1:1, không lệch khi đổi ký hiệu.
      **CẢNH BÁO cho code viết SAU NÀY**: `%s` khiến dấu `%` LITERAL (vd `LIKE '%x%'`) bị
      psycopg2 hiểu nhầm thành format specifier trừ khi viết `%%`. Dự án hiện KHÔNG có
      `LIKE` nào (đã grep xác nhận) nên chưa phát tác — nhưng nếu thêm `LIKE '%...%'` sau
      này, PHẢI viết `LIKE '%%...%%'` để chạy đúng ở nhánh Postgres.
    - `PRAGMA table_info(x)` -> `SELECT column_name AS name FROM information_schema.columns
      WHERE table_name = 'x' ORDER BY ordinal_position` — cùng hình dạng cột `name` mà mọi
      call site hiện tại đang đọc (`{row["name"] for row in conn.execute(...)}`).
    - Row factory: `psycopg2.extras.RealDictCursor` (row là `dict` thật) — tương thích
      `dict(row)` và `row["col"]` mà codebase dùng khắp nơi. Codebase KHÔNG truy cập row
      theo vị trí số (`row[0]`) ở bất kỳ đâu (đã verify bằng grep), nên không cần kiểu Row
      hỗ trợ cả 2 kiểu truy cập như `sqlite3.Row`.

  Những khác biệt KHÔNG thể dịch trong suốt (phải sửa tay ở call site, xem
  `core/production_time.py::production_date_sql_expr()` và `sql_datetime()` bên dưới):
  hàm `datetime(...)` của SQLite không tồn tại ở Postgres — mọi nơi dùng `datetime(...)`
  literal trong câu SQL phải đổi sang gọi `sql_datetime(...)`.
"""
from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Sequence

import click
from flask import Flask, current_app, g, has_app_context

try:
    import psycopg2
    import psycopg2.extras
except ImportError:  # psycopg2-binary chỉ thực sự cần khi DATABASE_URL được set
    psycopg2 = None  # type: ignore[assignment]

# Exception "trung lập dialect" — dùng ở call site thay cho `except sqlite3.Error`/
# `except sqlite3.IntegrityError` trực tiếp, để bắt đúng lỗi ở CẢ 2 dialect.
# LUÔN LUÔN là tuple (kể cả khi không có psycopg2, dùng tuple 1 phần tử) — KHÔNG bao giờ
# gán 1 class đơn lẻ. Lý do: `except (ValueError, DatabaseError):` — nếu `DatabaseError` là
# 1 class đơn thì việc lồng vào tuple ngoài vẫn ổn, NHƯNG nếu ai đó viết
# `except (ValueError, *DatabaseError):` (cách bắt buộc phải dùng khi cần kết hợp với type
# khác — xem 2 call site trong modules/dyeing/engines/{reports,excel_import}/routes.py) mà
# `DatabaseError` không phải tuple thì `*DatabaseError` sẽ lỗi (class không iterable). Ép
# LUÔN LUÔN là tuple giúp `*DatabaseError` an toàn ở MỌI trường hợp, cả 2 dialect.
if psycopg2 is not None:
    DatabaseError: tuple[type[Exception], ...] = (sqlite3.Error, psycopg2.Error)
    DatabaseIntegrityError: tuple[type[Exception], ...] = (sqlite3.IntegrityError, psycopg2.IntegrityError)
else:
    DatabaseError = (sqlite3.Error,)
    DatabaseIntegrityError = (sqlite3.IntegrityError,)

_PRAGMA_TABLE_INFO_RE = re.compile(r"^\s*PRAGMA\s+table_info\(\s*([A-Za-z0-9_]+)\s*\)\s*;?\s*$", re.IGNORECASE)
# Khớp cụm "VALUES (%s, %s, ..., %s)" — hình dạng CHUẨN mà mọi câu INSERT dùng với
# `conn.executemany()` trong dự án đang có (1 tuple placeholder lặp lại cho từng dòng qua
# executemany, có thể có `ON CONFLICT ... DO UPDATE` theo sau hoặc không). Dùng để phát hiện
# và gộp thành `execute_values()` — xem lý do ở `_PostgresConnCompat.executemany()`.
_EXECUTEMANY_VALUES_RE = re.compile(r"VALUES\s*\(\s*%s(?:\s*,\s*%s)*\s*\)", re.IGNORECASE)


def get_dialect() -> str:
    """"sqlite" (mặc định) hoặc "postgres" — quyết định BỞI CÓ hay KHÔNG có `DATABASE_URL`.
    Ưu tiên đọc từ `current_app.config` khi đang trong Flask app context (tôn trọng override
    trong test, vd `app.config["DATABASE_URL"] = ...`); NGOÀI app context (vd script/test gọi
    thẳng `recompute_daily(day, conn)` với 1 connection tự mở, không qua Flask — xem
    `tests/test_batch_matrix_formula.py`) fallback đọc thẳng biến môi trường `DATABASE_URL`.
    Không cache bằng biến toàn cục để tránh state ngầm giữa các test/app instance khác nhau."""
    if has_app_context():
        return "postgres" if current_app.config.get("DATABASE_URL") else "sqlite"
    return "postgres" if os.environ.get("DATABASE_URL") else "sqlite"


def sql_datetime(expr: str) -> str:
    """Bọc 1 biểu thức thời gian theo ĐÚNG dialect đang active — dùng THAY cho việc viết
    literal `datetime(...)` trong câu SQL. SQLite: giữ nguyên `datetime(expr)` (có tác dụng
    CHUẨN HOÁ — zero-pad, cắt phần giây lẻ/timezone — không chỉ ép kiểu). Postgres: không có
    hàm `datetime()`, dùng `(expr)::timestamp`. KHÔNG được tự ý bỏ hẳn wrapper này rồi so
    sánh chuỗi thường — dữ liệu mới luôn ghi đúng chuẩn `%Y-%m-%d %H:%M:%S` nên sẽ trông như
    "chạy đúng", nhưng mất khả năng chịu lỗi cho dữ liệu cũ/nhập tay lệch định dạng mà
    `datetime()` vốn được thêm vào để xử lý."""
    if get_dialect() == "postgres":
        return f"({expr})::timestamp"
    return f"datetime({expr})"


class _StaticRowCountCursor:
    """Bọc 1 cursor thật của psycopg2 sau khi chạy `execute_values()`, override `.rowcount`
    bằng giá trị tự tính (xem lý do trong `_PostgresConnCompat.executemany()`) — mọi thuộc
    tính/phương thức khác (`.close()`, `.fetchone()`, ...) forward nguyên sang cursor gốc."""

    def __init__(self, cur: Any, rowcount: int) -> None:
        self._cur = cur
        self.rowcount = rowcount

    def __getattr__(self, name: str) -> Any:
        return getattr(self._cur, name)


class _PostgresConnCompat:
    """Bọc 1 `psycopg2` connection để mô phỏng bề mặt API mà code hiện tại đang gọi trên
    `sqlite3.Connection`: `.execute()`/`.executemany()` shorthand (tự tạo cursor), giữ
    nguyên `?` làm placeholder trong SQL nguồn (dịch sang `%s` ở tầng này), và đáp ứng
    `PRAGMA table_info(x)` — TUYỆT ĐỐI KHÔNG sửa từng câu SQL rải rác trong ~16 file Engine
    để làm việc này, giữ tất cả logic dịch tập trung ở 1 chỗ, dễ review/rollback."""

    def __init__(self, dsn: str) -> None:
        if psycopg2 is None:
            raise RuntimeError(
                "DATABASE_URL đã được set nhưng chưa cài psycopg2-binary. "
                "Chạy: pip install psycopg2-binary"
            )
        self._conn = psycopg2.connect(dsn, cursor_factory=psycopg2.extras.RealDictCursor)

    @staticmethod
    def _translate(sql: str) -> str:
        pragma_match = _PRAGMA_TABLE_INFO_RE.match(sql)
        if pragma_match:
            table = pragma_match.group(1)
            return (
                "SELECT column_name AS name FROM information_schema.columns "
                f"WHERE table_name = '{table}' ORDER BY ordinal_position"
            )
        return sql.replace("?", "%s")

    def execute(self, sql: str, params: Sequence[Any] = ()) -> Any:
        cur = self._conn.cursor()
        cur.execute(self._translate(sql), tuple(params) if params else None)
        return cur

    def executemany(self, sql: str, seq_of_params: Iterable[Sequence[Any]]) -> Any:
        """`cursor.executemany()` mặc định của psycopg2 KHÔNG tự gộp batch — nó gửi 1
        round-trip mạng RIÊNG cho MỖI dòng (khác hẳn SQLite, chạy cục bộ nên chậm không đáng
        kể). Khi app chạy trên Vercel nói chuyện với Supabase qua Internet, mỗi round-trip tốn
        hàng chục/hàng trăm ms — import vài trăm/nghìn dòng kiểu 1-dòng-1-round-trip có thể mất
        hàng chục giây, thậm chí vượt timeout của Serverless Function. Nếu câu SQL đúng hình
        dạng chuẩn `INSERT ... VALUES (%s, %s, ...) [ON CONFLICT ...]` (mọi call site hiện tại
        đều vậy), gộp toàn bộ dòng vào 1 câu lệnh duy nhất bằng `execute_values()` — vài trăm/
        nghìn dòng chỉ còn vài round-trip thay vì hàng nghìn."""
        translated = self._translate(sql)
        seq = [tuple(p) for p in seq_of_params]
        cur = self._conn.cursor()
        values_sql, matched = _EXECUTEMANY_VALUES_RE.subn("VALUES %s", translated, count=1)
        if matched and seq:
            psycopg2.extras.execute_values(cur, values_sql, seq, page_size=1000)
            # `cur.rowcount` sau `execute_values()` chỉ phản ánh trang (page) CUỐI, không phải
            # tổng số dòng — không dùng được để báo "đã import N dòng". Mọi câu INSERT dùng
            # executemany() trong dự án hoặc có `ON CONFLICT ... DO UPDATE` (dòng nào cũng tính
            # là affected) hoặc là INSERT thường không thể âm thầm bỏ dòng (lỗi ràng buộc ném
            # exception, rollback cả batch) — nên số dòng THẬT luôn bằng đúng `len(seq)`.
            return _StaticRowCountCursor(cur, len(seq))
        cur.executemany(translated, seq)
        return cur

    def cursor(self) -> Any:
        return self._conn.cursor()

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()


def get_db() -> Any:
    """Lấy connection cho request hiện tại (tạo mới nếu chưa có trong `g`) — SQLite hoặc
    Postgres tuỳ `DATABASE_URL` có được set trong config hay không (xem `get_dialect()`)."""
    if "db" not in g:
        database_url = current_app.config.get("DATABASE_URL")
        if database_url:
            g.db = _PostgresConnCompat(database_url)
        else:
            db_path: Path = current_app.config["DATABASE_PATH"]
            g.db = sqlite3.connect(
                db_path,
                detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
            )
            g.db.row_factory = sqlite3.Row
            _apply_sqlite_pragmas(g.db, current_app.config["SQLITE_PRAGMAS"])
    return g.db


def _apply_sqlite_pragmas(conn: sqlite3.Connection, pragmas: dict[str, str]) -> None:
    """Áp dụng các PRAGMA tối ưu hiệu năng / an toàn dữ liệu cho một connection SQLite."""
    cur = conn.cursor()
    for key, value in pragmas.items():
        cur.execute(f"PRAGMA {key}={value};")
    cur.close()


def close_db(_exc: BaseException | None = None) -> None:
    """Đóng connection khi kết thúc application context (request)."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


def _discard_broken_connection() -> None:
    """Bỏ (best-effort close) connection Postgres đang cache trong `g.db` sau khi phát
    hiện nó đã hỏng (`OperationalError`/`InterfaceError` — vd Supabase pooler tự đóng 1
    connection đang mở do idle timeout/quá tải). Lần `get_db()` tiếp theo TRONG CÙNG
    request sẽ mở lại 1 connection MỚI thay vì tiếp tục dùng connection đã chết.

    **Bug thật đã gặp trên production** (Vercel + Supabase): 1 request gặp
    `OperationalError: SSL connection has been closed unexpectedly` ngay ở lệnh SELECT
    đầu tiên (`get_current_user()`) — Flask bắt exception, cố render `errors/500.html`,
    nhưng template đó lại chạy `context_processor` (`inject_nav_menu`) gọi
    `get_current_user()` LẦN NỮA, DÙNG LẠI đúng `g.db` đã hỏng -> `InterfaceError:
    connection already closed` -> trang lỗi thân thiện 500 KHÔNG BAO GIỜ render được,
    người dùng thấy lỗi thô của server thay vì trang lỗi tử tế. Gọi hàm này ngay khi phát
    hiện lỗi kết nối để các lệnh ĐỌC tiếp theo trong CÙNG request (kể cả từ template lỗi)
    có cơ hội tự phục hồi bằng connection mới, xem `execute_query()`/`execute_one()`."""
    db = g.pop("db", None)
    if db is not None:
        try:
            db.close()
        except Exception:
            pass


def get_raw_connection(db_path: Path, pragmas: dict[str, str] | None = None) -> sqlite3.Connection:
    """
    Mở một connection SQLite độc lập, KHÔNG phụ thuộc Flask app context.
    Dùng cho script CLI như `init_db.py`. CHỈ dùng cho SQLite (khởi tạo Postgres/Supabase
    thật dùng `supabase/schema.sql` áp trực tiếp qua công cụ của Supabase, không qua hàm này).
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    if pragmas:
        _apply_sqlite_pragmas(conn, pragmas)
    return conn


def get_raw_connection_for_app(app: Flask) -> Any:
    """Như `get_raw_connection()`, nhưng tự chọn ĐÚNG dialect theo `app.config["DATABASE_URL"]`
    — dùng ở những chỗ mở connection NGOÀI request cycle nhưng VẪN cần chạy đúng trên Postgres
    khi deploy (vd `core/auth.py::init_app()` chạy lúc `create_app()` khởi động, và CLI
    `flask sync-permissions`) — KHÁC với `init_db.py` (script seed/demo CHỈ dành cho SQLite
    cục bộ, Postgres/Supabase khởi tạo qua `supabase/schema.sql` riêng)."""
    database_url = app.config.get("DATABASE_URL")
    if database_url:
        return _PostgresConnCompat(database_url)
    return get_raw_connection(app.config["DATABASE_PATH"], app.config.get("SQLITE_PRAGMAS"))


def execute_query(sql: str, params: Sequence[Any] = ()) -> list[Any]:
    """Thực thi câu SELECT và trả về toàn bộ kết quả (list các row dict-like).

    Trên Postgres, nếu connection đã cache trong `g.db` bị đứt giữa chừng
    (`OperationalError`/`InterfaceError` — xem `_discard_broken_connection()`), tự mở lại
    connection MỚI và thử lại ĐÚNG 1 LẦN trước khi để lỗi lan ra ngoài. An toàn để retry vì
    đây LUÔN LUÔN là câu SELECT thuần (không có side-effect nào bị lặp lại/mất mát)."""
    try:
        db = get_db()
        cur = db.execute(sql, params)
        rows = cur.fetchall()
        cur.close()
        return rows
    except DatabaseError:
        if get_dialect() != "postgres":
            raise
        _discard_broken_connection()
        try:
            db = get_db()
            cur = db.execute(sql, params)
            rows = cur.fetchall()
            cur.close()
            return rows
        except DatabaseError:
            _discard_broken_connection()
            raise


def execute_one(sql: str, params: Sequence[Any] = ()) -> Any:
    """Thực thi câu SELECT và trả về một dòng duy nhất (hoặc None) — cùng cơ chế tự thử
    lại 1 lần khi connection Postgres bị đứt giữa chừng như `execute_query()`."""
    try:
        db = get_db()
        cur = db.execute(sql, params)
        row = cur.fetchone()
        cur.close()
        return row
    except DatabaseError:
        if get_dialect() != "postgres":
            raise
        _discard_broken_connection()
        try:
            db = get_db()
            cur = db.execute(sql, params)
            row = cur.fetchone()
            cur.close()
            return row
        except DatabaseError:
            _discard_broken_connection()
            raise


def execute_write(sql: str, params: Sequence[Any] = ()) -> int:
    """Thực thi INSERT/UPDATE/DELETE đơn lẻ, tự commit. Trả về id của dòng vừa insert
    (`cursor.lastrowid` ở SQLite; Postgres không có `lastrowid` nên tự thêm `RETURNING id`
    vào câu SQL trước khi chạy — CHỈ áp dụng khi SQL là INSERT và chưa có RETURNING sẵn)."""
    db = get_db()
    if get_dialect() == "postgres" and sql.strip().upper().startswith("INSERT") and "RETURNING" not in sql.upper():
        sql = sql.rstrip().rstrip(";") + " RETURNING id"
        cur = db.execute(sql, params)
        row = cur.fetchone()
        db.commit()
        last_id = row["id"] if row else None
        cur.close()
        return last_id
    cur = db.execute(sql, params)
    db.commit()
    last_id = cur.lastrowid
    cur.close()
    return last_id


def insert_returning_id(conn: Any, sql: str, params: Sequence[Any] = ()) -> int:
    """Dùng khi code ĐANG CÓ SẴN 1 `conn`/cursor riêng (không qua `execute_write()`) và cần
    lấy id vừa insert — thay cho việc gọi thẳng `cursor.lastrowid` (không tồn tại ở
    psycopg2/Postgres). Tự thêm `RETURNING id` khi chạy Postgres, dùng `lastrowid` khi SQLite."""
    if get_dialect() == "postgres" and "RETURNING" not in sql.upper():
        sql = sql.rstrip().rstrip(";") + " RETURNING id"
        cur = conn.execute(sql, params)
        row = cur.fetchone()
        new_id = row["id"] if row else None
        cur.close()
        return new_id
    cur = conn.execute(sql, params)
    new_id = cur.lastrowid
    cur.close()
    return new_id


def execute_many(sql: str, seq_of_params: Iterable[Sequence[Any]]) -> int:
    """
    Bulk insert bằng `executemany` bên trong MỘT transaction duy nhất.
    Trả về số dòng đã ảnh hưởng (rowcount). Dùng cho Excel Import Pipeline.
    """
    db = get_db()
    cur = db.executemany(sql, seq_of_params)
    db.commit()
    count = cur.rowcount
    cur.close()
    return count


def init_app(app: Flask) -> None:
    """Đăng ký teardown handler và CLI command `flask init-db` vào app."""
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)


@click.command("init-db")
def init_db_command() -> None:
    """Flask CLI command: `flask init-db` — khởi tạo lại schema (gọi script init_db.py)."""
    import init_db as init_db_module

    init_db_module.main()
    click.echo("Đã khởi tạo Database thành công.")
