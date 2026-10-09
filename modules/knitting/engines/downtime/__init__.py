"""
modules/knitting/engines/downtime/__init__.py
------------------------------------------------
Điểm vào Engine "downtime" của Domain "knitting" — nạp file "CET-Stop Reason Analysis by
Machine" (CSV, 1 file = 1 production_date đọc từ tên file) và hiển thị số liệu dừng máy dệt.
Khung sườn: báo cáo nghiệp vụ chi tiết bổ sung sau. Không có rollup (dữ liệu nguồn đã gộp
theo ngày).
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
                "Knitting Downtime: imports the daily 'Stop Reason Analysis by Machine' CSV (production "
                "date from the file name) and reports machine run/stop time and stops by reason."
            ),
            data_sources=["stop_reason_analysis_csv"],
            data_sinks=["knitting_machine_daily", "knitting_stop_details", "import_logs", "import_log_rows"],
            depends_on=[],
        )

    def create_blueprint(self) -> Blueprint:
        return build_blueprint(self)


engine = KnittingDowntimeEngine()
