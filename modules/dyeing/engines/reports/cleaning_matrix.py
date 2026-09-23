from __future__ import annotations

import calendar
import io
import logging
from collections import Counter, defaultdict
from datetime import date, datetime
from typing import Any, Mapping

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from core.batch_details_match import batch_details_join_sql
from core.brand_program_importer import ensure_brand_program_table
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
    "sap_lot": ("SapLot", "sap_lot"),
}

# Toàn bộ 11 mã badge hợp lệ (dùng để log kiểm tra đầu ra).
ALL_BADGE_CODES = ("CM", "B", "D", "M", "L", "W", "BR", "DR", "MR", "LR", "WR")

# Thứ tự cột hiển thị cho summary "Normal Dyeing Batches by Colour" (theo đúng thứ tự
# người dùng yêu cầu) — chỉ tính mẻ Normal (không CM, không Rework), map trực tiếp từ
# base badge code (B/D/M/L/W) đã phân loại sẵn ở `classify_batch_badge()`.
COLOR_LABEL_ORDER = ("Dark", "Light", "Medium", "Black", "White")
BADGE_TO_COLOR_LABEL: dict[str, str] = {"D": "Dark", "L": "Light", "M": "Medium", "B": "Black", "W": "White"}

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


def _dyelot_indicates_rework(dyelot: str | None) -> bool:
    """Điều kiện (a) của quy tắc Rework: chữ số CUỐI CÙNG của Dyelot là CHỮ SỐ khác '0'. Tách
    riêng hàm này (không viết trực tiếp trong `classify_batch_badge()`) để dùng lại CHÍNH XÁC
    ở `get_batch_summary()` khi người dùng bật nút "Ignore SapLot" trên tab Summary — tránh 2
    nơi tự viết lại cùng 1 quy tắc rồi lệch nhau nếu sau này chỉ sửa 1 chỗ."""
    dyelot = (dyelot or "").strip()
    return bool(dyelot) and dyelot[-1].isdigit() and dyelot[-1] != "0"


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

    # Bước 2: Xác định trạng thái Rework — 2 điều kiện dựa trên MÃ (Dyelot/SapLot), THAY THẾ
    # hoàn toàn cách cũ (batch_type='Rework' HOẶC log_rework_minutes>0) theo yêu cầu người dùng
    # (2026-09-22 bản 3):
    #   (a) CHỈ xét khi chữ số CUỐI CÙNG của Dyelot là CHỮ SỐ: khác '0' -> Rework, bằng '0' ->
    #       Normal. Dyelot kết thúc bằng CHỮ CÁI (hậu tố như "-WA"/"-KN"/"-DU" — mẻ rửa máy/mẻ
    #       thử nghiệm "experiment" hay bị loại khỏi tính toán khác) KHÔNG tính là tín hiệu
    #       Rework từ điều kiện này (mặc định Normal, kể cả hậu tố lạ chưa từng gặp — người
    #       dùng xác nhận rõ, "-WA" vẫn trả "CM" riêng ở Bước 1, không bao giờ chạm tới đây).
    #   (b) Chữ số ĐẦU TIÊN của SapLot > 1 -> Rework, = 1 -> Normal. SapLot rỗng/không bắt đầu
    #       bằng chữ số -> KHÔNG tính là tín hiệu Rework từ điều kiện này (an toàn, không bịa).
    # 2 điều kiện nối bằng HOẶC — chỉ cần 1 trong 2 báo Rework là đủ.
    dyelot_rework = _dyelot_indicates_rework(dyelot)

    sap_lot = _get_field(batch, "sap_lot")
    sap_lot_rework = False
    if sap_lot and sap_lot[0].isdigit():
        sap_lot_rework = int(sap_lot[0]) > 1

    is_rework = dyelot_rework or sap_lot_rework

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
        # id surrogate PK (KHÔNG còn `dyelot TEXT PRIMARY KEY`) — đồng bộ với schema mới của
        # `core/batch_importer.py::sync_batch_details()` (1 dyelot có thể có NHIỀU dòng, VD mẻ
        # gốc + mẻ redye). Bảng thường đã được tạo/migrate trước qua `core.batch_importer.
        # init_app()` lúc app khởi động, nhưng vẫn cần CREATE TABLE ĐÚNG schema ở đây phòng khi
        # hàm này chạy trước (batch_details chưa từng tồn tại) — nếu tạo sai schema cũ ở đây,
        # `batch_details_join_sql()` (tham chiếu cột `id`) sẽ lỗi "no such column".
        conn.execute("""
            CREATE TABLE IF NOT EXISTS batch_details (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dyelot TEXT NOT NULL, shade TEXT, colour_no TEXT, batch_type TEXT, is_rework INTEGER DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
    batch_columns = {row["name"] for row in conn.execute("PRAGMA table_info(batch_details)")}
    for column, definition in (("colour_no", "TEXT"), ("is_rework", "INTEGER NOT NULL DEFAULT 0"), ("recipe_no", "TEXT"), ("customer_color", "TEXT"), ("sap_lot", "TEXT")):
        if column not in batch_columns:
            conn.execute(f"ALTER TABLE batch_details ADD COLUMN {column} {definition}")
    machine_columns = {row["name"] for row in conn.execute("PRAGMA table_info(machines)")}
    # group_mc/status/production_status/orgatex (2026-09-22): bảng `machines` đổi vai trò
    # thành "Machine Master" — NGUỒN DUY NHẤT quyết định danh sách máy hiển thị trên báo
    # cáo "Batch Per Day by Machine" (xem get_cleaning_matrix()), không còn chỉ là bảng
    # enrichment tuỳ chọn. status/production_status là TEXT tự do ở tầng DB (validate giá
    # trị hợp lệ ở upsert_machine_config(), KHÔNG dùng CHECK constraint vì SQLite không thể
    # ALTER TABLE ADD COLUMN kèm CHECK — phải dựng lại bảng, không đáng làm cho migration
    # nhỏ này). orgatex là cờ boolean 0/1.
    for column, definition in (("machine_code", "TEXT"), ("mc_brand", "TEXT"), ("tank_type", "TEXT"), ("mc_quantity", "INTEGER"), ("tube_no", "INTEGER"), ("capacity_kg", "REAL"), ("group_mc", "TEXT"), ("status", "TEXT"), ("production_status", "TEXT"), ("orgatex", "INTEGER NOT NULL DEFAULT 0")):
        if column not in machine_columns:
            conn.execute(f"ALTER TABLE machines ADD COLUMN {column} {definition}")
    # Expression index cho đúng điều kiện JOIN lower(trim(...)) dùng trong recompute_daily() —
    # thiếu index này khiến SQLite phải SCAN nested-loop (đo thực tế: 436ms/ngày -> 3ms/ngày
    # sau khi có index, ~145 lần). Không đổi kết quả truy vấn, chỉ đổi execution plan.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_batch_details_dyelot_norm ON batch_details (LOWER(TRIM(dyelot)))")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_batch_details_greige_code_norm ON batch_details (LOWER(TRIM(greige_code)))")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_availability_batch_norm ON availability_logs (LOWER(TRIM(batch)))")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_availability_batch_ref_norm ON availability_logs (LOWER(TRIM(batch_ref_no)))")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_machines_code_norm ON machines (LOWER(TRIM(COALESCE(machine_code, machine_id))))")
    conn.commit()


def _ensure_summary_table(conn: Any) -> None:
    """CHỈ chạy DDL ở SQLite — ở Postgres bảng/cột đã có sẵn qua `supabase/schema.sql`
    (bản mới) hoặc phải áp `supabase/migrate_brand_program_mapping.sql` thủ công (bản cũ
    đã deploy trước khi có cột `brand_program`/`brand` — xem systemPatterns.md mục 5.1)."""
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
                brand_program TEXT,
                brand TEXT,
                fabric_type TEXT,
                badge TEXT NOT NULL,
                is_rework INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (production_date, availability_log_id)
            )
        """)
        existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(cleaning_mc_daily_summary)")}
        for column in ("brand_program", "brand", "fabric_type"):
            if column not in existing_cols:
                conn.execute(f"ALTER TABLE cleaning_mc_daily_summary ADD COLUMN {column} TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cleaning_mc_daily_summary_date ON cleaning_mc_daily_summary (production_date)")


