"""
modules/knitting/engines/excel_import/__init__.py
----------------------------------------------------
Điểm vào Engine "excel_import" của Domain "knitting" — giống `dyeing.excel_import`: KHÔNG có trang
riêng (ẩn khỏi menu), chỉ phục vụ Modal Import trên Knitting Hub. Sở hữu tầng dữ liệu dùng chung
của xưởng Dệt (bảng `knitting_*`), các Engine báo cáo (VD `downtime`) chỉ đọc.
"""
from __future__ import annotations

from flask import Blueprint

from core.engine_base import BaseEngine, EngineMetadata

from .routes import build_blueprint


class KnittingExcelImportEngine(BaseEngine):
    name = "excel_import"
    domain = "knitting"

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name=self.name,
            domain=self.domain,
            description=(
                "Imports knitting files from the Hub modal (auto-detected): Stop Reason Analysis by Machine "
                "(daily, replaces the production day), Piece Produced report (rolls, upsert by Roll No) and "
                "Knitting program (Greige -> Program + Core list, replaces all)."
            ),
            data_sources=["File CSV/Excel do người dùng tải lên (Stop Reason, Piece Produced, Knitting program)"],
            data_sinks=[
                "knitting_machine_daily", "knitting_stop_details", "knitting_piece_rolls",
                "knitting_greige_programs", "knitting_core_programs", "import_logs", "import_log_rows",
            ],
            depends_on=[],
        )

    def create_blueprint(self) -> Blueprint:
        return build_blueprint(self)


engine = KnittingExcelImportEngine()
