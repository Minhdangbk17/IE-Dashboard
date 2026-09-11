"""
modules/knitting/__init__.py
-------------------------------
Domain Container "knitting" (Dệt) — Phase 1 chỉ scaffold tối giản để CHỨNG
MINH kiến trúc Auto-loader hoạt động đúng với NHIỀU Domain cùng lúc (không
chỉ riêng "dyeing"). Cấu trúc và convention giống hệt `modules/dyeing/`.

Ở các Phase sau, domain này sẽ có đầy đủ Engine riêng (vd: `knitting_efficiency`,
`yarn_consumption`, ...) theo đúng khuôn mẫu của `modules/dyeing/engines/oee`.
"""
from __future__ import annotations

import importlib
import pkgutil

from flask import Flask

from core.engine_base import BaseEngine
from core.navigation import NavItem, register_menu

from .routes import knitting_bp, register_hub_routes

DOMAIN_NAME = "knitting"


def _autoload_engines() -> list[BaseEngine]:
    from . import engines

    loaded: list[BaseEngine] = []
    for _finder, module_name, is_pkg in pkgutil.iter_modules(engines.__path__):
        if not is_pkg:
            continue
        full_name = f"modules.{DOMAIN_NAME}.engines.{module_name}"
        engine_module = importlib.import_module(full_name)
        engine: BaseEngine | None = getattr(engine_module, "engine", None)
        if engine is None:
            continue
        knitting_bp.register_blueprint(engine.blueprint, url_prefix=f"/{engine.name}")
        loaded.append(engine)
    return loaded


def register(app: Flask) -> None:
    engines_loaded = _autoload_engines()
    register_hub_routes(knitting_bp, engines_loaded)
    app.register_blueprint(knitting_bp, url_prefix=f"/{DOMAIN_NAME}")

    children = [
        NavItem(
            label=e.name.replace("_", " ").title(),
            endpoint=f"{DOMAIN_NAME}.{e.name}.view",
            icon="graph",
            domain=e.domain,
            engine_name=e.name,
        )
        for e in engines_loaded
    ]
    register_menu(
        label="Knitting",
        endpoint=f"{DOMAIN_NAME}.hub",
        icon="pulse",
        children=children,
    )

    app.logger.info(
        "Domain '%s' đã nạp %d engine(s): %s", DOMAIN_NAME, len(engines_loaded), [e.name for e in engines_loaded]
    )
