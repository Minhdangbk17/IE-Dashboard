"""Blueprint và API cho báo cáo %Tank Loading.

- `GET  /dyeing/tank_loading/api/summary?capacities=&brand_programs=&from_date=&to_date=&group_by=`
  -> API JSON (LUÔN 3 dòng Cotton/CVC/Polyester cố định — xem `service.py`).
- `POST /dyeing/tank_loading/api/targets/<fabric_type>` -> Set/update Target (%) của 1
  trong 3 loại vải chính.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from flask import Blueprint, jsonify, render_template, request

from core.auth import permission_required

from . import service

if TYPE_CHECKING:
    from core.engine_base import BaseEngine


def build_blueprint(_engine: "BaseEngine") -> Blueprint:
    bp = Blueprint("tank_loading", __name__, template_folder="templates", static_folder="static")

    @bp.route("/")
    @permission_required("dyeing", "tank_loading", "view")
    def view() -> Any:
        return render_template("tank_loading_view.html")

    @bp.route("/api/summary")
    @permission_required("dyeing", "tank_loading", "view")
    def api_summary() -> Any:
        try:
            data = service.get_tank_loading_pivot_data(
                capacities=request.args.get("capacities") or None,
                brand_programs=request.args.get("brand_programs") or None,
                from_date=request.args.get("from_date") or None,
                to_date=request.args.get("to_date") or None,
                group_by=request.args.get("group_by", "date"),
            )
            return jsonify(data)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @bp.route("/api/targets/<fabric_type>", methods=["POST"])
    @permission_required("dyeing", "tank_loading", "edit")
    def api_set_target(fabric_type: str) -> Any:
        payload = request.get_json(silent=True) or {}
        try:
            target_value = float(payload.get("target_value"))
        except (TypeError, ValueError):
            return jsonify({"error": "target_value must be a number."}), 400
        try:
            target = service.set_target(fabric_type, target_value)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"status": "success", "target": target})

    return bp
