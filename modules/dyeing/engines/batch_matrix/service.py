"""
modules/dyeing/engines/batch_matrix/service.py
--------------------------------------------------
Ma trận Số mẻ/Máy theo Ngày: pivot Fabric Type x Color Group x Ngày sản xuất.

Daily Rollup Pattern (xem `memory-bank/systemPatterns.md`): JOIN `availability_logs`
với `batch_details` để lấy Shade/ColourNo/BatchType (phần tốn kém nhất — quét toàn bộ
dòng khớp bộ lọc mỗi lần load trang) giờ CHỈ chạy 1 lần trong `recompute_daily()`, lưu
kết quả đã phân loại + đếm sẵn. `build_matrix()` (đọc báo cáo) CHỦ YẾU SELECT từ bảng đã
tổng hợp sẵn — TRỪ dòng Total(Fabric)/Grand Total, PHẢI truy vấn lại raw data (xem mục
"Mẫu số" bên dưới, lý do bắt buộc).

CÔNG THỨC (bản THỨ 3, 2026-09-10 — sau 2 lần đổi trước: (1) đếm máy DISTINCT ->
(2) giờ máy dùng CHUNG toàn bảng theo Capacity+ngày -> **(3) giờ máy theo ĐÚNG TẬP MÁY của
từng cấp gộp**, bản hiện tại). Tử số và mẫu số tính KHÁC HẲN nhau, đừng nhầm lẫn:

  - **Tử số**: đếm số mẻ theo (production_date, fabric_type, color_group, capacity_kg) —
    MỖI MẺ nguyên vẹn 1 ngày (production_date = EndTime cắt 7h sáng, KHÔNG chia nhỏ).
    Fabric Type lấy trực tiếp từ `availability_logs.fabric_type` (loại rỗng/"Unknow(n)").
    Color Group: LEFT JOIN `batch_details` theo `availability_logs.batch = batch_details.dyelot`
    lấy Shade + ColourNo (Dark+BLACK->Black, Light+WHITE->White, Medium->Medium, JOIN miss/
    Shade rỗng -> "Unclassified"). Chỉ tính mẻ `batch_type='Normal'` (JOIN miss vẫn giữ).

  - **Mẫu số (bản 3 — thay thế hoàn toàn bản "giờ dùng chung toàn bảng")**: với 1 ô
    (fabric_type, color_group, capacity_kg, ngày), (1) xác định TẬP MÁY = các máy DUY NHẤT
    xuất hiện trong chính các mẻ đã đếm ở tử số của ô đó; (2) mẫu số = TỔNG giờ hoạt động
    (prorate theo ranh giới 7h sáng, `production_bounds(D,D)`) của ĐÚNG các máy trong tập
    đó trong ngày đó — tính CẢ các mẻ KHÁC màu/khác vải mà chính các máy này cũng chạy hôm
    đó (không giới hạn theo ColorGroup/FabricType ở bước tính giờ, chỉ giới hạn theo TẬP
    MÁY). `batch_matrix_daily_summary.operating_hours` lưu sẵn giá trị này CHO ĐÚNG GRAIN
    (fabric_type, color_group, capacity_kg, ngày) — vì trong dữ liệu thật, 1 máy chỉ có
    ĐÚNG 1 capacity_kg cố định (đã verify: 0 máy có >1 capacity_kg khác nhau), nên SUM
    operating_hours qua nhiều capacity_kg cho CÙNG 1 (fabric,color,ngày) là AN TOÀN (không
    trùng máy) — dùng cho dòng "data" hiển thị khi filter nhiều Capacity cùng lúc.

  - **RỦI RO PHẢI TRÁNH ở Total(Fabric)/Grand Total — ĐÚNG loại bug COUNT DISTINCT đã bắt
    được trước đây, chỉ khác ở "giờ" thay vì "đếm máy"**: TUYỆT ĐỐI KHÔNG cộng dồn
    `operating_hours` của các dòng ColorGroup con lại để ra mẫu số Total — 1 máy (VD DO01)
    chạy cả mẻ Black lẫn Dark cùng ngày sẽ bị CỘNG GIỜ 2 LẦN nếu cộng thẳng. Cách đúng
    (bắt buộc TRUY VẤN LẠI raw data ở `build_matrix()`, KHÔNG suy ra từ bảng summary):
    xác định TẬP MÁY = HỢP (union, khử trùng) của mọi máy chạy BẤT KỲ ColorGroup nào thuộc
    FabricType đó (Total Fabric) / BẤT KỲ Fabric+ColorGroup nào (Grand Total) trong ngày,
    rồi tính mẫu số từ đúng tập máy đã khử trùng này (mỗi máy cộng giờ ĐÚNG 1 LẦN dù chạy
    nhiều màu). Tử số của Total/Grand Total vẫn cộng thẳng bình thường (SUM batch_count —
    1 mẻ luôn thuộc đúng 1 Fabric+Color, không có rủi ro trùng ở tử số).

  - Giá trị ô = tử số × 24 / mẫu số (không đổi phần tam suất so với bản 2).

Verify: `tests/test_batch_matrix_formula.py` + `tests/verify_rollup_parity.py`
(`direct_build_matrix()`) — PHẢI có case 1 máy chạy đa màu/ngày để bẫy đúng lỗi cộng trùng
giờ nếu tái diễn.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from core.database import execute_query, get_db, get_dialect, sql_datetime
from core.production_time import get_production_date, production_bounds, production_date_sql_expr

# So khớp không phân biệt hoa/thường, chấp nhận cả lỗi chính tả gốc "Unknow" (thiếu "n").
_INVALID_FABRIC_TYPES = {"", "unknow", "unknown"}
UNCLASSIFIED_COLOR_GROUP = "Unclassified"


def _ensure_targets_table(conn: Any) -> None:
    """CHỈ chạy CREATE TABLE ở SQLite — ở Postgres bảng đã có sẵn qua `supabase/schema.sql`."""
    if get_dialect() == "sqlite":
        conn.execute("""
            CREATE TABLE IF NOT EXISTS batch_matrix_targets (
                fabric_type TEXT NOT NULL,
                color_group TEXT NOT NULL,
                target_value REAL NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (fabric_type, color_group)
            )
        """)
    conn.commit()


def _ensure_summary_table(conn: Any) -> None:
    """Ở SQLite: tự migrate schema cũ (bản trước không có cột `operating_hours`, xoá/tạo lại
    — an toàn vì bảng luôn tái tạo được 100% từ raw data qua `recompute_daily()`) rồi tạo
    bảng nếu chưa có. Ở Postgres: bảng đã có sẵn ĐÚNG schema mới qua `supabase/schema.sql`
    (deploy mới, không có schema cũ để migrate) — chỉ cần đảm bảo index tồn tại."""
    if get_dialect() == "sqlite":
        existing_columns = {row["name"] for row in conn.execute("PRAGMA table_info(batch_matrix_daily_summary)")}
        if existing_columns and "operating_hours" not in existing_columns:
            conn.execute("DROP TABLE batch_matrix_daily_summary")
        conn.execute("DROP TABLE IF EXISTS batch_matrix_capacity_hours_daily")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS batch_matrix_daily_summary (
                production_date TEXT NOT NULL,
                fabric_type TEXT NOT NULL,
                color_group TEXT NOT NULL,
                capacity_kg REAL NOT NULL,
                batch_count INTEGER NOT NULL DEFAULT 0,
                operating_hours REAL NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (production_date, fabric_type, color_group, capacity_kg)
            )
        """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_batch_matrix_daily_summary_date ON batch_matrix_daily_summary (production_date)")


