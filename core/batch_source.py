"""
core/batch_source.py
---------------------
NGUỒN SỰ THẬT DUY NHẤT (2026-10-02) cho 2 báo cáo "Batch/Day Trend" và "Batch Per Day by
Machine": dữ liệu báo cáo Batch (`batch_details`, sheet "Batch"). `availability_logs` KHÔNG
còn được dùng để quyết định mẻ nào tồn tại, chạy máy nào, loại vải gì hay rơi vào ngày nào —
trước đây Batch Per Day by Machine lấy Machine/FabricType/production_date từ Availability nên
lệch với Trend (và mất trắng các ngày chưa import Availability).

Quy tắc chuẩn hoá (đúng Power Query người dùng cung cấp, dùng CHUNG cho cả 2 báo cáo):
1. Machine trống -> Machine của dòng NGAY PHÍA TRÊN (fill-down theo `id` = thứ tự import).
2. Dòng không có StartTime hợp lệ (hoặc vẫn không có Machine) -> bỏ.
3. FabricType trống/"Unknown" -> FabricType của mẻ KẾ TIẾP cùng máy (theo StartTime); mẻ cuối
   của máy không có mẻ sau -> "Unknown".
4. production_date của mẻ = NGÀY KẾT THÚC theo khung 07:00 -> 07:00 (= ngày của đoạn CUỐI có
   giờ > 0 trong `split_production_days()`, nên mẻ kết thúc đúng 07:00:00 thuộc ngày hôm
   trước). Mẻ chưa có EndTime hợp lệ -> production_date của StartTime (chỉ Batch Per Day by
   Machine hiển thị được; Trend bỏ vì không tính được giờ).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from core.production_time import PRODUCTION_SHIFT_START_HOUR, get_production_date

INVALID_FABRIC_TYPES = {"", "unknow", "unknown"}
UNKNOWN_FABRIC_TYPE = "Unknown"
_OPTIONAL_COLUMNS: tuple[tuple[str, str], ...] = (
    ("shade", "''"), ("colour_no", "''"), ("recipe_no", "''"), ("customer_color", "''"),
    ("batch_type", "''"), ("is_rework", "0"), ("run_time", "0"),
)


def parse_batch_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
    return None


def split_production_days(start: datetime, end: datetime) -> list[tuple[date, float]]:
    """Tách [start, end) theo khung Production Date 07:00 -> 07:00 hôm sau, trả
    [(production_date, occupied_hours)] — bỏ đoạn 0h (khớp `List.Select(... > 0)` của Power Query)."""
    segments: list[tuple[date, float]] = []
    day = get_production_date(start)
    last_day = get_production_date(end)
    while day <= last_day:
        window_start = datetime(day.year, day.month, day.day, PRODUCTION_SHIFT_START_HOUR)
        window_end = window_start + timedelta(days=1)
        hours = (min(end, window_end) - max(start, window_start)).total_seconds() / 3600.0
        if hours > 0:
            segments.append((day, hours))
        day += timedelta(days=1)
    return segments


def load_resolved_batches(conn: Any) -> list[dict[str, Any]]:
    """TOÀN BỘ `batch_details` đã chuẩn hoá theo quy tắc ở docstring đầu file (1 round-trip).

    Mỗi phần tử giữ các cột thô cần dùng + `machine`/`fabric_type` ĐÃ điền, `_start_dt`,
    `_end_dt`, `_segments` (kết quả `split_production_days()`, rỗng nếu thiếu/ngược End) và
    `production_date` (`date`). Gọi `ensure_brand_program_table(conn)` TRƯỚC hàm này."""
    # Cột phụ (chỉ dùng phân loại badge/hiển thị) có thể thiếu ở DB SQLite cũ/DB test tối giản
    # -> thay bằng giá trị rỗng thay vì lỗi "no such column".
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(batch_details)").fetchall()}
    optional_columns = ", ".join(
        f"b.{name}" if name in existing else f"{default} AS {name}"
        for name, default in _OPTIONAL_COLUMNS
    )
    rows = conn.execute(
        f"""
        SELECT b.id, b.dyelot, b.sap_lot, b.redye, b.machine, b.fabric_type, b.start_time, b.end_time,
               {optional_columns},
               COALESCE(bpm.brand, '') AS brand, COALESCE(bpm.brand_program, '') AS brand_program
        FROM batch_details b
        LEFT JOIN brand_program_mapping bpm ON lower(trim(bpm.greige_code)) = lower(trim(b.greige_code))
        ORDER BY b.id
        """
    ).fetchall()

    # Bước 1-2: fill-down Machine theo thứ tự import, bỏ dòng thiếu StartTime/Machine.
    batches: list[dict[str, Any]] = []
    last_machine = ""
    for raw in rows:
        row = dict(raw)
        machine = str(row["machine"] or "").strip() or last_machine
        last_machine = machine
        start_dt = parse_batch_datetime(row["start_time"])
        if not machine or start_dt is None:
            continue
        fabric = str(row["fabric_type"] or "").strip()
        row.update({
            "machine": machine,
            "fabric_type": "" if fabric.lower() in INVALID_FABRIC_TYPES else fabric,
            "_start_dt": start_dt,
            "_end_dt": parse_batch_datetime(row["end_time"]),
        })
        batches.append(row)

    # Bước 3: FabricType trống -> FabricType của mẻ kế tiếp CÙNG máy (theo StartTime).
    by_machine: dict[str, list[dict[str, Any]]] = {}
    for batch in batches:
        by_machine.setdefault(batch["machine"], []).append(batch)
    for machine_batches in by_machine.values():
        machine_batches.sort(key=lambda b: b["_start_dt"])
        next_fabric = UNKNOWN_FABRIC_TYPE
        for batch in reversed(machine_batches):
            if batch["fabric_type"]:
                next_fabric = batch["fabric_type"]
            else:
                batch["fabric_type"] = next_fabric

    # Bước 4: production_date = ngày kết thúc (đoạn cuối có giờ > 0).
    for batch in batches:
        segments = split_production_days(batch["_start_dt"], batch["_end_dt"]) if batch["_end_dt"] else []
        batch["_segments"] = segments
        batch["production_date"] = segments[-1][0] if segments else get_production_date(batch["_start_dt"])
    return batches
