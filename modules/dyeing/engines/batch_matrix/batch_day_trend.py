"""Batch/Day Trend — tab thứ 2 của Engine `batch_matrix` (theo yêu cầu người dùng).

CÔNG THỨC (mỗi kỳ Day/Week/Month):
    Batch/Day = [Đếm số mẻ có Rework = 0] * 24 / [Tổng thời gian TẤT CẢ mẻ trong kỳ đó]

Nguồn dữ liệu CHÍNH: `availability_logs` — đếm theo `rework_hour = 0`, thời gian lấy từ
`planned_prd_time_hour` ("Planned PRD time (hour)").

Mẻ KHÔNG có trong `availability_logs` (dyelot không khớp bất kỳ `batch`/`batch_ref_no`
nào — CÙNG định nghĩa "mồ côi" đã dùng ở `reports/cleaning_matrix.py::_orphan_batch_rows()`,
VD line máy chỉ có dữ liệu Batch Detail) lấy từ `batch_details`: đếm theo `is_rework = 0`,
thời gian = `run_time` (giây, cột RunTime) / 3600.

QUY TẮC FabricType KHÔNG HỢP LỆ (rỗng/"Unknow(n)"): KHÔNG được tính là 1 mẻ riêng —
thời gian của dòng đó CỘNG DỒN (carry-forward) sang mẻ THẬT kế tiếp CÙNG MÁY (theo thời
gian thực tế) — đúng nghiệp vụ "khoảng trống/vệ sinh máy giữa 2 mẻ tính vào mẻ chạy sau
nó". Đây là điểm KHÁC biệt quan trọng so với các Daily Rollup khác trong dự án
(downtime/batch_matrix): công thức phụ thuộc THỨ TỰ THỜI GIAN xuyên suốt lịch sử của
từng máy, không tách rời được theo từng production_date một cách độc lập.

DAILY ROLLUP PATTERN (`batch_day_trend_daily_summary`, grain = 1 dòng/1 mẻ THẬT đã
resolve, giống `cleaning_mc_daily_summary`):
- `recompute_daily(D, conn)` KHÔNG thể chỉ nhìn dữ liệu của riêng ngày D (một mẻ Unknown
  kết thúc ngày D-1 có thể "đẩy" giờ của nó vào mẻ THẬT đầu tiên chạy sang ngày D) — giải
  quyết bằng cách: (1) tìm tập MÁY có ít nhất 1 mẻ THẬT (fabric hợp lệ) resolve đúng ngày D
  (`_find_candidate_machines()`), (2) với MỖI máy đó, lấy TOÀN BỘ lịch sử của riêng máy đó
  (`_machine_records()`, quét theo index cột `machine` — rẻ vì chỉ chạy cho vài chục máy
  liên quan, KHÔNG phải quét toàn bảng), chạy lại đúng thuật toán carry-forward, rồi CHỈ
  lưu các mẻ resolve đúng ngày D. Carry-forward của 1 máy chỉ phụ thuộc chính lịch sử máy
  đó nên kết quả giống hệt tính trực tiếp (live) cho đúng các mẻ thuộc ngày D.
- Đọc báo cáo (`get_batch_day_trend()`) chỉ SELECT từ bảng summary + lọc theo
  Capacity/FabricType/Date ở Python — không còn quét lại `availability_logs`/`batch_details`
  mỗi lần đổi filter.

Bộ lọc: Capacity (Kg) — Availability dùng `availability_logs.capacity_kg`, mẻ mồ côi
dùng `machines.capacity_kg` đã cấu hình qua UI Batch Per Day by Machine (nếu CHƯA cấu
hình, mẻ đó bị ẩn khi lọc Capacity cụ thể — giống hệt hạn chế đã ghi nhận ở
`reports/cleaning_matrix.py`). Fabric Type — CHỈ áp dụng cho mẻ THẬT (Unknown không bao
giờ được lưu thành 1 dòng riêng nên không thể lọc/hiện ra ở đây).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from core.database import execute_query, get_db, get_dialect
from core.production_time import get_production_date, production_date_sql_expr

INVALID_FABRIC_TYPES = {"", "unknow", "unknown"}


def _parse_capacities(capacities: str | list[str] | None) -> list[float]:
    if not capacities:
        return []
    values = capacities if isinstance(capacities, list) else str(capacities).split(",")
    parsed: list[float] = []
    for value in values:
        text = str(value).strip()
        if not text:
            continue
        try:
            number = float(text)
        except ValueError:
            continue
        if number not in parsed:
            parsed.append(number)
    return parsed


def _parse_fabric_types(fabric_types: str | list[str] | None) -> list[str]:
    if not fabric_types:
        return []
    values = fabric_types if isinstance(fabric_types, list) else str(fabric_types).split(",")
    return [text for value in values if (text := str(value).strip())]


def _parse_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
    return None


def _period(day: date, group_by: str) -> tuple[str, str]:
    if group_by == "month":
        return day.strftime("%Y-%m"), day.strftime("%b-%y")
    if group_by == "week":
        year, week, _ = day.isocalendar()
        return f"{year}-W{week:02d}", f"W{week:02d} {year}"
    return day.isoformat(), day.strftime("%d %b %Y")


# ---------------------------------------------------------------------------
# Daily Rollup: recompute_daily()
# ---------------------------------------------------------------------------


def _ensure_summary_table(conn: Any) -> None:
    """CHỈ chạy CREATE TABLE ở SQLite — ở Postgres bảng đã có sẵn qua `supabase/schema.sql`."""
    if get_dialect() == "sqlite":
        conn.execute("""
            CREATE TABLE IF NOT EXISTS batch_day_trend_daily_summary (
                production_date TEXT NOT NULL,
                machine TEXT NOT NULL,
                start_time TEXT NOT NULL,
                fabric_type TEXT NOT NULL,
                capacity_kg REAL,
                hours REAL NOT NULL DEFAULT 0,
                is_valid INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (production_date, machine, start_time)
            )
        """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_batch_day_trend_daily_summary_date ON batch_day_trend_daily_summary (production_date)")


def _find_candidate_machines(conn: Any, day_str: str) -> set[str]:
    """Tập MÁY có ít nhất 1 mẻ THẬT (FabricType hợp lệ) resolve đúng `day_str` — CHỈ những
    máy này mới có thể phát sinh dòng summary cho ngày D (mẻ Unknown không bao giờ tự sinh
    dòng summary, chỉ carry giờ sang mẻ THẬT kế tiếp — không cần xét riêng ở bước này)."""
    shifted_avail = production_date_sql_expr("COALESCE(end_time, start_time)")
    avail_rows = conn.execute(
        f"""
        SELECT DISTINCT machine FROM availability_logs
        WHERE fabric_type IS NOT NULL AND lower(trim(fabric_type)) NOT IN ('', 'unknow', 'unknown')
          AND {shifted_avail} = ?
        """,
        (day_str,),
    ).fetchall()
    shifted_batch = production_date_sql_expr("COALESCE(b.end_time, b.start_time)")
    batch_rows = conn.execute(
        f"""
        SELECT DISTINCT b.machine FROM batch_details b
        WHERE b.fabric_type IS NOT NULL AND lower(trim(b.fabric_type)) NOT IN ('', 'unknow', 'unknown')
          AND NOT EXISTS (
              SELECT 1 FROM availability_logs a2
              WHERE lower(trim(a2.batch)) = lower(trim(b.dyelot)) OR lower(trim(a2.batch_ref_no)) = lower(trim(b.dyelot))
          )
          AND {shifted_batch} = ?
        """,
        (day_str,),
    ).fetchall()
    machines = {(row["machine"] or "").strip() for row in avail_rows}
    machines.update((row["machine"] or "").strip() for row in batch_rows)
    machines.discard("")
    return machines


def _machine_records(conn: Any, machine: str) -> list[dict[str, Any]]:
    """TOÀN BỘ lịch sử (availability + mẻ mồ côi trong batch_details) của ĐÚNG 1 máy —
    quét theo cột `machine` (rẻ, chỉ chạy cho các máy có mặt trong `_find_candidate_machines()`,
    không phải toàn bảng)."""
    avail_rows = conn.execute(
        """
        SELECT fabric_type, start_time, end_time, planned_prd_time_hour, rework_hour, capacity_kg
        FROM availability_logs
        WHERE machine = ? AND start_time IS NOT NULL AND TRIM(start_time) != ''
        """,
        (machine,),
    ).fetchall()
    records: list[dict[str, Any]] = [
        {
            "fabric_type": (row["fabric_type"] or "").strip(),
            "start_time": row["start_time"],
            "end_time": row["end_time"],
            "hours": float(row["planned_prd_time_hour"] or 0),
            "is_valid": float(row["rework_hour"] or 0) == 0,
            "capacity": row["capacity_kg"],
        }
        for row in avail_rows
    ]

    orphan_rows = conn.execute(
        """
        SELECT b.fabric_type, b.start_time, b.end_time, b.run_time, COALESCE(b.is_rework, 0) AS is_rework,
               m.capacity_kg AS configured_capacity_kg
        FROM batch_details b
        LEFT JOIN machines m ON lower(trim(COALESCE(m.machine_code, m.machine_id))) = lower(trim(b.machine))
        WHERE b.machine = ? AND b.start_time IS NOT NULL AND TRIM(b.start_time) != ''
          AND NOT EXISTS (
              SELECT 1 FROM availability_logs a2
              WHERE lower(trim(a2.batch)) = lower(trim(b.dyelot)) OR lower(trim(a2.batch_ref_no)) = lower(trim(b.dyelot))
          )
        """,
        (machine,),
    ).fetchall()
    records.extend(
        {
            "fabric_type": (row["fabric_type"] or "").strip(),
            "start_time": row["start_time"],
            "end_time": row["end_time"],
            "hours": float(row["run_time"] or 0) / 3600.0,
            "is_valid": int(row["is_rework"] or 0) == 0,
            "capacity": row["configured_capacity_kg"],
        }
        for row in orphan_rows
    )
    return records


def recompute_daily(production_date: date, conn: Any) -> None:
    """Tính lại `batch_day_trend_daily_summary` cho ĐÚNG 1 production_date — idempotent
    (DELETE dòng cũ của ngày này rồi INSERT lại). Xem docstring đầu file mục "Daily Rollup
    Pattern" để biết lý do phải xử lý theo TỪNG MÁY thay vì chỉ lọc raw data theo ngày D."""
    _ensure_summary_table(conn)
    day_str = production_date.isoformat()
    conn.execute("DELETE FROM batch_day_trend_daily_summary WHERE production_date = ?", (day_str,))

    machines = _find_candidate_machines(conn, day_str)
    if not machines:
        return

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    inserts: list[tuple[Any, ...]] = []
    for machine in machines:
        records = []
        for record in _machine_records(conn, machine):
            start_dt = _parse_datetime(record["start_time"])
            if start_dt is None:
                continue
            records.append({**record, "_start_dt": start_dt})
        records.sort(key=lambda r: r["_start_dt"])

        carry_hours = 0.0
        for record in records:
            if record["fabric_type"].strip().lower() in INVALID_FABRIC_TYPES:
                carry_hours += record["hours"]
                continue
            total_hours = record["hours"] + carry_hours
            carry_hours = 0.0
            record_time = _parse_datetime(record["end_time"]) or record["_start_dt"]
            resolved_date = get_production_date(record_time)
            if resolved_date.isoformat() != day_str:
                continue
            capacity = record["capacity"]
            capacity_value = round(float(capacity), 2) if capacity not in (None, "") else None
            inserts.append((
                day_str, machine, record["start_time"], record["fabric_type"], capacity_value,
                total_hours, int(record["is_valid"]), now_str,
            ))

    if inserts:
        conn.executemany(
            """
            INSERT INTO batch_day_trend_daily_summary
                (production_date, machine, start_time, fabric_type, capacity_kg, hours, is_valid, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            inserts,
        )


# ---------------------------------------------------------------------------
# Đọc báo cáo — CHỈ SELECT từ `batch_day_trend_daily_summary`, lọc/gộp ở Python.
# ---------------------------------------------------------------------------


def _empty_trend(group_by: str) -> dict[str, Any]:
    return {
        "filters": {"capacities": [], "fabric_types": [], "from_date": None, "to_date": None, "group_by": group_by},
        "periods": [], "period_keys": [],
        "rows": [{"label": "Batch/Day", "values": [], "total": 0.0}],
        "chart": {"categories": [], "values": []},
        "kpis": {"batch_per_day": 0.0, "valid_batches": 0, "total_planned_hours": 0.0},
        "available_fabric_types": [],
        "available_capacities": [],
    }


def get_batch_day_trend(
    capacities: str | list[str] | None = None,
    fabric_types: str | list[str] | None = None,
    from_date: str | None = None, to_date: str | None = None,
    group_by: str = "date",
) -> dict[str, Any]:
    group_by = group_by if group_by in {"date", "week", "month"} else "date"
    conn = get_db()
    _ensure_summary_table(conn)

    sql = "SELECT production_date, machine, fabric_type, capacity_kg, hours, is_valid FROM batch_day_trend_daily_summary WHERE 1=1"
    params: list[Any] = []
    if from_date:
        sql += " AND production_date >= ?"
        params.append(from_date)
    if to_date:
        sql += " AND production_date <= ?"
        params.append(to_date)
    rows = execute_query(sql, params)
    if not rows:
        return _empty_trend(group_by)

    available_capacities = sorted({round(float(row["capacity_kg"]), 2) for row in rows if row["capacity_kg"] not in (None, "")})
    available_fabric_types = sorted({row["fabric_type"] for row in rows if row["fabric_type"]})

    selected_capacities = _parse_capacities(capacities)
    capacity_filter = {round(value, 2) for value in selected_capacities} if selected_capacities else None
    selected_fabric_types = _parse_fabric_types(fabric_types)
    fabric_filter = set(selected_fabric_types) if selected_fabric_types else None

    period_counts: dict[str, int] = {}
    period_hours: dict[str, float] = {}
    period_labels: dict[str, str] = {}
    for row in rows:
        if capacity_filter is not None:
            row_capacity = round(float(row["capacity_kg"]), 2) if row["capacity_kg"] not in (None, "") else None
            if row_capacity not in capacity_filter:
                continue
        if fabric_filter is not None and row["fabric_type"] not in fabric_filter:
            continue
        day = datetime.strptime(row["production_date"], "%Y-%m-%d").date()
        key, label = _period(day, group_by)
        period_labels[key] = label
        period_hours[key] = period_hours.get(key, 0.0) + float(row["hours"] or 0)
        if row["is_valid"]:
            period_counts[key] = period_counts.get(key, 0) + 1

    if not period_labels:
        result = _empty_trend(group_by)
        result["available_fabric_types"] = available_fabric_types
        result["available_capacities"] = available_capacities
        return result

    ordered_keys = sorted(period_labels.keys())
    labels = [period_labels[key] for key in ordered_keys]
    values = [
        round(period_counts.get(key, 0) * 24 / period_hours[key], 2) if period_hours.get(key) else 0.0
        for key in ordered_keys
    ]
    total_count = sum(period_counts.values())
    total_hours = sum(period_hours.values())
    total_value = round(total_count * 24 / total_hours, 2) if total_hours else 0.0

    return {
        "filters": {
            "capacities": selected_capacities or "all", "fabric_types": selected_fabric_types or "all",
            "from_date": from_date, "to_date": to_date, "group_by": group_by,
        },
        "periods": labels, "period_keys": ordered_keys,
        "rows": [{"label": "Batch/Day", "values": values, "total": total_value}],
        "chart": {"categories": labels, "values": values},
        "kpis": {
            "batch_per_day": total_value,
            "valid_batches": total_count,
            "total_planned_hours": round(total_hours, 1),
        },
        "available_fabric_types": available_fabric_types,
        "available_capacities": available_capacities,
    }
