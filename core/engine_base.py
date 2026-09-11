"""
core/engine_base.py
--------------------
Abstract Base Class cho "Engine" — đơn vị tính toán độc lập nhỏ nhất trong
kiến trúc Engine-Plugin (vd: `oee`, `downtime`, `excel_import`).

Mỗi Engine là một package Python nằm trong `modules/<domain>/engines/<engine_name>/`
và BẮT BUỘC expose một biến module-level tên `engine` là instance của một
subclass `BaseEngine`. Auto-loader (`modules/<domain>/__init__.py`) sẽ quét
(scan) các package con, import module, tìm biến `engine` và đăng ký
`engine.blueprint` vào Flask app — hoàn toàn không cần hardcode.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from flask import Blueprint


@dataclass
class EngineMetadata:
    """Thông tin mô tả của Engine — dùng cho Graphify để vẽ sơ đồ phụ thuộc."""

    name: str
    domain: str
    description: str = ""
    version: str = "0.1.0"
    # Danh sách nguồn dữ liệu đầu vào (vd: ["machine_telemetry"])
    data_sources: list[str] = field(default_factory=list)
    # Danh sách bảng/nguồn dữ liệu Engine này ghi ra (vd: ["oee_snapshots"])
    data_sinks: list[str] = field(default_factory=list)
    # Các engine khác mà engine này phụ thuộc dữ liệu vào (vd: excel_import -> oee)
    depends_on: list[str] = field(default_factory=list)


class BaseEngine(ABC):
    """
    Lớp cha trừu tượng cho mọi Engine.

    Mỗi Engine con phải implement:
      - `metadata` (property): thông tin mô tả engine.
      - `create_blueprint()`: xây dựng và trả về `flask.Blueprint` với các route.

    Thuộc tính `blueprint` được tính toán lười (lazy) và cache lại.
    """

    #: tên engine, vd "oee" — dùng làm url_prefix và blueprint name
    name: str = "base"
    #: tên domain cha, vd "dyeing" — được auto-loader gán khi phát hiện engine
    domain: str = "unknown"

    def __init__(self) -> None:
        self._blueprint: Blueprint | None = None

    @property
    @abstractmethod
    def metadata(self) -> EngineMetadata:
        """Trả về EngineMetadata mô tả engine (dùng bởi Graphify)."""
        raise NotImplementedError

    @abstractmethod
    def create_blueprint(self) -> Blueprint:
        """Xây dựng Blueprint chứa toàn bộ route (API + View) của Engine."""
        raise NotImplementedError

    def recompute_daily(self, production_date: date, conn: Any) -> None:
        """Daily Rollup Pattern (xem `memory-bank/systemPatterns.md`): tính lại bảng tổng
        hợp theo ngày (vd `downtime_daily_summary`) từ raw data cho đúng MỘT `production_date`.

        OPTIONAL — mặc định no-op, Engine nào không cần rollup thì không cần override.
        Implementation PHẢI idempotent: DELETE các dòng cũ của đúng `production_date` này
        trong bảng summary của Engine mình rồi INSERT lại từ raw data — an toàn khi gọi lại
        nhiều lần cho cùng 1 ngày (không tạo dòng trùng). KHÔNG tự `conn.commit()` — do
        `core/rollup.py::trigger_recompute()` gọi commit một lần cho cả batch xử lý.
        """
        return None

    @property
    def blueprint(self) -> Blueprint:
        if self._blueprint is None:
            self._blueprint = self.create_blueprint()
        return self._blueprint

    @property
    def full_name(self) -> str:
        """vd: 'dyeing.oee' — định danh duy nhất trong toàn hệ thống."""
        return f"{self.domain}.{self.name}"

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"<Engine {self.full_name}>"
