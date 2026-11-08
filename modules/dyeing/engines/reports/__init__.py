from __future__ import annotations

from datetime import date
from typing import Any, Iterable

from flask import Blueprint

from core.engine_base import BaseEngine, EngineMetadata
from . import cleaning_matrix
from .routes import build_blueprint


class ReportsEngine(BaseEngine):
    name = "reports"
    domain = "dyeing"

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name=self.name,
            domain=self.domain,
            description="Dyeing schedule and machine cleaning ratio report.",
            data_sources=["batch_details", "brand_program_mapping", "machines", "batch_manual_overrides"],
            data_sinks=["cleaning_mc_daily_summary", "machines", "batch_manual_overrides"],
            depends_on=["excel_import"],
        )

    def create_blueprint(self) -> Blueprint:
        return build_blueprint(self)

    def recompute_daily(self, production_date: date, conn: Any) -> None:
        cleaning_matrix.recompute_daily(production_date, conn)

    def recompute_all(self, dates: Iterable[date], conn: Any) -> None:
        cleaning_matrix.recompute_all(dates, conn)


engine = ReportsEngine()
