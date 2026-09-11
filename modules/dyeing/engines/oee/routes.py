"""
modules/dyeing/engines/oee/routes.py
---------------------------------------
Blueprint & Route (API + View) của Engine "oee".

- `GET /dyeing/oee/`               -> View trang chi tiết OEE.
- `GET /dyeing/oee/api/calculate`  -> API JSON tính OEE (dùng bởi Hub widget qua fetch()).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from flask import Blueprint, jsonify, render_template, request

from core.auth import permission_required

from . import service

if TYPE_CHECKING:
    from core.engine_base import BaseEngine


def build_blueprint(_engine: "BaseEngine") -> Blueprint:
    bp = Blueprint("oee", __name__, template_folder="templates")

    @bp.route("/")
    @permission_required("dyeing", "oee", "view")
    def view() -> Any:
        return render_template("oee_view.html")

    @bp.route("/api/calculate")
    @permission_required("dyeing", "oee", "view")
    def api_calculate() -> Any:
        machine_id = request.args.get("machine_id") or None
        days = request.args.get("days", default=7, type=int)
        data = service.calculate_oee(machine_id=machine_id, days=days)
        return jsonify(data)

    return bp
