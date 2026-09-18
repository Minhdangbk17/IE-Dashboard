"""Blueprint và API cho Dashboard Downtime Availability."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from flask import Blueprint, jsonify, render_template, request

from core.auth import get_current_user, permission_required, role_required

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
                fabric_types=request.args.get("fabric_types") or None,
                brand_programs=request.args.get("brand_programs") or None,
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
        fabric_types = request.args.get("fabric_types") or None
        brand_programs = request.args.get("brand_programs") or None
        try:
            data = service.get_top_batches_for_category(period, group_by, category, capacities, fabric_types=fabric_types, brand_programs=brand_programs)
            return jsonify(data)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @bp.route("/api/abnormal-point")
    @permission_required("dyeing", "downtime", "view")
    def api_abnormal_point() -> Any:
        data = service.get_abnormal_point_pivot(
            capacities=request.args.get("capacities") or None,
            fabric_types=request.args.get("fabric_types") or None,
            brand_programs=request.args.get("brand_programs") or None,
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
        fabric_types = request.args.get("fabric_types") or None
        brand_programs = request.args.get("brand_programs") or None
        from_date = request.args.get("from_date") or None
        to_date = request.args.get("to_date") or None
        period = request.args.get("period") or None
        group_by = request.args.get("group_by", "date")
        try:
            data = service.get_abnormal_point_batches(field, capacities, from_date, to_date, period, group_by, fabric_types=fabric_types, brand_programs=brand_programs)
            return jsonify(data)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @bp.route("/api/targets")
    @permission_required("dyeing", "downtime", "view")
    def api_get_targets() -> Any:
        return jsonify(service.get_targets())

    @bp.route("/api/targets", methods=["POST"])
    @role_required("admin")
    def api_set_target() -> Any:
        payload = request.get_json(silent=True) or {}
        category = str(payload.get("category", "")).strip()
        try:
            target_pct = float(payload.get("target_pct"))
            target_hours = float(payload.get("target_hours"))
        except (TypeError, ValueError):
            return jsonify({"error": "target_pct/target_hours phải là số."}), 400
        try:
            service.set_target(category, target_pct, target_hours)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"status": "success"})

    @bp.route("/api/case-notes/<int:availability_log_id>", methods=["POST"])
    @permission_required("dyeing", "downtime", "edit")
    def api_upsert_case_note(availability_log_id: int) -> Any:
        payload = request.get_json(silent=True) or {}
        context = str(payload.get("context") or "").strip()
        if not context:
            return jsonify({"error": "Missing context (category/field)."}), 400
        reason = str(payload.get("reason") or "").strip() or None
        detail = str(payload.get("detail") or "").strip() or None
        user = get_current_user()
        try:
            note = service.upsert_case_note(availability_log_id, context, reason, detail, user["id"])
            return jsonify({"status": "success", "note": note})
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    return bp
