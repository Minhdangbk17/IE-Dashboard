"""
core/navigation.py
-------------------
Menu Registry: nơi tập trung khai báo toàn bộ mục điều hướng (Sidebar) của
ứng dụng. Mỗi Domain module (dyeing, knitting, ...) tự đăng ký menu của mình
vào registry này (thông qua `register_menu`) khi được auto-load bởi `app.py`.

`inject_nav_menu` được đăng ký làm `app.context_processor`, tự động bơm biến
`NAV_MENU` (đã lọc theo role của user hiện tại) vào MỌI Jinja2 template mà
không cần mỗi view phải truyền tay.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from flask import Flask


@dataclass
class NavItem:
    """Một mục menu điều hướng (có thể là Domain cha hoặc Engine con)."""

    label: str
    endpoint: str  # tên endpoint Flask, vd: "dyeing.hub"
    icon: str = "gear"  # tên Octicon, vd: "graph", "clock", "upload"
    roles: tuple[str, ...] = ("admin", "operator")  # role nào thấy được mục này
    children: list["NavItem"] = field(default_factory=list)
    # domain/engine_name: CHỈ set cho mục con ứng với đúng 1 Engine (vd domain="dyeing",
    # engine_name="oee") — dùng để lọc thêm theo Permission Model (xem
    # `core/auth.py::has_permission()`) cho role='operator'. None = mục không gắn với
    # Engine nào (vd Domain cha, "Quản lý tài khoản") -> KHÔNG bị lọc theo quyền Engine,
    # chỉ lọc theo `roles` như trước.
    domain: str | None = None
    engine_name: str | None = None


class NavigationRegistry:
    """Registry đơn giản (singleton theo app) lưu danh sách NavItem cấp cao nhất."""

    def __init__(self) -> None:
        self._items: list[NavItem] = []

    def register(self, item: NavItem) -> None:
        self._items.append(item)

    def for_role(self, role: str | None) -> list[NavItem]:
        """Lọc menu theo role. Nếu role=None (chưa đăng nhập) -> menu rỗng."""
        if role is None:
            return []
        return [item for item in self._items if role in item.roles]

    @property
    def items(self) -> list[NavItem]:
        return list(self._items)


# Instance toàn cục — các Domain module import và gọi `nav_registry.register(...)`
nav_registry = NavigationRegistry()


def register_menu(
    label: str,
    endpoint: str,
    icon: str = "gear",
    roles: tuple[str, ...] = ("admin", "operator"),
    children: list[NavItem] | None = None,
) -> None:
    """Hàm tiện ích ngắn gọn để một Domain/Engine đăng ký mục menu của mình."""
    nav_registry.register(
        NavItem(label=label, endpoint=endpoint, icon=icon, roles=roles, children=children or [])
    )


def _filter_by_permission(items: list[NavItem], user_id: int) -> list[NavItem]:
    """Lọc thêm menu theo Permission Model (CHỈ áp dụng cho role='operator' — admin đã được
    `for_role()` cho qua nguyên vẹn, không gọi hàm này). Mục con gắn với 1 Engine cụ thể
    (`domain`+`engine_name` không None) chỉ giữ lại nếu `has_permission(..., "view")`==True.
    Mục cha (Domain hub) ẩn hẳn nếu KHÔNG còn Engine con nào hiển thị (tránh menu rỗng dẫn
    tới Hub trống). Mục không gắn Engine nào (domain/engine_name đều None, vd chính mục cha
    Domain, hoặc mục tương lai không phải Engine) đi qua nguyên vẹn — không đủ căn cứ để lọc."""
    from core.auth import has_permission

    filtered: list[NavItem] = []
    for item in items:
        if item.children:
            visible_children = [
                child
                for child in item.children
                if child.domain is None or child.engine_name is None
                or has_permission(user_id, child.domain, child.engine_name, "view")
            ]
            if visible_children:
                filtered.append(replace(item, children=visible_children))
            continue
        if item.domain is not None and item.engine_name is not None:
            if has_permission(user_id, item.domain, item.engine_name, "view"):
                filtered.append(item)
            continue
        filtered.append(item)
    return filtered


def init_app(app: Flask) -> None:
    """Đăng ký context_processor bơm NAV_MENU vào mọi template."""

    @app.context_processor
    def inject_nav_menu() -> dict[str, Any]:
        from core.auth import current_user_can, get_current_user

        user = get_current_user()
        role = user["role"] if user else None
        items = nav_registry.for_role(role)
        if role == "operator" and user:
            items = _filter_by_permission(items, user["id"])
        return {
            "NAV_MENU": items,
            "CURRENT_USER": user,
            "current_user_can": current_user_can,
        }
