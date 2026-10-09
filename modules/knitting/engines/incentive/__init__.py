"""
modules/knitting/engines/incentive/__init__.py
-------------------------------------------------
Điểm vào Engine "incentive" của Domain "knitting" — báo cáo thưởng theo %Achieve tháng cộng dồn
(Σ KNT N.W × Std.PTM / Σ Available) cho cả xưởng và từng Machine Group. Chỉ ĐỌC
`knitting_piece_rolls` (Engine `excel_import` ghi); ghi riêng bảng bậc đơn giá.
"""
from __future__ import annotations

from flask import Blueprint

from core.engine_base import BaseEngine, EngineMetadata

from .routes import build_blueprint


class KnittingIncentiveEngine(BaseEngine):
    name = "incentive"
    domain = "knitting"

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name=self.name,
            domain=self.domain,
            description=(
                "Knitting Incentive: month-to-date %Achieve = Σ(KNT N.W × Std.PTM) / Σ Available per workshop and "
                "machine group, mapped to VND/kg bands × KNT N.W; daily trend, machine breakdown, Excel export."
            ),
            data_sources=["knitting_piece_rolls"],
            data_sinks=["knitting_incentive_bands"],
            depends_on=["excel_import"],
        )

    def create_blueprint(self) -> Blueprint:
        return build_blueprint(self)


engine = KnittingIncentiveEngine()
