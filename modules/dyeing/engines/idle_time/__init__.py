"""
modules/dyeing/engines/idle_time/__init__.py
-----------------------------------------------
Điểm vào của Engine "idle_time" — báo cáo Idle Time (giờ máy không chạy mẻ nào) theo máy x
Production Date, đọc lại rollup `batch_day_trend_daily_summary` của Engine `batch_matrix`
nên KHÔNG có rollup riêng (không override `recompute_daily()`).
"""
from __future__ import annotations

from flask import Blueprint

from core.engine_base import BaseEngine, EngineMetadata

from .routes import build_blueprint


class IdleTimeEngine(BaseEngine):
    name = "idle_time"
    domain = "dyeing"

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(
            name=self.name,
            domain=self.domain,
            description=(
                "Idle Time: hours each machine runs no batch per production day (available hours "
                "minus occupied hours from the Batch/Day split), with % Idle vs target; Idle Entry "
                "records machine stops (time range + reason) that are matched to idle gaps at read time."
            ),
            data_sources=["batch_day_trend_daily_summary", "batch_details", "machines"],
            data_sinks=["idle_time_stops", "idle_time_settings"],
            # "batch_matrix": nguồn giờ hoạt động; "reports": chuẩn hoá Tank Type dùng chung.
            depends_on=["batch_matrix", "reports"],
        )

    def create_blueprint(self) -> Blueprint:
        return build_blueprint(self)


engine = IdleTimeEngine()
