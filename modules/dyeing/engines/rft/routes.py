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
                from_date=request.args.get("from_date") or None,
                to_date=request.args.get("to_date") or None,
                group_by=request.args.get("group_by", "date"),
            )
            return jsonify(data)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    return bp
