"""
core/auth.py
------------
Cơ chế xác thực & phân quyền tối giản cho Phase 1 (Foundation Skeleton).

Phase 1 dùng session-based "giả lập" đăng nhập (login đơn giản, không mã hoá
phức tạp) để tập trung vào kiến trúc Engine-Plugin. Ở Phase sau có thể thay
thế bằng Flask-Login / JWT mà không ảnh hưởng tới các Engine (vì các Engine
chỉ phụ thuộc vào decorator `@login_required` / `@role_required`).
"""
from __future__ import annotations

import hashlib
from functools import wraps
from typing import Any, Callable, TypeVar

import click
from flask import Flask, current_app, flash, g, has_app_context, redirect, request, session, url_for

from core.database import DatabaseError, execute_one

F = TypeVar("F", bound=Callable[..., Any])


def _get_secret_salt() -> str:
    """Lấy SECRET_KEY để làm salt băm mật khẩu.

    Ưu tiên lấy từ `current_app.config` khi đang chạy trong Flask app context
    (request/CLI command). Khi được gọi từ script độc lập KHÔNG có app context
    (vd `init_db.py`), fallback trực tiếp về `config.Config.SECRET_KEY` để
    tránh lỗi "Working outside of application context".
    """
    if has_app_context():
        return current_app.config.get("SECRET_KEY", "dev-secret-key")
    from config import Config

    return Config.SECRET_KEY


def hash_password(raw_password: str) -> str:
    """Băm mật khẩu bằng SHA-256 kèm salt cố định theo SECRET_KEY của app.

    Lưu ý: SHA-256 đơn giản chỉ phù hợp cho Phase 1 (demo). Production nên
    dùng `werkzeug.security.generate_password_hash` (bcrypt/scrypt).
    """
    salt = _get_secret_salt()
    return hashlib.sha256(f"{salt}:{raw_password}".encode("utf-8")).hexdigest()


def verify_password(raw_password: str, hashed: str) -> bool:
    """So khớp mật khẩu người dùng nhập với hash đã lưu trong DB."""
    return hash_password(raw_password) == hashed


def get_current_user() -> dict[str, Any] | None:
    """Lấy thông tin user hiện tại từ session (cache trong `g` theo request).

    Nếu DB lỗi (vd Postgres/Supabase mất kết nối giữa chừng — `execute_one()` đã tự thử
    lại 1 lần, xem `core/database.py::_discard_broken_connection()`), coi như "chưa đăng
    nhập" cho request này thay vì để exception lan ra ngoài. **Bug thật đã gặp trên
    production**: hàm này được gọi CẢ ở decorator phân quyền LẪN ở
    `navigation.py::inject_nav_menu` (context processor chạy cho MỌI template, kể cả
    `errors/500.html`) — nếu để lỗi lan ra, request lỗi DB gốc khiến Flask cố render trang
    500 thân thiện, nhưng chính việc render đó lại gọi hàm này lần nữa và crash tiếp,
    khiến người dùng không bao giờ thấy trang lỗi tử tế mà thấy lỗi thô của server. Chấp
    nhận được vì đây chỉ là suy giảm tạm thời (session vẫn còn, request kế tiếp có kết nối
    mới sẽ đăng nhập lại bình thường), không phải lỗ hổng bảo mật (KHÔNG cấp quyền gì)."""
    if "current_user" in g:
        return g.current_user  # type: ignore[no-any-return]

    user_id = session.get("user_id")
    if user_id is None:
        g.current_user = None
        return None

    try:
        row = execute_one(
            "SELECT id, username, full_name, role FROM users WHERE id = ?", (user_id,)
        )
    except DatabaseError:
        current_app.logger.exception("get_current_user(): loi DB, coi nhu chua dang nhap cho request nay")
        g.current_user = None
        return None
    g.current_user = dict(row) if row else None
    return g.current_user


def login_required(view_func: F) -> F:
    """Decorator: yêu cầu người dùng phải đăng nhập mới được truy cập route."""

    @wraps(view_func)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        if get_current_user() is None:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("auth.login", next=request.path))
        return view_func(*args, **kwargs)

    return wrapped  # type: ignore[return-value]


