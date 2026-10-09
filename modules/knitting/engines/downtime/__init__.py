"""
modules/knitting/engines/downtime/__init__.py
------------------------------------------------
Điểm vào Engine "downtime" của Domain "knitting" — báo cáo % Downtime / Standard Achievement
(cùng bố cục Dyeing Downtime). Chỉ ĐỌC bảng do Engine `excel_import` ghi (import trên Hub);
ghi riêng mapping mã dừng + Target. Không có rollup (dữ liệu nguồn đã gộp theo ngày).
"""
from __future__ import annotations

from flask import Blueprint

from core.engine_base import BaseEngine, EngineMetadata

from .routes import build_blueprint


class KnittingDowntimeEngine(BaseEngine):
    name = "downtime"
    domain = "knitting"

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name=self.name,
            domain=self.domain,
            description=(
                "Knitting Downtime: % downtime by 13 stop categories (stop time / Plan PRD = Available) per "
                "day/week/month vs Before/Target, Standard Achievement (% machine-days within target), "
                "daily drill-down, Program / Core program filter and Excel export."
            ),
            data_sources=[
                "knitting_machine_daily", "knitting_stop_details", "knitting_piece_rolls",
                "knitting_greige_programs", "knitting_core_programs",
            ],
            data_sinks=["knitting_stop_category_map", "knitting_downtime_targets"],
            depends_on=["excel_import"],
        )

    def create_blueprint(self) -> Blueprint:
        return build_blueprint(self)


engine = KnittingDowntimeEngine()
