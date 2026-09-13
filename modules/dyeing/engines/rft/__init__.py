"""
modules/dyeing/engines/rft/__init__.py
----------------------------------------
Điểm vào của Engine "rft" (Right First Time). Expose biến module-level `engine`.

Khung sườn (scaffold) — 6 bảng phân loại mẻ nhuộm theo loại lần chạy (Lab to Lab,
Lab to Bulk, Bulk to Bulk, 2nd Batch, Rework, Adjust Color) dựa trên dữ liệu Batch
(`batch_details` JOIN `availability_logs`). Quy tắc phân loại CHI TIẾT từng bảng
CHƯA được cung cấp (người dùng sẽ hướng dẫn sau) — xem
`service.py::classify_rft_category()`. Chưa có Daily Rollup (`recompute_daily`
không override, dùng no-op mặc định của `BaseEngine`) vì công thức chưa ổn định —
cùng quyết định đã áp dụng cho `oee` (xem `memory-bank/activeContext.md`).
"""
from __future__ import annotations

from flask import Blueprint

from core.engine_base import BaseEngine, EngineMetadata

from .routes import build_blueprint


class RftEngine(BaseEngine):
    name = "rft"
    domain = "dyeing"

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name=self.name,
            domain=self.domain,
            description=(
                "Right First Time report: classify batches by dyeing attempt type "
                "(Lab to Lab / Lab to Bulk / Bulk to Bulk / 2nd Batch / Rework / Adjust Color). "
                "Scaffold — classification rules pending."
            ),
            data_sources=["availability_logs", "batch_details"],
            data_sinks=[],
            depends_on=["excel_import"],
        )

    def create_blueprint(self) -> Blueprint:
        return build_blueprint(self)


engine = RftEngine()
