from __future__ import annotations

import logging
from collections import Counter
from datetime import date, datetime
from typing import Any, Mapping

from core.database import execute_query, get_db, get_dialect
from core.production_time import production_date_sql_expr

# Bảng bí danh field: chấp nhận cả PascalCase (theo header Excel gốc) lẫn
# snake_case (theo cột DB) để hàm phân loại badge không phụ thuộc nguồn dữ liệu.
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "dyelot": ("Dyelot", "dyelot"),
    "batch_type": ("BatchType", "batch_type", "Batch_Type"),
    "redye": ("ReDye", "redye", "re_dye"),
    "shade": ("Shade", "shade"),
    "colour_no": ("ColourNo", "colour_no", "Color", "color", "CustomerColor"),
    "recipe_no": ("RecipeNo", "recipe_no"),
    "customer_color": ("CustomerColor", "customer_color"),
    # Số phút Rework đo thực tế trên chính dòng lịch máy (availability_logs.rework) —
    # khảo sát dữ liệu thật cho thấy đây là tín hiệu Rework đáng tin cậy nhất vì
    # batch_type/is_rework từ file Batch Detail hầu như luôn rỗng ("Unknown").
    "log_rework_minutes": ("log_rework_minutes",),
}

# Toàn bộ 11 mã badge hợp lệ (dùng để log kiểm tra đầu ra).
ALL_BADGE_CODES = ("CM", "B", "D", "M", "L", "W", "BR", "DR", "MR", "LR", "WR")

# Từ khoá tông màu Đậm/Nhạt được đúc kết từ ColourNo thực tế trong hệ thống
# (VD: "115-23-11-MARINE BLUE" -> Đậm, "096-70-05-MORDEN MINT" -> Nhạt).
# Chỉ đưa vào các từ có tính đặc trưng cao để tránh đoán sai các tông trung tính
# (GREY/HEATHER/PURPLE/AQUA... vẫn rơi về Medium mặc định).
DARK_KEYWORDS = ("DARK", "DEEP", "NAVY", "MARINE", "CHARCOAL", "MAROON", "BURGUNDY", "EBONY", "MIDNIGHT", "INDIGO", "SHADOW", "GRAPHITE", "ESPRESSO", "COFFEE")
LIGHT_KEYWORDS = ("LIGHT", "PALE", "PASTEL", "CREAM", "IVORY", "BEIGE", "BLUSH", "PEACH", "MINT", "SKY", "BABY", "POWDER", "LILAC", "ROSE", "LEMON", "PINK", "PEARL", "ECRU", "BLANCH")

logger = logging.getLogger(__name__)


def _get_field(batch: Mapping[str, Any], name: str) -> str:
    """Lấy giá trị field từ Object/Row Batch, chấp nhận cả hai định dạng key (Upper/snake_case)."""
    for key in FIELD_ALIASES.get(name, (name,)):
        try:
            value = batch[key]
        except (KeyError, IndexError, TypeError):
            continue
        if value not in (None, ""):
            return str(value)
    return ""


