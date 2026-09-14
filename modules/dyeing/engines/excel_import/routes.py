"""
modules/dyeing/engines/excel_import/routes.py
--------------------------------------------------
Blueprint & Route (API only — không có View riêng, dùng qua Modal trên Hub).

- `GET  /dyeing/excel_import/api/template/<schema_key>` -> tải file Excel mẫu.
- `POST /dyeing/excel_import/api/preview`                -> xem trước 5 dòng + báo lỗi.
- `POST /dyeing/excel_import/api/import/<schema_key>`    -> import thật (bulk insert).
- `GET  /dyeing/excel_import/api/history`                -> lịch sử các lần import.
"""
from __future__ import annotations

import io
from typing import TYPE_CHECKING, Any

from flask import Blueprint, current_app, jsonify, request, send_file

from core.auth import get_current_user, permission_required
from core.database import DatabaseIntegrityError
from core.excel_importer import allowed_file, export_template, preview_file
from core.import_rows_service import list_import_rows, update_import_row, delete_import

from . import service

if TYPE_CHECKING:
    from core.engine_base import BaseEngine


def build_blueprint(_engine: "BaseEngine") -> Blueprint:
    bp = Blueprint("excel_import", __name__, static_folder="static")

    @bp.route("/api/import", methods=["POST"])
    @bp.route("/api/dyeing/import", methods=["POST"])
    @permission_required("dyeing", "excel_import", "edit")
    def import_raw() -> Any:
        uploaded = request.files.get("file")
        if not uploaded or not uploaded.filename:
            return jsonify({"status": "error", "errors": ["Please select a file."]}), 400
        if not allowed_file(uploaded.filename, current_app.config["ALLOWED_IMPORT_EXTENSIONS"]):
            return jsonify({"status": "error", "errors": ["Only .xlsx, .xls, and .csv are supported."]}), 400
        file_bytes = uploaded.read()
        try:
            requested_type = request.form.get("data_type", request.args.get("data_type", "auto"))
            if request.args.get("preview") == "1":
                return jsonify(service.preview_import_file(uploaded.filename, file_bytes, requested_type))
            user = get_current_user()
            result = service.import_selected_file(
                uploaded.filename,
                file_bytes,
                user["username"] if user else "unknown",
                requested_type,
            )
            return jsonify(result), 200
        except (ValueError, OSError, *DatabaseIntegrityError) as exc:
            return jsonify({"status": "error", "errors": [str(exc)]}), 400

    @bp.route("/api/template/<schema_key>")
    @permission_required("dyeing", "excel_import", "view")
    def download_template(schema_key: str) -> Any:
        try:
            schema = service.get_schema(schema_key)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 404

        content = export_template(schema, sample_rows=service.SAMPLE_ROWS.get(schema_key))
        return send_file(
            io.BytesIO(content),
            as_attachment=True,
            download_name=f"{schema_key}_template.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    @bp.route("/api/preview", methods=["POST"])
    @permission_required("dyeing", "excel_import", "view")
    def preview() -> Any:
        schema_key = request.form.get("schema_key", "")
        uploaded = request.files.get("file")

        if not uploaded or not uploaded.filename:
            return jsonify({"error": "Please select a file to preview."}), 400

        allowed_ext = current_app.config["ALLOWED_IMPORT_EXTENSIONS"]
        if not allowed_file(uploaded.filename, allowed_ext):
            return jsonify({"error": f"Unsupported file format (allowed: {', '.join(allowed_ext)})."}), 400

        try:
            schema = service.get_schema(schema_key)
            result = preview_file(uploaded.filename, uploaded.read(), schema)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        return jsonify(result)

    @bp.route("/api/import/<schema_key>", methods=["POST"])
    @permission_required("dyeing", "excel_import", "edit")
    def do_import(schema_key: str) -> Any:
        uploaded = request.files.get("file")
        if not uploaded or not uploaded.filename:
            return jsonify({"error": "Please select a file to import."}), 400

        allowed_ext = current_app.config["ALLOWED_IMPORT_EXTENSIONS"]
        if not allowed_file(uploaded.filename, allowed_ext):
            return jsonify({"error": f"Unsupported file format (allowed: {', '.join(allowed_ext)})."}), 400

        user = get_current_user()
        strict_mode = request.args.get("strict", default="0") == "1" or bool(
            current_app.config.get("IMPORT_STRICT_MODE")
        )

        try:
            result = service.do_import(
                schema_key=schema_key,
                filename=uploaded.filename,
                file_bytes=uploaded.read(),
                imported_by=user["username"] if user else "unknown",
                strict_mode=strict_mode,
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        status_code = 200 if result.committed else 422
        return jsonify(result.to_dict()), status_code

    @bp.route("/api/export")
    @permission_required("dyeing", "excel_import", "view")
    def export_data() -> Any:
        data_type = request.args.get("data_type", "")
        from_date = request.args.get("from_date") or None
        to_date = request.args.get("to_date") or None
        try:
            content, filename = service.export_data(data_type, from_date, to_date)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return send_file(
            io.BytesIO(content),
            as_attachment=True,
            download_name=filename,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    @bp.route("/api/history")
    @permission_required("dyeing", "excel_import", "view")
    def history() -> Any:
        limit = request.args.get("limit", default=20, type=int)
        return jsonify(service.get_history(limit=limit))

    @bp.route("/api/import-logs/<int:log_id>/rows")
    @permission_required("dyeing", "excel_import", "view")
    def get_import_rows(log_id: int) -> Any:
        try:
            return jsonify(list_import_rows(log_id))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 404

    @bp.route("/api/import-logs/<int:log_id>/rows/<int:row_id>", methods=["PATCH"])
    @permission_required("dyeing", "excel_import", "edit")
    def patch_import_row(log_id: int, row_id: int) -> Any:
        payload = request.get_json(silent=True) or {}
        edited_data = payload.get("data")
        if not isinstance(edited_data, dict):
            return jsonify({"error": "Missing 'data' (object) in request body."}), 400
        try:
            result = update_import_row(log_id, row_id, edited_data)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        status_code = 200 if result["status"] == "valid" else 422
        return jsonify(result), status_code

    @bp.route("/api/import-logs/<int:log_id>", methods=["DELETE"])
    @permission_required("dyeing", "excel_import", "delete")
    def delete_import_log(log_id: int) -> Any:
        try:
            return jsonify(delete_import(log_id))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 404

    return bp
