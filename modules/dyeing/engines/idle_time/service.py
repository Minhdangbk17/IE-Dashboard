"""Báo cáo Idle Time — thời gian máy KHÔNG chạy mẻ nào, theo máy x Production Date.

NGUỒN DỮ LIỆU: `batch_day_trend_daily_summary` (rollup của Batch/Day Trend, Engine
`batch_matrix`) — mỗi dòng là 1 ĐOẠN của 1 mẻ trong 1 production_date, đã chia theo khung
07:00 -> 07:00 (`core/batch_source.py::split_production_days()`). Đọc lại ĐÚNG bảng này nên
giờ hoạt động luôn khớp Batch/Day (cùng tập mẻ, gồm cả CM/Sample/Rework/FabricType Unknown),
KHÔNG có rollup riêng, KHÔNG cần `flask rebuild-summaries`.

CÁCH TÍNH (2026-10-05, đã chốt với người dùng):
1. Khoảng thời gian của 1 đoạn: [max(StartTime mẻ, 07:00 của ngày), + hours]. Đúng vì
   `split_production_days()` tính hours = min(End, 07:00 hôm sau) - max(Start, 07:00).
2. Giờ CÓ DỮ LIỆU của 1 ngày (mẫu số, tính trên TẤT CẢ máy — không phụ thuộc filter): bắt đầu
   07:00 nếu có mẻ chạy NỐI từ hôm trước sang, ngược lại = đoạn bắt đầu sớm nhất trong ngày;
   kết thúc 07:00 hôm sau nếu có mẻ chạy nối sang hôm sau, ngược lại = đoạn kết thúc muộn
   nhất. Ngày đầu/cuối file import (VD 02/09 bắt đầu 18:42) chỉ tính phần có dữ liệu thay vì
   24h; ngày KHÔNG có đoạn nào bị bỏ hẳn (khoảng hổng giữa 2 lần import, không phải idle).
3. Danh sách máy = máy có ít nhất 1 đoạn trong kỳ (người dùng: "máy phải hoạt động mới có
   data") — KHÔNG lấy từ Machine Master. Ngày máy không chạy mẻ nào = idle trọn giờ có dữ liệu.
4. Idle của 1 ô = tổng các KHOẢNG TRỐNG giữa các đoạn (đã gộp đoạn chồng nhau) trong giờ có
   dữ liệu -> luôn = giờ có dữ liệu - giờ hoạt động. Khoảng idle vắt qua 07:00 bị tách làm 2
   (mỗi ngày 1 khoảng, note riêng).
5. % Idle = idle / giờ có dữ liệu. Target là 1 ngưỡng % Idle CHUNG cho mọi máy.

Filter Tank (J tank / O tank / Unclassified) + Capacity tra `machines` tại read time, chuẩn hoá
Tank bằng `_normalize_tank_label()` giống Batch Per Day by Machine + Batch/Day Trend.

Note nguyên nhân (`idle_time_notes`) khoá theo (machine, gap_start) — 1 note/khoảng idle,
Reason chọn từ `IDLE_REASONS`, Detail nhập tự do. Import lại dữ liệu làm khoảng idle dịch
chuyển -> note cũ KHÔNG khớp khoảng nào nữa, được trả về riêng (`stale_notes`) thay vì âm
thầm mất.
"""
from __future__ import annotations

import io
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Iterable

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from core.batch_source import parse_batch_datetime
from core.database import execute_query, get_db, get_dialect
from core.production_time import PRODUCTION_SHIFT_START_HOUR
from modules.dyeing.engines.reports.cleaning_matrix import (
    CANONICAL_TANK_ORDER,
    UNCLASSIFIED_TANK_LABEL,
    _normalize_tank_label,
)

# Danh sách Reason cố định (người dùng chốt 2026-10-05) — bám theo các cột chờ/dừng của file
# Availability để đối chiếu được với báo cáo Downtime, + "Waiting for previous process".
IDLE_REASONS = (
    "Waiting for fabric",
    "Waiting for chemicals/dyes",
    "Waiting for water",
    "Waiting for steam",
    "Maintenance",
    "Machine breakdown",
    "Machine cleaning",
    "No order",
    "Waiting for previous process",
)
TARGET_SETTING_KEY = "target_idle_pct"
_TANK_ORDER: tuple[str, ...] = (*CANONICAL_TANK_ORDER, UNCLASSIFIED_TANK_LABEL)
_TIME_FMT = "%Y-%m-%d %H:%M:%S"

