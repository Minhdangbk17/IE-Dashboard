"""DCA Cost report — Sum(DyeCost) / Sum(số dyelot) từ `batch_details`, theo Day/Week/Month.

Nguồn dữ liệu: `batch_details` (đã có sẵn qua Import Batch Detail, KHÔNG cần luồng import mới)
— mỗi dòng = 1 lần chạy thật (1 dyelot có thể có NHIỀU dòng: mẻ gốc + mẻ redye chạy lại, xem
`core/batch_details_match.py`), không có rủi ro đếm trùng kiểu COUNT DISTINCT vì đây là báo cáo
COUNT trực tiếp số dòng. `dye_cost` là cột chi phí thuốc nhuộm/mẻ. `fabric_type`/`shade`/
`colour_no`/`recipe_no`/`customer_color`/`greige_code`/`start_time`/`end_time` đều lấy TRỰC TIẾP
từ `batch_details` (không cần JOIN gì thêm) — CHỈ `capacity_kg` (phục vụ filter Capacity) phải
LEFT JOIN `availability_logs`, chọn ĐÚNG 1 dòng khớp `end_time` với `batch_details` (tránh JOIN
1 dyelot khớp nhiều `availability_logs` gây nhân bản dòng — cùng nguyên tắc
`batch_details_join_sql()` nhưng đảo chiều, viết trực tiếp vì chỉ 1 nơi cần chiều này). Dòng
KHÔNG khớp `availability_logs` nào vẫn GIỮ LẠI khi không lọc Capacity, chỉ bị loại khi người
dùng chủ động chọn Capacity cụ thể.

Công thức mỗi ô `(fabric_type, color, kỳ)`: `DCA Cost = Sum(dye_cost) / COUNT(dyelot)` — tính
TẤT CẢ mẻ (KHÔNG loại CM/Rework, theo yêu cầu người dùng — khác "Normal Dyeing Batches by
Colour" của `reports/cleaning_matrix.py` vốn loại CM+Rework).

Phân loại 5 màu (`_classify_color`): tái hiện ĐÚNG Bước 3 (xác định tông màu cơ bản) của
`reports/cleaning_matrix.py::classify_batch_badge()` — B(Black)/W(White) từ từ khoá trong
ColourNo+RecipeNo+CustomerColor, D(Dark)/M(Medium)/L(Light) từ Shade rồi fallback từ khoá,
mặc định Medium. KHÔNG gọi thẳng `classify_batch_badge()` vì hàm đó trả "CM" ngay cho mẻ rửa
máy (Dyelot chứa "-WA") mà KHÔNG xác định màu — ở đây cần màu cho MỌI mẻ (kể cả CM/Rework).
Viết lại riêng (trùng lặp có kiểm soát, không import chéo Engine — cùng nguyên tắc
`MAIN_FABRIC_TYPES` đã áp dụng cho `tank_loading`/`rft`) — nếu sau này từ khoá màu ở
`classify_batch_badge()` đổi, PHẢI đồng bộ tay lại đây.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from core.brand_program_importer import ensure_brand_program_table
from core.database import DatabaseError, execute_query, get_db
from core.production_time import get_production_date

# Báo cáo LUÔN thể hiện ĐÚNG 3 loại vải chính này (cùng quyết định đã áp dụng cho "%Tank
# Loading"/"Batch/Day Trend"/"RFT"). Định nghĩa RIÊNG ở đây (không import cross-engine) để
# giữ đúng Vertical Slice Architecture (CLAUDE.md mục 3-4).
MAIN_FABRIC_TYPES: tuple[str, ...] = ("Cotton", "CVC", "Polyester")
_MAIN_FABRIC_TYPE_BY_NORM: dict[str, str] = {name.lower(): name for name in MAIN_FABRIC_TYPES}


def _normalize_main_fabric_type(value: str | None) -> str | None:
    return _MAIN_FABRIC_TYPE_BY_NORM.get(str(value or "").strip().lower())


# 5 nhóm màu cố định — cùng thứ tự hiển thị `COLOR_LABEL_ORDER` của
# `reports/cleaning_matrix.py`.
COLOR_LABELS: tuple[str, ...] = ("Dark", "Light", "Medium", "Black", "White")

# Từ khoá tông màu Đậm/Nhạt — COPY NGUYÊN VĂN từ `reports/cleaning_matrix.py::
# DARK_KEYWORDS`/`LIGHT_KEYWORDS` (Bước 3 của `classify_batch_badge()`) để 2 nơi phân loại
# cùng 1 tông màu ra kết quả giống nhau cho cùng 1 mẻ.
_DARK_KEYWORDS = ("DARK", "DEEP", "NAVY", "MARINE", "CHARCOAL", "MAROON", "BURGUNDY", "EBONY", "MIDNIGHT", "INDIGO", "SHADOW", "GRAPHITE", "ESPRESSO", "COFFEE")
_LIGHT_KEYWORDS = ("LIGHT", "PALE", "PASTEL", "CREAM", "IVORY", "BEIGE", "BLUSH", "PEACH", "MINT", "SKY", "BABY", "POWDER", "LILAC", "ROSE", "LEMON", "PINK", "PEARL", "ECRU", "BLANCH")


def _classify_color(row: dict[str, Any]) -> str:
    """Luôn trả về 1 trong 5 `COLOR_LABELS` (KHÔNG có nhóm "Unclassified"/None) — mặc định
    "Medium" khi hoàn toàn không có tín hiệu, cùng fallback của `classify_batch_badge()`."""
    colour_no = str(row.get("colour_no") or "")
    recipe_no = str(row.get("recipe_no") or "")
    customer_color = str(row.get("customer_color") or "")
    text_check = f"{colour_no} {recipe_no} {customer_color}".upper()
    shade = str(row.get("shade") or "").upper()

    if "BLACK" in text_check or "BLK" in text_check:
        return "Black"
    if "WHITE" in text_check or "WHT" in text_check or "BLANCH" in text_check:
        return "White"
    if shade == "DARK":
        return "Dark"
    if shade == "MEDIUM":
        return "Medium"
    if shade == "LIGHT":
        return "Light"
    if any(keyword in text_check for keyword in _LIGHT_KEYWORDS):
        return "Light"
    if any(keyword in text_check for keyword in _DARK_KEYWORDS):
        return "Dark"
    return "Medium"


_BRAND_PROGRAM_LABEL_SQL = "CASE WHEN COALESCE(bpm.brand, '') <> '' AND COALESCE(bpm.brand_program, '') <> '' THEN bpm.brand || ' - ' || bpm.brand_program ELSE '' END"


def _parse_capacities(capacities: str | list[str] | None) -> list[float]:
    """Parse capacities=25,50; ALL/rỗng nghĩa là không lọc theo Capacity."""
    if capacities is None:
        return []
    values = capacities if isinstance(capacities, list) else str(capacities).split(",")
    parsed: list[float] = []
    for value in values:
        text = str(value).strip()
        if not text or text.upper() == "ALL":
            return []
        try:
            number = float(text)
        except ValueError:
            continue
        if number not in parsed:
            parsed.append(number)
    return parsed


def _parse_text_filter(value: str | list[str] | None) -> list[str]:
    """Parse brand_programs= query param (CSV hoặc list) — rỗng/'ALL' nghĩa là không lọc
    theo chiều đó, cùng quy ước với `_parse_capacities()`."""
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


def _dca_rows(selected_capacities: list[float], from_date: str | None, to_date: str | None) -> list[dict[str, Any]]:
    """Lấy toàn bộ dòng `batch_details` khớp bộ lọc Capacity/Date, kèm nhãn Brand Program —
    query TRỰC TIẾP (chưa có Daily Rollup, cùng quyết định đã áp dụng lúc scaffold cho
    `rft`/`tank_loading`)."""
    ensure_brand_program_table(get_db())
    sql = f"""
        SELECT bd."dyelot" AS dyelot, bd."dye_cost" AS dye_cost, bd."fabric_type" AS fabric_type,
               bd."shade" AS shade, bd."colour_no" AS colour_no, bd."recipe_no" AS recipe_no,
               bd."customer_color" AS customer_color,
               bd."start_time" AS start_time, bd."end_time" AS end_time,
               a."capacity_kg" AS capacity_kg,
               {_BRAND_PROGRAM_LABEL_SQL} AS brand_program
        FROM batch_details bd
        LEFT JOIN availability_logs a ON a."id" = COALESCE(
            (SELECT aa."id" FROM availability_logs aa
             WHERE lower(trim(aa."batch")) = lower(trim(bd."dyelot")) AND aa."end_time" = bd."end_time"
             LIMIT 1),
            (SELECT aa."id" FROM availability_logs aa
             WHERE lower(trim(aa."batch")) = lower(trim(bd."dyelot"))
             ORDER BY aa."end_time" DESC LIMIT 1)
        )
        LEFT JOIN brand_program_mapping bpm ON lower(trim(bpm."greige_code")) = lower(trim(bd."greige_code"))
        WHERE bd."dyelot" IS NOT NULL AND TRIM(CAST(bd."dyelot" AS TEXT)) <> ''
    """
    params: list[Any] = []
    if selected_capacities:
        placeholders = ", ".join("?" for _ in selected_capacities)
        sql += f" AND CAST(a.\"capacity_kg\" AS REAL) IN ({placeholders})"
        params.extend(selected_capacities)
    try:
        rows = execute_query(sql, params)
    except DatabaseError:
        return []

    result: list[dict[str, Any]] = []
    for row in rows:
        record_time = _parse_datetime(row["end_time"]) or _parse_datetime(row["start_time"])
        production_date = get_production_date(record_time) if record_time is not None else None
        # Không xác định được production_date: vẫn GIỮ dòng khi KHÔNG có filter ngày (rơi vào
        # bucket "Unknown Date" lúc pivot), nhưng LOẠI khi người dùng đã chủ động lọc From/To
        # Date — cùng nguyên tắc `rft`/`tank_loading`.
        if from_date and (production_date is None or production_date.isoformat() < from_date):
            continue
        if to_date and (production_date is None or production_date.isoformat() > to_date):
            continue
        result.append({**dict(row), "production_date": production_date})
    return result


# 4 tab hiển thị — "Overview" gộp CẢ 3 loại vải chính lại làm 1 (không phân biệt Fabric
# Type, vẫn giữ nguyên phạm vi lọc "chỉ 3 loại chính", KHÔNG lẫn loại vải khác như Nylon),
# 3 tab còn lại tách riêng từng loại — theo yêu cầu người dùng.
REPORT_SECTIONS: tuple[str, ...] = ("Overview",) + MAIN_FABRIC_TYPES


def _empty_fabric_section() -> dict[str, Any]:
    return {
        "rows": [{"color": color, "values": [], "total": 0.0} for color in COLOR_LABELS],
        "kpis": {"total_dye_cost": 0.0, "total_batches": 0, "dca_cost": 0.0},
    }


def _build_section(fabric_rows: list[dict[str, Any]], ordered_keys: list[str]) -> dict[str, Any]:
    """Dựng 1 section (5 dòng màu + KPI) từ danh sách mẻ đã gán `dye_cost`/`period_key`/
    `color` — dùng CHUNG cho cả 3 tab theo từng loại vải LẪN tab "Overview" (gộp mọi loại)."""
    periods_by_color: dict[str, dict[str, dict[str, float]]] = {color: {} for color in COLOR_LABELS}
    for item in fabric_rows:
        period = periods_by_color[item["color"]].setdefault(item["period_key"], {"dye_cost": 0.0, "count": 0})
        period["dye_cost"] += item["dye_cost"]
        period["count"] += 1

    color_rows: list[dict[str, Any]] = []
    for color in COLOR_LABELS:
        periods = periods_by_color[color]
        values = [
            round(periods[key]["dye_cost"] / periods[key]["count"], 2) if periods.get(key) and periods[key]["count"] else 0.0
            for key in ordered_keys
        ]
        total_cost = sum(period["dye_cost"] for period in periods.values())
        total_count = sum(period["count"] for period in periods.values())
        total_value = round(total_cost / total_count, 2) if total_count else 0.0
        color_rows.append({"color": color, "values": values, "total": total_value})

    section_total_cost = sum(item["dye_cost"] for item in fabric_rows)
    section_total_count = len(fabric_rows)
    section_dca = round(section_total_cost / section_total_count, 2) if section_total_count else 0.0
    return {
        "rows": color_rows,
        "kpis": {
            "total_dye_cost": round(section_total_cost, 2),
            "total_batches": section_total_count,
            "dca_cost": section_dca,
        },
    }


def get_dca_cost_data(
    capacities: str | list[str] | None = None,
    brand_programs: str | list[str] | None = None,
    from_date: str | None = None, to_date: str | None = None, group_by: str = "date",
) -> dict[str, Any]:
    """Bảng + biểu đồ DCA Cost theo Day/Week/Month — LUÔN trả đủ 4 section
    (`REPORT_SECTIONS`): "Overview" (gộp CẢ 3 loại vải chính, không phân biệt Fabric Type) +
    Cotton/CVC/Polyester (tách riêng từng loại) — UI hiển thị dưới dạng 4 tab. Mỗi section có
    5 dòng màu (Dark/Light/Medium/Black/White). Mọi section dùng CHUNG 1 trục kỳ
    (`periods`/`period_keys`) để 4 chart thẳng hàng nhau."""
    group_by = group_by if group_by in {"date", "week", "month"} else "date"
    selected_capacities = _parse_capacities(capacities)
    selected_brand_programs = _parse_text_filter(brand_programs)

    all_rows = _dca_rows(selected_capacities, from_date, to_date)
    available_brand_programs = sorted({row["brand_program"] for row in all_rows if row["brand_program"]})

    brand_filter = set(selected_brand_programs) if selected_brand_programs else None
    rows = [
        row for row in all_rows
        if brand_filter is None or row["brand_program"] in brand_filter
    ]

    if not rows:
        return {
            "filters": {
                "capacities": selected_capacities or "all", "brand_programs": selected_brand_programs or "all",
                "from_date": from_date, "to_date": to_date, "group_by": group_by,
            },
            "periods": [], "period_keys": [],
            "fabrics": {name: _empty_fabric_section() for name in REPORT_SECTIONS},
            "available_brand_programs": available_brand_programs,
        }

    # Trục kỳ CHUNG cho cả 3 fabric — dựng từ TOÀN BỘ dòng (không riêng theo fabric), giống
    # cách `rft`/`tank_loading` dựng `ordered_keys` chung. "unknown" LUÔN xuống cuối.
    period_labels: dict[str, str] = {}
    for row in rows:
        if row["production_date"] is not None:
            key, label = _period(row["production_date"], group_by)
        else:
            key, label = "unknown", "Unknown Date"
        period_labels[key] = label
    known_keys = sorted(key for key in period_labels if key != "unknown")
    ordered_keys = known_keys + (["unknown"] if "unknown" in period_labels else [])
    labels = [period_labels[key] for key in ordered_keys]

    # Nhóm dòng theo fabric (chỉ 3 loại chính — loại khác bị loại khỏi báo cáo, cùng nguyên
    # tắc `tank_loading`), gán màu qua `_classify_color()` (LUÔN có màu, không rơi rớt dòng
    # nào — khác cơ chế fabric_type có thể rỗng ở `tank_loading`/`rft`).
    rows_by_fabric: dict[str, list[dict[str, Any]]] = {name: [] for name in MAIN_FABRIC_TYPES}
    for row in rows:
        fabric_type = _normalize_main_fabric_type(row["fabric_type"])
        if fabric_type is None:
            continue
        key = _period(row["production_date"], group_by)[0] if row["production_date"] is not None else "unknown"
        rows_by_fabric[fabric_type].append({
            "dye_cost": float(row["dye_cost"] or 0),
            "period_key": key,
            "color": _classify_color(row),
        })

    fabrics_out: dict[str, Any] = {
        "Overview": _build_section([item for fabric_type in MAIN_FABRIC_TYPES for item in rows_by_fabric[fabric_type]], ordered_keys),
    }
    for fabric_type in MAIN_FABRIC_TYPES:
        fabrics_out[fabric_type] = _build_section(rows_by_fabric[fabric_type], ordered_keys)

    return {
        "filters": {
            "capacities": selected_capacities or "all", "brand_programs": selected_brand_programs or "all",
            "from_date": from_date, "to_date": to_date, "group_by": group_by,
        },
        "periods": labels, "period_keys": ordered_keys,
        "fabrics": fabrics_out,
        "available_brand_programs": available_brand_programs,
    }
