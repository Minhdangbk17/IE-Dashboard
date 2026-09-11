"""
modules/dyeing/engines/oee/__init__.py
-----------------------------------------
Điểm vào của Engine "oee". Expose biến module-level `engine` — theo convention
mà Auto-loader của Domain (`modules/dyeing/__init__.py`) yêu cầu.
"""
from __future__ import annotations

from flask import Blueprint

from core.engine_base import BaseEngine, EngineMetadata

from .routes import build_blueprint


class OeeEngine(BaseEngine):
    name = "oee"
    domain = "dyeing"

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name=self.name,
            domain=self.domain,
            description="Calculates OEE (Availability x Performance x Quality) from machine_telemetry data.",
            data_sources=["machine_telemetry"],
            data_sinks=[],
            depends_on=["excel_import"],
        )

    def create_blueprint(self) -> Blueprint:
        return build_blueprint(self)


engine = OeeEngine()
