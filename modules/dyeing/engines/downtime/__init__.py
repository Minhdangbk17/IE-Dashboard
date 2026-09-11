"""
modules/dyeing/engines/downtime/__init__.py
----------------------------------------------
Điểm vào của Engine "downtime". Expose biến module-level `engine`.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from flask import Blueprint

from core.engine_base import BaseEngine, EngineMetadata

from . import service
from .routes import build_blueprint


class DowntimeEngine(BaseEngine):
    name = "downtime"
    domain = "dyeing"

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name=self.name,
            domain=self.domain,
            description="Downtime rate analysis by reason group from Availability data.",
            data_sources=["availability_logs"],
            data_sinks=["downtime_daily_summary"],
            depends_on=["excel_import"],
        )

    def create_blueprint(self) -> Blueprint:
        return build_blueprint(self)

    def recompute_daily(self, production_date: date, conn: Any) -> None:
        service.recompute_daily(production_date, conn)


engine = DowntimeEngine()
