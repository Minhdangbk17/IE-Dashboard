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
from typing import Any, Iterable

from core.batch_details_match import batch_details_join_sql
from core.brand_program_importer import ensure_brand_program_table
from core.database import DatabaseError, execute_query, get_db, get_dialect
from core.production_time import get_production_date, production_date_sql_expr

INVALID_FABRIC_TYPES = {"", "unknow", "unknown"}
# Báo cáo "Batch/Day Trend" LUÔN thể hiện ĐÚNG 3 loại vải chính này (theo yêu cầu người
# dùng — 1 đường/1 dòng cố định mỗi loại, không phụ thuộc filter hay dữ liệu thực tế đang
# có). Mọi `fabric_type` KHÁC 3 loại này (VD Nylon, Spandex...) bị loại khỏi báo cáo Trend
# hoàn toàn — khác các báo cáo khác trong `batch_matrix`/`downtime`/`rft` vốn hiển thị ĐỘNG
# theo `available_fabric_types` tìm thấy trong dữ liệu. So khớp không phân biệt hoa/thường
# (xem `_normalize_main_fabric_type()`) — CHƯA xác nhận dữ liệu thật có biến thể viết khác
# (VD viết tắt "PES" cho Polyester) hay không, nếu có sẽ cần bổ sung alias sau.
MAIN_FABRIC_TYPES: tuple[str, ...] = ("Cotton", "CVC", "Polyester")
_MAIN_FABRIC_TYPE_BY_NORM: dict[str, str] = {name.lower(): name for name in MAIN_FABRIC_TYPES}


def _normalize_main_fabric_type(value: str | None) -> str | None:
    """Khớp `fabric_type` thô (bất kỳ hoa/thường) với ĐÚNG 1 trong `MAIN_FABRIC_TYPES` —
    trả `None` nếu không khớp loại nào (loại đó bị loại khỏi báo cáo Trend)."""
    return _MAIN_FABRIC_TYPE_BY_NORM.get(str(value or "").strip().lower())
# Nhãn "Brand - Program" suy từ greige_code (batch_details) -> brand_program_mapping — cùng
# cơ chế `downtime/service.py`/`batch_matrix/service.py`. AN TOÀN thêm thẳng vào grain của
# bảng rollup này (khác `batch_matrix_daily_summary.operating_hours`): mỗi dòng summary ở
# đây LÀ 1 mẻ cụ thể đã resolve (không phải machine-hours dùng chung nhiều mẻ), nên lọc/gộp
# theo brand_program không có rủi ro cộng trùng giờ.
_BRAND_PROGRAM_LABEL_SQL = "CASE WHEN COALESCE(bpm.brand, '') <> '' AND COALESCE(bpm.brand_program, '') <> '' THEN bpm.brand || ' - ' || bpm.brand_program ELSE '' END"


def _parse_brand_programs(brand_programs: str | list[str] | None) -> list[str]:
    if not brand_programs:
        return []
    values = brand_programs if isinstance(brand_programs, list) else str(brand_programs).split(",")
    return [text for value in values if (text := str(value).strip())]


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
    """CHỈ chạy CREATE TABLE ở SQLite — ở Postgres bảng đã có sẵn qua `supabase/schema.sql`
    (DB production đã có dữ liệu thì áp `supabase/migrate_batch_day_trend_brand_program.sql`
    + chạy lại `flask rebuild-summaries`)."""
    if get_dialect() == "sqlite":
        existing_columns = {row["name"] for row in conn.execute("PRAGMA table_info(batch_day_trend_daily_summary)")}
        if existing_columns and "brand_program" not in existing_columns:
            # An toàn xoá/tạo lại (giống `batch_matrix/service.py::_ensure_summary_table()`)
            # vì bảng luôn tái tạo được 100% từ raw data qua `recompute_daily()`.
            conn.execute("DROP TABLE batch_day_trend_daily_summary")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS batch_day_trend_daily_summary (
                production_date TEXT NOT NULL,
                machine TEXT NOT NULL,
                start_time TEXT NOT NULL,
                fabric_type TEXT NOT NULL,
                capacity_kg REAL,
                brand_program TEXT NOT NULL DEFAULT '',
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
        f"""
        SELECT a.fabric_type, a.start_time, a.end_time, a.planned_prd_time_hour, a.rework_hour, a.capacity_kg,
               {_BRAND_PROGRAM_LABEL_SQL} AS brand_program
        FROM availability_logs a
        {batch_details_join_sql("a.batch", "a.end_time", alias="bd")}
        LEFT JOIN brand_program_mapping bpm ON lower(trim(bpm.greige_code)) = lower(trim(bd.greige_code))
        WHERE a.machine = ? AND a.start_time IS NOT NULL AND TRIM(a.start_time) != ''
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
            "brand_program": str(row["brand_program"] or "").strip(),
        }
        for row in avail_rows
    ]

    orphan_rows = conn.execute(
        f"""
        SELECT b.fabric_type, b.start_time, b.end_time, b.run_time, COALESCE(b.is_rework, 0) AS is_rework,
               m.capacity_kg AS configured_capacity_kg, {_BRAND_PROGRAM_LABEL_SQL} AS brand_program
        FROM batch_details b
        LEFT JOIN machines m ON lower(trim(COALESCE(m.machine_code, m.machine_id))) = lower(trim(b.machine))
        LEFT JOIN brand_program_mapping bpm ON lower(trim(bpm.greige_code)) = lower(trim(b.greige_code))
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
            "brand_program": str(row["brand_program"] or "").strip(),
        }
        for row in orphan_rows
    )
    return records


