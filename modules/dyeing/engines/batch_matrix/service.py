"""
modules/dyeing/engines/batch_matrix/service.py
--------------------------------------------------
Ma trận Số mẻ/Máy theo Ngày: pivot Fabric Type x Color Group x Ngày sản xuất.

2026-10-06 (yêu cầu người dùng): bộ lọc + mặc định GIỐNG HỆT tab Batch/Day Trend (Capacity,
Brand Program, Tank Type, Group By Day/Week/Month, ReDye = 0; bỏ filter Fabric Type), mẻ Normal
theo quy tắc Trend (`classify_batch_badge()`) thay cho `batch_type = 'Normal'`. `build_matrix()`
giờ tính TRỰC TIẾP từ raw cho mọi dòng (xem mục "Đọc báo cáo" bên dưới) — KHÔNG còn đọc
`batch_matrix_daily_summary`; `recompute_daily()` vẫn ghi bảng đó (quy tắc cũ) nhưng không
còn báo cáo nào đọc. Capacity + Tank tra Machine Master (`machines`) giống Trend, KHÔNG dùng
`availability_logs.capacity_kg`. Công thức mẫu số (giờ của ĐÚNG tập máy, khử trùng máy) giữ nguyên.

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

import io
from datetime import date, datetime, timedelta
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from core.batch_details_match import batch_details_join_sql
from core.batch_source import load_resolved_batches
from core.brand_program_importer import ensure_brand_program_table
from core.database import execute_query, get_db, get_dialect, sql_datetime
from core.production_time import get_production_date, normalize_production_date, production_bounds, production_date_sql_expr
from modules.dyeing.engines.reports.cleaning_matrix import UNCLASSIFIED_TANK_LABEL

from .batch_day_trend import _TANK_ORDER, _brand_program_label, get_batch_day_trend, _is_normal_batch, _machine_capacities, _machine_tank_labels, _period


def _parse_text_filter(value: str | list[str] | None) -> list[str]:
    """Parse fabric_types=/brand_programs= query param (CSV hoặc list) — rỗng/'ALL' nghĩa
    là không lọc theo chiều đó, cùng quy ước với `_parse_capacities()`."""
    if not value:
        return []
    values = value if isinstance(value, list) else str(value).split(",")
    result: list[str] = []
    for item in values:
        text = str(item).strip()
        if not text or text.upper() == "ALL":
            return []
        if text not in result:
            result.append(text)
    return result

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
    (deploy mới, không có schema cũ để migrate) — chỉ cần đảm bảo index tồn tại.

    **CỐ TÌNH KHÔNG thêm `brand_program` vào grain của bảng này** (khác `capacity_kg`) —
    xem `_live_matrix_data()` bên dưới để biết lý do (1 máy có thể chạy NHIỀU brand_program
    trong CÙNG 1 ngày, khác capacity_kg vốn cố định 1-máy-1-giá-trị đã verify — thêm
    brand_program vào grain rồi SUM operating_hours qua các bucket con sẽ tái diễn ĐÚNG bug
    COUNT DISTINCT đã tốn 3 lần sửa ở "Mẫu số"). Brand Program filter dùng đường tính TRỰC
    TIẾP riêng, không qua bảng rollup này."""
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


