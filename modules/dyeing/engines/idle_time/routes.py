"""
modules/dyeing/engines/idle_time/routes.py
---------------------------------------------
Blueprint & Route (API + View) của Engine "idle_time".

- `GET  /dyeing/idle_time/`                 -> View báo cáo Idle Time.
- `GET  /dyeing/idle_time/api/matrix?from_date=&to_date=&tank_type=...&capacity=...`
  -> API JSON ma trận máy x ngày (giờ hoạt động/idle/% Idle + Target).
- `GET  /dyeing/idle_time/api/gaps?machine=&date=` -> khoảng idle của 1 ô + note.
- `POST /dyeing/idle_time/api/notes`         -> lưu/xoá Reason/Detail của 1 khoảng idle.
- `POST /dyeing/idle_time/api/target`        -> đặt Target % Idle chung.
- `GET  /dyeing/idle_time/api/export?...&mode=idle|operating` -> file Excel theo filter đang chọn.
"""
from __future__ import annotations

import io
from datetime import datetime
from typing import TYPE_CHECKING, Any

from flask import Blueprint, jsonify, render_template, request, send_file

from core.auth import get_current_user, permission_required

from . import service

if TYPE_CHECKING:
    from core.engine_base import BaseEngine


def _filters() -> dict[str, Any]:
    return {
        "from_date": request.args.get("from_date") or None,
        "to_date": request.args.get("to_date") or None,
        "tank_types": [value for value in request.args.getlist("tank_type") if value] or None,
        "capacities": [value for value in request.args.getlist("capacity") if value] or None,
    }


def build_blueprint(_engine: "BaseEngine") -> Blueprint:
    bp = Blueprint("idle_time", __name__, template_folder="templates")

    @bp.route("/")
    @permission_required("dyeing", "idle_time", "view")
    def view() -> Any:
        return render_template("idle_time_view.html")

    @bp.route("/api/matrix")
    @permission_required("dyeing", "idle_time", "view")
    def api_matrix() -> Any:
        return jsonify(service.get_idle_matrix(**_filters()))

    @bp.route("/api/gaps")
    @permission_required("dyeing", "idle_time", "view")
    def api_gaps() -> Any:
        machine = (request.args.get("machine") or "").strip()
        production_date = (request.args.get("date") or "").strip()
        if not machine or not production_date:
            return jsonify({"error": "Missing machine/date."}), 400
        return jsonify(service.get_idle_gaps(machine, production_date))

    @bp.route("/api/notes", methods=["POST"])
    @permission_required("dyeing", "idle_time", "edit")
    def api_upsert_note() -> Any:
        payload = request.get_json(silent=True) or {}
        machine = str(payload.get("machine") or "").strip()
        production_date = str(payload.get("production_date") or "").strip()
        gap_start = str(payload.get("gap_start") or "").strip()
        if not machine or not production_date or not gap_start:
            return jsonify({"error": "Missing machine/production_date/gap_start."}), 400
        reason = str(payload.get("reason") or "").strip() or None
        detail = str(payload.get("detail") or "").strip() or None
        try:
            result = service.upsert_idle_note(machine, production_date, gap_start, reason, detail, get_current_user()["id"])
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"status": "success", **result})

    @bp.route("/api/target", methods=["POST"])
    @permission_required("dyeing", "idle_time", "edit")
    def api_set_target() -> Any:
        payload = request.get_json(silent=True) or {}
        try:
            target = float(payload.get("target_idle_pct"))
        except (TypeError, ValueError):
            return jsonify({"error": "target_idle_pct must be a number."}), 400
        try:
            return jsonify({"status": "success", **service.set_target(target)})
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @bp.route("/api/export")
    @permission_required("dyeing", "idle_time", "view")
    def api_export() -> Any:
        filters = _filters()
        mode = "operating" if request.args.get("mode") == "operating" else "idle"
        content = service.export_idle_excel(**filters, mode=mode)
        name_range = f"{filters['from_date']}_to_{filters['to_date']}" if filters["from_date"] and filters["to_date"] else datetime.now().strftime("%Y-%m-%d")
        return send_file(
            io.BytesIO(content),
            as_attachment=True,
            download_name=f"idle_time_{name_range}.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    return bp
