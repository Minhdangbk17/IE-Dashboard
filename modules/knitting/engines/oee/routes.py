"""modules/knitting/engines/oee/routes.py — Blueprint tối giản cho Engine OEE (stub) của Domain Dệt."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from flask import Blueprint, jsonify, render_template

from core.auth import permission_required

from . import service

if TYPE_CHECKING:
    from core.engine_base import BaseEngine


def build_blueprint(_engine: "BaseEngine") -> Blueprint:
    bp = Blueprint("oee", __name__, template_folder="templates")

    @bp.route("/")
    @permission_required("knitting", "oee", "view")
    def view() -> Any:
        return render_template("knitting_oee_view.html")

    @bp.route("/api/calculate")
    @permission_required("knitting", "oee", "view")
    def api_calculate() -> Any:
        return jsonify(service.calculate_oee_placeholder())

    return bp
