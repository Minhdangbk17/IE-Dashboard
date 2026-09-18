from __future__ import annotations

import importlib
import pkgutil
from typing import Any

from flask import Flask, redirect, render_template, request, session, url_for

from config import Config, get_config
from core import auth, database, navigation, rollup
from core.auth import get_current_user, hash_password, login_required, verify_password
from core.database import execute_one


def create_app(config_object: Any = None) -> Flask:
    """Application Factory: khởi tạo, cấu hình và lắp ráp toàn bộ ứng dụng."""
    app = Flask(__name__)
    app.config.from_object(config_object or get_config())
    Config.ensure_directories()

    # --- Hạ tầng lõi ---
    database.init_app(app)
    navigation.init_app(app)
    rollup.init_app(app)
    auth.init_app(app)  # đảm bảo bảng user_permissions tồn tại + đăng ký CLI sync-permissions

    # --- Blueprint nền tảng (auth, dashboard tổng) ---
    _register_auth_blueprint(app)
    _register_dashboard_blueprint(app)

    # --- Auto-loader: quét & đăng ký toàn bộ Domain modules (dyeing, knitting, ...) ---
    _autoload_domains(app)

    # --- Graphify Engine: sơ đồ phụ thuộc Engine / Data Flow ---
    _register_graphify(app)

    # --- Quản lý tài khoản (core-level, không phải Domain nghiệp vụ) ---
    _register_admin_blueprint(app)

    # --- Error handlers thân thiện ---
    _register_error_handlers(app)

    return app


# ---------------------------------------------------------------------------
# Auto-loader cho Domain modules trong package `modules/`
# ---------------------------------------------------------------------------


def _autoload_domains(app: Flask) -> None:
    """
    Quét mọi sub-package trực tiếp trong `modules/` (mỗi sub-package = 1 Domain,
    vd `modules.dyeing`, `modules.knitting`).

    Convention bắt buộc: mỗi Domain package phải expose hàm
    `register(app: Flask) -> None` trong `__init__.py` của nó. Hàm này chịu
    trách nhiệm tự đăng ký Blueprint của Domain (và auto-load các Engine con)
    vào `app`.
    """
    import modules  # package rỗng, chỉ đóng vai trò namespace

    discovered: list[str] = []
    for _finder, module_name, is_pkg in pkgutil.iter_modules(modules.__path__):
        if not is_pkg:
            continue
        full_name = f"modules.{module_name}"
        domain_module = importlib.import_module(full_name)
        register_fn = getattr(domain_module, "register", None)
        if register_fn is None:
            app.logger.warning(
                "Domain module '%s' không có hàm register(app) — bỏ qua.", full_name
            )
            continue
        register_fn(app)
        discovered.append(module_name)

    app.logger.info("Auto-loader: đã nạp %d domain(s): %s", len(discovered), discovered)


# ---------------------------------------------------------------------------
# Auth blueprint (đăng nhập / đăng xuất tối giản cho Phase 1)
# ---------------------------------------------------------------------------


def _register_auth_blueprint(app: Flask) -> None:
    from flask import Blueprint

    bp = Blueprint("auth", __name__, template_folder="templates")

    @bp.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            user = execute_one("SELECT * FROM users WHERE username = ?", (username,))
            if user and verify_password(password, user["password_hash"]):
                session["user_id"] = user["id"]
                next_url = request.args.get("next") or url_for("dashboard.index")
                return redirect(next_url)
            return render_template("login.html", error="Sai tên đăng nhập hoặc mật khẩu.")
        return render_template("login.html", error=None)

    @bp.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("auth.login"))

    app.register_blueprint(bp)


# ---------------------------------------------------------------------------
# Dashboard tổng (trang chủ sau khi đăng nhập)
# ---------------------------------------------------------------------------


def _register_dashboard_blueprint(app: Flask) -> None:
    from flask import Blueprint

    bp = Blueprint("dashboard", __name__, template_folder="templates")

    @bp.route("/")
    @login_required
    def index():
        user = get_current_user()
        return render_template("dashboard.html", user=user)

    app.register_blueprint(bp)


# ---------------------------------------------------------------------------
# Graphify: mount blueprint hiển thị sơ đồ phụ thuộc Engine/Data Flow
# ---------------------------------------------------------------------------


def _register_graphify(app: Flask) -> None:
    from graphify.routes import graphify_bp

    app.register_blueprint(graphify_bp, url_prefix="/graphify")
    navigation.register_menu(
        label="System Diagram (Graphify)",
        endpoint="graphify.graph_view",
        icon="git-branch",
        roles=("admin",),
    )


def _register_admin_blueprint(app: Flask) -> None:
    from admin.routes import admin_bp

    app.register_blueprint(admin_bp, url_prefix="/admin")
    navigation.register_menu(
        label="Account Management",
        endpoint="admin.list_accounts",
        icon="people",
        roles=("admin",),
    )
    navigation.register_menu(
        label="Data Tools",
        endpoint="admin.data_tools",
        icon="sync",
        roles=("admin",),
    )


def _register_error_handlers(app: Flask) -> None:
    @app.errorhandler(404)
    def not_found(_err: Any):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(_err: Any):
        return render_template("errors/500.html"), 500


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=app.config.get("DEBUG", True))
