"""
modules/dyeing/engines/batch_matrix/__init__.py
-----------------------------------------------------
Điểm vào của Engine "batch_matrix" — Ma trận Số mẻ/Máy theo Ngày (Fabric Type x
Color Group x Ngày sản xuất), dữ liệu từ `batch_details`.
"""
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
            data_sources=["availability_logs", "batch_details", "machines", "brand_program_mapping"],
            data_sinks=["batch_matrix_targets", "batch_matrix_daily_summary", "batch_day_trend_daily_summary"],
            # "reports": Trend + Matrix (từ 2026-10-06) dùng lại `classify_batch_badge()` (quy tắc Normal dyeing).
            depends_on=["excel_import", "reports"],
        )

    def create_blueprint(self) -> Blueprint:
        return build_blueprint(self)

    def recompute_daily(self, production_date: date, conn: Any) -> None:
        service.recompute_daily(production_date, conn)
        batch_day_trend.recompute_daily(production_date, conn)

    def recompute_all(self, dates: Iterable[date], conn: Any) -> None:
        """Override bản mặc định (lặp `recompute_daily()` từng ngày) vì
        `batch_day_trend.recompute_all()` có đường tính HÀNG LOẠT hiệu quả hơn nhiều cho
        Trend (đọc toàn bộ `batch_details` 1 lần để fill Machine/FabricType theo thứ tự — xem
        docstring đầu file `batch_day_trend.py`) —
        `service.recompute_daily()` (Fabric/Color Matrix) vẫn lặp theo ngày vì mỗi ngày độc
        lập, không có chi phí lặp lại tốn kém."""
        dates = list(dates)
        for production_date in sorted(dates):
            service.recompute_daily(production_date, conn)
        batch_day_trend.recompute_all(dates, conn)


engine = BatchMatrixEngine()
