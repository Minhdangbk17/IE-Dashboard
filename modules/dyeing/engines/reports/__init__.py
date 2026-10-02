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
            # 2026-10-02: Batch Per Day by Machine đọc DUY NHẤT batch_details (core/batch_source.py),
            # không còn availability_logs.
            data_sources=["batch_details", "brand_program_mapping", "machines"],
            data_sinks=["cleaning_mc_daily_summary", "machines"],
            depends_on=["excel_import"],
        )

    def create_blueprint(self) -> Blueprint:
        return build_blueprint(self)

    def recompute_daily(self, production_date: date, conn: Any) -> None:
        cleaning_matrix.recompute_daily(production_date, conn)

    def recompute_all(self, dates: Iterable[date], conn: Any) -> None:
        """Đọc `batch_details` ĐÚNG 1 LẦN cho cả tập ngày (fill-down/fill-up phụ thuộc toàn bộ
        lịch sử) — kết quả giống hệt gọi `recompute_daily()` từng ngày, chỉ nhanh hơn."""
        cleaning_matrix.recompute_all(dates, conn)


engine = ReportsEngine()
