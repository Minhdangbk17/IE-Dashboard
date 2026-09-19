"""Blueprint và API cho báo cáo Right First Time (RFT)."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from flask import Blueprint, jsonify, render_template, request

from core.auth import permission_required

from . import service

if TYPE_CHECKING:
    from core.engine_base import BaseEngine


def build_blueprint(_engine: "BaseEngine") -> Blueprint:
    bp = Blueprint("rft", __name__, template_folder="templates", static_folder="static")

    @bp.route("/")
    @permission_required("dyeing", "rft", "view")
    def view() -> Any:
        return render_template("rft_view.html", categories=list(service.RFT_CATEGORY_SLUGS.items()))

    @bp.route("/api/summary")
    @permission_required("dyeing", "rft", "view")
    def api_summary() -> Any:
        slug = request.args.get("category") or ""
        category = service.RFT_CATEGORY_SLUGS.get(slug)
        if category is None:
            return jsonify({"error": "Invalid or missing category."}), 400
        try:
            data = service.get_rft_pivot_data(
                category=category,
                capacities=request.args.get("capacities") or None,
                machine_types=request.args.get("machine_types") or None,
                brand_programs=request.args.get("brand_programs") or None,
                from_date=request.args.get("from_date") or None,
                to_date=request.args.get("to_date") or None,
                group_by=request.args.get("group_by", "date"),
            )
            return jsonify(data)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @bp.route("/api/targets/<slug>/<fabric_type>", methods=["POST"])
    @permission_required("dyeing", "rft", "edit")
    def api_set_target(slug: str, fabric_type: str) -> Any:
        category = service.RFT_CATEGORY_SLUGS.get(slug)
        if category is None:
            return jsonify({"error": "Invalid category."}), 400
        payload = request.get_json(silent=True) or {}
        try:
            target_value = float(payload.get("target_value"))
        except (TypeError, ValueError):
            return jsonify({"error": "target_value must be a number."}), 400
        try:
            target = service.set_target(category, fabric_type, target_value)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"status": "success", "target": target})

    return bp
