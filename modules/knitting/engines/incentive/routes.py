"""modules/knitting/engines/incentive/routes.py — View + API báo cáo Incentive xưởng Dệt."""
from __future__ import annotations

import io
from typing import TYPE_CHECKING, Any

from flask import Blueprint, jsonify, render_template, request, send_file

from core.auth import get_current_user, permission_required, role_required
from core.database import get_db

from . import service

if TYPE_CHECKING:
    from core.engine_base import BaseEngine


def _filters() -> dict[str, Any]:
    args = request.args
    return service.normalize_filters(get_db(), args.get("month"), args.get("as_of"), args.get("groups"))


def build_blueprint(_engine: "BaseEngine") -> Blueprint:
    bp = Blueprint("incentive", __name__, template_folder="templates", static_folder="static")

    @bp.route("/")
    @permission_required("knitting", "incentive", "view")
    def view() -> Any:
        return render_template("knitting_incentive_view.html")

    @bp.route("/api/options")
    @permission_required("knitting", "incentive", "view")
    def api_options() -> Any:
        return jsonify(service.list_options(get_db()))

    @bp.route("/api/summary")
    @permission_required("knitting", "incentive", "view")
    def api_summary() -> Any:
        try:
            return jsonify(service.build_report(get_db(), _filters()))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @bp.route("/api/day")
    @permission_required("knitting", "incentive", "view")
    def api_day() -> Any:
        try:
            return jsonify(service.get_day_details(get_db(), _filters(), request.args.get("date", "")))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @bp.route("/api/export")
    @permission_required("knitting", "incentive", "view")
    def api_export() -> Any:
        try:
            filters = _filters()
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return send_file(
            io.BytesIO(service.export_excel(get_db(), filters)),
            as_attachment=True,
            download_name=f"knitting_incentive_{filters['from_date']}_{filters['to_date']}.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    @bp.route("/api/bands", methods=["POST"])
    @role_required("admin")
    def api_save_bands() -> Any:
        payload = request.get_json(silent=True) or {}
        user = get_current_user()
        try:
            service.save_bands(get_db(), payload.get("bands") or [], user["username"] if user else None)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"ok": True, "bands": service.load_bands(get_db())})

    return bp