def _orphan_batch_rows(conn: Any, day_str: str, batch_columns: set[str]) -> list[Any]:
    """Lấy các dòng `batch_details` KHÔNG khớp bất kỳ dòng nào trong `availability_logs`
    (theo `batch`/`batch_ref_no`) và có production_date (tính từ EndTime/StartTime của
    chính batch_details) đúng bằng `day_str` — đây là các mẻ chạy trên MÁY chỉ tồn tại
    trong Batch Detail (VD line Polyester riêng dùng mã máy `0101`/`16xx`/`Hxxx`, xem
    memory-bank/activeContext.md), chưa từng được import qua Availability nên trước đây
    hoàn toàn KHÔNG xuất hiện trên báo cáo (vì hàm này trước đó chỉ FROM availability_logs).
    KHÔNG hardcode danh sách mã máy — mọi mẻ "mồ côi" nào khớp điều kiện đều được gộp vào,
    tự động phủ cả máy mới phát sinh sau này."""
    shifted_date_batch = production_date_sql_expr("COALESCE(b.end_time, b.start_time)")
    sql = f"""
         SELECT b.dyelot AS dyelot_ref, b.machine, b.start_time, b.end_time,
             COALESCE(b.batch_type, '') AS batch_type,
             {('COALESCE(b.redye, 0)' if 'redye' in batch_columns else '0')} AS redye,
             COALESCE(b.shade, '') AS shade, COALESCE(b.colour_no, '') AS colour_no,
             COALESCE(b.recipe_no, '') AS recipe_no, COALESCE(b.customer_color, '') AS customer_color,
             COALESCE(b.sap_lot, '') AS sap_lot,
             COALESCE(b.is_rework, 0) AS is_rework,
             COALESCE(m.machine_code, b.machine) AS machine_code, m.mc_brand, m.tank_type, m.mc_quantity, m.tube_no,
             m.capacity_kg AS configured_capacity_kg,
             COALESCE(bp.brand_program, '') AS brand_program, COALESCE(bp.brand, '') AS brand,
             {('COALESCE(b.fabric_type, \'\')' if 'fabric_type' in batch_columns else "''")} AS fabric_type
        FROM batch_details b
        LEFT JOIN machines m ON lower(trim(COALESCE(m.machine_code, m.machine_id))) = lower(trim(b.machine))
        LEFT JOIN brand_program_mapping bp ON lower(trim(bp.greige_code)) = lower(trim(b.greige_code))
        WHERE b.machine IS NOT NULL AND TRIM(b.machine) != ''
          AND {shifted_date_batch} = ?
          AND NOT EXISTS (
              SELECT 1 FROM availability_logs a2
              WHERE lower(trim(a2.batch)) = lower(trim(b.dyelot)) OR lower(trim(a2.batch_ref_no)) = lower(trim(b.dyelot))
          )
    """
    return conn.execute(sql, (day_str,)).fetchall()


