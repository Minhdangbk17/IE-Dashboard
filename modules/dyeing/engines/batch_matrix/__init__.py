from __future__ import annotations

from datetime import date
from typing import Any, Iterable

from flask import Blueprint

from core.engine_base import BaseEngine, EngineMetadata

from . import batch_day_trend, service
from .routes import build_blueprint


class BatchMatrixEngine(BaseEngine):
    name = "batch_matrix"
    domain = "dyeing"

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name=self.name,
            domain=self.domain,
            description=(
                "Batch/Day: Fabric Type x Color Group matrix (value = SUM(batches)/SUM(operating "
                "hours for that cell's machines)/24), plus a Batch/Day Trend tab "
                "(normal dyeing batches * 24 / total occupied hours, from batch_details only)."
            ),
            data_sources=["availability_logs", "batch_details", "machines", "brand_program_mapping", "batch_manual_overrides"],
            data_sinks=["batch_matrix_targets", "batch_shade_overrides", "batch_matrix_daily_summary", "batch_day_trend_daily_summary"],
            depends_on=["excel_import", "reports"],
        )

    def create_blueprint(self) -> Blueprint:
        return build_blueprint(self)

    def recompute_daily(self, production_date: date, conn: Any) -> None:
        service.recompute_daily(production_date, conn)
        batch_day_trend.recompute_daily(production_date, conn)

    def recompute_all(self, dates: Iterable[date], conn: Any) -> None:
        dates = list(dates)
        for production_date in sorted(dates):
            service.recompute_daily(production_date, conn)
        batch_day_trend.recompute_all(dates, conn)


engine = BatchMatrixEngine()