def classify_batch_badge(batch: Mapping[str, Any]) -> str:
    """Phân loại Batch Badge theo thuật toán 5 bước (CM -> Rework -> Base color -> ghép mã)."""
    # Bước 1: Mẻ rửa máy — Dyelot chứa '-WA' -> dừng kiểm tra, trả về CM ngay.
    dyelot = _get_field(batch, "dyelot").upper()
    if "-WA" in dyelot:
        return "CM"

    # Bước 3: Xác định tông màu cơ bản (B/W/D/M/L) từ ColourNo + RecipeNo + CustomerColor.
    colour_no = _get_field(batch, "colour_no")
    recipe_no = _get_field(batch, "recipe_no")
    customer_color = _get_field(batch, "customer_color")
    text_check = f"{colour_no} {recipe_no} {customer_color}".upper()
    shade = _get_field(batch, "shade").upper()

    if "BLACK" in text_check or "BLK" in text_check:
        base = "B"
    elif "WHITE" in text_check or "WHT" in text_check or "BLANCH" in text_check:
        base = "W"
    elif shade == "DARK":
        base = "D"
    elif shade == "MEDIUM":
        base = "M"
    elif shade == "LIGHT":
        base = "L"
    elif any(keyword in text_check for keyword in LIGHT_KEYWORDS):
        base = "L"
    elif any(keyword in text_check for keyword in DARK_KEYWORDS):
        base = "D"
    else:
        # Fallback mặc định khi hoàn toàn không có thông tin -> 'M', TUYỆT ĐỐI không phải 'D'.
        base = "M"

    # Bước 2: Xác định trạng thái Rework — CHỈ dựa vào nhãn khai báo (batch_type='Rework')
    # hoặc tín hiệu đo thực tế (log_rework_minutes, tức availability_logs.rework_hour —
    # số phút Rework THẬT SỰ ghi nhận trong ca chạy máy). KHÔNG dùng cờ `redye`: ReDye nghĩa
    # là mẻ quay LẠI máy nhuộm để chạy một QUY TRÌNH KHÁC (nhuộm lại màu/xử lý bổ sung theo
    # kế hoạch), KHÔNG đồng nghĩa với Rework (sửa lỗi/chạy lại do hỏng) — batch_type='Normal'
    # kèm redye=1 là tình huống hợp lệ, không phải mẻ lỗi (bug đã phát hiện qua báo cáo thực
    # tế: mẻ C260661030, xem memory-bank/activeContext.md).
    batch_type = _get_field(batch, "batch_type").upper()
    log_rework_raw = _get_field(batch, "log_rework_minutes")
    try:
        log_rework_minutes = float(log_rework_raw) if log_rework_raw else 0.0
    except ValueError:
        log_rework_minutes = 0.0
    is_rework = batch_type == "REWORK" or log_rework_minutes > 0

    # Bước 4: Ghép mã badge cuối cùng.
    return f"{base}R" if is_rework else base


# ---------------------------------------------------------------------------
# Daily Rollup Pattern (xem memory-bank/systemPatterns.md mục 6.2)
#
# KHÁC với downtime/batch_matrix: Cleaning MC hiển thị CHI TIẾT TỪNG MẺ theo trình tự
# (lịch máy dạng chuỗi badge, không phải số liệu đã gộp) — nên `cleaning_mc_daily_summary`
# lưu ở GRAIN 1 DÒNG = 1 MẺ (đã JOIN + phân loại badge sẵn), KHÔNG phải số đếm. Phần tốn
# kém (JOIN availability_logs x batch_details x machines VỚI điều kiện lower(trim(...))
# không dùng được index — xem log baseline 28s/full scan — + phân loại badge 5 bước) chỉ
# chạy 1 lần trong recompute_daily() cho đúng 1 production_date; đọc báo cáo chỉ SELECT
# từ bảng đã tổng hợp sẵn, dựng lại cấu trúc machines/days/batches y hệt code cũ.
# ---------------------------------------------------------------------------


