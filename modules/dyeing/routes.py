"""
modules/dyeing/routes.py
-------------------------
Định nghĩa Blueprint gốc của Domain "dyeing" (Nhuộm) và route cho Trang Hub
Tổng quan (`dyeing_hub.html`).

Blueprint `dyeing_bp` được tạo Ở ĐÂY (không phải trong `__init__.py`) để tránh
import vòng (circular import): `__init__.py` cần import `dyeing_bp` để gắn
các Engine con vào trước khi đăng ký vào Flask app.
"""
from __future__ import annotations

from typing import Any

from flask import Blueprint, render_template

from core.auth import login_required
from core.engine_base import BaseEngine

dyeing_bp = Blueprint(
    "dyeing",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/static",
)


def register_hub_routes(blueprint: Blueprint, engines_loaded: list[BaseEngine]) -> None:
    """
    Gắn route "/" (Hub Aggregator) vào `blueprint`.

    Được gọi từ `modules/dyeing/__init__.py` SAU KHI toàn bộ Engine con đã
    được Auto-loader nạp xong, để trang Hub biết chính xác những Engine nào
    đang khả dụng (hiển thị widget tương ứng) mà không cần hardcode tên Engine.
    """

    @blueprint.route("/")
    @login_required
    def hub() -> Any:
        # Loại "excel_import" khỏi danh sách widget hiển thị — nó chỉ phục vụ
        # Modal Import, không phải một widget dữ liệu độc lập.
        display_engines = [e for e in engines_loaded if e.name != "excel_import"]
        engine_info = [
            {
                "name": e.name,
                "endpoint": f"dyeing.{e.name}.view",
                "description": e.metadata.description,
            }
            for e in display_engines
        ]
        has_excel_import = any(e.name == "excel_import" for e in engines_loaded)
        return render_template("dyeing_hub.html", engines=engine_info, has_excel_import=has_excel_import)
