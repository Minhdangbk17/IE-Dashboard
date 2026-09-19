"""Blueprint và API cho báo cáo DCA Cost.

- `GET /dyeing/dca_cost/api/summary?capacities=&brand_programs=&from_date=&to_date=&group_by=`
  -> API JSON (LUÔN 3 section Cotton/CVC/Polyester cố định, mỗi section 5 dòng màu — xem
  `service.py`). Chỉ đọc, không có route ghi (chưa có Target cho báo cáo này).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from flask import Blueprint, jsonify, render_template, request

from core.auth import permission_required

from . import service

if TYPE_CHECKING:
    from core.engine_base import BaseEngine


def build_blueprint(_engine: "BaseEngine") -> Blueprint:
    bp = Blueprint("dca_cost", __name__, template_folder="templates", static_folder="static")

    @bp.route("/")
    @permission_required("dyeing", "dca_cost", "view")
    def view() -> Any:
        return render_template("dca_cost_view.html")

    @bp.route("/api/summary")
    @permission_required("dyeing", "dca_cost", "view")
    def api_summary() -> Any:
        data = service.get_dca_cost_data(
            capacities=request.args.get("capacities") or None,
            brand_programs=request.args.get("brand_programs") or None,
            from_date=request.args.get("from_date") or None,
            to_date=request.args.get("to_date") or None,
            group_by=request.args.get("group_by", "date"),
        )
        return jsonify(data)

    return bp