def recompute_daily(production_date: date, conn: Any) -> None:
    """Tính lại `cleaning_mc_daily_summary` cho ĐÚNG 1 production_date — idempotent
    (DELETE dòng cũ của ngày này rồi INSERT lại từ raw data). JOIN + phân loại badge
    (`classify_batch_badge`) CHỈ chạy ở đây, không chạy lúc đọc báo cáo.

    Gộp 2 nguồn: (1) mọi dòng `availability_logs` của ngày này (như trước), VÀ (2) các
    dòng `batch_details` "mồ côi" — có Machine/Time riêng nhưng KHÔNG có bản ghi
    `availability_logs` tương ứng (xem `_orphan_batch_rows()`) — để các máy chỉ tồn tại ở
    nguồn Batch Detail vẫn hiện đúng trên báo cáo Batch Per Day by Machine, KHÔNG chỉ ẩn đi
    vì thiếu Availability."""
    _ensure_batch_details_columns(conn)
    _ensure_summary_table(conn)
    ensure_brand_program_table(conn)
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
             COALESCE(b.sap_lot, '') AS sap_lot,
             {('COALESCE(b.redye, 0)' if 'redye' in batch_columns else '0')} AS redye,
             COALESCE(b.is_rework, 0) AS is_rework, COALESCE(b.dyelot, '') AS dyelot_ref,
             COALESCE(m.machine_code, a.machine) AS machine_code, m.mc_brand, m.tank_type, m.mc_quantity, m.tube_no,
             COALESCE(m.capacity_kg, a.capacity_kg) AS configured_capacity_kg,
             COALESCE(bp.brand_program, '') AS brand_program, COALESCE(bp.brand, '') AS brand,
             COALESCE(a.fabric_type, '') AS fabric_type
        FROM availability_logs a
        {batch_details_join_sql(["a.batch_ref_no", "a.batch"], "a.end_time")}
        LEFT JOIN machines m ON lower(trim(COALESCE(m.machine_code, m.machine_id))) = lower(trim(a.machine))
        LEFT JOIN brand_program_mapping bp ON lower(trim(bp.greige_code)) = lower(trim(b.greige_code))
        WHERE {shifted_date} = ?
    """
    rows = conn.execute(sql, (day_str,)).fetchall()
    orphan_rows = _orphan_batch_rows(conn, day_str, batch_columns)
    if not rows and not orphan_rows:
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
            "sap_lot": row["sap_lot"],
        }
        badge = classify_batch_badge(batch_record)
        is_rework = badge.endswith("R")
        inserts.append((
            day_str, row["availability_log_id"], row["machine"], float(row["capacity_kg"] or 0), row["configured_capacity_kg"],
            row["machine_code"], row["mc_brand"], row["tank_type"], row["mc_quantity"], row["tube_no"],
            row["sequence_order"], batch_no, row["dyelot_ref"], row["shade"], row["colour_no"], row["batch_type"],
            row["start_time"], row["end_time"], row["program"], row["brand_program"], row["brand"], row["fabric_type"], badge, int(is_rework), now_str,
        ))

    # `availability_log_id` âm (-1, -2, ...) đánh dấu mẻ "mồ côi" (không có availability_logs.id
    # thật) — chỉ cần duy nhất TRONG PHẠM VI 1 production_date (khoá PK là cặp
    # (production_date, availability_log_id)), KHÔNG bao giờ đụng độ với id thật (luôn dương).
    for index, row in enumerate(orphan_rows, start=1):
        batch_record = {
            "dyelot": row["dyelot_ref"],
            "batch_type": row["batch_type"],
            "redye": row["redye"],
            "shade": row["shade"],
            "colour_no": row["colour_no"],
            "recipe_no": row["recipe_no"],
            "customer_color": row["customer_color"],
            "log_rework_minutes": 0,
            "sap_lot": row["sap_lot"],
        }
        badge = classify_batch_badge(batch_record)
        is_rework = badge.endswith("R")
        capacity_value = float(row["configured_capacity_kg"] or 0)
        inserts.append((
            day_str, -index, row["machine"], capacity_value, row["configured_capacity_kg"],
            row["machine_code"], row["mc_brand"], row["tank_type"], row["mc_quantity"], row["tube_no"],
            row["start_time"], row["dyelot_ref"], row["dyelot_ref"], row["shade"], row["colour_no"], row["batch_type"],
            row["start_time"], row["end_time"], None, row["brand_program"], row["brand"], row["fabric_type"], badge, int(is_rework), now_str,
        ))

    conn.executemany(
        """
        INSERT INTO cleaning_mc_daily_summary (
            production_date, availability_log_id, machine, capacity_kg, configured_capacity_kg,
            machine_code, mc_brand, tank_type, mc_quantity, tube_no,
            sequence_order, batch_no, dyelot_ref, shade_raw, colour_no, batch_type,
            start_time, end_time, program, brand_program, brand, fabric_type, badge, is_rework, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        inserts,
    )


def _normalize_code(value: Any) -> str:
    return str(value or "").strip().lower()


def _blank_machine_item(machine_label: str, machine_code: str | None, master: Mapping[str, Any] | None) -> dict[str, Any]:
    """Khung 1 dòng machine cho matrix — dùng CHUNG cho máy có trong Machine Master (đủ
    thuộc tính) LẪN máy 'unmapped' (có mẻ thật nhưng chưa khai báo, `master=None`)."""
    return {
        "machine": machine_label,
        "machine_code": machine_code,
        "group_mc": ((master["group_mc"] if master else None) or "-"),
        "mc_brand": ((master["mc_brand"] if master else None) or "-"),
        "tank_type": ((master["tank_type"] if master else None) or "-"),
        "mc_quantity": ((master["mc_quantity"] if master else None) or 1),
        "tube_no": ((master["tube_no"] if master else None) or "-"),
        "capacity": (master["capacity_kg"] if master else None),
        "status": ((master["status"] if master else None) or "-"),
        "production_status": ((master["production_status"] if master else None) or "-"),
        "orgatex": bool(master["orgatex"]) if master and master["orgatex"] is not None else False,
        "is_unmapped": master is None,
        "cleaning_count": 0, "normal_batches": 0, "rd_batches": 0, "rework_batches": 0, "days": {}, "batches": [],
    }


