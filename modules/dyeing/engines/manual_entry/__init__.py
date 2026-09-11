from __future__ import annotations

from flask import Blueprint

from core.engine_base import BaseEngine, EngineMetadata
from .routes import build_blueprint


class ManualEntryEngine(BaseEngine):
    name = "manual_entry"
    domain = "dyeing"

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name=self.name,
            domain=self.domain,
            description="Manual Availability entry with planned/downtime hour calculation.",
            data_sources=["machines", "manual Availability form"],
            data_sinks=["availability_logs"],
            depends_on=[],
        )

    def create_blueprint(self) -> Blueprint:
        return build_blueprint(self)


engine = ManualEntryEngine()