# Màu ô vượt Target trong Excel — style "Bad" chuẩn của Excel (nền hồng/chữ đỏ đậm), tương
# đương `.ratio-warning` trên web (xem design/UI_GUIDELINES.md mục 6.3).
_EXCEL_OVER_TARGET_FILL = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
_EXCEL_OVER_TARGET_FONT = Font(color="9C0006")


# ---------------------------------------------------------------------------
# Bảng của Engine — SQLite tự tạo; Postgres tạo qua `supabase/migrate_idle_time.sql`.
# ---------------------------------------------------------------------------


def _ensure_tables(conn: Any) -> None:
    if get_dialect() == "sqlite":
        conn.execute("""
            CREATE TABLE IF NOT EXISTS idle_time_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                machine TEXT NOT NULL,
                production_date TEXT NOT NULL,
                gap_start TEXT NOT NULL,
                gap_end TEXT NOT NULL,
                reason TEXT,
                detail TEXT,
                updated_by INTEGER NOT NULL REFERENCES users (id),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE (machine, gap_start)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS idle_time_settings (
                key TEXT PRIMARY KEY,
                value REAL NOT NULL,
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_idle_time_notes_date ON idle_time_notes (production_date)")
    conn.commit()


# ---------------------------------------------------------------------------
# Dựng đoạn mẻ / giờ có dữ liệu / khoảng idle
# ---------------------------------------------------------------------------


def _day_window(day_str: str) -> tuple[datetime, datetime]:
    day = date.fromisoformat(day_str)
    start = datetime(day.year, day.month, day.day, PRODUCTION_SHIFT_START_HOUR)
    return start, start + timedelta(days=1)


def _load_day_segments(from_date: str | None, to_date: str | None) -> dict[str, dict[str, list[tuple[datetime, datetime, str]]]]:
    """{production_date: {machine: [(đoạn bắt đầu, đoạn kết thúc, StartTime gốc của mẻ)]}} — TẤT
    CẢ máy (chưa lọc), đoạn đã sắp theo thời gian. Kết thúc làm tròn tới giây để 2 mẻ nối
    liền nhau không sinh khoảng idle ảo do sai số float."""
    sql = "SELECT production_date, machine, start_time, hours FROM batch_day_trend_daily_summary WHERE hours > 0"
    params: list[Any] = []
    if from_date:
        sql += " AND production_date >= ?"
        params.append(from_date)
    if to_date:
        sql += " AND production_date <= ?"
        params.append(to_date)
    result: dict[str, dict[str, list[tuple[datetime, datetime, str]]]] = defaultdict(lambda: defaultdict(list))
    for row in execute_query(sql, params):
        batch_start = parse_batch_datetime(row["start_time"])
        machine = str(row["machine"] or "").strip()
        if batch_start is None or not machine:
            continue
        window_start, _ = _day_window(row["production_date"])
        seg_start = max(batch_start, window_start)
        seg_end = seg_start + timedelta(seconds=round(float(row["hours"]) * 3600))
        result[row["production_date"]][machine].append((seg_start, seg_end, str(row["start_time"])))
    for machines in result.values():
        for segments in machines.values():
            segments.sort()
    return result


def _available_window(day_str: str, machines: dict[str, list[tuple[datetime, datetime, str]]]) -> tuple[datetime, datetime]:
    """Giờ có dữ liệu của ngày — xem bước 2 docstring đầu file."""
    window_start, window_end = _day_window(day_str)
    all_segments = [segment for segments in machines.values() for segment in segments]
    carried_in = any(seg_start <= window_start for seg_start, _, _ in all_segments)
    carried_out = any(seg_end >= window_end for _, seg_end, _ in all_segments)
    start = window_start if carried_in else min(seg_start for seg_start, _, _ in all_segments)
    end = window_end if carried_out else max(seg_end for _, seg_end, _ in all_segments)
    return start, end


def _gaps(segments: list[tuple[datetime, datetime, str]], avail_start: datetime, avail_end: datetime) -> tuple[float, list[dict[str, Any]]]:
    """(giờ hoạt động = độ dài HỢP các đoạn, [khoảng idle]) trong [avail_start, avail_end].
    Mỗi khoảng idle kèm StartTime gốc của mẻ ngay trước/ngay sau (None nếu ở biên ngày)."""
    operating_seconds = 0.0
    gaps: list[dict[str, Any]] = []
    cursor = avail_start
    prev_batch: str | None = None
    for seg_start, seg_end, batch_start in segments:
        seg_start, seg_end = max(seg_start, avail_start), min(seg_end, avail_end)
        if seg_end <= seg_start:
            continue
        if seg_start > cursor:
            gaps.append({"start": cursor, "end": seg_start, "prev_batch_start": prev_batch, "next_batch_start": batch_start})
        if seg_end > cursor:
            operating_seconds += (seg_end - max(seg_start, cursor)).total_seconds()
            cursor = seg_end
            prev_batch = batch_start
    if avail_end > cursor:
        gaps.append({"start": cursor, "end": avail_end, "prev_batch_start": prev_batch, "next_batch_start": None})
    for gap in gaps:
        gap["hours"] = (gap["end"] - gap["start"]).total_seconds() / 3600.0
    return operating_seconds / 3600.0, gaps


def _machine_master(conn: Any) -> dict[str, dict[str, Any]]:
    """{mã máy (lower/trim): {"tank", "capacity"}} từ Machine Master."""
    master: dict[str, dict[str, Any]] = {}
    for row in conn.execute("SELECT machine_code, machine_id, tank_type, capacity_kg FROM machines").fetchall():
        code = str(row["machine_code"] or row["machine_id"] or "").strip().lower()
        if code and code not in master:
            capacity = round(float(row["capacity_kg"]), 2) if row["capacity_kg"] not in (None, "") else None
            master[code] = {"tank": _normalize_tank_label(row["tank_type"]), "capacity": capacity}
    return master


def _pct(idle: float, available: float) -> float | None:
    return round(idle / available * 100, 2) if available > 0 else None


def _fmt(value: datetime) -> str:
    return value.strftime(_TIME_FMT)


# ---------------------------------------------------------------------------
# Target (% Idle chung cho mọi máy)
# ---------------------------------------------------------------------------


def get_target() -> float | None:
    conn = get_db()
    _ensure_tables(conn)
    rows = execute_query("SELECT value FROM idle_time_settings WHERE key = ?", [TARGET_SETTING_KEY])
    return float(rows[0]["value"]) if rows else None


def set_target(target_idle_pct: float) -> dict[str, Any]:
    if not 0 <= target_idle_pct <= 100:
        raise ValueError("Target % Idle phải trong khoảng 0-100.")
    conn = get_db()
    _ensure_tables(conn)
    now_str = datetime.now().strftime(_TIME_FMT)
    conn.execute(
        "INSERT INTO idle_time_settings (key, value, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        (TARGET_SETTING_KEY, target_idle_pct, now_str),
    )
    conn.commit()
    return {"target_idle_pct": target_idle_pct, "updated_at": now_str}


# ---------------------------------------------------------------------------
# Ma trận máy x ngày
# ---------------------------------------------------------------------------


def _parse_capacities(capacities: Iterable[Any] | None) -> set[float] | None:
    values: set[float] = set()
    for raw in capacities or []:
        try:
            values.add(round(float(raw), 2))
        except (TypeError, ValueError):
            continue
    return values or None


def _notes_by_key(from_date: str | None, to_date: str | None) -> dict[tuple[str, str], Any]:
    sql = """
        SELECT n.machine, n.production_date, n.gap_start, n.gap_end, n.reason, n.detail, n.updated_at,
               u.username AS updated_by
        FROM idle_time_notes n LEFT JOIN users u ON u.id = n.updated_by WHERE 1=1
    """
    params: list[Any] = []
    if from_date:
        sql += " AND n.production_date >= ?"
        params.append(from_date)
    if to_date:
        sql += " AND n.production_date <= ?"
        params.append(to_date)
    return {(row["machine"], row["gap_start"]): row for row in execute_query(sql, params)}


def _build(from_date: str | None, to_date: str | None, tank_types: list[str] | None, capacities: Iterable[Any] | None) -> dict[str, Any]:
    """Tính toàn bộ ô + khoảng idle cho kỳ đang lọc — dùng chung cho API ma trận, Excel."""
    conn = get_db()
    _ensure_tables(conn)
    day_segments = _load_day_segments(from_date, to_date)
    master = _machine_master(conn)

    present_tanks = {master.get(m.lower(), {}).get("tank", UNCLASSIFIED_TANK_LABEL) for machines in day_segments.values() for m in machines}
    available_tank_types = [label for label in _TANK_ORDER if label in present_tanks]
    available_capacities = sorted({
        master[m.lower()]["capacity"] for machines in day_segments.values() for m in machines
        if m.lower() in master and master[m.lower()]["capacity"] is not None
    })
    tank_filter = set(tank_types) if tank_types else None
    capacity_filter = _parse_capacities(capacities)

    def keep(machine: str) -> bool:
        info = master.get(machine.lower(), {})
        if tank_filter is not None and info.get("tank", UNCLASSIFIED_TANK_LABEL) not in tank_filter:
            return False
        return capacity_filter is None or info.get("capacity") in capacity_filter

    days = sorted(day_segments)
    windows = {day: _available_window(day, day_segments[day]) for day in days}
    machine_names = sorted({m for machines in day_segments.values() for m in machines if keep(m)})
    notes = _notes_by_key(from_date, to_date)
    target = get_target()

    rows: list[dict[str, Any]] = []
    all_gaps: list[dict[str, Any]] = []
    day_totals = {day: {"operating": 0.0, "idle": 0.0, "available": 0.0} for day in days}
    for machine in machine_names:
        info = master.get(machine.lower(), {})
        row = {"machine": machine, "tank": info.get("tank", UNCLASSIFIED_TANK_LABEL), "capacity": info.get("capacity"), "cells": {}}
        row_totals = {"operating": 0.0, "idle": 0.0, "available": 0.0}
        for day in days:
            avail_start, avail_end = windows[day]
            available = (avail_end - avail_start).total_seconds() / 3600.0
            operating, gaps = _gaps(day_segments[day].get(machine, []), avail_start, avail_end)
            idle = sum(gap["hours"] for gap in gaps)
            noted = 0
            for gap in gaps:
                note = notes.get((machine, _fmt(gap["start"])))
                noted += note is not None
                all_gaps.append({"machine": machine, "production_date": day, **gap, "note": note})
            row["cells"][day] = {
                "operating": round(operating, 2), "idle": round(idle, 2), "available": round(available, 2),
                "idle_pct": _pct(idle, available), "gap_count": len(gaps), "noted_count": noted,
            }
            for totals in (row_totals, day_totals[day]):
                totals["operating"] += operating
                totals["idle"] += idle
                totals["available"] += available
        row.update({key: round(value, 2) for key, value in row_totals.items()})
        row["idle_pct"] = _pct(row_totals["idle"], row_totals["available"])
        rows.append(row)

    grand = {key: sum(totals[key] for totals in day_totals.values()) for key in ("operating", "idle", "available")}
    return {
        "days": days,
        "day_available_hours": {day: round((windows[day][1] - windows[day][0]).total_seconds() / 3600.0, 2) for day in days},
        "partial_days": [day for day in days if windows[day] != _day_window(day)],
        "rows": rows,
        "day_totals": {
            day: {**{key: round(value, 2) for key, value in totals.items()}, "idle_pct": _pct(totals["idle"], totals["available"])}
            for day, totals in day_totals.items()
        },
        "grand_total": {**{key: round(value, 2) for key, value in grand.items()}, "idle_pct": _pct(grand["idle"], grand["available"])},
        "target_idle_pct": target,
        "available_tank_types": available_tank_types,
        "available_capacities": available_capacities,
        "reasons": list(IDLE_REASONS),
        "_gaps": all_gaps,
    }


def get_idle_matrix(
    from_date: str | None = None, to_date: str | None = None,
    tank_types: list[str] | None = None, capacities: Iterable[Any] | None = None,
) -> dict[str, Any]:
    data = _build(from_date, to_date, tank_types, capacities)
    data.pop("_gaps")
    return data


# ---------------------------------------------------------------------------
# Drill-down 1 ô + note nguyên nhân
# ---------------------------------------------------------------------------


def _batch_dyelots(machine: str, start_times: set[str]) -> dict[str, str]:
    """{StartTime gốc: Dyelot} — chỉ để hiển thị mẻ trước/sau khoảng idle. Machine trong
    batch_details có thể trống (fill-down khi chuẩn hoá) nên nhận cả dòng machine rỗng."""
    if not start_times:
        return {}
    placeholders = ", ".join("?" for _ in start_times)
    rows = execute_query(f"SELECT dyelot, machine, start_time FROM batch_details WHERE start_time IN ({placeholders})", list(start_times))
    result: dict[str, str] = {}
    for row in sorted(rows, key=lambda r: str(r["machine"] or "").strip().lower() != machine.lower()):
        raw_machine = str(row["machine"] or "").strip().lower()
        if raw_machine in ("", machine.lower()):
            result.setdefault(str(row["start_time"]), row["dyelot"])
    return result


def _note_payload(note: Any) -> dict[str, Any] | None:
    if note is None:
        return None
    return {"reason": note["reason"], "detail": note["detail"], "gap_end_saved": note["gap_end"], "updated_by": note["updated_by"], "updated_at": note["updated_at"]}


def get_idle_gaps(machine: str, production_date: str) -> dict[str, Any]:
    """Danh sách khoảng idle của 1 ô (máy x ngày) + note đã nhập + note không còn khớp."""
    conn = get_db()
    _ensure_tables(conn)
    day_segments = _load_day_segments(production_date, production_date).get(production_date)
    if not day_segments:
        return {"machine": machine, "production_date": production_date, "gaps": [], "stale_notes": [], "reasons": list(IDLE_REASONS)}
    avail_start, avail_end = _available_window(production_date, day_segments)
    segments = day_segments.get(machine, [])
    operating, gaps = _gaps(segments, avail_start, avail_end)
    notes = {
        row["gap_start"]: row
        for row in execute_query(
            "SELECT n.gap_start, n.gap_end, n.reason, n.detail, n.updated_at, u.username AS updated_by "
            "FROM idle_time_notes n LEFT JOIN users u ON u.id = n.updated_by WHERE n.machine = ? AND n.production_date = ?",
            [machine, production_date],
        )
    }
    dyelots = _batch_dyelots(machine, {s for gap in gaps for s in (gap["prev_batch_start"], gap["next_batch_start"]) if s})
    gap_starts = {_fmt(gap["start"]) for gap in gaps}
    return {
        "machine": machine,
        "production_date": production_date,
        "available_from": _fmt(avail_start),
        "available_to": _fmt(avail_end),
        "operating": round(operating, 2),
        "idle": round(sum(gap["hours"] for gap in gaps), 2),
        "gaps": [
            {
                "gap_start": _fmt(gap["start"]), "gap_end": _fmt(gap["end"]), "hours": round(gap["hours"], 2),
                "prev_batch": dyelots.get(gap["prev_batch_start"] or "") or gap["prev_batch_start"],
                "next_batch": dyelots.get(gap["next_batch_start"] or "") or gap["next_batch_start"],
                "note": _note_payload(notes.get(_fmt(gap["start"]))),
            }
            for gap in gaps
        ],
        "stale_notes": [
            {"gap_start": key, **(_note_payload(note) or {})} for key, note in notes.items() if key not in gap_starts
        ],
        "reasons": list(IDLE_REASONS),
    }


def upsert_idle_note(machine: str, production_date: str, gap_start: str, reason: str | None, detail: str | None, user_id: int) -> dict[str, Any]:
    """Lưu Reason/Detail cho ĐÚNG 1 khoảng idle đang tồn tại (khoá machine + gap_start). Cả
    Reason lẫn Detail rỗng -> xoá note. Reason phải thuộc `IDLE_REASONS`."""
    if reason and reason not in IDLE_REASONS:
        raise ValueError(f"Reason không hợp lệ: {reason}")
    current = get_idle_gaps(machine, production_date)
    gap = next((g for g in current["gaps"] if g["gap_start"] == gap_start), None)
    stale = any(note["gap_start"] == gap_start for note in current["stale_notes"])
    conn = get_db()
    if not reason and not detail:
        if gap is None and not stale:
            raise ValueError("Không tìm thấy khoảng idle cần xoá note.")
        conn.execute("DELETE FROM idle_time_notes WHERE machine = ? AND gap_start = ?", (machine, gap_start))
        conn.commit()
        return {"machine": machine, "gap_start": gap_start, "note": None}
    if gap is None:
        raise ValueError(f"Không còn khoảng idle bắt đầu lúc {gap_start} của máy {machine} ngày {production_date}.")
    now_str = datetime.now().strftime(_TIME_FMT)
    conn.execute(
        """
        INSERT INTO idle_time_notes (machine, production_date, gap_start, gap_end, reason, detail, updated_by, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(machine, gap_start)
        DO UPDATE SET production_date = excluded.production_date, gap_end = excluded.gap_end, reason = excluded.reason,
                      detail = excluded.detail, updated_by = excluded.updated_by, updated_at = excluded.updated_at
        """,
        (machine, production_date, gap_start, gap["gap_end"], reason, detail, user_id, now_str),
    )
    conn.commit()
    saved = next(g for g in get_idle_gaps(machine, production_date)["gaps"] if g["gap_start"] == gap_start)
    return {"machine": machine, "gap_start": gap_start, "note": saved["note"]}


# ---------------------------------------------------------------------------
# Excel export — y hệt bảng trên UI + sheet chi tiết khoảng idle kèm note
# ---------------------------------------------------------------------------


def export_idle_excel(
    from_date: str | None = None, to_date: str | None = None,
    tank_types: list[str] | None = None, capacities: Iterable[Any] | None = None, mode: str = "idle",
) -> bytes:
    """Sheet "Idle Time": máy x ngày theo `mode` ("idle" = giờ idle, "operating" = giờ hoạt
    động) + Total/% Idle/Target, dòng Total/% Idle/Available (h) theo ngày; ô có % Idle vượt
    Target tô màu cảnh báo. Sheet "Idle Gaps": từng khoảng idle + Reason/Detail."""
    data = _build(from_date, to_date, tank_types, capacities)
    value_key = "operating" if mode == "operating" else "idle"
    target = data["target_idle_pct"]
    days = data["days"]
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="24292F", end_color="24292F", fill_type="solid")
    bold = Font(bold=True)

    def over_target(pct: float | None) -> bool:
        return target is not None and pct is not None and pct > target

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Idle Time"
    headers = ["Machine", "Tank", "Capacity (Kg)", *days, "Total (h)", "% Idle", "Target % Idle"]
    for col, header in enumerate(headers, start=1):
        cell = sheet.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        sheet.column_dimensions[cell.column_letter].width = 12
    first_day_col = 4
    total_col = first_day_col + len(days)
    for row_idx, row in enumerate(data["rows"], start=2):
        sheet.cell(row=row_idx, column=1, value=row["machine"])
        sheet.cell(row=row_idx, column=2, value=row["tank"])
        sheet.cell(row=row_idx, column=3, value=row["capacity"])
        for offset, day in enumerate(days):
            cell_data = row["cells"][day]
            cell = sheet.cell(row=row_idx, column=first_day_col + offset, value=round(cell_data[value_key], 1))
            if over_target(cell_data["idle_pct"]):
                cell.fill, cell.font = _EXCEL_OVER_TARGET_FILL, _EXCEL_OVER_TARGET_FONT
        sheet.cell(row=row_idx, column=total_col, value=round(row[value_key], 1))
        pct_cell = sheet.cell(row=row_idx, column=total_col + 1, value=row["idle_pct"])
        if over_target(row["idle_pct"]):
            pct_cell.fill, pct_cell.font = _EXCEL_OVER_TARGET_FILL, _EXCEL_OVER_TARGET_FONT
        sheet.cell(row=row_idx, column=total_col + 2, value=target)

    footer_row = len(data["rows"]) + 2
    for label_offset, (label, key) in enumerate((("Total", value_key), ("% Idle", "idle_pct"), ("Available (h/machine)", None))):
        row_idx = footer_row + label_offset
        sheet.cell(row=row_idx, column=1, value=label).font = bold
        for offset, day in enumerate(days):
            value = data["day_available_hours"][day] if key is None else data["day_totals"][day][key]
            cell = sheet.cell(row=row_idx, column=first_day_col + offset, value=round(value, 1) if key == value_key else value)
            cell.font = bold
            if key == "idle_pct" and over_target(value):
                cell.fill, cell.font = _EXCEL_OVER_TARGET_FILL, _EXCEL_OVER_TARGET_FONT
        if key == value_key:
            sheet.cell(row=row_idx, column=total_col, value=round(data["grand_total"][value_key], 1)).font = bold
        elif key == "idle_pct":
            sheet.cell(row=row_idx, column=total_col + 1, value=data["grand_total"]["idle_pct"]).font = bold
    sheet.freeze_panes = sheet.cell(row=2, column=first_day_col)

    gap_sheet = workbook.create_sheet("Idle Gaps")
    gap_headers = ["Machine", "Production Date", "From", "To", "Idle (h)", "Reason", "Detail", "Updated by", "Updated at"]
    for col, header in enumerate(gap_headers, start=1):
        cell = gap_sheet.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        gap_sheet.column_dimensions[cell.column_letter].width = 20
    for row_idx, gap in enumerate(data["_gaps"], start=2):
        note = gap["note"]
        values = [
            gap["machine"], gap["production_date"], _fmt(gap["start"]), _fmt(gap["end"]), round(gap["hours"], 2),
            note["reason"] if note else None, note["detail"] if note else None,
            note["updated_by"] if note else None, note["updated_at"] if note else None,
        ]
        for col, value in enumerate(values, start=1):
            gap_sheet.cell(row=row_idx, column=col, value=value)
    gap_sheet.freeze_panes = "A2"

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
