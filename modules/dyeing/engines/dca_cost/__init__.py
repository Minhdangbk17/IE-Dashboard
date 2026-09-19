"""
modules/dyeing/engines/dca_cost/__init__.py
--------------------------------------------
Điểm vào của Engine "dca_cost" (DCA Cost). Expose biến module-level `engine`.

Báo cáo DCA Cost = Sum(DyeCost) / Sum(số dyelot) theo Day/Week/Month, phân theo 3 loại vải
chính (Cotton/CVC/Polyester) x 5 nhóm màu (Dark/Light/Medium/Black/White). Nguồn dữ liệu
`batch_details` (đã có sẵn qua Import Batch Detail — Engine này KHÔNG cần luồng import mới).
"""
from __future__ import annotations

from flask import Blueprint

from core.engine_base import BaseEngine, EngineMetadata

from .routes import build_blueprint


class DcaCostEngine(BaseEngine):
    name = "dca_cost"
    domain = "dyeing"

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name=self.name,
            domain=self.domain,
            description="DCA Cost report: Sum(DyeCost) / Sum(dyelot count) from Batch Detail data, by Fabric Type x Color, Day/Week/Month.",
            data_sources=["batch_details", "availability_logs", "brand_program_mapping"],
            data_sinks=[],
            depends_on=["excel_import"],
        )

    def create_blueprint(self) -> Blueprint:
        return build_blueprint(self)


engine = DcaCostEngine()