def get_cleaning_matrix(
    from_date: str | None = None, to_date: str | None = None, capacities: list[float] | None = None,
    brand_programs: list[str] | None = None, fabric_types: list[str] | None = None,
) -> dict[str, Any]:
    """Danh sách machine hiển thị (2026-09-22, đổi thiết kế theo yêu cầu người dùng) giờ
    LUÔN xuất phát từ Machine Master (`machines`, domain='dyeing') — KHÔNG còn tự phát hiện
    từ chính dữ liệu batch như bản cũ (máy chưa có mẻ trong kỳ đang lọc vẫn hiện đủ, với các
    cột ngày để trống). Batch nào có `machine` KHÔNG khớp mã máy nào trong Machine Master vẫn
    được GIỮ LẠI (không âm thầm bỏ, đúng nguyên tắc 'double-check' của dự án — mọi số liệu
    hiển thị phải khớp dữ liệu gốc) dưới dạng dòng 'unmapped' (`is_unmapped=True`, luôn hiện
    bất kể filter Capacity vì chưa có capacity khai báo để so khớp) kèm cảnh báo
    `unmapped_machines` trả về cho UI nhắc khai báo qua "Add Machine"."""
    conn = get_db()
    _ensure_batch_details_columns(conn)
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
    empty_result = {"time_labels": [], "daily_sequence": {}, "kpis": {"normal_batches": 0, "cleaning_count": 0, "cleaning_ratio": 0.0, "rework_batches": 0}, "matrix": [], "available_capacities": [], "available_brand_programs": [], "available_fabric_types": [], "color_summary": {"labels": list(COLOR_LABEL_ORDER), "by_day": {}}, "unmapped_machines": []}
    try:
        rows = execute_query(sql, params)
        master_rows = execute_query(
            "SELECT machine_id, machine_code, group_mc, mc_brand, tank_type, mc_quantity, tube_no, capacity_kg, "
            "status, production_status, orgatex FROM machines WHERE domain = 'dyeing' "
            "ORDER BY COALESCE(group_mc, ''), COALESCE(machine_code, machine_id)",
            [],
        )
    except Exception as exc:
        return {**empty_result, "error": str(exc)}

    # available_capacities giờ lấy từ capacity_kg đã KHAI BÁO trong Machine Master, không
    # còn suy từ configured_capacity_kg thô của batch — máy chưa chạy mẻ nào vẫn góp mặt
    # vào bộ lọc nếu đã khai báo Capacity.
    available_capacities = sorted({round(float(m["capacity_kg"]), 2) for m in master_rows if m["capacity_kg"] not in (None, "")})
    capacity_filter = {round(float(value), 2) for value in capacities} if capacities else None
    # Brand Program gộp "Brand - Program" (VD "UQ - Ht Fleece") thành 1 giá trị filter duy nhất —
    # mẻ chưa map được Greige Code nào (đa số, vì mapping chỉ phủ dần theo từng file Brand import)
    # có brand/brand_program rỗng, KHÔNG xuất hiện trong danh sách lọc, luôn hiện khi không lọc.
    available_brand_programs = sorted({f"{row['brand']} - {row['brand_program']}" for row in rows if row["brand"] and row["brand_program"]})
    brand_program_filter = set(brand_programs) if brand_programs else None
    available_fabric_types = sorted({row["fabric_type"] for row in rows if row["fabric_type"]})
    fabric_type_filter = set(fabric_types) if fabric_types else None

    machines: dict[str, dict[str, Any]] = {}
    master_by_norm: dict[str, Mapping[str, Any]] = {}
    for master in master_rows:
        machine_code_value = master["machine_code"] or master["machine_id"]
        if not machine_code_value:
            continue
        norm = _normalize_code(machine_code_value)
        master_by_norm[norm] = master
        if capacity_filter is not None:
            row_capacity = round(float(master["capacity_kg"]), 2) if master["capacity_kg"] not in (None, "") else None
            if row_capacity not in capacity_filter:
                continue
        machines[norm] = _blank_machine_item(machine_code_value, machine_code_value, master)

    unmapped: dict[str, dict[str, Any]] = {}
    normal = cleaning_count = rework = 0
    badge_counter: Counter[str] = Counter()
    # Đếm mẻ Normal (không CM, không Rework) theo (ngày, màu) cho summary "Normal Dyeing
    # Batches by Colour" — CÙNG điều kiện với KPI "Normal Dyeing" (`normal`/`item["normal_batches"]`
    # bên dưới), không định nghĩa tiêu chí "Normal" riêng để tránh 2 số lệch nhau.
    color_by_day: dict[str, Counter[str]] = defaultdict(Counter)
    # Đếm bao nhiêu dòng lịch máy KHÔNG join được với batch_details (thiếu ColourNo/Shade
    # nguồn) — dùng để phân biệt "toàn M vì thiếu dữ liệu import" với lỗi thuật toán thật.
    color_source_missing = color_source_present = 0
    for row in rows:
        if brand_program_filter is not None:
            row_brand_program = f"{row['brand']} - {row['brand_program']}" if row["brand"] and row["brand_program"] else None
            if row_brand_program not in brand_program_filter:
                continue
        if fabric_type_filter is not None and row["fabric_type"] not in fabric_type_filter:
            continue
        raw_machine = (row["machine"] or "").strip()
        norm = _normalize_code(raw_machine)
        item = machines.get(norm)
        if item is None:
            master = master_by_norm.get(norm)
            if master is not None:
                # Máy CÓ trong Machine Master nhưng bị loại bởi filter Capacity đang chọn —
                # đúng ý nghĩa filter, KHÔNG rơi vào nhóm 'unmapped' (đã biết máy này là gì).
                continue
            item = unmapped.setdefault(norm, _blank_machine_item(raw_machine or "(unknown)", None, None))
        normalized_batch_type = str(row["batch_type"] or "").strip().lower()
        if not normalized_batch_type:
            normalized_batch_type = "normal"
        if row["dyelot_ref"] or row["colour_no"] or row["shade_raw"]:
            color_source_present += 1
        else:
            color_source_missing += 1
        code = row["badge"]
        is_rework_badge = bool(row["is_rework"])
        badge_counter[code] += 1
        day = row["production_date"] or "Unknown"
        item["days"].setdefault(day, []).append(code)
        item["batches"].append({"batch_no": row["batch_no"], "machine_code": row["machine_code"], "mc_brand": row["mc_brand"], "tank_type": row["tank_type"], "capacity_kg": row["configured_capacity_kg"], "shade_raw": row["shade_raw"], "colour_no": row["colour_no"], "batch_type": normalized_batch_type, "sequence_order": row["sequence_order"], "production_date": day, "start_time": row["start_time"], "end_time": row["end_time"], "duration_minutes": round((datetime.fromisoformat(row["end_time"]) - datetime.fromisoformat(row["start_time"])).total_seconds() / 60, 1) if row["start_time"] and row["end_time"] else None, "program": row["program"], "brand_program": row["brand_program"] or None, "brand": row["brand"] or None, "color_code_display": code, "is_rework": is_rework_badge})
        if code == "CM":
            item["cleaning_count"] += 1
            cleaning_count += 1
        elif not is_rework_badge and normalized_batch_type in {"normal", "unknown", ""}:
            item["normal_batches"] += 1
            normal += 1
            color_label = BADGE_TO_COLOR_LABEL.get(code)
            if color_label:
                color_by_day[day][color_label] += 1
        if normalized_batch_type in {"r&d", "rd", "research", "development"}:
            item["rd_batches"] += 1
        if is_rework_badge:
            item["rework_batches"] += 1
            rework += 1
    matrix = []
    for item in list(machines.values()) + list(unmapped.values()):
        item["cleaning_ratio"] = round(item["normal_batches"] / item["cleaning_count"], 2) if item["cleaning_count"] else None
        matrix.append(item)
    unmapped_machines = [{"machine": item["machine"], "batch_count": len(item["batches"])} for item in unmapped.values()]
    time_labels = sorted({day for item in matrix for day in item["days"]})
    color_summary = {
        "labels": list(COLOR_LABEL_ORDER),
        "by_day": {day: [color_by_day.get(day, Counter()).get(label, 0) for label in COLOR_LABEL_ORDER] for day in time_labels},
    }
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
        "daily_sequence": {(item["machine_code"] or item["machine"]): item["days"] for item in matrix},
        "kpis": {"normal_batches": normal, "cleaning_count": cleaning_count, "cleaning_ratio": round(normal / cleaning_count, 2) if cleaning_count else 0.0, "rework_batches": rework},
        "matrix": matrix,
        "available_capacities": available_capacities,
        "available_brand_programs": available_brand_programs,
        "available_fabric_types": available_fabric_types,
        "color_summary": color_summary,
        "unmapped_machines": unmapped_machines,
        "color_data_coverage": {
            "present": color_source_present,
            "missing": color_source_missing,
            "missing_pct": round(100.0 * color_source_missing / len(rows), 1) if rows else 0.0,
        },
    }