def _operating_hours_by_machine_for_window(rows: Any, window_start_dt: datetime, window_end_dt: datetime) -> dict[str, float]:
    """Từ danh sách dòng thô (machine, start_time, end_time), tính giờ hoạt động
    (prorate theo cửa sổ [window_start_dt, window_end_dt)) của TỪNG MÁY — dùng chung cho cả
    `recompute_daily()` (1 ngày) lẫn build_matrix() (nhiều ngày, gọi lặp lại theo từng cửa
    sổ ngày)."""
    hours_by_machine: dict[str, float] = {}
    for row in rows:
        machine = (row["machine"] or "").strip()
        if not machine:
            continue
        try:
            start_dt = datetime.strptime(row["start_time"], "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            continue
        end_raw = row["end_time"] or row["start_time"]
        try:
            end_dt = datetime.strptime(end_raw, "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            end_dt = start_dt
        overlap_start = max(start_dt, window_start_dt)
        overlap_end = min(end_dt, window_end_dt)
        overlap_hours = (overlap_end - overlap_start).total_seconds() / 3600.0
        if overlap_hours <= 0:
            continue
        hours_by_machine[machine] = hours_by_machine.get(machine, 0.0) + overlap_hours
    return hours_by_machine


def _compute_operating_hours_by_machine(conn: Any, production_date: date) -> dict[str, float]:
    """Giờ hoạt động thực tế của TỪNG MÁY, đóng góp vào ĐÚNG 1 `production_date` (prorate
    theo ranh giới 7h sáng, `production_bounds(D,D)`) — lấy MỌI dòng `availability_logs`
    (mọi FabricType, kể cả Unknown) vì đây là thời gian máy BẬN nói chung, không lọc theo
    phân loại mẻ. Dùng làm nguồn tra cứu khi gán giờ cho TẬP MÁY của từng ô
    (fabric,color,capacity) trong `recompute_daily()`."""
    day_str = production_date.isoformat()
    window_start, window_end = production_bounds(day_str, day_str)
    rows = conn.execute(
        f"""
        SELECT machine, start_time, end_time
        FROM availability_logs
        WHERE machine IS NOT NULL AND machine != ''
          AND start_time IS NOT NULL AND start_time != ''
          AND {sql_datetime("COALESCE(end_time, start_time)")} > {sql_datetime("?")}
          AND {sql_datetime("start_time")} < {sql_datetime("?")}
        """,
        (window_start, window_end),
    ).fetchall()
    if not rows:
        return {}
    window_start_dt = datetime.strptime(window_start, "%Y-%m-%d %H:%M:%S")
    window_end_dt = datetime.strptime(window_end, "%Y-%m-%d %H:%M:%S")
    return _operating_hours_by_machine_for_window(rows, window_start_dt, window_end_dt)


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
            parsed.append(float(text))
        except ValueError:
            continue
    return parsed


def _classify_color_group(shade: Any, colour_no: Any) -> str:
    shade_norm = str(shade or "").strip()
    if not shade_norm:
        return UNCLASSIFIED_COLOR_GROUP
    colour_upper = str(colour_no or "").upper()
    shade_upper = shade_norm.upper()
    if shade_upper == "DARK":
        return "Black" if "BLACK" in colour_upper else "Dark"
    if shade_upper == "LIGHT":
        return "White" if "WHITE" in colour_upper else "Light"
    if shade_upper == "MEDIUM":
        return "Medium"
    return shade_norm


def get_targets() -> list[dict[str, Any]]:
    conn = get_db()
    _ensure_targets_table(conn)
    rows = execute_query("SELECT fabric_type, color_group, target_value FROM batch_matrix_targets ORDER BY fabric_type, color_group")
    return [dict(row) for row in rows]


def set_target(fabric_type: str, color_group: str, target_value: float) -> None:
    conn = get_db()
    _ensure_targets_table(conn)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT INTO batch_matrix_targets (fabric_type, color_group, target_value, updated_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(fabric_type, color_group) DO UPDATE SET target_value=excluded.target_value, updated_at=excluded.updated_at",
        (fabric_type, color_group, target_value, now_str),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Daily Rollup: recompute_daily()
# ---------------------------------------------------------------------------


def recompute_daily(production_date: date, conn: Any) -> None:
    """Tính lại `batch_matrix_daily_summary` cho ĐÚNG 1 production_date — idempotent
    (DELETE dòng cũ của ngày này rồi INSERT lại từ raw data). Với MỖI ô (fabric_type,
    color_group, capacity_kg): (1) đếm batch_count + xác định TẬP MÁY từ chính các mẻ đó,
    (2) tra `operating_hours` của ĐÚNG tập máy đó (không giới hạn FabricType/ColorGroup ở
    bước tra giờ — xem docstring đầu file mục "Mẫu số")."""
    _ensure_summary_table(conn)
    day_str = production_date.isoformat()
    conn.execute("DELETE FROM batch_matrix_daily_summary WHERE production_date = ?", (day_str,))

    # --- Tử số + tập máy: số mẻ VÀ danh sách máy theo (fabric_type, color_group, capacity_kg). ---
    shifted_date = production_date_sql_expr("a.end_time")
    sql = f"""
        SELECT a.fabric_type, a.machine, a.capacity_kg, b.shade, b.colour_no
        FROM availability_logs a
        LEFT JOIN batch_details b ON lower(trim(a.batch)) = lower(trim(b.dyelot))
        WHERE a.end_time IS NOT NULL AND a.end_time != ''
          AND a.fabric_type IS NOT NULL AND lower(trim(a.fabric_type)) NOT IN (?, ?, ?)
          AND (b.batch_type IS NULL OR lower(trim(b.batch_type)) = 'normal')
          AND {shifted_date} = ?
    """
    rows = conn.execute(sql, [*_INVALID_FABRIC_TYPES, day_str]).fetchall()
    if not rows:
        return

    buckets: dict[tuple[str, str, float], dict[str, Any]] = {}
    for row in rows:
        fabric_type = row["fabric_type"].strip()
        color_group = _classify_color_group(row["shade"], row["colour_no"])
        capacity = round(float(row["capacity_kg"] or 0), 2)
        key = (fabric_type, color_group, capacity)
        bucket = buckets.setdefault(key, {"count": 0, "machines": set()})
        bucket["count"] += 1
        machine = (row["machine"] or "").strip()
        if machine:
            bucket["machines"].add(machine)

    # --- Mẫu số: giờ hoạt động của TỪNG MÁY trong ngày (mọi FabricType, không lọc) — tra
    # cứu 1 lần, dùng cho MỌI ô (chỉ khác nhau ở TẬP MÁY được lấy giờ ra). ---
    hours_by_machine = _compute_operating_hours_by_machine(conn, production_date)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.executemany(
        "INSERT INTO batch_matrix_daily_summary (production_date, fabric_type, color_group, capacity_kg, batch_count, operating_hours, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (
                # KHÔNG làm tròn operating_hours trước khi lưu — mẫu số của 1 ô có thể chỉ
                # vài chục giây (VD mẻ kết thúc 1-2 phút sau mốc 7h, máy không hoạt động gì
                # thêm hôm đó) nên làm tròn sớm (VD 4 chữ số) khuếch đại sai số đáng kể khi
                # chia (đã phát hiện qua tests/verify_rollup_parity.py: lệch ~0.2% ở 1 ca cực
                # đoan mẫu số ~79 giây). Chỉ làm tròn ở bước hiển thị cuối cùng (cell_value/
                # total_value), không phải lúc lưu.
                day_str, fabric_type, color_group, capacity, bucket["count"],
                sum(hours_by_machine.get(m, 0.0) for m in bucket["machines"]), now_str,
            )
            for (fabric_type, color_group, capacity), bucket in buckets.items()
        ],
    )


# ---------------------------------------------------------------------------
# Đọc báo cáo — dòng "data" đọc từ batch_matrix_daily_summary; dòng Total(Fabric)/
# Grand Total PHẢI truy vấn lại raw data để khử trùng máy (xem docstring đầu file).
# ---------------------------------------------------------------------------


def _raw_fabric_and_grand_machines(
    date_from: str | None, date_to: str | None, capacity_filter: set[float] | None,
) -> tuple[dict[tuple[str, str], set[str]], dict[str, set[str]]]:
    """Truy vấn lại raw `availability_logs` (CÙNG điều kiện lọc tử số như `recompute_daily()`)
    để lấy TẬP MÁY đã khử trùng cho Total(Fabric) — `fabric_machines[(day, fabric_type)]` —
    và Grand Total — `grand_machines[day]` — union qua MỌI ColorGroup (Total Fabric) hoặc
    MỌI Fabric+ColorGroup (Grand Total). KHÔNG được suy ra từ `operating_hours` đã lưu sẵn
    theo từng ColorGroup — cộng thẳng sẽ đếm trùng giờ nếu 1 máy chạy nhiều màu/ngày (đúng
    loại bug COUNT DISTINCT đã bắt được trước đây, ở "giờ" thay vì "đếm máy")."""
    shifted_date = production_date_sql_expr("a.end_time")
    sql = f"""
        SELECT {shifted_date} AS production_date, a.fabric_type, a.machine, a.capacity_kg
        FROM availability_logs a
        LEFT JOIN batch_details b ON lower(trim(a.batch)) = lower(trim(b.dyelot))
        WHERE a.end_time IS NOT NULL AND a.end_time != ''
          AND a.fabric_type IS NOT NULL AND lower(trim(a.fabric_type)) NOT IN (?, ?, ?)
          AND (b.batch_type IS NULL OR lower(trim(b.batch_type)) = 'normal')
    """
    params: list[Any] = list(_INVALID_FABRIC_TYPES)
    if date_from:
        sql += f" AND {shifted_date} >= ?"
        params.append(date_from)
    if date_to:
        sql += f" AND {shifted_date} <= ?"
        params.append(date_to)

    fabric_machines: dict[tuple[str, str], set[str]] = {}
    grand_machines: dict[str, set[str]] = {}
    for row in execute_query(sql, params):
        day = row["production_date"]
        machine = (row["machine"] or "").strip()
        if not day or not machine:
            continue
        if capacity_filter is not None:
            row_capacity = round(float(row["capacity_kg"]), 2) if row["capacity_kg"] not in (None, "") else None
            if row_capacity not in capacity_filter:
                continue
        fabric_type = row["fabric_type"].strip()
        fabric_machines.setdefault((day, fabric_type), set()).add(machine)
        grand_machines.setdefault(day, set()).add(machine)
    return fabric_machines, grand_machines


def _machine_hours_by_day_for_range(days: list[str]) -> dict[str, dict[str, float]]:
    """Giờ hoạt động của TỪNG MÁY theo TỪNG NGÀY trong `days` — 1 query duy nhất quét cả
    khoảng ngày (không lặp N lần theo từng ngày); mỗi dòng raw chỉ được prorate vào ĐÚNG
    các ngày nó thực sự overlap (dùng production_date của StartTime/EndTime để giới hạn
    vòng lặp, thường chỉ 1-2 ngày mỗi dòng, không duyệt hết cả khoảng hiển thị)."""
    if not days:
        return {}
    range_start, _ = production_bounds(days[0], days[0])
    _, range_end = production_bounds(days[-1], days[-1])
    rows = execute_query(
        f"""
        SELECT machine, start_time, end_time
        FROM availability_logs
        WHERE machine IS NOT NULL AND machine != ''
          AND start_time IS NOT NULL AND start_time != ''
          AND {sql_datetime("COALESCE(end_time, start_time)")} > {sql_datetime("?")}
          AND {sql_datetime("start_time")} < {sql_datetime("?")}
        """,
        (range_start, range_end),
    )
    day_set = set(days)
    day_windows: dict[str, tuple[datetime, datetime]] = {}
    for day in days:
        window_start, window_end = production_bounds(day, day)
        day_windows[day] = (datetime.strptime(window_start, "%Y-%m-%d %H:%M:%S"), datetime.strptime(window_end, "%Y-%m-%d %H:%M:%S"))

    result: dict[str, dict[str, float]] = {}
    for row in rows:
        machine = (row["machine"] or "").strip()
        if not machine:
            continue
        try:
            start_dt = datetime.strptime(row["start_time"], "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            continue
        end_raw = row["end_time"] or row["start_time"]
        try:
            end_dt = datetime.strptime(end_raw, "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            end_dt = start_dt
        current = get_production_date(start_dt)
        last_day = get_production_date(end_dt)
        while current <= last_day:
            day_str = current.isoformat()
            if day_str in day_set:
                window_start_dt, window_end_dt = day_windows[day_str]
                overlap_start = max(start_dt, window_start_dt)
                overlap_end = min(end_dt, window_end_dt)
                overlap_hours = (overlap_end - overlap_start).total_seconds() / 3600.0
                if overlap_hours > 0:
                    day_bucket = result.setdefault(day_str, {})
                    day_bucket[machine] = day_bucket.get(machine, 0.0) + overlap_hours
            current += timedelta(days=1)
    return result


def _empty_result(date_from: str | None = None, date_to: str | None = None, error: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "date_from": date_from, "date_to": date_to,
        "days": [], "day_labels": [],
        "capacities": [], "available_capacities": [],
        "rows": [], "grand_total": None,
    }
    if error:
        result["error"] = error
    return result


def build_matrix(date_from: str | None = None, date_to: str | None = None, capacities: str | list[str] | None = None) -> dict[str, Any]:
    conn = get_db()
    _ensure_targets_table(conn)
    _ensure_summary_table(conn)

    sql = "SELECT production_date, fabric_type, color_group, capacity_kg, batch_count, operating_hours FROM batch_matrix_daily_summary WHERE 1=1"
    params: list[Any] = []
    if date_from:
        sql += " AND production_date >= ?"
        params.append(date_from)
    if date_to:
        sql += " AND production_date <= ?"
        params.append(date_to)

    try:
        all_rows = execute_query(sql, params)
    except Exception as exc:
        return _empty_result(date_from, date_to, error=str(exc))

    if not all_rows:
        return _empty_result(date_from, date_to)

    # Cột ngày = khoảng đã chọn (Từ ngày/Đến ngày) nếu có, hoặc MIN..MAX production_date
    # thực tế trong dữ liệu đã lọc nếu người dùng không chọn ngày. KHÔNG lọc theo Capacity
    # ở bước này, để bộ lọc Capacity chỉ đổi GIÁ TRỊ ô chứ không làm nhảy tập cột ngày.
    all_days_sorted = sorted({row["production_date"] for row in all_rows if row["production_date"]})
    if not all_days_sorted:
        return _empty_result(date_from, date_to)
    start_day = datetime.strptime(date_from, "%Y-%m-%d").date() if date_from else datetime.strptime(all_days_sorted[0], "%Y-%m-%d").date()
    end_day = datetime.strptime(date_to, "%Y-%m-%d").date() if date_to else datetime.strptime(all_days_sorted[-1], "%Y-%m-%d").date()
    if end_day < start_day:
        start_day, end_day = end_day, start_day
    days: list[str] = []
    current = start_day
    while current <= end_day:
        days.append(current.isoformat())
        current += timedelta(days=1)
    day_set = set(days)

    available_capacities = sorted({round(float(row["capacity_kg"]), 2) for row in all_rows if row["capacity_kg"] not in (None, "")})
    selected_capacities = _parse_capacities(capacities)
    capacity_filter = {round(value, 2) for value in selected_capacities} if selected_capacities else None

    # Dòng "data": tử số + mẫu số đọc TRỰC TIẾP từ bảng summary — AN TOÀN để SUM
    # operating_hours qua nhiều capacity_kg cho CÙNG 1 (fabric,color,ngày) vì 1 máy chỉ có
    # ĐÚNG 1 capacity_kg cố định trong dữ liệu thật (đã verify: 0 máy có >1 capacity_kg) nên
    # không có rủi ro cộng trùng giờ khi filter nhiều Capacity cùng lúc cho CÙNG 1 dòng màu.
    by_cell_count: dict[tuple[str, str], dict[str, int]] = {}
    by_cell_hours: dict[tuple[str, str], dict[str, float]] = {}
    by_fabric_count: dict[str, dict[str, int]] = {}

    for row in all_rows:
        day = row["production_date"]
        if day not in day_set:
            continue
        row_capacity = round(float(row["capacity_kg"]), 2) if row["capacity_kg"] not in (None, "") else None
        if capacity_filter is not None and row_capacity not in capacity_filter:
            continue
        fabric_type = row["fabric_type"]
        color_group = row["color_group"]
        batch_count = int(row["batch_count"] or 0)
        operating_hours = float(row["operating_hours"] or 0)

        cell_key = (fabric_type, color_group)
        count_bucket = by_cell_count.setdefault(cell_key, {})
        count_bucket[day] = count_bucket.get(day, 0) + batch_count
        hours_bucket = by_cell_hours.setdefault(cell_key, {})
        hours_bucket[day] = hours_bucket.get(day, 0.0) + operating_hours

        fabric_count_bucket = by_fabric_count.setdefault(fabric_type, {})
        fabric_count_bucket[day] = fabric_count_bucket.get(day, 0) + batch_count

    # Dòng Total(Fabric)/Grand Total: BẮT BUỘC truy vấn lại raw data để khử trùng máy —
    # KHÔNG được cộng operating_hours của các dòng ColorGroup con (xem docstring đầu file,
    # đúng loại bug COUNT DISTINCT đã bắt được trước đây, ở "giờ" thay vì "đếm máy").
    fabric_machines, grand_machines = _raw_fabric_and_grand_machines(date_from, date_to, capacity_filter)
    machine_hours_by_day = _machine_hours_by_day_for_range(days)

    def _dedup_hours(machines: set[str], day: str) -> float:
        day_hours = machine_hours_by_day.get(day, {})
        return sum(day_hours.get(m, 0.0) for m in machines)

    grand_count: dict[str, int] = {}
    for count_bucket in by_fabric_count.values():
        for day, count in count_bucket.items():
            grand_count[day] = grand_count.get(day, 0) + count

    targets = {(row["fabric_type"], row["color_group"]): row["target_value"] for row in execute_query("SELECT fabric_type, color_group, target_value FROM batch_matrix_targets")}

    def cell_value_from_hours(count: int | None, hours: float | None) -> float | None:
        if count is None or not hours:
            return None
        return round(count / (hours / 24), 2)

    def cell_value(day: str, count_by_day: dict[str, int], hours_by_day: dict[str, float]) -> float | None:
        return cell_value_from_hours(count_by_day.get(day), hours_by_day.get(day))

    def total_value(count_by_day: dict[str, int], hours_by_day: dict[str, float]) -> float | None:
        numerator = sum(count_by_day.values())
        # Chỉ SUM operating_hours ở ĐÚNG các ngày mà dòng này có batch_count (giữ đúng quy
        # ước Sum(tử theo ngày)/Sum(mẫu theo ngày) đã chốt trước đây) — sum RAW hours rồi
        # mới chia 24 MỘT LẦN ở bước cuối.
        denominator_hours = sum(hours_by_day.get(day, 0.0) for day in count_by_day)
        return round(numerator / (denominator_hours / 24), 2) if denominator_hours else None

    def cell_value_dedup(day: str, count_by_day: dict[str, int], machines_by_day: dict[str, set[str]]) -> float | None:
        return cell_value_from_hours(count_by_day.get(day), _dedup_hours(machines_by_day.get(day, set()), day))

    def total_value_dedup(count_by_day: dict[str, int], machines_by_day: dict[str, set[str]]) -> float | None:
        numerator = sum(count_by_day.values())
        denominator_hours = sum(_dedup_hours(machines_by_day.get(day, set()), day) for day in count_by_day)
        return round(numerator / (denominator_hours / 24), 2) if denominator_hours else None

    def color_group_sort_key(name: str) -> tuple[int, str]:
        return (1, name) if name == UNCLASSIFIED_COLOR_GROUP else (0, name)

    rows: list[dict[str, Any]] = []
    for fabric_type in sorted(by_fabric_count.keys()):
        color_groups = sorted({color_group for (ft, color_group) in by_cell_count if ft == fabric_type}, key=color_group_sort_key)
        for color_group in color_groups:
            cell_key = (fabric_type, color_group)
            count_by_day = by_cell_count[cell_key]
            hours_by_day = by_cell_hours[cell_key]
            rows.append({
                "row_type": "data",
                "fabric_type": fabric_type,
                "color_group": color_group,
                "target": targets.get((fabric_type, color_group)),
                "days": {day: cell_value(day, count_by_day, hours_by_day) for day in days},
                "total": total_value(count_by_day, hours_by_day),
            })
        fabric_count_by_day = by_fabric_count[fabric_type]
        fabric_machines_by_day = {day: fabric_machines.get((day, fabric_type), set()) for day in days}
        rows.append({
            "row_type": "fabric_total",
            "fabric_type": fabric_type,
            "color_group": None,
            "target": None,
            "days": {day: cell_value_dedup(day, fabric_count_by_day, fabric_machines_by_day) for day in days},
            "total": total_value_dedup(fabric_count_by_day, fabric_machines_by_day),
        })

    grand_machines_by_day = {day: grand_machines.get(day, set()) for day in days}
    rows.append({
        "row_type": "grand_total",
        "fabric_type": None,
        "color_group": None,
        "target": None,
        "days": {day: cell_value_dedup(day, grand_count, grand_machines_by_day) for day in days},
        "total": total_value_dedup(grand_count, grand_machines_by_day),
    })

    return {
        "date_from": date_from, "date_to": date_to,
        "days": days,
        "day_labels": [datetime.strptime(day, "%Y-%m-%d").strftime("%d/%m") for day in days],
        "capacities": selected_capacities, "available_capacities": available_capacities,
        "rows": rows, "grand_total": total_value_dedup(grand_count, grand_machines_by_day),
    }


# ---------------------------------------------------------------------------
# Drill-down: danh sách batch thật của 1 ô (double-check số liệu ma trận)
# ---------------------------------------------------------------------------


def get_day_batches(
    production_date: str, fabric_type: str, color_group: str, capacities: str | list[str] | None = None,
) -> list[dict[str, Any]]:
    """Trả về danh sách mẻ THẬT được tính vào đúng 1 ô (production_date, fabric_type,
    color_group[, capacity]) của ma trận — dùng để double-check khi người dùng bấm vào ô
    ngày trên UI. Query trực tiếp trên raw data (KHÔNG qua `batch_matrix_daily_summary`):
    đây là truy vấn hẹp (1 ngày, 1 ô), chỉ chạy khi bấm xem chi tiết — không phải đường đọc
    tần suất cao nên không cần rollup riêng (xem nguyên tắc "không bắt buộc rollup 100% mọi
    chỉ số" ở memory-bank/systemPatterns.md mục 6.2). Dùng LẠI ĐÚNG điều kiện lọc/JOIN như
    `recompute_daily()` (fabric_type hợp lệ, batch_type Normal, cùng công thức Color Group)
    để đảm bảo khớp 100% với số mẻ đã hiển thị trên ma trận."""
    conn = get_db()
    shifted_date = production_date_sql_expr("a.end_time")
    sql = f"""
        SELECT a.machine, a.batch, a.batch_ref_no, a.capacity_kg, a.start_time, a.end_time,
               b.shade, b.colour_no, b.dyelot, b.batch_type
        FROM availability_logs a
        LEFT JOIN batch_details b ON lower(trim(a.batch)) = lower(trim(b.dyelot))
        WHERE a.end_time IS NOT NULL AND a.end_time != ''
          AND a.fabric_type IS NOT NULL AND TRIM(a.fabric_type) = TRIM(?)
          AND (b.batch_type IS NULL OR lower(trim(b.batch_type)) = 'normal')
          AND {shifted_date} = ?
        ORDER BY a.machine, a.start_time
    """
    rows = conn.execute(sql, (fabric_type, production_date)).fetchall()

    selected_capacities = _parse_capacities(capacities)
    capacity_filter = {round(value, 2) for value in selected_capacities} if selected_capacities else None

    batches: list[dict[str, Any]] = []
    for row in rows:
        if capacity_filter is not None:
            row_capacity = round(float(row["capacity_kg"] or 0), 2) if row["capacity_kg"] not in (None, "") else None
            if row_capacity not in capacity_filter:
                continue
        if _classify_color_group(row["shade"], row["colour_no"]) != color_group:
            continue
        batches.append({
            "machine": row["machine"],
            "batch_no": row["batch_ref_no"] or row["batch"],
            "dyelot": row["dyelot"],
            "shade": row["shade"],
            "colour_no": row["colour_no"],
            "batch_type": row["batch_type"],
            "capacity_kg": row["capacity_kg"],
            "start_time": row["start_time"],
            "end_time": row["end_time"],
        })
    return batches
