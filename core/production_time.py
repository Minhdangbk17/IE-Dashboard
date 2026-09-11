"""
core/production_time.py
------------------------
Khái niệm "Ngày sản xuất" (production_date) dùng CHUNG cho mọi Engine tính
toán trên dữ liệu Nhuộm (downtime, batch_matrix — Xem `systemPatterns.md`
mục "Daily Rollup Pattern").

Quy ước: một ca sản xuất chạy 07:00 hôm nay -> trước 07:00 hôm sau được tính
vào "ngày hôm nay" (KHÔNG phải ngày dương lịch thô của timestamp). VD:
2026-09-06 05:30 thuộc production_date 2026-09-05; 2026-09-06 08:00 thuộc
production_date 2026-09-06.

Trước đây logic này bị lặp lại (và có lúc viết tay khác nhau) ở nhiều nơi —
`downtime/service.py::operational_bounds()` (SQL) và `batch_matrix/service.py`
(cũng SQL, cùng "-7 hours") — module này gộp về MỘT nguồn duy nhất, cả bản
Python (`get_production_date`) lẫn bản chuỗi SQL (`PRODUCTION_DATE_SQL_EXPR`)
để service.py nào cũng dùng lại được thay vì viết lại biểu thức SQL.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from core.database import get_dialect

PRODUCTION_SHIFT_START_HOUR = 7

# Biểu thức SQLite tính production_date từ một cột/biểu thức datetime bất kỳ —
# dùng trực tiếp trong câu SELECT/GROUP BY, tránh phải viết tay "-7 hours" rải rác.
# GIỮ LẠI làm hằng số cho khả năng đọc/tương thích ngược, nhưng KHÔNG dùng trực tiếp
# `.format(col=...)` ở call site mới — dùng hàm `production_date_sql_expr(col)` bên dưới
# (tự chọn đúng bản SQLite/Postgres theo dialect DB đang active).
PRODUCTION_DATE_SQL_EXPR = f"date(datetime({{col}}), '-{PRODUCTION_SHIFT_START_HOUR} hours')"
# Bản Postgres tương đương — psycopg2/Supabase không có hàm datetime() của SQLite.
_PRODUCTION_DATE_SQL_EXPR_POSTGRES = (
    f"(({{col}})::timestamp - interval '{PRODUCTION_SHIFT_START_HOUR} hours')::date"
)


def production_date_sql_expr(col: str) -> str:
    """Biểu thức SQL tính production_date từ 1 cột/biểu thức datetime — bản SQL của
    `get_production_date()`, tự chọn ĐÚNG cú pháp theo dialect DB đang active
    (`core/database.py::get_dialect()`). Dùng hàm này ở MỌI câu SQL cần production_date
    (thay vì `PRODUCTION_DATE_SQL_EXPR.format(col=...)` cũ) để tự động đúng cả SQLite lẫn
    Postgres/Supabase."""
    template = _PRODUCTION_DATE_SQL_EXPR_POSTGRES if get_dialect() == "postgres" else PRODUCTION_DATE_SQL_EXPR
    return template.format(col=col)


def get_production_date(value: datetime) -> date:
    """Quy đổi 1 mốc thời gian sang production_date (cắt lúc 07:00 sáng).

    QUAN TRỌNG: với dữ liệu dạng BATCH (có cả StartTime lẫn EndTime — VD
    `availability_logs`), LUÔN truyền EndTime (thời điểm mẻ KẾT THÚC), KHÔNG
    truyền StartTime. Một mẻ được tính vào "ngày sản xuất" theo lúc nó hoàn
    thành, không phải lúc bắt đầu. VD mẻ chạy qua đêm StartTime=2026-08-24
    21:43, EndTime=2026-08-25 09:19 -> `get_production_date(EndTime)` trả về
    2026-08-25 (ĐÚNG); `get_production_date(StartTime)` sẽ trả về 2026-08-24
    (SAI — đã từng gây bug hiển thị nhầm ngày ở báo cáo Cleaning MC do tầng
    JS lấy StartTime thay vì production_date đã tính đúng ở backend, xem
    memory-bank/systemPatterns.md mục 6.2). Chỉ dùng StartTime làm fallback
    khi EndTime NULL (mẻ chưa hoàn thành), không bao giờ dùng làm nguồn chính.

    Với dữ liệu dạng time-series đơn (1 cột timestamp duy nhất, VD
    `machine_telemetry`), truyền thẳng cột timestamp đó — không áp dụng phân
    biệt Start/End vì không có khái niệm "khoảng thời gian" ở đây.
    """
    if value.time() < time(PRODUCTION_SHIFT_START_HOUR, 0):
        return (value - timedelta(days=1)).date()
    return value.date()


def production_bounds(date_from: str | None, date_to: str | None) -> tuple[str | None, str | None]:
    """Quy đổi khoảng [date_from, date_to] (theo production_date) sang cặp mốc thời gian
    nửa-mở [start, end) để dùng trực tiếp trong WHERE ... datetime(col) >= / < .

    VD: date_from='2026-09-05' -> start='2026-09-05 07:00:00'
        date_to='2026-09-05'   -> end='2026-09-06 07:00:00' (đến hết ca ngày 05, trước ca 06)
    """
    start = datetime.strptime(date_from, "%Y-%m-%d") if date_from else None
    end = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1) if date_to else None
    return (
        start.replace(hour=PRODUCTION_SHIFT_START_HOUR).strftime("%Y-%m-%d %H:%M:%S") if start else None,
        end.replace(hour=PRODUCTION_SHIFT_START_HOUR).strftime("%Y-%m-%d %H:%M:%S") if end else None,
    )


def production_date_range(date_from: str, date_to: str) -> list[str]:
    """Danh sách các production_date (chuỗi 'YYYY-MM-DD') trong khoảng [date_from, date_to]."""
    start = datetime.strptime(date_from, "%Y-%m-%d").date()
    end = datetime.strptime(date_to, "%Y-%m-%d").date()
    if end < start:
        start, end = end, start
    days: list[str] = []
    current = start
    while current <= end:
        days.append(current.isoformat())
        current += timedelta(days=1)
    return days
