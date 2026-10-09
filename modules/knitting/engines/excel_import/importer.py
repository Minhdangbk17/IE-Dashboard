"""
modules/knitting/engines/excel_import/importer.py
------------------------------------------------
Parse file "CET-Stop Reason Analysis by Machine" (CSV do hệ thống giám sát máy dệt xuất).

- Production Date lấy từ TÊN FILE, không có trong nội dung: "... - 14-09-2026 07;00;00 -
  15-09-2026 07;00;00.csv" (dấu `;` thay `:` vì Windows cấm `:` trong tên file). Khoảng thời
  gian PHẢI là đúng 1 ngày sản xuất (bắt đầu 07:00, dài 24h) — import ghi đè TOÀN BỘ ngày đó,
  file khoảng khác (1 ca, nhiều ngày) sẽ làm sai số nên bị từ chối thay vì đoán.
- Header 2 dòng: dòng 1 là nhóm cột (Key Items / Efficiency / Times...), dòng 2 là tên cột thật
  — tìm dòng có ô đầu "M/c Code", không cố định vị trí.
- Mỗi dòng = 1 (máy, mã dừng); cột cấp máy (Efficiency, Times, Revolution, Output) LẶP LẠI ở
  mọi dòng dừng của cùng máy -> tách thành 2 danh sách `machines` / `stops`.
- Số có dấu phân cách nghìn ("1,523.00") -> bỏ dấu phẩy.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timedelta
from typing import Any

from core.production_time import PRODUCTION_SHIFT_START_HOUR, get_production_date

FILE_TYPE = "KNITTING_STOP_REASON"

# Header đã chuẩn hoá (viết thường, gộp khoảng trắng) -> field.
HEADER_MAP: dict[str, str] = {
    "m/c code": "machine_code",
    "job mc spec": "job_mc_spec",
    "knitting structure": "knitting_structure",
    "machine": "machine_efficiency",
    "operator": "operator_efficiency",
    "available": "available_time",
    "run": "run_time",
    "total stop": "total_stop_time",
    "# rev": "revolutions",
    "act.speed": "actual_speed",
    "# total production": "total_production",
    "stop code": "stop_code",
    "stop description": "stop_description",
    "stop color": "stop_color",
    "stop time details": "stop_time",
    "stop # details": "stop_count",
    "% loss stop time": "loss_ratio",
    "average stop time": "avg_stop_time",
}
MACHINE_FIELDS: tuple[str, ...] = (
    "machine_code", "job_mc_spec", "knitting_structure", "machine_efficiency", "operator_efficiency",
    "available_time", "run_time", "total_stop_time", "revolutions", "actual_speed", "total_production",
)
STOP_FIELDS: tuple[str, ...] = (
    "machine_code", "stop_code", "stop_description", "stop_color", "stop_time", "stop_count",
    "loss_ratio", "avg_stop_time",
)
_NUMERIC_FIELDS = {
    "machine_efficiency", "operator_efficiency", "available_time", "run_time", "total_stop_time",
    "revolutions", "actual_speed", "total_production", "stop_time", "stop_count", "loss_ratio", "avg_stop_time",
}
_INTEGER_FIELDS = {"stop_color"}
_REQUIRED_HEADERS = {"machine_code", "stop_code", "stop_time"}

_FILENAME_PERIOD = re.compile(
    r"(\d{2})-(\d{2})-(\d{4})\s+(\d{2})[;:_.](\d{2})[;:_.](\d{2})\s*-\s*"
    r"(\d{2})-(\d{2})-(\d{4})\s+(\d{2})[;:_.](\d{2})[;:_.](\d{2})"
)


def parse_period_from_filename(filename: str) -> tuple[datetime, datetime]:
    """Trả (period_start, period_end) đọc từ tên file dạng `dd-mm-yyyy HH;MM;SS - dd-mm-yyyy HH;MM;SS`."""
    match = _FILENAME_PERIOD.search(filename or "")
    if match is None:
        raise ValueError(
            "Không đọc được khoảng thời gian trong tên file — cần dạng "
            "'... dd-mm-yyyy 07;00;00 - dd-mm-yyyy 07;00;00.csv' (giữ nguyên tên file hệ thống xuất)."
        )
    g = [int(x) for x in match.groups()]
    try:
        start = datetime(g[2], g[1], g[0], g[3], g[4], g[5])
        end = datetime(g[8], g[7], g[6], g[9], g[10], g[11])
    except ValueError as exc:
        raise ValueError(f"Ngày giờ trong tên file không hợp lệ: {exc}") from exc
    return start, end


def production_date_from_filename(filename: str) -> tuple[str, datetime, datetime]:
    """Production Date (YYYY-MM-DD) + khoảng thời gian; từ chối khoảng không trọn 1 ngày sản xuất."""
    start, end = parse_period_from_filename(filename)
    if start.hour != PRODUCTION_SHIFT_START_HOUR or start.minute or start.second or end - start != timedelta(days=1):
        raise ValueError(
            f"Khoảng thời gian trong tên file ({start:%d-%m-%Y %H:%M} -> {end:%d-%m-%Y %H:%M}) không phải "
            f"đúng 1 ngày sản xuất ({PRODUCTION_SHIFT_START_HOUR:02d}:00 -> {PRODUCTION_SHIFT_START_HOUR:02d}:00 hôm sau)."
        )
    return get_production_date(start).isoformat(), start, end


def _header_key(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _decode(file_bytes: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return file_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("Không đọc được bảng mã file CSV (cần UTF-8).")


def _to_number(raw: str, field: str) -> float | int | None:
    text = raw.strip().replace(",", "")
    if not text:
        return None
    try:
        return int(float(text)) if field in _INTEGER_FIELDS else float(text)
    except ValueError as exc:
        raise ValueError(f"cột '{field}' không phải số: {raw!r}") from exc


def parse_stop_reason_file(file_bytes: bytes, filename: str) -> dict[str, Any]:
    """Parse toàn bộ file. Lỗi cấp file (tên file, thiếu header) -> raise ValueError; lỗi cấp dòng
    -> gom vào `errors` (dòng lỗi bị bỏ, dòng hợp lệ vẫn import — giống các importer khác)."""
    production_date, period_start, period_end = production_date_from_filename(filename)
    rows = list(csv.reader(io.StringIO(_decode(file_bytes))))

    header_index = next((i for i, row in enumerate(rows) if row and _header_key(row[0]) == "m/c code"), None)
    if header_index is None:
        raise ValueError("Không tìm thấy dòng header có cột 'M/c Code' — không phải file Stop Reason Analysis by Machine.")
    columns = {HEADER_MAP[key]: idx for idx, cell in enumerate(rows[header_index]) if (key := _header_key(cell)) in HEADER_MAP}
    missing = _REQUIRED_HEADERS - columns.keys()
    if missing:
        raise ValueError(f"File thiếu cột bắt buộc: {', '.join(sorted(missing))}.")

    machines: dict[str, dict[str, Any]] = {}
    stops: dict[tuple[str, str], dict[str, Any]] = {}
    errors: list[dict[str, Any]] = []
    warnings: list[str] = []
    row_details: list[dict[str, Any]] = []

    for offset, raw in enumerate(rows[header_index + 1:], start=header_index + 2):
        if not any(cell.strip() for cell in raw):
            continue
        data = {field: (raw[idx].strip() if idx < len(raw) else "") for field, idx in columns.items()}
        try:
            if not data["machine_code"]:
                raise ValueError("thiếu M/c Code")
            record = {
                field: (_to_number(value, field) if field in _NUMERIC_FIELDS | _INTEGER_FIELDS else value or None)
                for field, value in data.items()
            }
            machine = {field: record.get(field) for field in MACHINE_FIELDS}
            previous = machines.get(machine["machine_code"])
            if previous is None:
                machines[machine["machine_code"]] = machine
            elif previous != machine:
                warnings.append(f"Dòng {offset}: số liệu cấp máy {machine['machine_code']} khác dòng trước — giữ dòng đầu tiên.")

            # Máy không có lần dừng nào: dòng chỉ có cột cấp máy, Stop Code trống.
            if record.get("stop_code"):
                key = (machine["machine_code"], str(record["stop_code"]))
                if key in stops:
                    raise ValueError(f"trùng mã dừng {key[1]} của máy {key[0]}")
                stops[key] = {field: record.get(field) for field in STOP_FIELDS}
            row_details.append({"row_number": offset, "status": "valid", "data": data})
        except ValueError as exc:
            errors.append({"row": offset, "error": str(exc)})
            row_details.append({"row_number": offset, "status": "invalid", "error": str(exc), "data": data})

    return {
        "production_date": production_date,
        "period_start": period_start.strftime("%Y-%m-%d %H:%M:%S"),
        "period_end": period_end.strftime("%Y-%m-%d %H:%M:%S"),
        "machines": list(machines.values()),
        "stops": list(stops.values()),
        "errors": errors,
        "warnings": warnings,
        "row_details": row_details,
        "total_rows": len(row_details),
    }


def argb_to_hex(value: int | None) -> str | None:
    """`Stop Color` là ARGB 32-bit có dấu (kiểu .NET `Color.ToArgb()`, VD -65536 = đỏ #FF0000)."""
    if value is None:
        return None
    return f"#{value & 0xFFFFFF:06X}"
