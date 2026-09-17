"""
modules/dyeing/engines/tank_loading/__init__.py
--------------------------------------------------
Điểm vào của Engine "tank_loading" (%Tank Loading). Expose biến module-level `engine`.

Báo cáo %Tank Loading = Sum(OutputKgH) / Sum(MaxOutputKgH) theo Day/Week/Month, nguồn
dữ liệu `performance_logs` (import qua Modal Import Data, loại "Performance") — Engine
đầu tiên đọc bảng này (trước đây `performance_logs` chỉ dùng cho Import/Raw Data Viewer,
xem `modules/dyeing/engines/excel_import/service.py`).
"""
from __future__ import annotations

from flask import Blueprint

from core.engine_base import BaseEngine, EngineMetadata

from .routes import build_blueprint


class TankLoadingEngine(BaseEngine):
    name = "tank_loading"
    domain = "dyeing"

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name=self.name,
            domain=self.domain,
            description="%Tank Loading report: Sum(OutputKgH) / Sum(MaxOutputKgH) from Performance data, by Day/Week/Month.",
            data_sources=["performance_logs"],
            data_sinks=[],
            depends_on=["excel_import"],
        )

    def create_blueprint(self) -> Blueprint:
        return build_blueprint(self)


engine = TankLoadingEngine()
