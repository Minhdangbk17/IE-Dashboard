"""
core/rollup.py
----------------
Daily Rollup Pattern — điều phối việc tính lại bảng tổng hợp theo ngày
(`recompute_daily()`, xem `core/engine_base.py::BaseEngine`) sau mỗi lần
import dữ liệu, và cung cấp lệnh CLI để backfill toàn bộ lịch sử.

Nguyên tắc cốt lõi (giữ tốc độ import nhanh dù dữ liệu lịch sử đã lớn): CHỈ
tính lại đúng các `production_date` thực sự bị ảnh hưởng bởi các dòng vừa
insert/update — KHÔNG bao giờ quét lại toàn bộ lịch sử mỗi lần import. Chạy
đồng bộ trong cùng request import (dự án chưa có Celery/APScheduler, và
import không phải thao tác tần suất cao nên chấp nhận cộng thêm chút thời
gian xử lý thay vì thêm dependency mới).
"""
from __future__ import annotations

from datetime import date, datetime

import click
from flask import Flask

from core.database import get_db
from core.engine_registry import discover_engines
from core.production_time import production_date_sql_expr


def trigger_recompute(affected_dates: set[date]) -> None:
    """Gọi `engine.recompute_daily(d, conn)` cho MỌI Engine đã auto-load (Engine nào
    không override thì no-op mặc định) — với từng `production_date` trong `affected_dates`.

    Gọi ngay sau khi một lần import Excel commit thành công, chỉ truyền các
    production_date thực sự bị ảnh hưởng bởi batch dữ liệu vừa import.
    """
    if not affected_dates:
        return
    conn = get_db()
    engines = discover_engines()
    for production_date in sorted(affected_dates):
        for engine in engines:
            engine.recompute_daily(production_date, conn)
    conn.commit()


def _all_known_production_dates() -> set[date]:
    """Toàn bộ production_date đã từng xuất hiện trong `availability_logs` — nguồn dữ
    liệu chính nuôi cả `downtime_daily_summary` lẫn `batch_matrix_daily_summary`."""
    conn = get_db()
    expr = production_date_sql_expr("COALESCE(end_time, start_time)")
    rows = conn.execute(
        f"SELECT DISTINCT {expr} AS d FROM availability_logs WHERE end_time IS NOT NULL OR start_time IS NOT NULL"
    ).fetchall()
    return {datetime.strptime(row["d"], "%Y-%m-%d").date() for row in rows if row["d"]}


def rebuild_all_summaries() -> int:
    """Chạy `recompute_daily()` cho TOÀN BỘ production_date đã từng xuất hiện trong dữ
    liệu hiện có — dùng 1 lần khi triển khai Daily Rollup lần đầu (dữ liệu cũ chưa có
    summary), hoặc bất cứ khi nào cần sửa lỗi công thức/đổi logic tính toán sau này."""
    dates = _all_known_production_dates()
    trigger_recompute(dates)
    return len(dates)


def init_app(app: Flask) -> None:
    """Đăng ký CLI command `flask rebuild-summaries` vào app."""
    app.cli.add_command(rebuild_summaries_command)


@click.command("rebuild-summaries")
def rebuild_summaries_command() -> None:
    """Flask CLI command: `flask rebuild-summaries` — tính lại toàn bộ bảng tổng hợp
    theo ngày (Daily Rollup) từ raw data hiện có trong DB."""
    count = rebuild_all_summaries()
    click.echo(f"Đã tính lại summary cho {count} production_date.")
