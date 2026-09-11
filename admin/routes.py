"""
admin/routes.py
-----------------
Route quản lý tài khoản (tạo user, gán quyền Xem/Sửa/Xoá theo TỪNG ENGINE) — chỉ dành
cho role='admin' (gate bằng `@role_required("admin")` có sẵn ở mọi route).

- GET  /admin/accounts                       -> danh sách tài khoản.
- GET/POST /admin/accounts/new                -> tạo tài khoản mới.
- GET/POST /admin/accounts/<id>/permissions   -> ma trận quyền theo Engine (liệt kê ĐỘNG
  qua `core/engine_registry.py::discover_engines()` — KHÔNG hardcode danh sách Engine).

Admin là superuser cố định — KHÔNG đi qua bảng `user_permissions`, route permissions của
1 tài khoản admin chỉ hiển thị thông báo, không cho sửa (tránh tự khoá nhầm chính mình).
"""
from __future__ import annotations

from typing import Any

from flask import Blueprint, flash, redirect, render_template, request, url_for

from core.auth import hash_password, role_required
from core.database import execute_one, execute_query, execute_write, get_db
from core.engine_registry import discover_engines

admin_bp = Blueprint("admin", __name__, template_folder="templates")


def _engine_catalog() -> list[dict[str, str]]:
    """Danh sách ĐỘNG (domain, engine_name) từ `engine_registry` — KHÔNG hardcode ở đây
    hay bất kỳ đâu khác, đúng nguyên tắc Auto-loader "no hardcoding"."""
    return sorted(
        ({"domain": e.domain, "engine_name": e.name} for e in discover_engines()),
        key=lambda item: (item["domain"], item["engine_name"]),
    )


@admin_bp.route("/accounts")
@role_required("admin")
def list_accounts() -> Any:
    users = execute_query("SELECT id, username, full_name, role, created_at FROM users ORDER BY role, username")
    return render_template("accounts_list.html", users=[dict(user) for user in users])


@admin_bp.route("/accounts/new", methods=["GET", "POST"])
@role_required("admin")
def new_account() -> Any:
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        full_name = request.form.get("full_name", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", "operator")

        errors: list[str] = []
        if not username:
            errors.append("Username is required.")
        if not full_name:
            errors.append("Full name is required.")
        if len(password) < 6:
            errors.append("Password must be at least 6 characters.")
        if role not in ("admin", "operator"):
            errors.append("Invalid role.")
        if not errors and execute_one("SELECT id FROM users WHERE username = ?", (username,)):
            errors.append(f"Username '{username}' already exists.")

        if errors:
            for error in errors:
                flash(error, "danger")
            return render_template("account_new.html", form=request.form)

        user_id = execute_write(
            "INSERT INTO users (username, password_hash, full_name, role) VALUES (?, ?, ?, ?)",
            (username, hash_password(password), full_name, role),
        )
        flash(f"Account '{username}' created.", "success")
        if role == "operator":
            # UX 1 luồng: tạo xong -> gán quyền ngay (operator mới mặc định KHÔNG có
            # quyền gì, an toàn hơn — admin phải chủ động gán, xem core/auth.py::
            # sync_permissions_command() docstring).
            return redirect(url_for("admin.account_permissions", user_id=user_id))
        return redirect(url_for("admin.list_accounts"))

    return render_template("account_new.html", form={})


@admin_bp.route("/accounts/<int:user_id>/permissions", methods=["GET", "POST"])
@role_required("admin")
def account_permissions(user_id: int) -> Any:
    target = execute_one("SELECT id, username, full_name, role FROM users WHERE id = ?", (user_id,))
    if target is None:
        flash("Account not found.", "danger")
        return redirect(url_for("admin.list_accounts"))

    engines = _engine_catalog()

    if request.method == "POST":
        if target["role"] == "admin":
            flash("Admin is a fixed superuser and cannot be assigned permissions here.", "warning")
            return redirect(url_for("admin.account_permissions", user_id=user_id))
        conn = get_db()
        for engine in engines:
            key = f"{engine['domain']}__{engine['engine_name']}"
            can_view = 1 if request.form.get(f"view__{key}") else 0
            can_edit = 1 if request.form.get(f"edit__{key}") else 0
            can_delete = 1 if request.form.get(f"delete__{key}") else 0
            conn.execute(
                """
                INSERT INTO user_permissions (user_id, domain, engine_name, can_view, can_edit, can_delete)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, domain, engine_name)
                DO UPDATE SET can_view=excluded.can_view, can_edit=excluded.can_edit, can_delete=excluded.can_delete
                """,
                (user_id, engine["domain"], engine["engine_name"], can_view, can_edit, can_delete),
            )
        conn.commit()
        flash(f"Permissions updated for '{target['username']}'.", "success")
        return redirect(url_for("admin.account_permissions", user_id=user_id))

    existing = {
        (row["domain"], row["engine_name"]): row
        for row in execute_query("SELECT * FROM user_permissions WHERE user_id = ?", (user_id,))
    }
    rows = []
    for engine in engines:
        perm = existing.get((engine["domain"], engine["engine_name"]))
        rows.append({
            "domain": engine["domain"],
            "engine_name": engine["engine_name"],
            "key": f"{engine['domain']}__{engine['engine_name']}",
            "can_view": bool(perm["can_view"]) if perm else False,
            "can_edit": bool(perm["can_edit"]) if perm else False,
            "can_delete": bool(perm["can_delete"]) if perm else False,
        })

    return render_template("account_permissions.html", target=dict(target), rows=rows)
