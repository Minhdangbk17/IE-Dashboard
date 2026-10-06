"""
modules/dyeing/engines/batch_matrix/routes.py
--------------------------------------------------
Blueprint & Route (API + View) của Engine "batch_matrix".

- `GET /dyeing/batch_matrix/`               -> View trang Ma trận Số mẻ/Máy theo Ngày.
- `GET /dyeing/batch_matrix/api/matrix?<filter Trend>` -> API JSON dựng ma trận Fabric/Color.
  Bộ lọc GIỐNG HỆT tab Trend: from_date, to_date, capacities, brand_programs, tank_types,
  group_by, require_redye_zero (2026-10-06).
- `GET /dyeing/batch_matrix/api/matrix/batches?fabric_type=&color_group=&period_key=&<filter>`
  -> danh sách mẻ của 1 ô ma trận (`period_key` rỗng = ô Total).
- `GET /dyeing/batch_matrix/api/matrix/export?<filter>` -> .xlsx (Matrix + Batches + Filters).
- `GET  /dyeing/batch_matrix/api/targets`   -> API JSON danh sách Target đã cấu hình.
- `POST /dyeing/batch_matrix/api/targets`   -> Set/update 1 Target (fabric_type, color_group).
- `GET  /dyeing/batch_matrix/api/batch-day-trend?capacities=&brand_programs=&tank_types=&require_redye_zero=1&from_date=&to_date=&group_by=`
  -> API JSON tab "Batch/Day Trend" (LUÔN 3 dòng Cotton/CVC/Polyester cố định — xem
  `batch_day_trend.py` cho công thức đầy đủ).
- `GET  /dyeing/batch_matrix/api/batch-day-trend/batches?fabric_type=&period_key=&<filter Trend>`
  -> API JSON danh sách đoạn (mẻ x ngày) của 1 ô Trend (`period_key` rỗng = ô Total).
- `GET  /dyeing/batch_matrix/api/batch-day-trend/export?<filter Trend>[&fabric_type=&period_key=]`
  -> File .xlsx: không có `fabric_type` = cả báo cáo (Trend + Batches), có = danh sách mẻ 1 ô.
- `POST /dyeing/batch_matrix/api/batch-day-trend/targets/<fabric_type>` -> Set/update
  Target (giờ/kỳ) của 1 trong 3 loại vải chính cho báo cáo Batch/Day Trend.
"""
from __future__ import annotations

import io
from datetime import datetime
from typing import TYPE_CHECKING, Any

from flask import Blueprint, jsonify, render_template, request, send_file

from core.auth import permission_required

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
        """Bộ lọc tab Matrix — CÙNG tên tham số với tab Trend (xem `_trend_filters()`)."""
        return {
            "date_from": request.args.get("from_date") or None,
            "date_to": request.args.get("to_date") or None,
            "capacities": request.args.get("capacities") or None,
            "brand_programs": request.args.get("brand_programs") or None,
            "tank_types": request.args.get("tank_types") or None,
            "group_by": request.args.get("group_by", "date"),
            "require_redye_zero": request.args.get("require_redye_zero", "1") != "0",
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
        """Bộ lọc tab Trend — dùng CHUNG cho bảng, drill-down và Export để luôn khớp nhau."""
        return {
            "capacities": request.args.get("capacities") or None,
            "brand_programs": request.args.get("brand_programs") or None,
            "tank_types": request.args.get("tank_types") or None,
            "from_date": request.args.get("from_date") or None,
            "to_date": request.args.get("to_date") or None,
            "group_by": request.args.get("group_by", "date"),
            "require_redye_zero": request.args.get("require_redye_zero", "1") != "0",
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
        try:
            target_value = float(payload.get("target_value"))
        except (TypeError, ValueError):
            return jsonify({"error": "target_value must be a number."}), 400
        service.set_target(fabric_type, color_group, target_value)
        return jsonify({"status": "success"})

    return bp