# ---------------------------------------------------------------------------
# Quản lý Machine Master (`machines`) — Group MC/MC brand/Tank/MC quantity/Tube no/
# Capacity/Status/Production Status/Orgatex.
#
# Đổi thiết kế (2026-09-22, theo yêu cầu người dùng): TRƯỚC ĐÂY danh sách máy hiển thị
# trên "Batch Per Day by Machine" tự phát hiện từ dữ liệu batch thật (availability_logs/
# batch_details) — máy nào có mẻ trong kỳ đang lọc mới hiện ra, và bị ẩn nếu capacity_kg
# thô của máy không khớp filter Capacity mặc định. Người dùng xác nhận KHÔNG muốn cơ chế
# tự phát hiện này nữa — `machines` giờ là "Machine Master" NGUỒN DUY NHẤT quyết định máy
# nào hiển thị (xem get_cleaning_matrix()), quản lý thủ công qua UI (nút "Add Machine" +
# inline edit từng ô, cùng pattern Case Notes ở Engine downtime).
# ---------------------------------------------------------------------------

# Status: TEXT TỰ DO (2026-09-22, đổi từ dropdown 2 giá trị cố định ban đầu) — dữ liệu máy
# thật ("0 CETVN Dyeing MC 2026_08 19.xlsm") có tới 6 giá trị Status khác nhau, gồm cả mô tả
# gộp/tách máy (VD "Grouped to D514", "Splitted into 2 300kg tank D258, D259") không fit vào
# tập cố định nhỏ — giữ nguyên linh hoạt như MC brand/Tank thay vì mất thông tin thật.
# Production Status VẪN là dropdown cố định (dữ liệu thật khớp đúng 3 giá trị, không có case
# lạ như Status) — "No production" thêm vào sau khi thấy 10/69 máy thật ở trạng thái này
# (máy Uninstall/Removed/Grouped, không sản xuất gì).
PRODUCTION_STATUS_VALUES = ("Sample", "Bulk", "No production")


def list_machine_configs() -> list[dict[str, Any]]:
    """Liệt kê toàn bộ máy đã khai báo trong Machine Master — KHÔNG còn hợp thêm mã máy suy
    ra từ availability_logs/batch_details (đã bỏ auto-detect, xem ghi chú ở đầu mục)."""
    conn = get_db()
    _ensure_batch_details_columns(conn)
    sql = """
        SELECT machine_id, COALESCE(machine_code, machine_id) AS machine_code, group_mc, mc_brand, tank_type,
               mc_quantity, tube_no, capacity_kg, status, production_status, orgatex
        FROM machines
        WHERE domain = 'dyeing'
        ORDER BY COALESCE(group_mc, ''), COALESCE(machine_code, machine_id)
    """
    rows = execute_query(sql, [])
    return [dict(row) for row in rows]


def upsert_machine_config(machine_code: str, fields: Mapping[str, Any]) -> dict[str, Any]:
    """UPSERT 1 dòng `machines` theo mã máy (khớp `machine_id`). Chỉ ghi đè các field THỰC
    SỰ có trong `fields` (partial update — cho phép sửa từng ô một, giống pattern Case Notes
    đã có ở Engine downtime). Dùng ĐỂ khai báo máy MỚI (Add Machine — machine_code chưa từng
    tồn tại sẽ rơi vào nhánh INSERT của ON CONFLICT) LẪN sửa máy đã có.

    Dùng 1 câu `INSERT ... ON CONFLICT(machine_id) DO UPDATE` NGUYÊN TỬ — KHÔNG phải
    "SELECT xem đã có chưa, rồi INSERT hoặc UPDATE" ở 2 câu SQL riêng biệt như bản cũ.
    **Bug thật đã phát hiện** (người dùng report "lưu lúc được lúc không"): vì `machines`
    mặc định RỖNG, mọi máy CHƯA từng sửa lần nào đều rơi vào nhánh INSERT ở LẦN SỬA ĐẦU
    TIÊN. Sửa liên tiếp nhiều field của CÙNG 1 máy (VD Tab qua MC brand -> Tank -> Qty)
    bắn nhiều request gần như đồng thời — 2 request có thể CÙNG chạy xong bước SELECT
    trước khi request nào kịp COMMIT INSERT, cả 2 CÙNG thấy "chưa có dòng" -> cả 2 CÙNG
    INSERT -> request thua vi phạm `machine_id TEXT NOT NULL UNIQUE` (`init_db.py`) ->
    lỗi 400. UPSERT nguyên tử loại bỏ hẳn khoảng hở race này (cùng nguyên tắc với
    `upsert_case_note()` ở `downtime/service.py`)."""
    machine_code = machine_code.strip()
    if not machine_code:
        raise ValueError("Machine code không được rỗng.")
    allowed = {"group_mc", "mc_brand", "tank_type", "mc_quantity", "tube_no", "capacity_kg", "status", "production_status", "orgatex"}
    updates = {key: value for key, value in fields.items() if key in allowed}
    if not updates:
        raise ValueError("Không có field hợp lệ để cập nhật.")
    if "production_status" in updates and updates["production_status"] not in (None, "") and updates["production_status"] not in PRODUCTION_STATUS_VALUES:
        raise ValueError(f"Production Status phải là một trong: {', '.join(PRODUCTION_STATUS_VALUES)}.")
    if "orgatex" in updates:
        updates["orgatex"] = 1 if updates["orgatex"] in (True, 1, "1", "true", "True", "yes", "Yes") else 0

    conn = get_db()
    _ensure_batch_details_columns(conn)
    columns = ["machine_id", "machine_code", "machine_name", "domain", *updates.keys()]
    placeholders = ",".join("?" for _ in columns)
    set_clause = ", ".join(f"{key} = excluded.{key}" for key in updates)
    conn.execute(
        f"""
        INSERT INTO machines ({','.join(columns)}) VALUES ({placeholders})
        ON CONFLICT (machine_id) DO UPDATE SET {set_clause}
        """,
        (machine_code, machine_code, machine_code, "dyeing", *updates.values()),
    )
    conn.commit()

    affected_dates_rows = conn.execute(
        "SELECT DISTINCT production_date FROM cleaning_mc_daily_summary WHERE lower(trim(machine)) = lower(trim(?))",
        (machine_code,),
    ).fetchall()
    affected_dates = {datetime.strptime(row["production_date"], "%Y-%m-%d").date() for row in affected_dates_rows}
    if affected_dates:
        from core.rollup import trigger_recompute  # import trễ để tránh vòng lặp import với core.rollup

        trigger_recompute(affected_dates)

    row = conn.execute(
        "SELECT machine_code, mc_brand, tank_type, mc_quantity, tube_no, capacity_kg FROM machines WHERE lower(trim(COALESCE(machine_code, machine_id))) = lower(trim(?))",
        (machine_code,),
    ).fetchone()
    return dict(row) if row else {"machine_code": machine_code, **updates}


