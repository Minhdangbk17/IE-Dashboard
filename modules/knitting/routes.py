"""modules/knitting/routes.py — Blueprint gốc + route Hub cho Domain "knitting".

Hub giống Dyeing: header có nút Import Data (Modal, Engine `excel_import`) + vùng Dashboard
(hiện để TRỐNG — người dùng sẽ thiết kế sau, 2026-10-09).
"""
from __future__ import annotations

from typing import Any

from flask import Blueprint, render_template

from core.auth import current_user_can, login_required
from core.engine_base import BaseEngine

knitting_bp = Blueprint("knitting", __name__, template_folder="templates")


def register_hub_routes(blueprint: Blueprint, engines_loaded: list[BaseEngine]) -> None:
    @blueprint.route("/")
    @login_required
    def hub() -> Any:
        has_excel_import = any(e.name == "excel_import" for e in engines_loaded)
        return render_template(
            "knitting_hub.html",
            has_excel_import=has_excel_import,
            can_import=has_excel_import and current_user_can("knitting", "excel_import", "edit"),
        )
