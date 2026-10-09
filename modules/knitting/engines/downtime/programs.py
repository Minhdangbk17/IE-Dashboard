"""
modules/knitting/engines/downtime/programs.py
------------------------------------------------
Program của 1 (máy, production_date) cho bộ lọc Program / Core program của báo cáo Downtime Dệt.

File Stop Reason không có Greige — nguồn là `knitting_piece_rolls` (Piece Produced report, 1 dòng =
1 cuộn, Record Start/End CHỈ có ngày). Quy tắc (chốt 2026-10-09 sau khi đo trên file tháng 7):
- Cuộn "phủ" mọi ngày từ Record Start tới Record End (phủ 982/1302 máy-ngày tháng 7; chỉ dùng
  Record End phủ 880). Ngày lịch được coi là production_date — không tách được mốc 07:00 vì file
  không có giờ (sai lệch chỉ ở cuộn kết thúc 00:00–07:00, hầu hết máy chạy cùng Greige nhiều ngày).
- Nhiều Greige cùng phủ 1 máy-ngày (17/1302) -> lấy Greige có nhiều phút Available nhất (Available
  của cuộn chia đều cho số ngày cuộn phủ).
- Không cuộn nào phủ, hoặc Greige không có trong `knitting_greige_programs` -> Program ĐỂ TRỐNG
  (người dùng chốt 2026-10-09 "không có thì để trống"); KHÔNG kéo Greige ngày trước sang (đo được
  9/12 khoảng trống ngắn đổi Greige ở 2 đầu, đoán sẽ sai). Bộ lọc chọn các dòng trống qua mục
  "(Blank)" (khoá rỗng), giống "(blank)" của pivot Excel.
Program so khớp theo khoá chuẩn hoá (`normalize_program`), Core = danh sách `knitting_core_programs`.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from modules.knitting.engines.excel_import.program_importer import normalize_program
from modules.knitting.engines.excel_import.service import ensure_tables

BLANK_OPTION = "(Blank)"  # mục lọc cho máy-ngày không có Program; KHÔNG phải tên hiển thị
BLANK_KEY = ""


def core_program_keys(conn: Any) -> set[str]:
    return {r["program_key"] for r in conn.execute("SELECT program_key FROM knitting_core_programs")}


def machine_day_programs(conn: Any, from_date: str, to_date: str, machines: list[str] | None = None) -> dict[tuple[str, str], dict[str, Any]]:
    """{(production_date, machine_code): {greige_id, program, program_key}} cho máy-ngày CÓ cuộn phủ.
    Máy-ngày không có trong dict = không có cuộn -> Program trống."""
    ensure_tables(conn)
    start, end = date.fromisoformat(from_date), date.fromisoformat(to_date)
    sql = "SELECT machine_code, greige_id, available, record_start, record_end FROM knitting_piece_rolls WHERE record_start <= ? AND record_end >= ?"
    params: list[Any] = [to_date, from_date]
    if machines:
        sql += f" AND machine_code IN ({','.join('?' for _ in machines)})"
        params += machines

    weight: dict[tuple[str, str], dict[str, list[float]]] = defaultdict(lambda: defaultdict(lambda: [0.0, 0]))
    for row in conn.execute(sql, params):
        roll_start, roll_end = date.fromisoformat(row["record_start"]), date.fromisoformat(row["record_end"])
        per_day = (row["available"] or 0) / ((roll_end - roll_start).days + 1)
        day = max(roll_start, start)
        while day <= min(roll_end, end):
            bucket = weight[(day.isoformat(), row["machine_code"])][row["greige_id"]]
            bucket[0] += per_day
            bucket[1] += 1
            day += timedelta(days=1)

    programs = {r["greige_code"]: (r["program"], r["program_key"]) for r in conn.execute("SELECT greige_code, program, program_key FROM knitting_greige_programs")}
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for key, by_greige in weight.items():
        greige = max(sorted(by_greige), key=lambda g: (by_greige[g][0], by_greige[g][1]))
        program, program_key = programs.get(greige, ("", BLANK_KEY))  # Greige ngoài danh mục: Program trống
        result[key] = {"greige_id": greige, "program": program, "program_key": program_key}
    return result


def program_of(mapping: dict[tuple[str, str], dict[str, Any]], production_date: str, machine_code: str) -> dict[str, Any]:
    return mapping.get((production_date, machine_code)) or {"greige_id": None, "program": "", "program_key": BLANK_KEY}


def allowed_program_keys(conn: Any, programs: list[str], core_only: bool) -> set[str] | None:
    """Tập khoá Program được giữ lại; None = không lọc theo Program."""
    if not programs and not core_only:
        return None
    keys = {BLANK_KEY if p == BLANK_OPTION else normalize_program(p) for p in programs} if programs else None
    if core_only:
        core = core_program_keys(conn)
        keys = core if keys is None else keys & core
    return keys


def list_program_options(conn: Any) -> dict[str, Any]:
    """Program xuất hiện trong dữ liệu cuộn (không liệt kê cả 140 tên của danh mục) + Core."""
    ensure_tables(conn)
    names = [
        r["program"] for r in conn.execute(
            """
            SELECT DISTINCT p.program FROM knitting_piece_rolls r
            JOIN knitting_greige_programs p ON p.greige_code = r.greige_id
            ORDER BY p.program
            """
        )
    ]
    core = [r["program"] for r in conn.execute("SELECT program FROM knitting_core_programs ORDER BY program")]
    for name in core:
        if name not in names:
            names.append(name)
    return {"programs": sorted(names, key=str.lower) + [BLANK_OPTION], "core_programs": core}