# ---------------------------------------------------------------------------
# Tab "Summary" (2026-09-23, đổi cấu trúc 3 tầng 2026-09-24) — bảng tổng hợp theo
# Group Machine x Tank Type x Category x Tháng, hiển thị cạnh tab "Detail" (bảng lịch máy
# hiện có) trên cùng trang "Batch Per Day by Machine". Xem đầy đủ các quyết định nghiệp vụ
# đã hỏi-đáp với người dùng trước khi code ở memory-bank/activeContext.md.
# ---------------------------------------------------------------------------

# 3 mức Group Machine chuẩn (đổi ranh giới 2026-09-24 — mốc 500 chuyển từ nhóm giữa sang
# nhóm trên, KHÁC bản cũ "<300Kg"/"300 to 500 Kg"/"600kg or above") — hiển thị ĐÚNG theo thứ
# tự người dùng nêu (giảm dần theo sức chứa), KHÔNG sort alphabet. `group_mc` VẪN là field
# nhập tay trên từng máy (không tự tính lại từ Capacity mỗi lần đọc) — đổi ranh giới đòi hỏi
# chạy lại 1 SQL UPDATE trên Supabase để gán lại `group_mc` theo mốc mới, xem
# activeContext.md. Giá trị group_mc nào KHÔNG khớp 3 mức chuẩn (VD còn sót nhãn cũ chưa
# migrate) vẫn hiển thị đầy đủ (không bỏ sót), xếp SAU 3 mức chuẩn, sắp theo alphabet.
CANONICAL_GROUP_MC_ORDER = (">=500Kg", ">=300 to <500Kg", "<300Kg")
UNCLASSIFIED_GROUP_LABEL = "Unclassified"
ALL_GROUPS_LABEL = "All Groups"

# Tầng nhóm phụ THEO TANK TYPE (2026-09-24, mới) — lồng BÊN TRONG từng Group Machine. Mỗi
# Group Machine giờ có: 1 khối "Subtotal" (gộp CẢ tank) + khối "J tank" + khối "O tank" +
# khối "Unclassified" (chỉ hiện nếu có máy chưa khai báo Tank Type rõ ràng) — theo đúng thứ
# tự CANONICAL_TANK_ORDER. So khớp `tank_type` KHÔNG phân biệt hoa/thường + khoảng trắng thừa
# (giống mọi so khớp text khác trong dự án) — giá trị khác "J tank"/"O tank" (rỗng hoặc lạ)
# đều rơi vào "Unclassified", KHÔNG bỏ sót dữ liệu.
CANONICAL_TANK_ORDER = ("J tank", "O tank")
UNCLASSIFIED_TANK_LABEL = "Unclassified"
SUBTOTAL_TANK_LABEL = "Subtotal"

SUMMARY_CATEGORIES = (
    "No. total day",
    "No. Dyeing machine",
    "No. of time Cleaning MC",
    "No. of normal dyeing batch",
    "Cleaning MC Ratio",
    "No. of R&D batch",
    "Rework batch",
    "Rework ratio",
    "Daily batch/day",
)


def _empty_summary_bucket() -> dict[str, Any]:
    return {"cm": 0, "normal": 0, "rd": 0, "rework": 0, "machines": set()}


def _normalize_tank_label(raw: str | None) -> str:
    normalized = (raw or "").strip().lower()
    if not normalized:
        return UNCLASSIFIED_TANK_LABEL
    for canonical in CANONICAL_TANK_ORDER:
        if normalized == canonical.lower():
            return canonical
    return UNCLASSIFIED_TANK_LABEL


def _merge_summary_buckets(month_data_list: list[dict[int, dict[str, Any]]]) -> dict[int, dict[str, Any]]:
    """Cộng dồn TRỰC TIẾP từ accumulator thô (KHÔNG suy từ giá trị đã làm tròn ở
    `_build_summary_category_rows()`) — dùng cho cả khối "Subtotal" trong 1 Group (gộp các
    Tank) LẪN khối "All Groups" cuối bảng (gộp mọi Group/Tank)."""
    merged: dict[int, dict[str, Any]] = {}
    for month_data in month_data_list:
        for month, bucket in month_data.items():
            target = merged.setdefault(month, _empty_summary_bucket())
            target["cm"] += bucket["cm"]
            target["normal"] += bucket["normal"]
            target["rd"] += bucket["rd"]
            target["rework"] += bucket["rework"]
            target["machines"] |= bucket["machines"]
    return merged


