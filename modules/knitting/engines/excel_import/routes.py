"""modules/knitting/engines/excel_import/routes.py — API import cho Modal trên Knitting Hub."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from flask import Blueprint, jsonify, request

from core.auth import get_current_user, permission_required
from core.database import DatabaseError, get_db

from . import service

if TYPE_CHECKING:
    from core.engine_base import BaseEngine

_ALLOWED_EXTENSIONS = (".csv", ".xlsx", ".xlsm")


def build_blueprint(_engine: "BaseEngine") -> Blueprint:
    bp = Blueprint("excel_import", __name__, static_folder="static")

    @bp.route("/api/import", methods=["POST"])
    @permission_required("knitting", "excel_import", "edit")
    def api_import() -> Any:
        upload = request.files.get("file")
        if upload is None or not upload.filename:
            return jsonify({"error": "Chưa chọn file."}), 400
        if not upload.filename.lower().endswith(_ALLOWED_EXTENSIONS):
            return jsonify({"error": "Chỉ nhận .csv (Stop Reason / Piece Produced) hoặc .xlsx (Knitting program)."}), 400
        user = get_current_user()
        try:
            # Dùng tên file GỐC (không secure_filename) — Production Date của Stop Reason nằm trong tên file.
            result = service.import_file(
                get_db(), upload.read(), upload.filename, request.form.get("data_type", "auto"), user["username"] if user else None
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except DatabaseError as exc:
            return jsonify({"error": f"Lỗi database: {exc}"}), 500
        return jsonify(result)

    @bp.route("/api/status")
    @permission_required("knitting", "excel_import", "view")
    def api_status() -> Any:
        conn = get_db()
        return jsonify({
            "days": service.list_imported_days(conn, limit=14),
            "sources": service.get_program_sources(conn),
            "imports": service.list_recent_imports(conn),
        })

    return bp
