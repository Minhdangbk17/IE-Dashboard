"""
modules/dyeing/__init__.py
----------------------------
Domain Container "dyeing" (Nhuộm).

Expose hàm `register(app)` theo convention mà `app.py::_autoload_domains()`
yêu cầu. Hàm này:

  1. Auto-load mọi Engine con nằm trong `modules/dyeing/engines/` (quét bằng
     `pkgutil`, KHÔNG hardcode tên engine).
  2. Gắn Blueprint của từng Engine vào `dyeing_bp` (Nested Blueprint Pattern),
     mount tại `/dyeing/<engine_name>/...`.
  3. Gắn route Hub Aggregator (`/dyeing/`).
  4. Đăng ký toàn bộ Blueprint domain vào Flask app.
  5. Đăng ký mục menu Sidebar (cha "Nhuộm (Dyeing)" + các mục con tương ứng
     mỗi Engine) vào Navigation Registry.
"""
from __future__ import annotations

import importlib
import pkgutil

from flask import Flask

from core.engine_base import BaseEngine
from core.navigation import NavItem, register_menu

from .routes import dyeing_bp, register_hub_routes

DOMAIN_NAME = "dyeing"


def _autoload_engines() -> list[BaseEngine]:
    """Quét package `modules.dyeing.engines`, import từng Engine con và gắn
    Blueprint của nó vào `dyeing_bp`. Trả về danh sách instance Engine đã nạp."""
    from . import engines  # package chứa các sub-engine (oee, downtime, excel_import, ...)

    loaded: list[BaseEngine] = []
    for _finder, module_name, is_pkg in pkgutil.iter_modules(engines.__path__):
        if not is_pkg:
            continue
        full_name = f"modules.{DOMAIN_NAME}.engines.{module_name}"
        engine_module = importlib.import_module(full_name)
        engine: BaseEngine | None = getattr(engine_module, "engine", None)
        if engine is None:
            continue  # module không expose `engine` -> không phải Engine hợp lệ, bỏ qua
        dyeing_bp.register_blueprint(engine.blueprint, url_prefix=f"/{engine.name}")
        loaded.append(engine)
    return loaded


def register(app: Flask) -> None:
    """Điểm vào duy nhất mà Auto-loader của `app.py` gọi tới."""
    engines_loaded = _autoload_engines()
    register_hub_routes(dyeing_bp, engines_loaded)
    app.register_blueprint(dyeing_bp, url_prefix=f"/{DOMAIN_NAME}")

    children = [
        NavItem(
            label=_engine_display_name(e.name),
            endpoint=f"{DOMAIN_NAME}.{e.name}.view",
            icon="graph",
            domain=e.domain,
            engine_name=e.name,
        )
        for e in engines_loaded
        if e.name != "excel_import"  # excel_import chỉ dùng qua Modal, không có trang riêng
    ]
    register_menu(
        label="Dyeing",
        endpoint=f"{DOMAIN_NAME}.hub",
        icon="beaker",
        children=children,
    )

    app.logger.info(
        "Domain '%s' đã nạp %d engine(s): %s",
        DOMAIN_NAME,
        len(engines_loaded),
        [e.name for e in engines_loaded],
    )


def _engine_display_name(engine_name: str) -> str:
    return {
        "oee": "OEE",
        "downtime": "Downtime",
        "manual_entry": "Manual Availability Entry",
        "reports": "Batch Per Day by Machine",
        "batch_matrix": "Batch/Day",
        "rft": "Right First Time",
        "tank_loading": "%Tank Loading",
    }.get(engine_name, engine_name.replace("_", " ").title())
