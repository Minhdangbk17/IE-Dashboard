"""
modules/dyeing/engines/batch_matrix/routes.py
--------------------------------------------------
Blueprint & Route (API + View) của Engine "batch_matrix".

- `GET /dyeing/batch_matrix/`               -> View trang Ma trận Số mẻ/Máy theo Ngày.
- `GET /dyeing/batch_matrix/api/matrix?date_from=&date_to=&capacity=...&capacity=...`
  -> API JSON dựng ma trận (dùng bởi View + widget tóm tắt trên Hub). `date_from`/
  `date_to` tuỳ chọn — không truyền thì cột ngày tự lấy MIN..MAX production_date thật
  có trong `availability_logs`.
- `GET  /dyeing/batch_matrix/api/targets`   -> API JSON danh sách Target đã cấu hình.
- `POST /dyeing/batch_matrix/api/targets`   -> Set/update 1 Target (fabric_type, color_group).
- `GET  /dyeing/batch_matrix/api/day-batches?date=&fabric_type=&color_group=&capacity=...`
  -> API JSON danh sách mẻ THẬT của 1 ô ma trận (drill-down double-check, bấm vào ô ngày trên UI).
- `GET  /dyeing/batch_matrix/api/batch-day-trend?capacities=&fabric_types=&from_date=&to_date=&group_by=`
  -> API JSON tab "Batch/Day Trend" — xem `batch_day_trend.py` cho công thức đầy đủ.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from flask import Blueprint, jsonify, render_template, request

from core.auth import permission_required

from . import service
from .batch_day_trend import get_batch_day_trend

if TYPE_CHECKING:
    from core.engine_base import BaseEngine


def build_blueprint(_engine: "BaseEngine") -> Blueprint:
    bp = Blueprint("batch_matrix", __name__, template_folder="templates")

    @bp.route("/")
    @permission_required("dyeing", "batch_matrix", "view")
    def view() -> Any:
        return render_template("batch_matrix_view.html")

    @bp.route("/api/matrix")
    @permission_required("dyeing", "batch_matrix", "view")
    def api_matrix() -> Any:
        date_from = request.args.get("date_from") or None
        date_to = request.args.get("date_to") or None
        capacities = request.args.getlist("capacity") or None
        fabric_types = request.args.get("fabric_types") or None
        brand_programs = request.args.get("brand_programs") or None
        data = service.build_matrix(date_from, date_to, capacities, fabric_types=fabric_types, brand_programs=brand_programs)
        return jsonify(data)

    @bp.route("/api/day-batches")
    @permission_required("dyeing", "batch_matrix", "view")
    def api_day_batches() -> Any:
        production_date = request.args.get("date") or ""
        fabric_type = request.args.get("fabric_type") or ""
        color_group = request.args.get("color_group") or ""
        if not production_date or not fabric_type or not color_group:
            return jsonify({"error": "Missing date/fabric_type/color_group."}), 400
        capacities = request.args.getlist("capacity") or None
        brand_programs = request.args.get("brand_programs") or None
        return jsonify(service.get_day_batches(production_date, fabric_type, color_group, capacities, brand_programs=brand_programs))

    @bp.route("/api/batch-day-trend")
    @permission_required("dyeing", "batch_matrix", "view")
    def api_batch_day_trend() -> Any:
        data = get_batch_day_trend(
            capacities=request.args.get("capacities") or None,
            fabric_types=request.args.get("fabric_types") or None,
            brand_programs=request.args.get("brand_programs") or None,
            from_date=request.args.get("from_date") or None,
            to_date=request.args.get("to_date") or None,
            group_by=request.args.get("group_by", "date"),
        )
        return jsonify(data)

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
