"""modules/knitting/routes.py — Blueprint gốc + route Hub cho Domain "knitting"."""
from __future__ import annotations

from typing import Any

from flask import Blueprint, render_template

from core.auth import login_required
from core.engine_base import BaseEngine

knitting_bp = Blueprint("knitting", __name__, template_folder="templates")


def register_hub_routes(blueprint: Blueprint, engines_loaded: list[BaseEngine]) -> None:
    @blueprint.route("/")
    @login_required
    def hub() -> Any:
        engine_info = [{"name": e.name, "description": e.metadata.description} for e in engines_loaded]
        return render_template("knitting_hub.html", engines=engine_info)
