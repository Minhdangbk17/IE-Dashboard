from __future__ import annotations

import io
from datetime import datetime
from typing import TYPE_CHECKING, Any

from flask import Blueprint, jsonify, render_template, request, send_file

from core.auth import get_current_user, permission_required

from . import service
from .batch_day_trend import export_batch_day_trend_excel, get_batch_day_trend, get_trend_batches, set_trend_target

if TYPE_CHECKING:
    from core.engine_base import BaseEngine


def build_blueprint(_engine: "BaseEngine") -> Blueprint:
    bp = Blueprint("batch_matrix", __name__, template_folder="templates")

    @bp.route("/")
    @permission_required("dyeing", "batch_matrix", "view")
    def view() -> Any:
        return render_template("batch_matrix_view.html")

    def _matrix_filters() -> dict[str, Any]:
        return {
            "date_from": request.args.get("from_date") or None,
            "date_to": request.args.get("to_date") or None,
            "capacities": request.args.get("capacities") or None,
            "brand_programs": request.args.get("brand_programs") or None,
            "tank_types": request.args.get("tank_types") or None,
            "group_by": request.args.get("group_by", "date"),
        }

    @bp.route("/api/matrix")
    @permission_required("dyeing", "batch_matrix", "view")
    def api_matrix() -> Any:
        return jsonify(service.build_matrix(**_matrix_filters()))

    @bp.route("/api/matrix/batches")
    @permission_required("dyeing", "batch_matrix", "view")
    def api_matrix_batches() -> Any:
        fabric_type = request.args.get("fabric_type") or ""
        color_group = request.args.get("color_group") or ""
        if not fabric_type or not color_group:
            return jsonify({"error": "Missing fabric_type/color_group."}), 400
        return jsonify(service.get_cell_batches(
            fabric_type, color_group, period_key=request.args.get("period_key") or None, **_matrix_filters(),
        ))

    @bp.route("/api/matrix/export")
    @permission_required("dyeing", "batch_matrix", "view")
    def api_matrix_export() -> Any:
        filters = _matrix_filters()
        content = service.export_matrix_excel(**filters)
        if filters["date_from"] and filters["date_to"]:
            name_range = f"{filters['date_from']}_to_{filters['date_to']}"
        else:
            name_range = datetime.now().strftime("%Y-%m-%d")
        return send_file(
            io.BytesIO(content),
            as_attachment=True,
            download_name=f"fabric_color_matrix_{name_range}.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    def _trend_filters() -> dict[str, Any]:
        return {
            "capacities": request.args.get("capacities") or None,
            "brand_programs": request.args.get("brand_programs") or None,
            "tank_types": request.args.get("tank_types") or None,
            "from_date": request.args.get("from_date") or None,
            "to_date": request.args.get("to_date") or None,
            "group_by": request.args.get("group_by", "date"),
        }

    @bp.route("/api/batch-day-trend")
    @permission_required("dyeing", "batch_matrix", "view")
    def api_batch_day_trend() -> Any:
        return jsonify(get_batch_day_trend(**_trend_filters()))

    @bp.route("/api/batch-day-trend/batches")
    @permission_required("dyeing", "batch_matrix", "view")
    def api_trend_batches() -> Any:
        try:
            data = get_trend_batches(
                request.args.get("fabric_type", ""),
                period_key=request.args.get("period_key") or None,
                **_trend_filters(),
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify(data)

    @bp.route("/api/batch-day-trend/export")
    @permission_required("dyeing", "batch_matrix", "view")
    def api_trend_export() -> Any:
        filters = _trend_filters()
        fabric_type = request.args.get("fabric_type") or None
        period_key = request.args.get("period_key") or None
        try:
            content = export_batch_day_trend_excel(**filters, fabric_type=fabric_type, period_key=period_key)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        if filters["from_date"] and filters["to_date"]:
            name_range = f"{filters['from_date']}_to_{filters['to_date']}"
        else:
            name_range = datetime.now().strftime("%Y-%m-%d")
        scope = f"_{fabric_type}_{period_key or 'total'}" if fabric_type else ""
        return send_file(
            io.BytesIO(content),
            as_attachment=True,
            download_name=f"batch_day_trend{scope}_{name_range}.xlsx".replace(" ", "_"),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    @bp.route("/api/batch-day-trend/targets/<fabric_type>", methods=["POST"])
    @permission_required("dyeing", "batch_matrix", "edit")
    def api_set_trend_target(fabric_type: str) -> Any:
        payload = request.get_json(silent=True) or {}
        try:
            target_value = float(payload.get("target_value"))
        except (TypeError, ValueError):
            return jsonify({"error": "target_value must be a number."}), 400
        try:
            target = set_trend_target(fabric_type, target_value)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"status": "success", "target": target})

    @bp.route("/api/targets")
    @permission_required("dyeing", "batch_matrix", "view")
    def api_get_targets() -> Any:
        return jsonify(service.get_targets())

    @bp.route("/api/targets", methods=["POST"])
    @permission_required("dyeing", "batch_matrix", "edit")
    def api_set_target() -> Any:
        payload = request.get_json(silent=True) or {}
        fabric_type = str(payload.get("fabric_type", "")).strip()
        color_group = str(payload.get("color_group", "")).strip()
        if not fabric_type or not color_group:
            return jsonify({"error": "Missing fabric_type/color_group."}), 400
        raw_value = payload.get("target_value")
        if raw_value is None or str(raw_value).strip() == "":
            target_value = None
        else:
            try:
                target_value = float(raw_value)
            except (TypeError, ValueError):
                return jsonify({"error": "target_value must be a number."}), 400
        service.set_target(fabric_type, color_group, target_value)
        return jsonify({"status": "success"})

    @bp.route("/api/shade-overrides", methods=["POST"])
    @permission_required("dyeing", "batch_matrix", "edit")
    def api_set_shade_override() -> Any:
        payload = request.get_json(silent=True) or {}
        user = get_current_user()
        try:
            service.set_shade_override(
                str(payload.get("dyelot", "")), payload.get("shade"), user["username"] if user else None,
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"status": "success"})

    return bp