def _ensure_batch_details_columns(conn: Any) -> None:
    """CHỈ chạy CREATE TABLE ở SQLite — ở Postgres `batch_details`/`machines` đã có sẵn qua
    `supabase/schema.sql` (đầy đủ cột hơn bản tối giản này, vốn chỉ để tự vá DB SQLite cũ)."""
    if get_dialect() == "sqlite":
        conn.execute("""
            CREATE TABLE IF NOT EXISTS batch_details (
                dyelot TEXT PRIMARY KEY, shade TEXT, colour_no TEXT, batch_type TEXT, is_rework INTEGER DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
    batch_columns = {row["name"] for row in conn.execute("PRAGMA table_info(batch_details)")}
    for column, definition in (("colour_no", "TEXT"), ("is_rework", "INTEGER NOT NULL DEFAULT 0"), ("recipe_no", "TEXT"), ("customer_color", "TEXT")):
        if column not in batch_columns:
            conn.execute(f"ALTER TABLE batch_details ADD COLUMN {column} {definition}")
    machine_columns = {row["name"] for row in conn.execute("PRAGMA table_info(machines)")}
    for column, definition in (("machine_code", "TEXT"), ("mc_brand", "TEXT"), ("tank_type", "TEXT"), ("mc_quantity", "INTEGER"), ("tube_no", "INTEGER"), ("capacity_kg", "REAL")):
        if column not in machine_columns:
            conn.execute(f"ALTER TABLE machines ADD COLUMN {column} {definition}")
    # Expression index cho đúng điều kiện JOIN lower(trim(...)) dùng trong recompute_daily() —
    # thiếu index này khiến SQLite phải SCAN nested-loop (đo thực tế: 436ms/ngày -> 3ms/ngày
    # sau khi có index, ~145 lần). Không đổi kết quả truy vấn, chỉ đổi execution plan.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_batch_details_dyelot_norm ON batch_details (LOWER(TRIM(dyelot)))")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_availability_batch_norm ON availability_logs (LOWER(TRIM(batch)))")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_availability_batch_ref_norm ON availability_logs (LOWER(TRIM(batch_ref_no)))")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_machines_code_norm ON machines (LOWER(TRIM(COALESCE(machine_code, machine_id))))")
    conn.commit()


def _ensure_summary_table(conn: Any) -> None:
    """CHỈ chạy CREATE TABLE ở SQLite — ở Postgres bảng đã có sẵn qua `supabase/schema.sql`."""
    if get_dialect() == "sqlite":
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cleaning_mc_daily_summary (
                production_date TEXT NOT NULL,
                availability_log_id INTEGER NOT NULL,
                machine TEXT NOT NULL,
                capacity_kg REAL NOT NULL DEFAULT 0,
                configured_capacity_kg REAL,
                machine_code TEXT,
                mc_brand TEXT,
                tank_type TEXT,
                mc_quantity INTEGER,
                tube_no TEXT,
                sequence_order TEXT,
                batch_no TEXT,
                dyelot_ref TEXT,
                shade_raw TEXT,
                colour_no TEXT,
                batch_type TEXT,
                start_time TEXT,
                end_time TEXT,
                program TEXT,
                badge TEXT NOT NULL,
                is_rework INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (production_date, availability_log_id)
            )
        """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cleaning_mc_daily_summary_date ON cleaning_mc_daily_summary (production_date)")


def recompute_daily(production_date: date, conn: Any) -> None:
    """Tính lại `cleaning_mc_daily_summary` cho ĐÚNG 1 production_date — idempotent
    (DELETE dòng cũ của ngày này rồi INSERT lại từ raw data). JOIN + phân loại badge
    (`classify_batch_badge`) CHỈ chạy ở đây, không chạy lúc đọc báo cáo."""
    _ensure_batch_details_columns(conn)
    _ensure_summary_table(conn)
    day_str = production_date.isoformat()
    conn.execute("DELETE FROM cleaning_mc_daily_summary WHERE production_date = ?", (day_str,))

    availability_columns = {row["name"] for row in conn.execute("PRAGMA table_info(availability_logs)")}
    batch_columns = {row["name"] for row in conn.execute("PRAGMA table_info(batch_details)")}
    sequence_expression = 'a."sequence_order"' if "sequence_order" in availability_columns else 'a."start_time"'
    shifted_date = production_date_sql_expr("COALESCE(a.end_time, a.start_time)")

    sql = f"""
         SELECT a.id AS availability_log_id, a.machine, a.capacity_kg, a.program, a.start_time, a.end_time,
             a.rework_hour AS log_rework_minutes,
             a.batch_ref_no, a.batch, {sequence_expression} AS sequence_order, COALESCE(b.shade, '') AS shade,
             COALESCE(b.colour_no, '') AS colour_no, COALESCE(b.customer_color, '') AS customer_color, COALESCE(b.batch_type, '') AS batch_type,
             COALESCE(b.recipe_no, '') AS recipe_no,
             {('COALESCE(b.redye, 0)' if 'redye' in batch_columns else '0')} AS redye,
             COALESCE(b.is_rework, 0) AS is_rework, COALESCE(b.dyelot, '') AS dyelot_ref,
             COALESCE(m.machine_code, a.machine) AS machine_code, m.mc_brand, m.tank_type, m.mc_quantity, m.tube_no,
             COALESCE(m.capacity_kg, a.capacity_kg) AS configured_capacity_kg
        FROM availability_logs a
        LEFT JOIN batch_details b ON lower(trim(b.dyelot)) = lower(trim(a.batch_ref_no)) OR lower(trim(b.dyelot)) = lower(trim(a.batch))
        LEFT JOIN machines m ON lower(trim(COALESCE(m.machine_code, m.machine_id))) = lower(trim(a.machine))
        WHERE {shifted_date} = ?
    """
    rows = conn.execute(sql, (day_str,)).fetchall()
    if not rows:
        return

    inserts = []
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for row in rows:
        batch_no = "|".join(value for value in (row["batch_ref_no"], row["batch"]) if value)
        batch_record = {
            "dyelot": row["dyelot_ref"] or batch_no,
            "batch_type": row["batch_type"],
            "redye": row["redye"],
            "shade": row["shade"],
            "colour_no": row["colour_no"],
            "recipe_no": row["recipe_no"],
            "customer_color": row["customer_color"],
            "log_rework_minutes": row["log_rework_minutes"],
        }
        badge = classify_batch_badge(batch_record)
        is_rework = badge.endswith("R")
        inserts.append((
            day_str, row["availability_log_id"], row["machine"], float(row["capacity_kg"] or 0), row["configured_capacity_kg"],
            row["machine_code"], row["mc_brand"], row["tank_type"], row["mc_quantity"], row["tube_no"],
            row["sequence_order"], batch_no, row["dyelot_ref"], row["shade"], row["colour_no"], row["batch_type"],
            row["start_time"], row["end_time"], row["program"], badge, int(is_rework), now_str,
        ))

    conn.executemany(
        """
        INSERT INTO cleaning_mc_daily_summary (
            production_date, availability_log_id, machine, capacity_kg, configured_capacity_kg,
            machine_code, mc_brand, tank_type, mc_quantity, tube_no,
            sequence_order, batch_no, dyelot_ref, shade_raw, colour_no, batch_type,
            start_time, end_time, program, badge, is_rework, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        inserts,
    )


def get_cleaning_matrix(from_date: str | None = None, to_date: str | None = None, capacities: list[float] | None = None) -> dict[str, Any]:
    conn = get_db()
    _ensure_summary_table(conn)

    sql = "SELECT * FROM cleaning_mc_daily_summary WHERE 1=1"
    params: list[Any] = []
    if from_date:
        sql += " AND production_date >= ?"
        params.append(from_date)
    if to_date:
        sql += " AND production_date <= ?"
        params.append(to_date)
    sql += " ORDER BY production_date, machine, sequence_order, start_time, end_time"
    try:
        rows = execute_query(sql, params)
    except Exception as exc:
        return {"time_labels": [], "daily_sequence": {}, "error": str(exc), "kpis": {"normal_batches": 0, "cleaning_count": 0, "cleaning_ratio": 0.0, "rework_batches": 0}, "matrix": [], "available_capacities": []}

    # Quét toàn bộ mức Capacity thực tế có trong dữ liệu (trước khi áp filter) để làm nguồn cho bộ lọc.
    available_capacities = sorted({round(float(row["configured_capacity_kg"]), 2) for row in rows if row["configured_capacity_kg"] not in (None, "")})
    capacity_filter = {round(float(value), 2) for value in capacities} if capacities else None

    machines: dict[tuple[str, float], dict[str, Any]] = {}
    normal = cleaning_count = rework = 0
    badge_counter: Counter[str] = Counter()
    # Đếm bao nhiêu dòng lịch máy KHÔNG join được với batch_details (thiếu ColourNo/Shade
    # nguồn) — dùng để phân biệt "toàn M vì thiếu dữ liệu import" với lỗi thuật toán thật.
    color_source_missing = color_source_present = 0
    for row in rows:
        if capacity_filter is not None:
            row_capacity = round(float(row["configured_capacity_kg"]), 2) if row["configured_capacity_kg"] not in (None, "") else None
            if row_capacity not in capacity_filter:
                continue
        machine_key = (row["machine"], float(row["capacity_kg"] or 0))
        normalized_batch_type = str(row["batch_type"] or "").strip().lower()
        if not normalized_batch_type:
            normalized_batch_type = "normal"
        item = machines.setdefault(machine_key, {"machine": row["machine_code"], "machine_code": row["machine_code"], "mc_brand": row["mc_brand"] or "-", "tank_type": row["tank_type"] or "-", "mc_quantity": row["mc_quantity"] or 1, "tube_no": row["tube_no"] or "-", "capacity": row["configured_capacity_kg"], "cleaning_count": 0, "normal_batches": 0, "rd_batches": 0, "rework_batches": 0, "days": {}, "batches": []})
        if row["dyelot_ref"] or row["colour_no"] or row["shade_raw"]:
            color_source_present += 1
        else:
            color_source_missing += 1
        code = row["badge"]
        is_rework_badge = bool(row["is_rework"])
        badge_counter[code] += 1
        day = row["production_date"] or "Unknown"
        item["days"].setdefault(day, []).append(code)
        item["batches"].append({"batch_no": row["batch_no"], "machine_code": row["machine_code"], "mc_brand": row["mc_brand"], "tank_type": row["tank_type"], "capacity_kg": row["configured_capacity_kg"], "shade_raw": row["shade_raw"], "colour_no": row["colour_no"], "batch_type": normalized_batch_type, "sequence_order": row["sequence_order"], "production_date": day, "start_time": row["start_time"], "end_time": row["end_time"], "duration_minutes": round((datetime.fromisoformat(row["end_time"]) - datetime.fromisoformat(row["start_time"])).total_seconds() / 60, 1) if row["start_time"] and row["end_time"] else None, "program": row["program"], "color_code_display": code, "is_rework": is_rework_badge})
        if code == "CM":
            item["cleaning_count"] += 1
            cleaning_count += 1
        elif not is_rework_badge and normalized_batch_type in {"normal", "unknown", ""}:
            item["normal_batches"] += 1
            normal += 1
        if normalized_batch_type in {"r&d", "rd", "research", "development"}:
            item["rd_batches"] += 1
        if is_rework_badge:
            item["rework_batches"] += 1
            rework += 1
    matrix = []
    for item in machines.values():
        item["cleaning_ratio"] = round(item["normal_batches"] / item["cleaning_count"], 2) if item["cleaning_count"] else None
        matrix.append(item)
    time_labels = sorted({day for item in matrix for day in item["days"]})
    logger.info(
        "Machine Scheduling Matrix badge check: found=%s missing=%s counts=%s | batch_details join coverage: co_du_lieu_mau=%d thieu_du_lieu_mau=%d (%.0f%% thiếu -> cần bổ sung file Batch Detail nếu tỷ lệ cao)",
        sorted(badge_counter),
        [code for code in ALL_BADGE_CODES if code not in badge_counter],
        dict(badge_counter),
        color_source_present,
        color_source_missing,
        (100.0 * color_source_missing / len(rows)) if rows else 0.0,
    )
    return {
        "time_labels": time_labels,
        "daily_sequence": {item["machine_code"]: item["days"] for item in matrix},
        "kpis": {"normal_batches": normal, "cleaning_count": cleaning_count, "cleaning_ratio": round(normal / cleaning_count, 2) if cleaning_count else 0.0, "rework_batches": rework},
        "matrix": matrix,
        "available_capacities": available_capacities,
        "color_data_coverage": {
            "present": color_source_present,
            "missing": color_source_missing,
            "missing_pct": round(100.0 * color_source_missing / len(rows), 1) if rows else 0.0,
        },
    }