def _build_summary_category_rows(year: int, month_data: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    """Dựng 9 dòng Category cho 1 Group Machine (hoặc cho All Groups) — `month_data` đã là
    accumulator THEO ĐÚNG group đó (hoặc đã cộng dồn sẵn cho All Groups, xem
    get_batch_summary()). Mọi tỷ lệ tính theo Sum/Sum của CHÍNH tháng đó (KHÔNG suy từ tỷ lệ
    trung bình cộng — cùng nguyên tắc Sum/Sum thống nhất đã áp dụng cho batch_matrix/downtime).

    "No. of normal dyeing batch"/"Cleaning MC Ratio"/"No. of R&D batch"/"Rework batch" ĐÚNG
    NGUYÊN định nghĩa đã dùng ở tab "Detail" (`get_cleaning_matrix()` — cột "No. of normal
    dyeing batch"/"Cleaning MC Ratio"/"No. of R&D batch"/"Rework batch" trên bảng lịch máy) —
    Summary chỉ CỘNG DỒN THEO THÁNG cùng 1 định nghĩa, không tự đặt tiêu chí riêng (người dùng
    yêu cầu rõ 2026-09-23, xem activeContext.md)."""
    values: dict[str, list[Any]] = {category: [] for category in SUMMARY_CATEGORIES}
    for month in range(1, 13):
        bucket = month_data.get(month) or _empty_summary_bucket()
        days = calendar.monthrange(year, month)[1]
        n_machines = len(bucket["machines"])
        cm = bucket["cm"]
        normal = bucket["normal"]
        rd = bucket["rd"]
        rework = bucket["rework"]
        values["No. total day"].append(days)
        values["No. Dyeing machine"].append(n_machines)
        values["No. of time Cleaning MC"].append(cm)
        values["No. of normal dyeing batch"].append(normal)
        values["Cleaning MC Ratio"].append(round(normal / cm, 2) if cm else None)
        values["No. of R&D batch"].append(rd)
        values["Rework batch"].append(rework)
        values["Rework ratio"].append(round(normal / rework, 2) if rework else None)
        values["Daily batch/day"].append(round(normal / (days * n_machines), 2) if (days and n_machines) else None)
    return [{"category": category, "values": values[category]} for category in SUMMARY_CATEGORIES]


def get_batch_summary(year: int, ignore_sap_lot: bool = False) -> dict[str, Any]:
    """Bảng Summary: Group Machine x Tank Type x Category (9 dòng cố định) x 12 tháng của
    `year`.

    `ignore_sap_lot=True` (nút "Ignore SapLot" trên tab Summary, 2026-09-24): chỉ xét ĐIỀU
    KIỆN (a) của quy tắc Rework (chữ số cuối Dyelot khác '0', xem `_dyelot_indicates_rework()`
    — dùng LẠI CHÍNH XÁC hàm `classify_batch_badge()` đang gọi, không viết lại rule lần 2),
    BỎ QUA điều kiện (b) dựa trên SapLot — tính lại `is_rework` NGAY TẠI ĐÂY từ `dyelot_ref`
    đã có sẵn trong `cleaning_mc_daily_summary` (KHÔNG cần lưu thêm cột `sap_lot` vào bảng
    rollup, vì điều kiện (a) không cần SapLot). Mặc định (`False`) giữ NGUYÊN `is_rework` đã
    tính sẵn ở `recompute_daily()` (gộp CẢ 2 điều kiện, hành vi cũ không đổi). CHỈ ảnh hưởng
    tab Summary — tab "Detail" (`get_cleaning_matrix()`) KHÔNG có nút này, đúng phạm vi người
    dùng yêu cầu ("trong báo cáo summary").

    Nguồn dữ liệu: TÁI DÙNG `cleaning_mc_daily_summary` đã có (grain 1 mẻ/ngày, đã có
    badge/is_rework/batch_type/machine từ Daily Rollup) — LEFT JOIN `machines` lấy
    `group_mc`/`tank_type` tại thời điểm đọc (giống hệt cách get_cleaning_matrix() tra Machine
    Master), gộp theo THÁNG thay vì theo ngày. KHÔNG cần bảng mới, KHÔNG cần luồng import mới.

    "No. of normal dyeing batch"/"No. of time Cleaning MC"/"Cleaning MC Ratio"/"No. of R&D
    batch"/"Rework batch" dùng ĐÚNG NGUYÊN 4 điều kiện phân loại của tab "Detail"
    (`get_cleaning_matrix()`, xem đoạn phân loại `normal`/`rd_batches`/`is_rework_badge` ở đó)
    — Summary CHỈ cộng dồn theo tháng, KHÔNG tự định nghĩa lại tiêu chí "Normal"/"R&D" riêng
    (người dùng yêu cầu rõ 2026-09-23, tránh 2 số "Normal"/"Cleaning MC Ratio" lệch nhau giữa
    2 tab). "Normal" = badge != CM, KHÔNG phải Rework, VÀ batch_type thuộc {normal, unknown,
    rỗng} (loại cả R&D). "R&D" = batch_type thuộc {r&d, rd, research, development} — CỜ RIÊNG,
    không loại trừ lẫn "Rework" (1 mẻ có thể vừa Rework vừa R&D nếu dữ liệu thật vậy).

    "No. Dyeing machine" đếm SỐ MÁY DISTINCT có >=1 mẻ NHUỘM THẬT (Normal/Rework/R&D, loại
    CM) trong tháng — máy chỉ chạy CM tháng đó KHÔNG được tính (đã xác nhận với người dùng,
    ĐỊNH NGHĨA NÀY KHÔNG ĐỔI so với bản trước — chỉ 4 dòng Category ở trên đổi). Tính bằng
    set() theo từng (group, tank, tháng) rồi lấy len(), KHÔNG cộng dồn số đếm sẵn — tránh đúng
    bug COUNT DISTINCT kinh điển của dự án. AN TOÀN cộng dồn set MACHINES giữa các Group/Tank
    lên cấp "Subtotal"/"All Groups" vì (Group Machine, Tank Type) là PHÂN HOẠCH không giao
    nhau (1 máy chỉ thuộc đúng 1 Group + 1 Tank tại 1 thời điểm) — hợp (union) các set rời
    nhau = tổng độ lớn, không đếm trùng.

    Mỗi Group Machine có 2-4 khối con theo Tank Type, THEO THỨ TỰ: "Subtotal" (gộp mọi Tank
    trong group đó) -> "J tank" -> "O tank" -> "Unclassified" (chỉ hiện nếu group đó có máy
    chưa khai báo Tank Type rõ ràng). Khối "All Groups" cuối bảng KHÔNG tách theo Tank (giữ 1
    khối tổng gộp duy nhất, đúng yêu cầu người dùng) — trả về dưới dạng `tanks` chỉ có 1 phần
    tử với `tank=None` để frontend/Excel export dùng CHUNG 1 cấu trúc lặp, không cần rẽ nhánh
    riêng cho "All Groups".
    """
    conn = get_db()
    _ensure_batch_details_columns(conn)
    _ensure_summary_table(conn)

    from_date = f"{year:04d}-01-01"
    to_date = f"{year:04d}-12-31"
    rows = execute_query(
        "SELECT production_date, machine, badge, is_rework, batch_type, dyelot_ref FROM cleaning_mc_daily_summary WHERE production_date >= ? AND production_date <= ?",
        [from_date, to_date],
    )
    master_rows = execute_query("SELECT machine_id, machine_code, group_mc, tank_type FROM machines WHERE domain = 'dyeing'", [])
    machine_meta_by_norm: dict[str, dict[str, str | None]] = {}
    for master in master_rows:
        code = master["machine_code"] or master["machine_id"]
        if not code:
            continue
        machine_meta_by_norm[_normalize_code(code)] = {
            "group": (master["group_mc"] or "").strip() or None,
            "tank": master["tank_type"],
        }

    # accumulators[group_label][tank_label][month] = {"cm","normal","rd","rework","machines"}
    accumulators: dict[str, dict[str, dict[int, dict[str, Any]]]] = defaultdict(lambda: defaultdict(dict))
    distinct_groups: set[str] = set()
    for row in rows:
        production_date = row["production_date"] or ""
        if len(production_date) < 7:
            continue
        try:
            month = int(production_date[5:7])
        except ValueError:
            continue
        if not (1 <= month <= 12):
            continue
        norm = _normalize_code(row["machine"])
        meta = machine_meta_by_norm.get(norm)
        group_label = (meta["group"] if meta else None) or UNCLASSIFIED_GROUP_LABEL
        tank_label = _normalize_tank_label(meta["tank"] if meta else None)
        distinct_groups.add(group_label)
        bucket = accumulators[group_label][tank_label].setdefault(month, _empty_summary_bucket())
        normalized_batch_type = str(row["batch_type"] or "").strip().lower() or "normal"
        is_rework_badge = _dyelot_indicates_rework(row["dyelot_ref"]) if ignore_sap_lot else bool(row["is_rework"])
        if row["badge"] == "CM":
            bucket["cm"] += 1
        else:
            bucket["machines"].add(norm)
            if not is_rework_badge and normalized_batch_type in {"normal", "unknown", ""}:
                bucket["normal"] += 1
            if normalized_batch_type in {"r&d", "rd", "research", "development"}:
                bucket["rd"] += 1
            if is_rework_badge:
                bucket["rework"] += 1

    ordered_groups = [g for g in CANONICAL_GROUP_MC_ORDER if g in distinct_groups]
    ordered_groups += sorted(g for g in distinct_groups if g not in CANONICAL_GROUP_MC_ORDER and g != UNCLASSIFIED_GROUP_LABEL)
    if UNCLASSIFIED_GROUP_LABEL in distinct_groups:
        ordered_groups.append(UNCLASSIFIED_GROUP_LABEL)

    groups_output = []
    for group_label in ordered_groups:
        tank_buckets = accumulators[group_label]
        present_tanks = set(tank_buckets.keys())
        ordered_tanks = [t for t in CANONICAL_TANK_ORDER if t in present_tanks]
        if UNCLASSIFIED_TANK_LABEL in present_tanks:
            ordered_tanks.append(UNCLASSIFIED_TANK_LABEL)

        tanks_output = [{"tank": SUBTOTAL_TANK_LABEL, "rows": _build_summary_category_rows(year, _merge_summary_buckets(list(tank_buckets.values())))}]
        for tank_label in ordered_tanks:
            tanks_output.append({"tank": tank_label, "rows": _build_summary_category_rows(year, tank_buckets[tank_label])})
        groups_output.append({"group": group_label, "tanks": tanks_output})

    # All Groups: cộng dồn TRỰC TIẾP từ accumulator thô của MỌI (group, tank) — KHÔNG suy từ
    # giá trị đã làm tròn ở groups_output — rồi mới tính lại 3 dòng tỷ lệ theo Sum/Sum của
    # TOÀN nhà máy. KHÔNG tách theo Tank (giữ 1 khối tổng gộp, đúng yêu cầu người dùng).
    all_groups_month_data = [accumulators[group_label][tank_label] for group_label in ordered_groups for tank_label in accumulators[group_label]]
    all_groups_data = _merge_summary_buckets(all_groups_month_data)
    groups_output.append({"group": ALL_GROUPS_LABEL, "tanks": [{"tank": None, "rows": _build_summary_category_rows(year, all_groups_data)}]})

    month_labels = [date(year, month, 1).strftime("%b-%y") for month in range(1, 13)]
    year_rows = execute_query("SELECT DISTINCT substr(production_date, 1, 4) AS y FROM cleaning_mc_daily_summary WHERE production_date IS NOT NULL", [])
    available_years = sorted({int(r["y"]) for r in year_rows if r["y"] and r["y"].isdigit()})
    if year not in available_years:
        available_years = sorted({*available_years, year})

    return {
        "year": year,
        "available_years": available_years,
        "months": month_labels,
        "groups": groups_output,
    }


def export_batch_summary_excel(year: int, ignore_sap_lot: bool = False) -> bytes:
    """Xuất tab "Summary" ra file `.xlsx` — 1 sheet, cấu trúc y hệt bảng trên UI (cột Group
    Machine merge theo khối gồm mọi Tank con, cột Tank merge theo khối 9 dòng Category, 12
    cột tháng). Style header dùng CHUNG font/màu với `core/excel_importer.py::
    export_template()` (nền tối `24292F`/chữ trắng đậm) để nhất quán giao diện file export
    trong toàn ứng dụng. `ignore_sap_lot` chuyển thẳng cho `get_batch_summary()` — file xuất
    ra PHẢI khớp đúng trạng thái nút "Ignore SapLot" đang bật/tắt trên UI lúc bấm Export, KHÔNG
    export riêng theo mặc định. Trả về bytes — route chỉ cần gói vào `send_file(io.BytesIO(...))`,
    cùng pattern `excel_import/routes.py::download_template()`."""
    data = get_batch_summary(year, ignore_sap_lot=ignore_sap_lot)

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = f"Summary {year}"[:31]

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="24292F", end_color="24292F", fill_type="solid")
    group_font = Font(bold=True)
    subtotal_font = Font(bold=True, italic=True)
    total_font = Font(bold=True)

    headers = ["Group Machine", "Tank", "Category", *data["months"]]
    for col_idx, header in enumerate(headers, start=1):
        cell = sheet.cell(row=1, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
    sheet.column_dimensions["A"].width = 18
    sheet.column_dimensions["B"].width = 14
    sheet.column_dimensions["C"].width = 26
    for col_idx in range(4, len(headers) + 1):
        sheet.column_dimensions[sheet.cell(row=1, column=col_idx).column_letter].width = 12

    current_row = 2
    for group in data["groups"]:
        is_total_group = group["group"] == ALL_GROUPS_LABEL
        group_start_row = current_row
        for tank_block in group["tanks"]:
            is_subtotal = tank_block["tank"] == SUBTOTAL_TANK_LABEL
            emphasize = is_total_group or is_subtotal
            tank_start_row = current_row
            for row in tank_block["rows"]:
                sheet.cell(row=current_row, column=1, value=group["group"] if current_row == group_start_row else None)
                sheet.cell(row=current_row, column=2, value=(tank_block["tank"] or "-") if current_row == tank_start_row else None)
                category_cell = sheet.cell(row=current_row, column=3, value=row["category"])
                if emphasize:
                    category_cell.font = total_font if is_total_group else subtotal_font
                for col_offset, value in enumerate(row["values"]):
                    value_cell = sheet.cell(row=current_row, column=4 + col_offset, value=value)
                    if emphasize:
                        value_cell.font = total_font if is_total_group else subtotal_font
                current_row += 1
            sheet.merge_cells(start_row=tank_start_row, start_column=2, end_row=current_row - 1, end_column=2)
            sheet.cell(row=tank_start_row, column=2).font = total_font if is_total_group else (subtotal_font if is_subtotal else group_font)
        sheet.merge_cells(start_row=group_start_row, start_column=1, end_row=current_row - 1, end_column=1)
        sheet.cell(row=group_start_row, column=1).font = total_font if is_total_group else group_font

    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()
