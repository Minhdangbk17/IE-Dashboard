"""
modules/dyeing/engines/idle_time/routes.py
---------------------------------------------
Blueprint & Route (API + View) của Engine "idle_time".

- `GET  /dyeing/idle_time/`                 -> View báo cáo Idle Time.
- `GET  /dyeing/idle_time/entry`            -> View Idle Entry (nhập tay lần dừng, dùng trên điện thoại).
- `GET  /dyeing/idle_time/api/matrix?from_date=&to_date=&tank_type=...&capacity=...`
  -> API JSON ma trận máy x ngày (giờ hoạt động/idle/% Idle + Target).
- `GET  /dyeing/idle_time/api/gaps?machine=&date=` -> khoảng idle của 1 ô, chia đoạn theo lần dừng.
- `POST /dyeing/idle_time/api/report-stops` -> Save trong drawer báo cáo (giờ = đúng đoạn idle).
- `GET  /dyeing/idle_time/api/stops?from_date=&to_date=&machine=` -> lần dừng + trạng thái ghép.
- `POST /dyeing/idle_time/api/stops`, `PUT|DELETE /dyeing/idle_time/api/stops/<id>` -> nhập/sửa/xoá.
- `GET  /dyeing/idle_time/api/machines`      -> danh sách máy (Machine Master) cho Idle Entry.
- `POST /dyeing/idle_time/api/target`        -> đặt Target % Idle chung — CHỈ admin.
- `GET  /dyeing/idle_time/api/export?...&mode=idle|operating` -> file Excel theo filter đang chọn.
"""
from __future__ import annotations

import io
from datetime import datetime
from typing import TYPE_CHECKING, Any

from flask import Blueprint, jsonify, render_template, request, send_file

from core.auth import get_current_user, permission_required, role_required

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


def _payload_text(payload: dict[str, Any], key: str) -> str | None:
    return str(payload.get(key) or "").strip() or None


def build_blueprint(_engine: "BaseEngine") -> Blueprint:
    bp = Blueprint("idle_time", __name__, template_folder="templates")

    @bp.route("/")
    @permission_required("dyeing", "idle_time", "view")
    def view() -> Any:
        return render_template("idle_time_view.html")

    @bp.route("/entry")
    @permission_required("dyeing", "idle_time", "view")
    def entry_view() -> Any:
        return render_template("idle_entry_view.html", reasons=service.IDLE_REASONS)

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

    @bp.route("/api/report-stops", methods=["POST"])
    @permission_required("dyeing", "idle_time", "edit")
    def api_save_from_report() -> Any:
        payload = request.get_json(silent=True) or {}
        machine, start, end = _payload_text(payload, "machine"), _payload_text(payload, "start"), _payload_text(payload, "end")
        if not machine or not start or not end:
            return jsonify({"error": "Missing machine/start/end."}), 400
        try:
            stop = service.save_from_report(machine, start, end, _payload_text(payload, "reason"), _payload_text(payload, "detail"), get_current_user()["id"])
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"status": "success", "stop": stop})

    @bp.route("/api/machines")
    @permission_required("dyeing", "idle_time", "view")
    def api_machines() -> Any:
        return jsonify(service.get_master_machines())

    @bp.route("/api/stops")
    @permission_required("dyeing", "idle_time", "view")
    def api_list_stops() -> Any:
        from_date, to_date = request.args.get("from_date") or "", request.args.get("to_date") or ""
        if not from_date or not to_date:
            return jsonify({"error": "Missing from_date/to_date."}), 400
        return jsonify(service.list_stops(from_date, to_date, request.args.get("machine") or None))

    @bp.route("/api/stops", methods=["POST"])
    @permission_required("dyeing", "idle_time", "edit")
    def api_create_stop() -> Any:
        payload = request.get_json(silent=True) or {}
        try:
            stop = service.create_stop(
                _payload_text(payload, "machine") or "", _payload_text(payload, "stop_start"), _payload_text(payload, "stop_end"),
                _payload_text(payload, "reason"), _payload_text(payload, "detail"), get_current_user()["id"],
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"status": "success", "stop": stop})

    @bp.route("/api/stops/<int:stop_id>", methods=["PUT"])
    @permission_required("dyeing", "idle_time", "edit")
    def api_update_stop(stop_id: int) -> Any:
        payload = request.get_json(silent=True) or {}
        try:
            stop = service.update_stop(
                stop_id, _payload_text(payload, "machine") or "", _payload_text(payload, "stop_start"), _payload_text(payload, "stop_end"),
                _payload_text(payload, "reason"), _payload_text(payload, "detail"), get_current_user()["id"],
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"status": "success", "stop": stop})

    @bp.route("/api/stops/<int:stop_id>", methods=["DELETE"])
    @permission_required("dyeing", "idle_time", "delete")
    def api_delete_stop(stop_id: int) -> Any:
        try:
            service.delete_stop(stop_id)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"status": "success"})

    @bp.route("/api/target", methods=["POST"])
    @role_required("admin")
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
