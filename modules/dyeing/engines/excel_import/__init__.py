"""
modules/dyeing/engines/excel_import/__init__.py
----------------------------------------------------
Điểm vào của Engine "excel_import". Engine này KHÔNG có trang View riêng —
nó phục vụ Modal Import trên `dyeing_hub.html` thông qua các API route.
"""
from __future__ import annotations

from flask import Blueprint

from core.engine_base import BaseEngine, EngineMetadata

from .routes import build_blueprint


class ExcelImportEngine(BaseEngine):
    name = "excel_import"
    domain = "dyeing"

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name=self.name,
            domain=self.domain,
            description="Auto-detects and imports Availability/Performance data from Excel/CSV with transactional upsert.",
            data_sources=["File Excel (.xlsx/.csv) do người dùng tải lên"],
            data_sinks=["availability_logs", "performance_logs", "machine_telemetry", "downtime_logs", "import_logs", "brand_program_mapping"],
            depends_on=[],
        )

    def create_blueprint(self) -> Blueprint:
        return build_blueprint(self)


engine = ExcelImportEngine()
