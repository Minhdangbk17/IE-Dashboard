from __future__ import annotations

from typing import TYPE_CHECKING, Any

from flask import Blueprint, current_app, jsonify, render_template, request
from core.auth import get_current_user, permission_required
from core.batch_importer import sync_batch_details
from core.database import DatabaseError
from .cleaning_matrix import get_cleaning_matrix

if TYPE_CHECKING:
    from core.engine_base import BaseEngine


def build_blueprint(_engine: "BaseEngine") -> Blueprint:
    bp = Blueprint("reports", __name__, template_folder="templates")

    @bp.route("/cleaning-matrix", endpoint="view")
    @permission_required("dyeing", "reports", "view")
    def cleaning_matrix() -> Any:
        return render_template("cleaning_matrix_view.html")

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
        try:
            return jsonify(get_cleaning_matrix(request.args.get("from_date"), request.args.get("to_date"), capacities or None, brand_programs or None))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

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
