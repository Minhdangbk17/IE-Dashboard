"""
graphify/routes.py
-------------------
API & View hiển thị Graph Diagram (sơ đồ phụ thuộc Engine / Data Flow).

- `GET /graphify/`          -> View trang trực quan hóa (graph_view.html).
- `GET /graphify/api/graph` -> API JSON trả về Node/Edge cho Frontend tự vẽ SVG.
"""
from __future__ import annotations

from typing import Any

from flask import Blueprint, jsonify, render_template

from core.auth import role_required

from . import mapper

graphify_bp = Blueprint("graphify", __name__, template_folder="templates")


@graphify_bp.route("/")
@role_required("admin")
def graph_view() -> Any:
    return render_template("graph_view.html")


@graphify_bp.route("/api/graph")
@role_required("admin")
def api_graph() -> Any:
    graph = mapper.build_graph()
    return jsonify(graph.to_dict())
