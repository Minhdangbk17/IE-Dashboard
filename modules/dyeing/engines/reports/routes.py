from __future__ import annotations

import io
from datetime import datetime
from typing import TYPE_CHECKING, Any

from flask import Blueprint, current_app, jsonify, render_template, request, send_file
from core.auth import get_current_user, permission_required
from core.batch_importer import sync_batch_details
from core.database import DatabaseError
from core.rollup import trigger_recompute
from .cleaning_matrix import (
    delete_manual_override, export_batch_summary_excel, export_cleaning_matrix_excel, get_batch_summary, get_cleaning_matrix, get_data_quality,
    list_machine_configs, save_manual_override, upsert_machine_config,
)

if TYPE_CHECKING:
    from core.engine_base import BaseEngine


def build_blueprint(_engine: "BaseEngine") -> Blueprint:
    bp = Blueprint("reports", __name__, template_folder="templates")

    @bp.route("/cleaning-matrix", endpoint="view")
    @permission_required("dyeing", "reports", "view")
    def cleaning_matrix() -> Any:
        return render_template("cleaning_matrix_view.html")

    @bp.route("/machines", endpoint="machines_view")
    @permission_required("dyeing", "reports", "view")
    def machines_view() -> Any:
        return render_template("machine_master_view.html")

    @bp.route("/api/cleaning-matrix")
    @permission_required("dyeing", "reports", "view")
    def api_cleaning_matrix() -> Any:
        capacities: list[float] = []
        for raw_value in request.args.getlist("capacity"):
            try:
                capacities.append(float(raw_value))
            except ValueError:
                continue
        brand_programs = [value for value in request.args.getlist("brand_program") if value]
        fabric_types = [value for value in request.args.getlist("fabric_type") if value]
        tank_types = [value for value in request.args.getlist("tank_type") if value]
        try:
            return jsonify(get_cleaning_matrix(request.args.get("from_date"), request.args.get("to_date"), capacities or None, brand_programs or None, fabric_types or None, tank_types or None))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @bp.route("/api/cleaning-matrix/export")
    @permission_required("dyeing", "reports", "view")
    def api_cleaning_matrix_export() -> Any:
        capacities: list[float] = []
        for raw_value in request.args.getlist("capacity"):
            try:
                capacities.append(float(raw_value))
            except ValueError:
                continue
        brand_programs = [value for value in request.args.getlist("brand_program") if value]
        fabric_types = [value for value in request.args.getlist("fabric_type") if value]
        tank_types = [value for value in request.args.getlist("tank_type") if value]
        from_date = request.args.get("from_date")
        to_date = request.args.get("to_date")
        content = export_cleaning_matrix_excel(from_date, to_date, capacities or None, brand_programs or None, fabric_types or None, tank_types or None)
        name_range = f"{from_date}_to_{to_date}" if from_date and to_date else datetime.now().strftime("%Y-%m-%d")
        return send_file(
            io.BytesIO(content),
            as_attachment=True,
            download_name=f"batch_detail_{name_range}.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    @bp.route("/api/batch-summary")
    @permission_required("dyeing", "reports", "view")
    def api_batch_summary() -> Any:
        try:
            year = int(request.args.get("year") or datetime.now().year)
        except ValueError:
            year = datetime.now().year
        return jsonify(get_batch_summary(year))

    @bp.route("/api/batch-summary/export")
    @permission_required("dyeing", "reports", "view")
    def api_batch_summary_export() -> Any:
        try:
            year = int(request.args.get("year") or datetime.now().year)
        except ValueError:
            year = datetime.now().year
        content = export_batch_summary_excel(year)
        return send_file(
            io.BytesIO(content),
            as_attachment=True,
            download_name=f"batch_summary_{year}.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    @bp.route("/api/data-quality")
    @permission_required("dyeing", "reports", "view")
    def api_data_quality() -> Any:
        return jsonify(get_data_quality(request.args.get("from_date"), request.args.get("to_date")))

    @bp.route("/api/manual-overrides", methods=["POST"])
    @permission_required("dyeing", "reports", "edit")
    def api_save_manual_override() -> Any:
        payload = request.get_json(silent=True) or {}
        try:
            batch_id = int(payload.get("batch_id"))
        except (TypeError, ValueError):
            return jsonify({"status": "error", "error": "batch_id is required."}), 400
        try:
            affected = save_manual_override(batch_id, payload.get("batch_type"), payload.get("fabric_type"), payload.get("shade"), (get_current_user() or {}).get("username"))
            trigger_recompute(affected)
        except (ValueError, *DatabaseError) as exc:
            return jsonify({"status": "error", "error": str(exc)}), 400
        return jsonify({"status": "ok", "recomputed_days": len(affected)})

    @bp.route("/api/manual-overrides/<int:override_id>", methods=["DELETE"])
    @permission_required("dyeing", "reports", "delete")
    def api_delete_manual_override(override_id: int) -> Any:
        try:
            affected = delete_manual_override(override_id)
            trigger_recompute(affected)
        except (ValueError, *DatabaseError) as exc:
            return jsonify({"status": "error", "error": str(exc)}), 400
        return jsonify({"status": "ok", "recomputed_days": len(affected)})

    @bp.route("/api/machines")
    @permission_required("dyeing", "reports", "view")
    def api_list_machines() -> Any:
        return jsonify({"machines": list_machine_configs()})

    @bp.route("/api/machines/<machine_code>", methods=["POST"])
    @permission_required("dyeing", "reports", "edit")
    def api_update_machine(machine_code: str) -> Any:
        payload = request.get_json(silent=True) or {}
        try:
            updated = upsert_machine_config(machine_code, payload)
            return jsonify({"status": "ok", "machine": updated})
        except (ValueError, *DatabaseError) as exc:
            return jsonify({"status": "error", "error": str(exc)}), 400

    @bp.route("/api/dyeing/import-batch-detail", methods=["POST"])
    @permission_required("dyeing", "reports", "edit")
    def import_batch_detail() -> Any:
        uploaded = request.files.get("file")
        if not uploaded or not uploaded.filename.lower().endswith(".xlsx"):
            return jsonify({"status": "error", "errors": ["Please select a Batch .xlsx file."]}), 400
        try:
            result = sync_batch_details(uploaded.read(), (get_current_user() or {}).get("username"), uploaded.filename)
            return jsonify(result)
        except (ValueError, *DatabaseError) as exc:
            current_app.logger.exception("Batch detail import failed")
            return jsonify({"status": "error", "errors": [str(exc)]}), 400

    return bp
