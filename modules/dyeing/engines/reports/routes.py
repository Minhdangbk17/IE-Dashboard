from __future__ import annotations

import io
from datetime import datetime
from typing import TYPE_CHECKING, Any

from flask import Blueprint, current_app, jsonify, render_template, request, send_file
from core.auth import get_current_user, permission_required
from core.batch_importer import sync_batch_details
from core.database import DatabaseError
from .cleaning_matrix import export_batch_summary_excel, export_cleaning_matrix_excel, get_batch_summary, get_cleaning_matrix, list_machine_configs, upsert_machine_config

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
        require_redye_zero = request.args.get("require_redye_zero", "1") != "0"
        try:
            return jsonify(get_cleaning_matrix(request.args.get("from_date"), request.args.get("to_date"), capacities or None, brand_programs or None, fabric_types or None, require_redye_zero))
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
        require_redye_zero = request.args.get("require_redye_zero", "1") != "0"
        from_date = request.args.get("from_date")
        to_date = request.args.get("to_date")
        content = export_cleaning_matrix_excel(from_date, to_date, capacities or None, brand_programs or None, fabric_types or None, require_redye_zero)
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
        require_redye_zero = request.args.get("require_redye_zero", "1") != "0"
        return jsonify(get_batch_summary(year, require_redye_zero=require_redye_zero))

    @bp.route("/api/batch-summary/export")
    @permission_required("dyeing", "reports", "view")
    def api_batch_summary_export() -> Any:
        try:
            year = int(request.args.get("year") or datetime.now().year)
        except ValueError:
            year = datetime.now().year
        require_redye_zero = request.args.get("require_redye_zero", "1") != "0"
        content = export_batch_summary_excel(year, require_redye_zero=require_redye_zero)
        return send_file(
            io.BytesIO(content),
            as_attachment=True,
            download_name=f"batch_summary_{year}.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

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
