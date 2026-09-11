"""modules/knitting/engines/oee/__init__.py — Điểm vào Engine "oee" (stub) của Domain "knitting"."""
from __future__ import annotations

from flask import Blueprint

from core.engine_base import BaseEngine, EngineMetadata

from .routes import build_blueprint


class KnittingOeeEngine(BaseEngine):
    name = "oee"
    domain = "knitting"

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name=self.name,
            domain=self.domain,
            description="[Phase 2] OEE for Knitting — calculation logic not yet implemented.",
            data_sources=[],
            data_sinks=[],
            depends_on=[],
        )

    def create_blueprint(self) -> Blueprint:
        return build_blueprint(self)


engine = KnittingOeeEngine()
