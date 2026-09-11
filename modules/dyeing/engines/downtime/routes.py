"""Blueprint và API cho Dashboard Downtime Availability."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from flask import Blueprint, jsonify, render_template, request

from core.auth import get_current_user, permission_required

from . import service

if TYPE_CHECKING:
    from core.engine_base import BaseEngine


def build_blueprint(_engine: "BaseEngine") -> Blueprint:
    bp = Blueprint("downtime", __name__, template_folder="templates", static_folder="static")

    @bp.route("/")
    @permission_required("dyeing", "downtime", "view")
    def view() -> Any:
        return render_template("downtime_view.html")

    @bp.route("/api/summary")
    @permission_required("dyeing", "downtime", "view")
    def api_summary() -> Any:
        try:
            data = service.get_downtime_pivot_data(
                capacities=request.args.get("capacities") or None,
                from_date=request.args.get("from_date") or None,
                to_date=request.args.get("to_date") or None,
                group_by=request.args.get("group_by", "date"),
            )
            return jsonify(data)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @bp.route("/api/top-batches")
    @permission_required("dyeing", "downtime", "view")
    def api_top_batches() -> Any:
        period = request.args.get("period") or ""
        group_by = request.args.get("group_by", "date")
        category = request.args.get("category") or ""
        if not period or not category:
            return jsonify({"error": "Missing period/category."}), 400
        capacities = request.args.get("capacities") or None
        try:
            data = service.get_top_batches_for_category(period, group_by, category, capacities)
            return jsonify(data)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @bp.route("/api/abnormal-point")
    @permission_required("dyeing", "downtime", "view")
    def api_abnormal_point() -> Any:
        data = service.get_abnormal_point_pivot(
            capacities=request.args.get("capacities") or None,
            from_date=request.args.get("from_date") or None,
            to_date=request.args.get("to_date") or None,
            group_by=request.args.get("group_by", "date"),
        )
        return jsonify(data)

    @bp.route("/api/abnormal-point-batches")
    @permission_required("dyeing", "downtime", "view")
    def api_abnormal_point_batches() -> Any:
        field = request.args.get("field") or ""
        capacities = request.args.get("capacities") or None
        from_date = request.args.get("from_date") or None
        to_date = request.args.get("to_date") or None
        period = request.args.get("period") or None
        group_by = request.args.get("group_by", "date")
        try:
            data = service.get_abnormal_point_batches(field, capacities, from_date, to_date, period, group_by)
            return jsonify(data)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @bp.route("/api/case-notes/<int:availability_log_id>", methods=["POST"])
    @permission_required("dyeing", "downtime", "edit")
    def api_upsert_case_note(availability_log_id: int) -> Any:
        payload = request.get_json(silent=True) or {}
        reason = str(payload.get("reason") or "").strip() or None
        detail = str(payload.get("detail") or "").strip() or None
        user = get_current_user()
        try:
            note = service.upsert_case_note(availability_log_id, reason, detail, user["id"])
            return jsonify({"status": "success", "note": note})
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    return bp