def role_required(*allowed_roles: str) -> Callable[[F], F]:
    """Decorator factory: giới hạn route chỉ cho một số vai trò (role) nhất định.

    Ví dụ:
        @role_required("admin")
        def delete_machine(): ...
    """

    def decorator(view_func: F) -> F:
        @wraps(view_func)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            user = get_current_user()
            if user is None:
                flash("Please log in to continue.", "warning")
                return redirect(url_for("auth.login", next=request.path))
            if user["role"] not in allowed_roles:
                flash("You do not have permission to access this feature.", "danger")
                return redirect(url_for("dashboard.index"))
            return view_func(*args, **kwargs)

        return wrapped  # type: ignore[return-value]

    return decorator


# ---------------------------------------------------------------------------
# Permission Model — phân quyền Xem/Sửa/Xoá theo TỪNG ENGINE (bảng
# `user_permissions`). admin luôn superuser cố định, KHÔNG đi qua bảng này —
# tránh tự khoá nhầm chính mình qua UI quản lý tài khoản.
# ---------------------------------------------------------------------------

_VALID_ACTIONS = {"view": "can_view", "edit": "can_edit", "delete": "can_delete"}


def ensure_user_permissions_table(conn: Any) -> None:
    """Tạo bảng `user_permissions` nếu chưa có — AN TOÀN gọi lại nhiều lần, không phá
    vỡ dữ liệu cũ (CREATE TABLE IF NOT EXISTS). Gọi 1 lần lúc app khởi động (`init_app()`)
    để phân quyền hoạt động được ngay cả trên DB thật đã có dữ liệu từ trước, không cần
    chạy lại `init_db.py --reset`. CHỈ chạy DDL này ở SQLite (`AUTOINCREMENT` là cú pháp
    SQLite-only) — ở Postgres bảng đã có sẵn qua `supabase/schema.sql`."""
    from core.database import get_dialect

    if get_dialect() == "sqlite":
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_permissions (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                domain        TEXT NOT NULL,
                engine_name   TEXT NOT NULL,
                can_view      INTEGER NOT NULL DEFAULT 0 CHECK (can_view IN (0,1)),
                can_edit      INTEGER NOT NULL DEFAULT 0 CHECK (can_edit IN (0,1)),
                can_delete    INTEGER NOT NULL DEFAULT 0 CHECK (can_delete IN (0,1)),
                UNIQUE(user_id, domain, engine_name)
            )
        """)
    conn.commit()


def has_permission(user_id: int, domain: str, engine_name: str, action: str) -> bool:
    """Kiểm tra user (KHÔNG PHẢI admin — admin luôn True ở tầng gọi, không nên gọi hàm
    này cho admin để tránh query DB không cần thiết) có quyền `action`
    ('view'|'edit'|'delete') trên đúng 1 Engine (`domain`, `engine_name`) hay không."""
    column = _VALID_ACTIONS.get(action)
    if column is None:
        raise ValueError(f"action không hợp lệ: {action!r} (phải là 'view'/'edit'/'delete')")
    row = execute_one(
        f"SELECT {column} AS allowed FROM user_permissions WHERE user_id = ? AND domain = ? AND engine_name = ?",
        (user_id, domain, engine_name),
    )
    return bool(row and row["allowed"])


def current_user_can(domain: str, engine_name: str, action: str) -> bool:
    """Helper dùng trong template (Jinja2) VÀ code Python — admin luôn True (superuser cố
    định, không qua bảng `user_permissions`). Trả về False nếu chưa đăng nhập."""
    user = get_current_user()
    if user is None:
        return False
    if user["role"] == "admin":
        return True
    return has_permission(user["id"], domain, engine_name, action)


def permission_required(domain: str, engine_name: str, action: str) -> Callable[[F], F]:
    """Decorator cho route của từng Engine — gate theo đúng 1 (domain, engine_name, action).

    - Chưa đăng nhập -> redirect trang login (giữ hành vi như `login_required`).
    - role='admin' -> luôn cho qua, KHÔNG query `user_permissions` (superuser cố định).
    - role='operator' -> kiểm tra `has_permission(...)`; nếu False -> flash lỗi + redirect
      về Hub của đúng domain đó (không phải dashboard chung, để user biết đang ở đâu).
    """

    def decorator(view_func: F) -> F:
        @wraps(view_func)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            user = get_current_user()
            if user is None:
                flash("Please log in to continue.", "warning")
                return redirect(url_for("auth.login", next=request.path))
            if user["role"] == "admin":
                return view_func(*args, **kwargs)
            if not has_permission(user["id"], domain, engine_name, action):
                flash("You do not have permission to access this feature.", "danger")
                try:
                    return redirect(url_for(f"{domain}.hub"))
                except Exception:
                    return redirect(url_for("dashboard.index"))
            return view_func(*args, **kwargs)

        return wrapped  # type: ignore[return-value]

    return decorator


@click.command("sync-permissions")
@click.option("--yes", is_flag=True, default=False, help="Ghi thẳng vào DB, bỏ qua bước xác nhận.")
def sync_permissions_command(yes: bool) -> None:
    """Flask CLI: `flask sync-permissions [--yes]` — đồng bộ `user_permissions` cho MỌI user
    role='operator' đã tồn tại với MỌI Engine hiện có (quét động qua `engine_registry`).

    Với mỗi (user, engine) CHƯA có dòng trong `user_permissions`: đề xuất mặc định
    can_view=1/can_edit=0/can_delete=0 (giữ hành vi không đổi đột ngột cho user operator ĐÃ
    TỒN TẠI TỪ TRƯỚC — trước đây họ xem được mọi thứ theo role nhị phân cũ). User operator
    TẠO MỚI sau khi có tính năng phân quyền không cần lệnh này (route tạo tài khoản không
    tự gán quyền gì — an toàn hơn, admin phải chủ động gán qua UI).

    LUÔN in ra bảng dự kiến trước, KHÔNG ghi gì vào DB nếu thiếu `--yes`."""
    from core.database import get_raw_connection_for_app
    from core.engine_registry import discover_engines

    conn = get_raw_connection_for_app(current_app)
    try:
        ensure_user_permissions_table(conn)
        engines = discover_engines()
        operators = conn.execute("SELECT id, username FROM users WHERE role = 'operator' ORDER BY username").fetchall()
        existing = {
            (row["user_id"], row["domain"], row["engine_name"])
            for row in conn.execute("SELECT user_id, domain, engine_name FROM user_permissions").fetchall()
        }

        to_add: list[tuple[int, str, str, str]] = []
        for user in operators:
            for engine in engines:
                key = (user["id"], engine.domain, engine.name)
                if key not in existing:
                    to_add.append((user["id"], user["username"], engine.domain, engine.name))

        if not to_add:
            click.echo("Không có gì cần đồng bộ — mọi (user operator, engine) đã có dòng quyền.")
            return

        click.echo(f"Sẽ thêm {len(to_add)} dòng quyền mới (mặc định can_view=1, can_edit=0, can_delete=0):")
        for user_id, username, domain, engine_name in to_add:
            click.echo(f"  user={username} (id={user_id})  {domain}.{engine_name}  view=1 edit=0 delete=0")

        if not yes:
            click.echo("\nCHƯA ghi gì vào DB. Chạy lại với --yes để xác nhận ghi thật.")
            return

        conn.executemany(
            "INSERT INTO user_permissions (user_id, domain, engine_name, can_view, can_edit, can_delete) VALUES (?, ?, ?, 1, 0, 0)",
            [(user_id, domain, engine_name) for user_id, _, domain, engine_name in to_add],
        )
        conn.commit()
        click.echo(f"Đã ghi {len(to_add)} dòng quyền mới vào DB.")
    finally:
        conn.close()


def init_app(app: Flask) -> None:
    """Đảm bảo bảng `user_permissions` tồn tại (an toàn cho DB đã có dữ liệu thật, không
    cần `init_db.py --reset`) + đăng ký CLI `flask sync-permissions`."""
    from core.database import get_raw_connection_for_app

    conn = get_raw_connection_for_app(app)
    try:
        ensure_user_permissions_table(conn)
    finally:
        conn.close()
    app.cli.add_command(sync_permissions_command)