def set_target(fabric_type: str, color_group: str, target_value: float | None) -> None:
    """`target_value=None` = xoá Target của ô (ô để trống người dùng nhập -> không tô màu)."""
    conn = get_db()
    _ensure_targets_table(conn)
    if target_value is None:
        conn.execute("DELETE FROM batch_matrix_targets WHERE fabric_type = ? AND color_group = ?", (fabric_type, color_group))
        conn.commit()
        return
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT INTO batch_matrix_targets (fabric_type, color_group, target_value, updated_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(fabric_type, color_group) DO UPDATE SET target_value=excluded.target_value, updated_at=excluded.updated_at",
        (fabric_type, color_group, target_value, now_str),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Shade nhập tay cho mẻ "Unclassified" (2026-10-26): batch_details.shade rỗng -> mẻ rơi vào
# Color Group "Unclassified"; người dùng mở danh sách ô đó và tự chọn Shade cho từng Dyelot.
# Khoá theo Dyelot (cùng Dyelot = cùng màu, kể cả mẻ chạy lại); ghi đè lên batch_details.shade
# ở READ TIME nên không phải import/rebuild lại gì. Chỉ ảnh hưởng Fabric/Color Matrix.
# ---------------------------------------------------------------------------

SHADE_CHOICES: tuple[str, ...] = ("Dark", "Medium", "Light")


def _ensure_shade_overrides_table(conn: Any) -> None:
    """CHỈ chạy CREATE TABLE ở SQLite — ở Postgres bảng có sẵn qua `supabase/schema.sql`."""
    if get_dialect() == "sqlite":
        conn.execute("""
            CREATE TABLE IF NOT EXISTS batch_shade_overrides (
                dyelot TEXT PRIMARY KEY,
                shade TEXT NOT NULL,
                updated_by TEXT,
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
    conn.commit()


def _load_shade_overrides(conn: Any) -> dict[str, str]:
    _ensure_shade_overrides_table(conn)
    return {str(row["dyelot"]).strip(): row["shade"] for row in conn.execute("SELECT dyelot, shade FROM batch_shade_overrides").fetchall()}


def set_shade_override(dyelot: str, shade: str | None, updated_by: str | None = None) -> None:
    """Gán Shade cho 1 Dyelot; `shade` rỗng/None = xoá (trả về Shade gốc của Batch Detail)."""
    dyelot = dyelot.strip()
    if not dyelot:
        raise ValueError("Missing dyelot.")
    shade = (shade or "").strip()
    if shade and shade not in SHADE_CHOICES:
        raise ValueError(f"Shade must be one of: {', '.join(SHADE_CHOICES)}.")
    conn = get_db()
    _ensure_shade_overrides_table(conn)
    if not shade:
        conn.execute("DELETE FROM batch_shade_overrides WHERE dyelot = ?", (dyelot,))
    else:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "INSERT INTO batch_shade_overrides (dyelot, shade, updated_by, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(dyelot) DO UPDATE SET shade=excluded.shade, updated_by=excluded.updated_by, updated_at=excluded.updated_at",
            (dyelot, shade, updated_by, now_str),
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
        {batch_details_join_sql("a.batch", "a.end_time")}
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
# Đọc báo cáo (2026-10-06) — TÍNH TRỰC TIẾP từ raw data cho MỌI dòng (không còn đọc
# `batch_matrix_daily_summary`): dòng Total(Fabric)/Grand Total vốn đã luôn phải truy vấn raw để
# khử trùng máy, nay dòng "data" dùng chung 1 lần truy vấn đó. Bộ lọc + mặc định GIỐNG HỆT tab
# Batch/Day Trend (theo yêu cầu người dùng): Capacity, Brand Program, Tank Type, Group By
# (Day/Week/Month), ReDye = 0. Mẻ Normal theo ĐÚNG quy tắc Trend (`classify_batch_badge()`:
# Dyelot *0, SapLot 1*/3*, ReDye = 0 nếu bật) — thay cho `batch_type = 'Normal'` cũ; dòng
# availability không JOIN được batch_details (không có Dyelot/SapLot) -> không tính.
# Ô Week/Month = tổng mẻ trong kỳ * 24 / tổng giờ máy trong kỳ (giờ mỗi máy tính 1 lần/ngày).
# ---------------------------------------------------------------------------


def _load_matrix_source(
    date_from: str | None, date_to: str | None, require_redye_zero: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, float]]]:
    """Nguồn Matrix (2026-10-26): `batch_details` qua `core/batch_source.py::load_resolved_batches()`
    — CÙNG nguồn + CÙNG chuẩn hoá với Batch/Day Trend (Machine fill-down, FabricType fill-up,
    production_date = ngày kết thúc theo khung 07:00) nên tập mẻ Normal của Matrix == Trend.
    (Trước đây Matrix đọc `availability_logs` nên thiếu/lệch mẻ so với Trend — local: 3252 so 5219.)

    Trả (rows, hours): `rows` = mọi mẻ Normal (quy tắc `classify_batch_badge()`) ĐÃ phân loại
    color_group + Brand Program, KHÔNG lọc capacity/brand/tank (lọc ở `_build_core()` để
    `available_*` phản ánh toàn khoảng ngày); `hours` = {ngày: {máy: giờ chiếm máy}} của TẤT CẢ mẻ
    (mọi loại vải, kể cả CM/Sample/Rework) — nguồn mẫu số, cắt theo khung 07:00."""
    conn = get_db()
    shade_overrides = _load_shade_overrides(conn)
    rows: list[dict[str, Any]] = []
    hours: dict[str, dict[str, float]] = {}
    for batch in load_resolved_batches(conn):
        segments = batch["_segments"]
        if not segments:
            continue
        machine = batch["machine"]
        for seg_day, seg_hours in segments:
            day_bucket = hours.setdefault(seg_day.isoformat(), {})
            day_bucket[machine] = day_bucket.get(machine, 0.0) + seg_hours
        day = segments[-1][0].isoformat()
        if (date_from and day < date_from) or (date_to and day > date_to):
            continue
        if not _is_normal_batch(batch, require_redye_zero):
            continue
        override = shade_overrides.get(str(batch["dyelot"]).strip())
        shade = override or batch["shade"]
        rows.append({
            "day": day,
            "fabric_type": batch["fabric_type"],
            "color_group": _classify_color_group(shade, batch["colour_no"]),
            "shade_override": override,
            "capacity": None,  # gán từ Machine Master ở `_build_core()`
            "machine": machine,
            "brand_program": _brand_program_label(batch),
            "batch_no": batch["dyelot"],
            "dyelot": batch["dyelot"], "sap_lot": batch["sap_lot"], "redye": batch["redye"],
            "shade": shade, "colour_no": batch["colour_no"],
            "start_time": batch["start_time"], "end_time": batch["end_time"],
        })
    return rows, hours


def _empty_result(date_from: str | None = None, date_to: str | None = None, group_by: str = "date", error: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "date_from": date_from, "date_to": date_to, "group_by": group_by,
        "periods": [], "period_keys": [], "day_count": 0,
        "available_capacities": [], "available_brand_programs": [], "available_tank_types": [],
        "rows": [], "grand_total": None,
    }
    if error:
        result["error"] = error
    return result


def _build_core(
    date_from: str | None, date_to: str | None, capacities: str | list[str] | None,
    brand_programs: str | list[str] | None, tank_types: str | list[str] | None,
    group_by: str, require_redye_zero: bool,
) -> dict[str, Any] | None:
    """Truy vấn raw 1 lần, áp bộ lọc, xác định cột kỳ — dùng CHUNG cho bảng, drill-down và
    Excel export. Trả `None` khi không có dữ liệu trong khoảng ngày."""
    conn = get_db()
    ensure_brand_program_table(conn)
    raw_rows, machine_hours_by_day = _load_matrix_source(date_from, date_to, require_redye_zero)
    if not raw_rows:
        return None
    # Capacity + Tank tra Machine Master (`machines`) tại read time — GIỐNG Trend; máy chưa khai
    # báo Capacity -> None (bị ẩn khi lọc Capacity cụ thể, như Trend).
    tank_by_machine = _machine_tank_labels(conn)
    capacity_by_machine = _machine_capacities(conn)
    for row in raw_rows:
        code = row["machine"].lower()
        row["tank"] = tank_by_machine.get(code, UNCLASSIFIED_TANK_LABEL)
        row["capacity"] = capacity_by_machine.get(code)

    selected_capacities = _parse_capacities(capacities)
    capacity_filter = {round(value, 2) for value in selected_capacities} if selected_capacities else None
    selected_brand_programs = _parse_text_filter(brand_programs)
    brand_program_filter = set(selected_brand_programs) if selected_brand_programs else None
    selected_tank_types = [value for value in _parse_text_filter(tank_types) if value in _TANK_ORDER]
    tank_filter = set(selected_tank_types) if selected_tank_types else None
    rows = [
        row for row in raw_rows
        if (capacity_filter is None or row["capacity"] in capacity_filter)
        and (brand_program_filter is None or row["brand_program"] in brand_program_filter)
        and (tank_filter is None or row["tank"] in tank_filter)
    ]

    # Cột kỳ = khoảng đã chọn (From/To) nếu có, hoặc MIN..MAX ngày có dữ liệu. Bộ lọc chỉ đổi
    # GIÁ TRỊ ô, không làm nhảy tập cột.
    all_days = sorted({row["day"] for row in raw_rows})
    start_day = datetime.strptime(date_from or all_days[0], "%Y-%m-%d").date()
    end_day = datetime.strptime(date_to or all_days[-1], "%Y-%m-%d").date()
    if end_day < start_day:
        start_day, end_day = end_day, start_day
    days: list[str] = []
    period_of_day: dict[str, str] = {}
    period_labels: dict[str, str] = {}
    current = start_day
    while current <= end_day:
        key, label = _period(current, group_by)
        days.append(current.isoformat())
        period_of_day[current.isoformat()] = key
        period_labels[key] = label
        current += timedelta(days=1)
    for row in rows:
        row["period_key"] = period_of_day.get(row["day"])
    period_keys = sorted(period_labels)
    return {
        "rows": [row for row in rows if row["period_key"] is not None],
        "machine_hours_by_day": machine_hours_by_day,
        "days": days,
        "period_of_day": period_of_day,
        "period_keys": period_keys,
        "periods": [period_labels[key] for key in period_keys],
        "period_labels": period_labels,
        "available_capacities": sorted({row["capacity"] for row in raw_rows if row["capacity"] is not None}),
        "available_brand_programs": sorted({row["brand_program"] for row in raw_rows if row["brand_program"]}),
        "available_tank_types": [label for label in _TANK_ORDER if label in {row["tank"] for row in raw_rows}],
        "selected_capacities": selected_capacities,
        "selected_brand_programs": selected_brand_programs,
        "selected_tank_types": selected_tank_types,
    }


def build_matrix(
    date_from: str | None = None, date_to: str | None = None, capacities: str | list[str] | None = None,
    brand_programs: str | list[str] | None = None, tank_types: str | list[str] | None = None,
    group_by: str = "date", require_redye_zero: bool = True,
) -> dict[str, Any]:
    conn = get_db()
    _ensure_targets_table(conn)
    group_by = group_by if group_by in {"date", "week", "month"} else "date"
    try:
        core = _build_core(date_from, date_to, capacities, brand_programs, tank_types, group_by, require_redye_zero)
    except Exception as exc:
        return _empty_result(date_from, date_to, group_by, error=str(exc))
    if core is None:
        return _empty_result(date_from, date_to, group_by)

    days, period_keys = core["days"], core["period_keys"]
    machine_hours_by_day = core["machine_hours_by_day"]

    # Đếm mẻ + TẬP MÁY theo (cấp gộp, ngày). Mẫu số của mọi cấp = giờ máy của ĐÚNG tập máy đó
    # trong ngày, mỗi máy cộng 1 lần (khử trùng máy — xem docstring đầu file).
    cell_count: dict[tuple[str, str], dict[str, int]] = {}
    cell_machines: dict[tuple[str, str], dict[str, set[str]]] = {}
    fabric_count: dict[str, dict[str, int]] = {}
    fabric_machines: dict[str, dict[str, set[str]]] = {}
    grand_count: dict[str, int] = {}
    grand_machines: dict[str, set[str]] = {}
    for row in core["rows"]:
        day, fabric_type, machine = row["day"], row["fabric_type"], row["machine"]
        cell_key = (fabric_type, row["color_group"])
        cell_bucket = cell_count.setdefault(cell_key, {})
        cell_bucket[day] = cell_bucket.get(day, 0) + 1
        cell_machines.setdefault(cell_key, {}).setdefault(day, set()).add(machine)
        fabric_bucket = fabric_count.setdefault(fabric_type, {})
        fabric_bucket[day] = fabric_bucket.get(day, 0) + 1
        fabric_machines.setdefault(fabric_type, {}).setdefault(day, set()).add(machine)
        grand_count[day] = grand_count.get(day, 0) + 1
        grand_machines.setdefault(day, set()).add(machine)

    period_of_day = core["period_of_day"]

    def ratio(count_by_day: dict[str, int], machines_by_day: dict[str, set[str]], period_key: str | None) -> float | None:
        """Tổng mẻ * 24 / tổng giờ tập máy của các ngày có mẻ trong kỳ (`None` = cả khoảng)."""
        selected = [day for day in count_by_day if period_key is None or period_of_day.get(day) == period_key]
        numerator = sum(count_by_day[day] for day in selected)
        hours = sum(
            sum(machine_hours_by_day.get(day, {}).get(machine, 0.0) for machine in machines_by_day.get(day, set()))
            for day in selected
        )
        return round(numerator * 24 / hours, 2) if numerator and hours else None

    def values(count_by_day: dict[str, int], machines_by_day: dict[str, set[str]]) -> dict[str, float | None]:
        return {key: ratio(count_by_day, machines_by_day, key) for key in period_keys}

    targets = {(row["fabric_type"], row["color_group"]): row["target_value"] for row in execute_query("SELECT fabric_type, color_group, target_value FROM batch_matrix_targets")}

    def color_group_sort_key(name: str) -> tuple[int, str]:
        return (1, name) if name == UNCLASSIFIED_COLOR_GROUP else (0, name)

    # Grand Total = ĐÚNG dòng Total của Batch/Day Trend cùng bộ lọc (yêu cầu người dùng 2026-10-26:
    # 2 báo cáo phải bằng nhau, số của Trend là số đúng) — KHÔNG tự tính từ tập máy như các dòng trên.
    trend = get_batch_day_trend(
        capacities=capacities, brand_programs=brand_programs, tank_types=tank_types,
        from_date=date_from, to_date=date_to, group_by=group_by, require_redye_zero=require_redye_zero,
    )
    trend_total = trend["total_row"]
    trend_by_key = {
        key: value for key, value, hours in zip(trend["period_keys"], trend_total["values"], trend_total["hours"]) if hours
    }
    # Dòng Total(Fabric) = ĐÚNG dòng cùng loại vải của Trend (Cotton/CVC/Polyester, hoặc loại khác như
    # Unknown) — số mẻ * 24 / giờ chiếm máy; chỉ ô data (Fabric x Color) giữ công thức tập máy.
    trend_fabric = {row["fabric_type"]: row for row in trend["rows"]}
    trend_fabric.update(trend["other_fabrics"])

    def trend_fabric_values(fabric_type: str) -> tuple[dict[str, float | None], float | None] | None:
        source = trend_fabric.get(fabric_type)
        if source is None:
            return None
        by_key = {key: value for key, value, hours in zip(trend["period_keys"], source["values"], source["hours"]) if hours}
        return {key: by_key.get(key) for key in period_keys}, (source["total"] if source.get("total_hours", 1) else None)

    rows: list[dict[str, Any]] = []
    for fabric_type in sorted(fabric_count):
        color_groups = sorted({color_group for (ft, color_group) in cell_count if ft == fabric_type}, key=color_group_sort_key)
        for color_group in color_groups:
            cell_key = (fabric_type, color_group)
            rows.append({
                "row_type": "data", "fabric_type": fabric_type, "color_group": color_group,
                "target": targets.get(cell_key),
                "values": values(cell_count[cell_key], cell_machines[cell_key]),
                "total": ratio(cell_count[cell_key], cell_machines[cell_key], None),
            })
        from_trend = trend_fabric_values(fabric_type)
        rows.append({
            "row_type": "fabric_total", "fabric_type": fabric_type, "color_group": None, "target": None,
            "values": from_trend[0] if from_trend else values(fabric_count[fabric_type], fabric_machines[fabric_type]),
            "total": from_trend[1] if from_trend else ratio(fabric_count[fabric_type], fabric_machines[fabric_type], None),
        })
    grand_total = trend_total["total"] if trend_total["total_hours"] else None
    rows.append({
        "row_type": "grand_total", "fabric_type": None, "color_group": None, "target": None,
        "values": {key: trend_by_key.get(key) for key in period_keys}, "total": grand_total,
    })

    return {
        "date_from": date_from, "date_to": date_to, "group_by": group_by,
        "require_redye_zero": require_redye_zero,
        "periods": core["periods"], "period_keys": period_keys, "day_count": len(days),
        "capacities": core["selected_capacities"], "available_capacities": core["available_capacities"],
        "brand_programs": core["selected_brand_programs"], "available_brand_programs": core["available_brand_programs"],
        "tank_types": core["selected_tank_types"], "available_tank_types": core["available_tank_types"],
        "rows": rows, "grand_total": grand_total,
    }


# ---------------------------------------------------------------------------
# Drill-down: danh sách batch thật của 1 ô (double-check số liệu ma trận)
# ---------------------------------------------------------------------------


_BATCH_FIELDS: tuple[tuple[str, str], ...] = (
    ("day", "Production Date"), ("machine", "Machine"), ("capacity", "Capacity (Kg)"), ("tank", "Tank"),
    ("fabric_type", "Fabric Type"), ("color_group", "Color Group"), ("brand_program", "Brand Program"),
    ("batch_no", "Batch No"), ("dyelot", "Dyelot"), ("sap_lot", "SapLot"), ("redye", "ReDye"),
    ("shade", "Shade"), ("colour_no", "ColourNo"), ("start_time", "Start"), ("end_time", "End"),
)


def _public_batch(row: dict[str, Any]) -> dict[str, Any]:
    return {**{key: row[key] for key, _ in _BATCH_FIELDS}, "shade_override": row.get("shade_override")}


def get_cell_batches(
    fabric_type: str, color_group: str, period_key: str | None = None,
    date_from: str | None = None, date_to: str | None = None, capacities: str | list[str] | None = None,
    brand_programs: str | list[str] | None = None, tank_types: str | list[str] | None = None,
    group_by: str = "date", require_redye_zero: bool = True,
) -> list[dict[str, Any]]:
    """Danh sách mẻ được đếm vào 1 ô (fabric_type, color_group, kỳ) — `period_key` rỗng = ô
    Total. Dùng CHUNG `_build_core()` với bảng nên luôn khớp đúng số mẻ trên ma trận."""
    group_by = group_by if group_by in {"date", "week", "month"} else "date"
    core = _build_core(date_from, date_to, capacities, brand_programs, tank_types, group_by, require_redye_zero)
    if core is None:
        return []
    batches = [
        _public_batch(row) for row in core["rows"]
        if row["fabric_type"] == fabric_type and row["color_group"] == color_group
        and (not period_key or row["period_key"] == period_key)
    ]
    batches.sort(key=lambda b: (b["day"], str(b["machine"]).lower(), str(b["start_time"])))
    return batches


def export_matrix_excel(
    date_from: str | None = None, date_to: str | None = None, capacities: str | list[str] | None = None,
    brand_programs: str | list[str] | None = None, tank_types: str | list[str] | None = None,
    group_by: str = "date", require_redye_zero: bool = True,
) -> bytes:
    """Sheet "Matrix" (y hệt bảng trên web) + "Batches" (mọi mẻ Normal được đếm) + "Filters"."""
    group_by = group_by if group_by in {"date", "week", "month"} else "date"
    data = build_matrix(date_from, date_to, capacities, brand_programs, tank_types, group_by, require_redye_zero)
    core = _build_core(date_from, date_to, capacities, brand_programs, tank_types, group_by, require_redye_zero)
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="24292F", end_color="24292F", fill_type="solid")
    bold = Font(bold=True)

    def write_header(sheet: Any, headers: list[str]) -> None:
        for col, header in enumerate(headers, start=1):
            cell = sheet.cell(row=1, column=col, value=header)
            cell.font, cell.fill = header_font, header_fill
            sheet.column_dimensions[cell.column_letter].width = 14

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Matrix"
    write_header(sheet, ["Fabric Type", "Color Group", "Target", "Total", *data["periods"]])
    for row_idx, row in enumerate(data["rows"], start=2):
        if row["row_type"] == "data":
            label = (row["fabric_type"], row["color_group"])
        elif row["row_type"] == "fabric_total":
            label = (row["fabric_type"], f"Total ({row['fabric_type']})")
        else:
            label = ("Grand Total", None)
        values = [*label, row["target"], row["total"], *(row["values"].get(key) for key in data["period_keys"])]
        for col, value in enumerate(values, start=1):
            cell = sheet.cell(row=row_idx, column=col, value=value)
            if row["row_type"] != "data":
                cell.font = bold
    sheet.freeze_panes = "E2"

    batches_sheet = workbook.create_sheet("Batches")
    write_header(batches_sheet, [label for _, label in _BATCH_FIELDS])
    batches = sorted((_public_batch(row) for row in (core or {}).get("rows", [])), key=lambda b: (b["day"], str(b["machine"]).lower(), str(b["start_time"])))
    for row_idx, batch in enumerate(batches, start=2):
        for col, (key, _) in enumerate(_BATCH_FIELDS, start=1):
            batches_sheet.cell(row=row_idx, column=col, value=batch[key])
    batches_sheet.auto_filter.ref = f"A1:{batches_sheet.cell(row=1, column=len(_BATCH_FIELDS)).column_letter}{len(batches) + 1}"
    batches_sheet.freeze_panes = "A2"

    filters_sheet = workbook.create_sheet("Filters")
    write_header(filters_sheet, ["Filter", "Value"])
    filters_sheet.column_dimensions["B"].width = 40
    filters = [
        ("From Date", date_from or "All"), ("To Date", date_to or "All"),
        ("Group By", {"date": "Day", "week": "Week", "month": "Month"}[group_by]),
        ("Capacity (Kg)", ", ".join(str(value) for value in _parse_capacities(capacities)) or "All"),
        ("Brand Program", ", ".join(_parse_text_filter(brand_programs)) or "All"),
        ("Tank Type", ", ".join(_parse_text_filter(tank_types)) or "All"),
        ("ReDye = 0", "Yes" if require_redye_zero else "No"),
    ]
    for row_idx, (label, value) in enumerate(filters, start=2):
        filters_sheet.cell(row=row_idx, column=1, value=label)
        filters_sheet.cell(row=row_idx, column=2, value=value)

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
