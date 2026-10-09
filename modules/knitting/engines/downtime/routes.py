"""modules/knitting/engines/downtime/routes.py — View + API báo cáo Downtime xưởng Dệt (import nằm ở
Engine `excel_import`, gọi từ Modal trên Knitting Hub)."""
from __future__ import annotations

import io
from typing import TYPE_CHECKING, Any

from flask import Blueprint, jsonify, render_template, request, send_file

from core.auth import get_current_user, permission_required, role_required
from core.database import get_db

from . import report

if TYPE_CHECKING:
    from core.engine_base import BaseEngine

def _username() -> str | None:
    user = get_current_user()
    return user["username"] if user else None


def _filters_from_args() -> dict[str, Any]:
    args = request.args
    return report.normalize_filters(
        args.get("from_date"), args.get("to_date"), args.get("group_by"), args.get("machines"), args.get("structures"),
        args.get("programs"), args.get("core_only"),
    )


def build_blueprint(_engine: "BaseEngine") -> Blueprint:
    bp = Blueprint("downtime", __name__, template_folder="templates", static_folder="static")

    @bp.route("/")
    @permission_required("knitting", "downtime", "view")
    def view() -> Any:
        return render_template("knitting_downtime_view.html", categories=report.CATEGORIES)

    @bp.route("/api/filters")
    @permission_required("knitting", "downtime", "view")
    def api_filters() -> Any:
        return jsonify(report.list_filter_options(get_db()))

    @bp.route("/api/summary")
    @permission_required("knitting", "downtime", "view")
    def api_summary() -> Any:
        try:
            return jsonify(report.build_report(get_db(), _filters_from_args()))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @bp.route("/api/cell")
    @permission_required("knitting", "downtime", "view")
    def api_cell() -> Any:
        try:
            data = report.get_cell_details(get_db(), _filters_from_args(), request.args.get("period", ""), request.args.get("category", ""))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify(data)

    @bp.route("/api/export")
    @permission_required("knitting", "downtime", "view")
    def api_export() -> Any:
        try:
            filters = _filters_from_args()
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        content = report.export_excel(get_db(), filters)
        return send_file(
            io.BytesIO(content),
            as_attachment=True,
            download_name=f"knitting_downtime_{filters['from_date']}_{filters['to_date']}.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    @bp.route("/api/stop-codes")
    @permission_required("knitting", "downtime", "view")
    def api_stop_codes() -> Any:
        return jsonify({"stop_codes": report.list_stop_codes(get_db()), "categories": list(report.CATEGORIES)})

    @bp.route("/api/stop-codes", methods=["POST"])
    @role_required("admin")
    def api_set_stop_code() -> Any:
        payload = request.get_json(silent=True) or {}
        try:
            report.set_stop_category(get_db(), payload.get("stop_code", ""), payload.get("category"), _username())
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"ok": True})

    @bp.route("/api/targets", methods=["POST"])
    @role_required("admin")
    def api_set_target() -> Any:
        payload = request.get_json(silent=True) or {}

        def number(key: str) -> float | None:
            value = payload.get(key)
            return None if value in (None, "") else float(value)

        try:
            report.set_target(get_db(), payload.get("category", ""), number("before_pct"), number("target_pct"), _username())
        except (TypeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"ok": True})

    return bp
