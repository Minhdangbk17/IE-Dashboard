"""
modules/dyeing/engines/rft/__init__.py
----------------------------------------
Điểm vào của Engine "rft" (Right First Time). Expose biến module-level `engine`.

5 tab: Lab to Bulk / Bulk to Bulk / 2nd Batch (tỷ lệ DyeingRFT = OK theo Stage) và Rework /
Adjustment (tỷ lệ ReworkCount, chỉ máy >=500kg). Nguồn: `batch_details` (mẻ, Dyelot đuôi "0")
+ 2 nguồn tra cứu nạp hằng ngày `dye_production_ops` (Production Report, công đoạn DG*) và
`dye_nc_reports` (NC Report). Tính trực tiếp ở read time, không có Daily Rollup — xem
`service.py`.
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
                "Right First Time report: DyeingRFT OK rate by stage (Lab to Bulk / Bulk to Bulk / "
                "2nd Batch) and Rework / Adjustment rate on >=500kg machines."
            ),
            data_sources=["batch_details", "dye_production_ops", "dye_nc_reports", "brand_program_mapping"],
            data_sinks=["rft_targets"],
            depends_on=["excel_import"],
        )

    def create_blueprint(self) -> Blueprint:
        return build_blueprint(self)


engine = RftEngine()