def recompute_daily(production_date: date, conn: Any) -> None:
    """Tính lại `batch_day_trend_daily_summary` cho ĐÚNG 1 production_date — idempotent
    (DELETE dòng cũ của ngày này rồi INSERT lại). Xem docstring đầu file mục "Daily Rollup
    Pattern" để biết lý do phải xử lý theo TỪNG MÁY thay vì chỉ lọc raw data theo ngày D."""
    _ensure_summary_table(conn)
    ensure_brand_program_table(conn)
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
                record["brand_program"], total_hours, int(record["is_valid"]), now_str,
            ))

    if inserts:
        conn.executemany(
            """
            INSERT INTO batch_day_trend_daily_summary
                (production_date, machine, start_time, fabric_type, capacity_kg, brand_program, hours, is_valid, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            inserts,
        )


def recompute_all(dates: Iterable[date], conn: Any) -> None:
    """Biến thể HÀNG LOẠT của `recompute_daily()` (xem `core/engine_base.py::
    BaseEngine.recompute_all()`), cho kết quả GIỐNG HỆT gọi `recompute_daily()` lần lượt
    cho từng ngày trong `dates` — chỉ khác ở hiệu năng: fetch + sort lịch sử của MỖI máy
    liên quan ĐÚNG 1 LẦN (không phải N lần, N = số ngày trong `dates`).

    **BUG THẬT đã phát hiện + sửa bằng hàm này (2026-09-18)**: thuật toán carry-forward
    BẮT BUỘC quét TOÀN BỘ lịch sử của 1 máy để gán đúng giờ carry từ mẻ FabricType không
    hợp lệ đứng trước — `recompute_daily()` gọi riêng lẻ cho HÀNG TRĂM ngày (VD
    `flask rebuild-summaries` trên dữ liệu nhiều tháng) sẽ fetch+sort lại NGUYÊN VẸN lịch
    sử đó hàng trăm lần (mỗi lần fetch = 2 round-trip mạng khi DB là Postgres remote) — đủ
    chậm để người dùng coi tiến trình là "treo"/ngắt giữa chừng, chỉ backfill được vài
    ngày ĐẦU TIÊN theo thứ tự xử lý (`sorted(affected_dates)` — ngày cũ nhất trước). Triệu
    chứng thật đã xác nhận: DB production có dữ liệu Batch/Day Trend CHỈ cho 6 ngày đầu
    06/2026 dù `availability_logs` có dữ liệu tới ngày hiện tại (khớp chính xác kịch bản
    "dừng giữa chừng khi xử lý theo thứ tự ngày tăng dần")."""
    _ensure_summary_table(conn)
    ensure_brand_program_table(conn)
    date_strs = {d.isoformat() for d in dates}
    if not date_strs:
        return

    machines: set[str] = set()
    for day_str in date_strs:
        machines |= _find_candidate_machines(conn, day_str)

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
            day_str = resolved_date.isoformat()
            if day_str not in date_strs:
                continue
            capacity = record["capacity"]
            capacity_value = round(float(capacity), 2) if capacity not in (None, "") else None
            inserts.append((
                day_str, machine, record["start_time"], record["fabric_type"], capacity_value,
                record["brand_program"], total_hours, int(record["is_valid"]), now_str,
            ))

    for day_str in date_strs:
        conn.execute("DELETE FROM batch_day_trend_daily_summary WHERE production_date = ?", (day_str,))
    if inserts:
        conn.executemany(
            """
            INSERT INTO batch_day_trend_daily_summary
                (production_date, machine, start_time, fabric_type, capacity_kg, brand_program, hours, is_valid, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            inserts,
        )


# ---------------------------------------------------------------------------
# Target — bảng cấu hình `batch_day_trend_targets`, khoá theo `fabric_type` (CHỈ 3 giá trị
# `MAIN_FABRIC_TYPES`). Cùng pattern `downtime_targets`/`batch_matrix_targets` đã có sẵn
# trong dự án — mỗi báo cáo 1 bảng riêng, khoá theo đúng "đơn vị hàng" của báo cáo đó.
# KHÔNG tái dùng `batch_matrix_targets` (khoá `(fabric_type, color_group)`) — 2 bảng trả lời
# 2 câu hỏi khác nhau ("target cho 1 ô fabric+color của Matrix" vs "target cho tổng
# Batch/Day của 1 loại vải ở Trend"), đơn vị đo cũng khác quy mô nhau dù cùng công thức gốc.
# ---------------------------------------------------------------------------


def _ensure_trend_targets_table(conn: Any) -> None:
    """CHỈ chạy CREATE TABLE ở SQLite — Postgres tạo qua `supabase/schema.sql`."""
    if get_dialect() == "sqlite":
        conn.execute("""
            CREATE TABLE IF NOT EXISTS batch_day_trend_targets (
                fabric_type TEXT PRIMARY KEY,
                target_value REAL NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
    conn.commit()


def get_trend_targets() -> dict[str, float | None]:
    """{fabric_type: target_value} cho ĐÚNG 3 loại `MAIN_FABRIC_TYPES` — loại CHƯA từng
    được cấu hình trả `None` (hiển thị "-" trên UI, phân biệt với target THẬT SỰ = 0)."""
    conn = get_db()
    _ensure_trend_targets_table(conn)
    rows = execute_query("SELECT fabric_type, target_value FROM batch_day_trend_targets")
    result: dict[str, float | None] = {row["fabric_type"]: float(row["target_value"]) for row in rows}
    for name in MAIN_FABRIC_TYPES:
        result.setdefault(name, None)
    return result


def set_trend_target(fabric_type: str, target_value: float) -> dict[str, Any]:
    if fabric_type not in MAIN_FABRIC_TYPES:
        raise ValueError(f"Fabric type không hợp lệ: {fabric_type}")
    conn = get_db()
    _ensure_trend_targets_table(conn)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT INTO batch_day_trend_targets (fabric_type, target_value, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(fabric_type) DO UPDATE SET target_value = excluded.target_value, updated_at = excluded.updated_at",
        (fabric_type, target_value, now_str),
    )
    conn.commit()
    return {"fabric_type": fabric_type, "target_value": target_value, "updated_at": now_str}


# ---------------------------------------------------------------------------
# Đọc báo cáo — CHỈ SELECT từ `batch_day_trend_daily_summary`, lọc/gộp ở Python.
# ---------------------------------------------------------------------------


def _empty_trend(group_by: str, targets: dict[str, float | None] | None = None) -> dict[str, Any]:
    targets = targets or {}
    return {
        "filters": {"capacities": [], "brand_programs": [], "from_date": None, "to_date": None, "group_by": group_by},
        "periods": [], "period_keys": [],
        "rows": [{"fabric_type": name, "target": targets.get(name), "values": [], "total": 0.0} for name in MAIN_FABRIC_TYPES],
        "chart": {"categories": [], "series": []},
        "kpis": {"batch_per_day": 0.0, "valid_batches": 0, "total_planned_hours": 0.0},
        "available_capacities": [],
        "available_brand_programs": [],
    }


def get_batch_day_trend(
    capacities: str | list[str] | None = None,
    brand_programs: str | list[str] | None = None,
    from_date: str | None = None, to_date: str | None = None,
    group_by: str = "date",
) -> dict[str, Any]:
    group_by = group_by if group_by in {"date", "week", "month"} else "date"
    trend_targets = get_trend_targets()
    conn = get_db()
    sql = "SELECT production_date, machine, fabric_type, capacity_kg, brand_program, hours, is_valid FROM batch_day_trend_daily_summary WHERE 1=1"
    params: list[Any] = []
    if from_date:
        sql += " AND production_date >= ?"
        params.append(from_date)
    if to_date:
        sql += " AND production_date <= ?"
        params.append(to_date)
    try:
        _ensure_summary_table(conn)
        rows = execute_query(sql, params)
    except DatabaseError:
        # Bảng `batch_day_trend_daily_summary` chưa tồn tại trên Postgres (chưa áp
        # `supabase/migrate_batch_day_trend.sql`) hoặc lỗi tương tự — trả kết quả rỗng
        # thay vì crash cả trang, giống cách `rft`/`tank_loading` xử lý.
        return _empty_trend(group_by, trend_targets)
    if not rows:
        return _empty_trend(group_by, trend_targets)

    available_capacities = sorted({round(float(row["capacity_kg"]), 2) for row in rows if row["capacity_kg"] not in (None, "")})
    available_brand_programs = sorted({row["brand_program"] for row in rows if row["brand_program"]})

    selected_capacities = _parse_capacities(capacities)
    capacity_filter = {round(value, 2) for value in selected_capacities} if selected_capacities else None
    selected_brand_programs = _parse_brand_programs(brand_programs)
    brand_program_filter = set(selected_brand_programs) if selected_brand_programs else None

    # Mỗi loại vải chính (Cotton/CVC/Polyester) có tử số/mẫu số RIÊNG — tính ĐỘC LẬP theo
    # ĐÚNG công thức gốc (đếm mẻ Rework=0 * 24 / tổng giờ TẤT CẢ mẻ), không dùng chung mẫu
    # số như bản 1-đường-gộp cũ. Loại KHÁC 3 loại chính (`_normalize_main_fabric_type()`
    # trả None) bị loại bỏ hoàn toàn khỏi báo cáo Trend.
    period_counts: dict[str, dict[str, int]] = {name: {} for name in MAIN_FABRIC_TYPES}
    period_hours: dict[str, dict[str, float]] = {name: {} for name in MAIN_FABRIC_TYPES}
    period_labels: dict[str, str] = {}
    for row in rows:
        fabric_type = _normalize_main_fabric_type(row["fabric_type"])
        if fabric_type is None:
            continue
        if capacity_filter is not None:
            row_capacity = round(float(row["capacity_kg"]), 2) if row["capacity_kg"] not in (None, "") else None
            if row_capacity not in capacity_filter:
                continue
        if brand_program_filter is not None and (row["brand_program"] or "") not in brand_program_filter:
            continue
        day = datetime.strptime(row["production_date"], "%Y-%m-%d").date()
        key, label = _period(day, group_by)
        period_labels[key] = label
        period_hours[fabric_type][key] = period_hours[fabric_type].get(key, 0.0) + float(row["hours"] or 0)
        if row["is_valid"]:
            period_counts[fabric_type][key] = period_counts[fabric_type].get(key, 0) + 1

    if not period_labels:
        result = _empty_trend(group_by, trend_targets)
        result["available_capacities"] = available_capacities
        result["available_brand_programs"] = available_brand_programs
        return result

    ordered_keys = sorted(period_labels.keys())
    labels = [period_labels[key] for key in ordered_keys]

    rows_out: list[dict[str, Any]] = []
    total_count_all = 0
    total_hours_all = 0.0
    for name in MAIN_FABRIC_TYPES:
        counts = period_counts[name]
        hours = period_hours[name]
        values = [round(counts.get(key, 0) * 24 / hours[key], 2) if hours.get(key) else 0.0 for key in ordered_keys]
        total_count = sum(counts.values())
        total_hours = sum(hours.values())
        total_value = round(total_count * 24 / total_hours, 2) if total_hours else 0.0
        rows_out.append({"fabric_type": name, "target": trend_targets.get(name), "values": values, "total": total_value})
        total_count_all += total_count
        total_hours_all += total_hours

    overall_value = round(total_count_all * 24 / total_hours_all, 2) if total_hours_all else 0.0

    return {
        "filters": {
            "capacities": selected_capacities or "all",
            "brand_programs": selected_brand_programs or "all",
            "from_date": from_date, "to_date": to_date, "group_by": group_by,
        },
        "periods": labels, "period_keys": ordered_keys,
        "rows": rows_out,
        "chart": {"categories": labels, "series": [{"name": row["fabric_type"], "data": row["values"]} for row in rows_out]},
        "kpis": {
            "batch_per_day": overall_value,
            "valid_batches": total_count_all,
            "total_planned_hours": round(total_hours_all, 1),
        },
        "available_capacities": available_capacities,
        "available_brand_programs": available_brand_programs,
    }
