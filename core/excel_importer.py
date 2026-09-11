"""
core/excel_importer.py
-----------------------
Core Utility dùng chung cho toàn bộ Excel Import Pipeline của mọi Engine.

Chức năng:
  1. Định nghĩa Schema (tên cột, kiểu dữ liệu, bắt buộc hay không) bằng
     `ColumnSpec` + `ImportSchema`.
  2. Đọc file `.xlsx` / `.xls` bằng `openpyxl`, hoặc `.csv` bằng module `csv`
     built-in — KHÔNG dùng pandas để giữ dependency tối giản cho Phase 1.
  3. Validate từng dòng: bỏ qua dòng trống, kiểm tra field bắt buộc, ép kiểu
     (datetime / float / int / enum), thu thập lỗi chi tiết theo số dòng.
  4. Bulk insert bằng `executemany` trong MỘT transaction duy nhất.
  5. Sinh file Excel mẫu (`export_template`) để người dùng tải về điền dữ liệu.

Kết quả trả về luôn là `ImportResult` — dataclass JSON-serializable, phù hợp
để các route Flask trả thẳng ra `jsonify(result.to_dict())`.
"""
from __future__ import annotations

import csv
import io
import json
import math
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Sequence

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.worksheet.worksheet import Worksheet

from core.database import get_dialect
from core.production_time import get_production_date


# Header và schema của hai file raw dữ liệu từ xưởng.
AVAILABILITY_COLUMNS: dict[str, str] = {
    "Batch": "batch", "Batch Ref No": "batch_ref_no", "Fabric Type": "fabric_type",
    "Brand Name": "brand_name", "Machine": "machine", "Capacity (Kg)": "capacity_kg",
    "Program": "program", "Start Time": "start_time", "End Time": "end_time",
    "Availability (%)": "availability_pct",
    "Total operation time (cal) (hour)": "total_op_time_cal_hour",
    "Planned PRD time (hour)": "planned_prd_time_hour", "No Order (hour)": "no_order_hour",
    "Testing Sample order (hour)": "testing_sample_order_hour", "Running time (hour)": "running_time_hour",
    "Total Downtime (hour)": "total_downtime_hour", "Rework (hour)": "rework_hour",
    "Adjust color (hour)": "adjust_color_hour", "Bleaching (hour)": "bleaching_hour",
    "Load (hour)": "load_hour", "Unload (hour)": "unload_hour",
    "Testing Bulk order (hour)": "testing_bulk_order_hour", "Sample checking (hour)": "sample_checking_hour",
    "PH checking (hour)": "ph_checking_hour", "Wait for chemical load (hour)": "wait_chemical_load_hour",
    "Wait for color load (hour)": "wait_color_load_hour", "Wait for fabric (hour)": "wait_fabric_hour",
    "Wait for water (hour)": "wait_water_hour", "Wait for steam (hour)": "wait_steam_hour",
    "Cleaning (hour)": "cleaning_hour", "Maintenance (hour)": "maintenance_hour",
    "Others (hour)": "others_hour",
}
# Sinh cột Kg-H bằng cách thay đúng hậu tố " (hour)" -> " (Kg-H)" trên chính header (hour) đã
# khai báo ở trên — giữ nguyên chữ gốc (VD: "Total operation time (cal)") thay vì suy luận lại
# từ snake_case field name (dễ sai như "Total Op Time Cal" != "Total operation time (cal)").
for _hour_header, _hour_field in list(AVAILABILITY_COLUMNS.items()):
    if _hour_header.endswith(" (hour)") and _hour_field.endswith("_hour"):
        _kgh_header = _hour_header[: -len(" (hour)")] + " (Kg-H)"
        _kgh_field = _hour_field[: -len("_hour")] + "_kgh"
        AVAILABILITY_COLUMNS[_kgh_header] = _kgh_field
# Ngoại lệ đã xác minh trên file mẫu thật (Availability_20260908to09.xlsx): 2 cột Kg-H này
# KHÔNG theo đúng quy tắc thay hậu tố ở trên — đổi hẳn chữ "Testing" -> "Test Production -".
# Khai báo thêm alias đúng chữ thật để không mất dữ liệu 2 cột này khi import.
AVAILABILITY_COLUMNS["Test Production - Sample order (Kg-H)"] = "testing_sample_order_kgh"
AVAILABILITY_COLUMNS["Test Production - Bulk order (Kg-H)"] = "testing_bulk_order_kgh"

PERFORMANCE_COLUMNS: dict[str, str] = {
    "Dyelot": "dyelot", "BrandName": "brand_name", "Machine": "machine",
    "MachineGroup": "machine_group", "MaxCapacityPercent": "max_capacity_pct", "Capacity": "capacity",
    "DyelotRefNo": "dyelot_ref_no",
    "FabricType": "fabric_type", "TreatmentProgram": "program", "Redye": "redye",
    "SapNo": "sap_no", "PTH": "pth", "StartTime": "start_time", "EndTime": "end_time",
    "Performance": "performance", "Speed": "speed", "Loading": "loading",
    "OutputKg": "output_kg", "OutputKgH": "output_kgh", "OutputMaxLoadKgH": "output_max_load_kgh",
    "RunningTime": "running_time", "RunningTimeKgH": "running_time_kgh",
}

BATCH_SIGNATURE = {"dyelot", "treatmentprogram", "shade", "recipeno"}
PERFORMANCE_SIGNATURE = {"mc", "shift", "program", "runtime"}
AVAILABILITY_SIGNATURE = {"dyelot", "availability", "reason"}
BATCH_ALIASES = {
    "dyelot": "dyelot", "dyelot no": "dyelot", "customer": "customer", "brand_name": "customer",
    "customer name": "customer", "machine": "machine", "mc": "machine", "treatmentprogram": "program",
    "program": "program", "processtype": "program", "shade": "shade", "colourno": "colour_no",
    "colour_no": "colour_no", "weight": "weight", "capacity": "weight", "weight (kg)": "weight",
}


def _normalized_headers(headers: list[str]) -> set[str]:
    return {" ".join(str(header).strip().lower().split()) for header in headers if str(header).strip()}


def detect_file_type_from_headers(headers: list[str]) -> str:
    """Detect Availability, Performance or Batch from header signatures."""
    normalized = _normalized_headers(headers)
    compact = {header.replace(" ", "") for header in normalized}
    if BATCH_SIGNATURE <= compact:
        return "BATCH"
    if PERFORMANCE_SIGNATURE <= compact:
        return "PERFORMANCE"
    if {header.replace(" ", "") for header in AVAILABILITY_SIGNATURE} <= compact:
        return "AVAILABILITY"
    raise ValueError(
        "Không nhận diện được loại file. Signature yêu cầu: Batch (Dyelot, TreatmentProgram, Shade, RecipeNo), "
        "Performance (MC, Shift, Program, Run time) hoặc Availability (Dyelot, Availability, Reason)."
    )

_AVAILABILITY_REQUIRED = {"batch", "machine", "start_time"}
_PERFORMANCE_REQUIRED = {"dyelot", "machine", "start_time"}
_DATETIME_FIELDS = {"start_time", "end_time"}
_NUMERIC_FIELDS = {
    "capacity_kg", "availability_pct",
    *[field for field in AVAILABILITY_COLUMNS.values() if field.endswith(("_hour", "_kgh"))],
    "capacity", "max_capacity_pct", "performance", "speed", "loading", "pth",
    "output_kg", "output_kgh", "output_max_load_kgh", "running_time", "running_time_kgh",
}

STANDARD_HOURS = {
    "load_hour": 0.15,
    "unload_hour": 0.10,
    "sample_checking_hour": 0.50,
    "ph_checking_hour": 0.50,
    "wait_chemical_load_hour": 0.50,
    "wait_color_load_hour": 0.50,
}
ACH_FIELDS = ("ach_load", "ach_unload", "ach_sample_check", "ach_ph", "ach_chemical", "ach_color")
AVAILABILITY_DB_FIELDS = tuple(AVAILABILITY_COLUMNS.values()) + (
    "production_date", "week_label", "month_label", *ACH_FIELDS,
    "ach_evaluated", "ach_passed", "ach_all_items",
)

# ---------------------------------------------------------------------------
# Kiểu dữ liệu hỗ trợ ép kiểu (Data Type Parsing)
# ---------------------------------------------------------------------------

DATE_FORMATS: tuple[str, ...] = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y",
)


def calculate_production_date(value: Any) -> date | None:
    """Tính ngày sản xuất (production_date) — CHỈ ép kiểu giá trị đầu vào rồi delegate
    sang `core/production_time.py::get_production_date()` (nguồn DUY NHẤT cho công thức
    cắt ca 07:00). Trước đây hàm này tự viết lại công thức cắt ca riêng — cùng kết quả
    nhưng là rủi ro lệch nhau nếu 1 trong 2 nơi bị sửa mà quên sửa nơi còn lại (xem
    memory-bank/systemPatterns.md mục 6.2)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        normalized = _raw_datetime(value)
        if normalized is None:
            return None
        parsed = datetime.strptime(normalized, "%Y-%m-%d %H:%M:%S")
    return get_production_date(parsed)


def _standard_result(value: Any, standard: float) -> int | None:
    numeric = _raw_float(value)
    if numeric <= 0:
        return None
    return 1 if numeric <= standard else 0


def _add_availability_business_fields(record: dict[str, Any]) -> None:
    reference_time = record.get("end_time") or record.get("start_time")
    production = calculate_production_date(reference_time)
    if production is None:
        return
    record["production_date"] = production.isoformat()
    iso_year, iso_week, _ = production.isocalendar()
    record["week_label"] = f"{iso_year}-W{iso_week:02d}"
    record["month_label"] = production.strftime("%Y-%m")
    results = {
        "ach_load": _standard_result(record.get("load_hour"), STANDARD_HOURS["load_hour"]),
        "ach_unload": _standard_result(record.get("unload_hour"), STANDARD_HOURS["unload_hour"]),
        "ach_sample_check": _standard_result(record.get("sample_checking_hour"), STANDARD_HOURS["sample_checking_hour"]),
        "ach_ph": _standard_result(record.get("ph_checking_hour"), STANDARD_HOURS["ph_checking_hour"]),
        "ach_chemical": _standard_result(record.get("wait_chemical_load_hour"), STANDARD_HOURS["wait_chemical_load_hour"]),
        "ach_color": _standard_result(record.get("wait_color_load_hour"), STANDARD_HOURS["wait_color_load_hour"]),
    }
    evaluated = [result for result in results.values() if result is not None]
    record.update(results)
    record["ach_evaluated"] = len(evaluated)
    record["ach_passed"] = sum(evaluated)
    record["ach_all_items"] = int(bool(evaluated) and record["ach_passed"] == record["ach_evaluated"])


def _parse_datetime(value: Any) -> datetime:
    """Ép kiểu giá trị (str hoặc datetime từ openpyxl) sang `datetime`.

    Ném `ValueError` với thông báo tiếng Việt rõ ràng nếu không parse được —
    dùng trực tiếp làm nội dung lỗi trả về cho người dùng.
    """
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise ValueError(
        f"không đúng định dạng ngày giờ (ví dụ hợp lệ: 'YYYY-MM-DD HH:MM')"
    )


def _parse_float(value: Any) -> float:
    try:
        return float(str(value).strip().replace(",", ""))
    except (ValueError, TypeError) as exc:
        raise ValueError("không phải là số thực (float) hợp lệ") from exc


def _parse_int(value: Any) -> int:
    try:
        return int(float(str(value).strip()))
    except (ValueError, TypeError) as exc:
        raise ValueError("không phải là số nguyên (int) hợp lệ") from exc


def _parse_str(value: Any) -> str:
    return str(value).strip()


def _parse_enum(allowed_values: Sequence[str]) -> Callable[[Any], str]:
    def _parser(value: Any) -> str:
        text = str(value).strip().upper()
        if text not in allowed_values:
            raise ValueError(
                f"giá trị '{text}' không hợp lệ, phải là một trong {list(allowed_values)}"
            )
        return text

    return _parser


TYPE_PARSERS: dict[str, Callable[[Any], Any]] = {
    "datetime": _parse_datetime,
    "float": _parse_float,
    "int": _parse_int,
    "str": _parse_str,
}


# ---------------------------------------------------------------------------
# Schema definition
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ColumnSpec:
    """Đặc tả một cột trong schema import."""

    name: str  # tên cột trong file Excel/CSV (không phân biệt hoa/thường)
    dtype: str  # "str" | "int" | "float" | "datetime" | "enum"
    required: bool = True
    enum_values: tuple[str, ...] = ()
    description: str = ""

    def parser(self) -> Callable[[Any], Any]:
        if self.dtype == "enum":
            return _parse_enum(self.enum_values)
        return TYPE_PARSERS[self.dtype]


@dataclass(frozen=True)
class ImportSchema:
    """Schema đầy đủ cho một loại import (vd: Telemetry, Downtime)."""

    key: str  # định danh, vd "telemetry"
    table_name: str  # bảng SQLite đích
    columns: tuple[ColumnSpec, ...]
    insert_sql: str  # câu SQL INSERT dùng cho executemany

    @property
    def required_columns(self) -> list[str]:
        return [c.name for c in self.columns if c.required]

    @property
    def column_names(self) -> list[str]:
        return [c.name for c in self.columns]


# ---------------------------------------------------------------------------
# Kết quả Import
# ---------------------------------------------------------------------------


@dataclass
class RowError:
    row: int  # số dòng trong file gốc (tính cả header, 1-indexed, dễ đối chiếu Excel)
    error: str

    def to_dict(self) -> dict[str, Any]:
        return {"row": self.row, "error": self.error}


@dataclass
class ImportResult:
    schema_key: str
    total_rows: int = 0
    inserted_rows: int = 0
    skipped_rows: int = 0
    errors: list[RowError] = field(default_factory=list)
    committed: bool = False
    preview: list[dict[str, Any]] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.committed and (self.inserted_rows > 0 or self.total_rows == 0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema_key,
            "success": self.success,
            "committed": self.committed,
            "total_rows": self.total_rows,
            "inserted_rows": self.inserted_rows,
            "skipped_rows": self.skipped_rows,
            "error_count": len(self.errors),
            "errors": [e.to_dict() for e in self.errors],
            "preview": self.preview,
        }


# ---------------------------------------------------------------------------
# Đọc file nguồn (xlsx / xls / csv) -> list[dict] thô (chưa ép kiểu)
# ---------------------------------------------------------------------------


def _read_rows_from_xlsx(file_stream: io.BytesIO) -> tuple[list[str], list[tuple[int, list[Any]]]]:
    """Đọc sheet đầu tiên của workbook. Trả về (header, [(row_index, values), ...])."""
    workbook = load_workbook(filename=file_stream, data_only=True, read_only=True)
    sheet: Worksheet = workbook.worksheets[0]
    rows_iter = sheet.iter_rows(values_only=True)
    header = [str(h).strip() if h is not None else "" for h in next(rows_iter, [])]
    raw_rows: list[tuple[int, list[Any]]] = []
    for idx, row in enumerate(rows_iter, start=2):  # dòng 1 là header
        raw_rows.append((idx, list(row)))
    workbook.close()
    return header, raw_rows


def _read_rows_from_csv(file_stream: io.BytesIO) -> tuple[list[str], list[tuple[int, list[Any]]]]:
    text_stream = io.TextIOWrapper(file_stream, encoding="utf-8-sig")
    reader = csv.reader(text_stream)
    rows = list(reader)
    if not rows:
        return [], []
    header = [h.strip() for h in rows[0]]
    raw_rows = [(idx, row) for idx, row in enumerate(rows[1:], start=2)]
    return header, raw_rows


def _is_blank_row(values: Sequence[Any]) -> bool:
    """Một dòng được coi là trống nếu toàn bộ ô đều None hoặc chuỗi rỗng."""
    return all(v is None or str(v).strip() == "" for v in values)


# ---------------------------------------------------------------------------
# API chính: validate_and_parse + bulk_insert
# ---------------------------------------------------------------------------


def parse_file(
    filename: str, file_bytes: bytes, schema: ImportSchema
) -> tuple[list[dict[str, Any]], list[RowError]]:
    """
    Đọc + validate + ép kiểu dữ liệu theo `schema`.

    Trả về (parsed_rows, errors):
      - parsed_rows: danh sách dict đã ép kiểu đúng, sẵn sàng insert.
      - errors: danh sách RowError chi tiết theo số dòng, KHÔNG làm crash ứng dụng.
    """
    ext = filename.rsplit(".", 1)[-1].lower()
    stream = io.BytesIO(file_bytes)

    if ext in ("xlsx", "xls"):
        header, raw_rows = _read_rows_from_xlsx(stream)
    elif ext == "csv":
        header, raw_rows = _read_rows_from_csv(stream)
    else:
        raise ValueError(f"Định dạng file '.{ext}' không được hỗ trợ.")

    header_lower = [h.lower() for h in header]
    missing_columns = [c for c in schema.required_columns if c.lower() not in header_lower]
    if missing_columns:
        raise ValueError(
            f"File thiếu (các) cột bắt buộc: {', '.join(missing_columns)}. "
            f"Cột hiện có: {', '.join(header) or '(rỗng)'}"
        )

    # map: tên cột (lowercase) -> vị trí trong hàng
    col_index: dict[str, int] = {name: header_lower.index(name.lower()) for name in schema.column_names if name.lower() in header_lower}

    parsed_rows: list[dict[str, Any]] = []
    errors: list[RowError] = []

    for row_number, values in raw_rows:
        if _is_blank_row(values):
            continue  # tự động bỏ qua dòng trống

        parsed: dict[str, Any] = {}
        row_has_error = False
        for col in schema.columns:
            idx = col_index.get(col.name.lower())
            raw_value = values[idx] if idx is not None and idx < len(values) else None

            if raw_value is None or str(raw_value).strip() == "":
                if col.required:
                    errors.append(
                        RowError(row=row_number, error=f"Cột '{col.name}' bị thiếu giá trị (bắt buộc).")
                    )
                    row_has_error = True
                    break
                parsed[col.name] = None
                continue

            try:
                parsed[col.name] = col.parser()(raw_value)
            except ValueError as exc:
                errors.append(RowError(row=row_number, error=f"Cột '{col.name}' {exc}"))
                row_has_error = True
                break

        if not row_has_error:
            parsed_rows.append(parsed)

    return parsed_rows, errors


def bulk_insert(
    conn: Any,
    schema: ImportSchema,
    parsed_rows: list[dict[str, Any]],
    extra_params: Sequence[Any] = (),
) -> int:
    """
    Chèn hàng loạt bằng `executemany` trong MỘT transaction duy nhất.

    `extra_params` cho phép truyền thêm giá trị cố định vào cuối mỗi dòng
    (vd: `import_log_id`) — các cột này phải khớp thứ tự với `insert_sql`.
    """
    if not parsed_rows:
        return 0
    values = [tuple(row[col.name] for col in schema.columns) + tuple(extra_params) for row in parsed_rows]
    cur = conn.executemany(schema.insert_sql, values)
    conn.commit()
    count = cur.rowcount
    cur.close()
    return count


def run_import(
    conn: Any,
    filename: str,
    file_bytes: bytes,
    schema: ImportSchema,
    strict_mode: bool = False,
    extra_params: Sequence[Any] = (),
) -> ImportResult:
    """
    Orchestrator: parse -> (strict check) -> bulk insert -> trả ImportResult.

    - `strict_mode=True`: nếu có BẤT KỲ dòng lỗi nào -> KHÔNG commit, trả lỗi.
    - `strict_mode=False`: bỏ qua dòng lỗi, commit các dòng hợp lệ còn lại.
    """
    parsed_rows, errors = parse_file(filename, file_bytes, schema)
    result = ImportResult(
        schema_key=schema.key,
        total_rows=len(parsed_rows) + len(errors),
        skipped_rows=len(errors),
        errors=errors,
        preview=parsed_rows[:5],
    )

    if strict_mode and errors:
        result.committed = False
        return result

    inserted = bulk_insert(conn, schema, parsed_rows, extra_params=extra_params)
    result.inserted_rows = inserted
    result.committed = True
    return result


def preview_file(filename: str, file_bytes: bytes, schema: ImportSchema, limit: int = 5) -> dict[str, Any]:
    """Xem trước (Preview) N dòng đầu tiên + lỗi phát hiện được, KHÔNG ghi DB."""
    parsed_rows, errors = parse_file(filename, file_bytes, schema)
    return {
        "columns": schema.column_names,
        "preview_rows": parsed_rows[:limit],
        "total_valid_rows": len(parsed_rows),
        "errors": [e.to_dict() for e in errors[:20]],
        "error_count": len(errors),
    }


# ---------------------------------------------------------------------------
# Sinh file Excel mẫu (Template Export)
# ---------------------------------------------------------------------------


def export_template(schema: ImportSchema, sample_rows: list[tuple[Any, ...]] | None = None) -> bytes:
    """
    Sinh file `.xlsx` mẫu cho một schema: header in đậm + vài dòng dữ liệu mẫu
    (nếu có) để người dùng biết định dạng cần điền.

    Trả về bytes của file — route chỉ cần gói vào `send_file(io.BytesIO(...))`.
    """
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = schema.key[:31]

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="24292F", end_color="24292F", fill_type="solid")

    for col_idx, column in enumerate(schema.columns, start=1):
        cell = sheet.cell(row=1, column=col_idx, value=column.name)
        cell.font = header_font
        cell.fill = header_fill
        sheet.column_dimensions[cell.column_letter].width = max(18, len(column.name) + 4)

    if sample_rows:
        for row_idx, sample in enumerate(sample_rows, start=2):
            for col_idx, value in enumerate(sample, start=1):
                sheet.cell(row=row_idx, column=col_idx, value=value)

    # Thêm sheet hướng dẫn cột bắt buộc / kiểu dữ liệu
    guide_sheet = workbook.create_sheet("Huong_Dan")
    guide_sheet.append(["Cột", "Kiểu dữ liệu", "Bắt buộc", "Mô tả"])
    for cell in guide_sheet[1]:
        cell.font = header_font
        cell.fill = header_fill
    for column in schema.columns:
        guide_sheet.append(
            [column.name, column.dtype, "Có" if column.required else "Không", column.description]
        )
    for col_letter in ("A", "B", "C", "D"):
        guide_sheet.column_dimensions[col_letter].width = 28

    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()


def allowed_file(filename: str, allowed_extensions: set[str]) -> bool:
    """Kiểm tra phần mở rộng file có nằm trong danh sách cho phép hay không."""
    return "." in filename and filename.rsplit(".", 1)[-1].lower() in allowed_extensions


# ---------------------------------------------------------------------------
# Raw Availability / Performance importer
# ---------------------------------------------------------------------------

def _raw_cell(value: Any) -> Any:
    """Chuẩn hóa giá trị rỗng của Excel/CSV mà không làm mất số 0 hợp lệ."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip()
    return None if text == "" or text.lower() in {"nan", "nat", "none"} else value


def _raw_datetime(value: Any) -> str | None:
    value = _raw_cell(value)
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    text = str(value).strip()
    formats = (
        "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M", "%m/%d/%Y",
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
        "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y",
    )
    for date_format in formats:
        try:
            return datetime.strptime(text, date_format).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    raise ValueError(f"không đúng định dạng ngày giờ: {text}")


def _raw_float(value: Any) -> float:
    value = _raw_cell(value)
    if value is None:
        return 0.0
    try:
        return float(str(value).strip().replace(",", ""))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"không phải số hợp lệ: {value}") from exc


def _read_raw_file(file_path: str) -> tuple[list[str], list[tuple[int, list[Any]]]]:
    path = Path(file_path)
    if path.suffix.lower() in {".xlsx", ".xls"}:
        return _read_rows_from_xlsx(io.BytesIO(path.read_bytes()))
    if path.suffix.lower() == ".csv":
        return _read_rows_from_csv(io.BytesIO(path.read_bytes()))
    raise ValueError("Chỉ hỗ trợ file .xlsx, .xls hoặc .csv.")


def _raw_mapping(headers: list[str], mapping: dict[str, str]) -> dict[str, int]:
    normalized = {header.strip().lower(): index for index, header in enumerate(headers)}
    return {field: normalized[header.lower()] for header, field in mapping.items() if header.lower() in normalized}


def _build_raw_row_dict(fields: list[str], indexes: dict[str, int], values: list[Any]) -> dict[str, str]:
    """Trích xuất {field: raw_value_str} từ 1 dòng sheet — snapshot lưu vào `import_log_rows`
    để Raw Data Viewer hiển thị/sửa, độc lập với việc ép kiểu sau đó thành công hay không."""
    raw: dict[str, str] = {}
    for field in fields:
        idx = indexes.get(field)
        value = values[idx] if idx is not None and idx < len(values) else None
        cleaned = _raw_cell(value)
        raw[field] = "" if cleaned is None else str(cleaned)
    return raw


def _parse_raw_row(file_type: str, fields: list[str], required: set[str], raw: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """Ép kiểu + áp business rule cho 1 dòng Availability/Performance ở dạng raw dict.

    Dùng chung cho vòng lặp import hàng loạt (`detect_and_parse_file`) VÀ cho
    `revalidate_raw_row()` khi người dùng sửa 1 dòng lỗi trong Raw Data Viewer — đảm bảo
    cùng một luật ép kiểu, không lặp code hai nơi.
    """
    record: dict[str, Any] = {}
    try:
        for field in fields:
            raw_value = raw.get(field)
            if field in _DATETIME_FIELDS:
                record[field] = _raw_datetime(raw_value)
            elif field in _NUMERIC_FIELDS:
                record[field] = _raw_float(raw_value)
            else:
                record[field] = str(_raw_cell(raw_value) or "").strip()
        if file_type == "AVAILABILITY" and not record.get("batch_ref_no"):
            record["batch_ref_no"] = record.get("batch", "")
        # Dòng Tổng Kết (Summary Row) ở cuối file Availability/Performance: Batch/Dyelot hoặc
        # Machine = 'All', Start Time/Program rỗng — kiểm tra TRƯỚC missing-required để báo
        # đúng lý do "dòng tổng kết" thay vì lẫn với thông báo thiếu field chung chung.
        summary_key = "dyelot" if file_type == "PERFORMANCE" else "batch"
        if record.get(summary_key, "").strip().lower() == "all" or record.get("machine", "").strip().lower() == "all":
            return None, "Dòng tổng hợp 'All' — bị bỏ qua khi import (không phải dòng dữ liệu thật)."
        missing = [field for field in required if record.get(field) is None or not str(record.get(field, "")).strip()]
        if missing:
            return None, f"Thiếu giá trị bắt buộc: {', '.join(missing)}"
        if file_type == "AVAILABILITY":
            _add_availability_business_fields(record)
        return record, None
    except ValueError as exc:
        return None, str(exc)


def revalidate_raw_row(file_type: str, raw: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """Re-validate 1 dòng Availability/Performance đã được sửa qua Inline Edit."""
    if file_type == "AVAILABILITY":
        fields, required = list(AVAILABILITY_COLUMNS.values()), _AVAILABILITY_REQUIRED
    elif file_type == "PERFORMANCE":
        fields, required = list(PERFORMANCE_COLUMNS.values()), _PERFORMANCE_REQUIRED
    else:
        raise ValueError(f"file_type '{file_type}' không hỗ trợ revalidate.")
    return _parse_raw_row(file_type, fields, required, raw)


def detect_and_parse_file(file_path: str) -> dict[str, Any]:
    """Tự nhận diện và làm sạch một file Availability hoặc Performance.

    Kết quả có dạng ``{"file_type": ..., "columns": ..., "rows": ..., "errors": ...}``.
    ``rows`` là danh sách record chuẩn hóa, dùng được như DataFrame records mà
    không bắt buộc cài thêm pandas vào hệ thống offline.
    """
    headers, raw_rows = _read_raw_file(file_path)
    # Chỉ dùng signature-match để nhận diện sớm BATCH (đã xác minh khớp đúng file thật: Dyelot +
    # TreatmentProgram + Shade + RecipeNo). KHÔNG được raise ở đây cho Availability/Performance —
    # file thật của 2 loại này không có cột Dyelot/Availability/Reason hay MC/Shift/RunTime như
    # signature cũ giả định; để logic required-field mạnh mẽ hơn bên dưới tự nhận diện.
    try:
        detected_type = detect_file_type_from_headers(headers)
    except ValueError:
        detected_type = None
    if detected_type == "BATCH":
        mapping = {header: field for header, field in BATCH_ALIASES.items()}
        indexes = {field: index for index, header in enumerate(headers) for alias, field in mapping.items() if str(header).strip().lower() == alias}
        fields = sorted(set(indexes))
        rows = []
        errors = []
        for row_number, values in raw_rows:
            if _is_blank_row(values):
                continue
            record = {field: str(_raw_cell(values[indexes[field]]) or "").strip() if indexes[field] < len(values) else None for field in fields}
            if not record.get("dyelot"):
                errors.append({"row": row_number, "error": "Thiếu cột/giá trị bắt buộc Dyelot."})
                continue
            rows.append(record)
        return {"file_type": "BATCH", "columns": fields, "rows": rows, "errors": errors}

    availability_index = _raw_mapping(headers, AVAILABILITY_COLUMNS)
    performance_index = _raw_mapping(headers, PERFORMANCE_COLUMNS)
    if _AVAILABILITY_REQUIRED <= set(availability_index):
        file_type, mapping, required = "AVAILABILITY", AVAILABILITY_COLUMNS, _AVAILABILITY_REQUIRED
    elif _PERFORMANCE_REQUIRED <= set(performance_index):
        file_type, mapping, required = "PERFORMANCE", PERFORMANCE_COLUMNS, _PERFORMANCE_REQUIRED
    else:
        raise ValueError(
            "Không nhận diện được file. Cần header Availability (Batch, Machine, Start Time) "
            "hoặc Performance (Dyelot, Machine, StartTime)."
        )

    indexes = availability_index if file_type == "AVAILABILITY" else performance_index
    fields = list(mapping.values())
    errors: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    row_details: list[dict[str, Any]] = []
    for row_number, values in raw_rows:
        if _is_blank_row(values):
            continue
        raw = _build_raw_row_dict(fields, indexes, values)
        record, error = _parse_raw_row(file_type, fields, required, raw)
        if error is not None:
            errors.append({"row": row_number, "error": error})
            row_details.append({"row_number": row_number, "status": "invalid", "error": error, "data": raw})
            continue
        rows.append(record)
        row_details.append({"row_number": row_number, "status": "valid", "error": None, "data": raw})
    return {"file_type": file_type, "columns": fields, "rows": rows, "errors": errors, "row_details": row_details}


# Tên cột cũ (Phase trước khi chuẩn hoá mapping "_hour"/"_kgh") -> tên cột chuẩn mới, dùng để
# migrate DB cũ bằng `ALTER TABLE ... RENAME COLUMN` (giữ nguyên dữ liệu đã import trước đó,
# KHÔNG cần xoá/tạo lại bảng hay yêu cầu người dùng import lại từ đầu).
_AVAILABILITY_COLUMN_RENAMES: dict[str, str] = {
    "planned_prd_time": "planned_prd_time_hour", "running_time": "running_time_hour",
    "total_downtime": "total_downtime_hour", "rework": "rework_hour", "adjust_color": "adjust_color_hour",
    "bleaching": "bleaching_hour", "load": "load_hour", "unload": "unload_hour",
    "sample_checking": "sample_checking_hour", "ph_checking": "ph_checking_hour",
    "wait_chemical": "wait_chemical_load_hour", "wait_color": "wait_color_load_hour",
    "wait_fabric": "wait_fabric_hour", "wait_water": "wait_water_hour", "wait_steam": "wait_steam_hour",
    "cleaning": "cleaning_hour", "maintenance": "maintenance_hour", "no_order": "no_order_hour",
    "others": "others_hour",
}


def _ensure_raw_tables(conn: Any) -> None:
    """Tạo bảng raw khi app đang chạy trên DB cũ chưa chạy init_db lại — đồng thời migrate
    `availability_logs` sang chuẩn cột `_hour`/`_kgh` mới (đổi tên cột cũ nếu có, thêm cột mới
    còn thiếu) mà KHÔNG làm mất dữ liệu đã import trước đó. CHỈ chạy DDL/`executescript` này ở
    SQLite — `executescript()` là API riêng của `sqlite3.Connection`, không tồn tại ở
    psycopg2; ở Postgres 2 bảng này đã được tạo trước qua `supabase/schema.sql`."""
    if get_dialect() == "sqlite":
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS availability_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, batch TEXT NOT NULL, batch_ref_no TEXT,
                fabric_type TEXT, brand_name TEXT, machine TEXT NOT NULL, capacity_kg REAL NOT NULL DEFAULT 0,
                program TEXT, start_time TEXT NOT NULL, end_time TEXT, production_date TEXT, week_label TEXT, month_label TEXT,
                ach_load INTEGER, ach_unload INTEGER, ach_sample_check INTEGER, ach_ph INTEGER,
                ach_chemical INTEGER, ach_color INTEGER, ach_evaluated INTEGER NOT NULL DEFAULT 0,
                ach_passed INTEGER NOT NULL DEFAULT 0, ach_all_items INTEGER NOT NULL DEFAULT 0,
                import_log_id INTEGER, created_at TEXT NOT NULL DEFAULT (datetime('now')), UNIQUE(batch, machine, start_time)
            );
            CREATE TABLE IF NOT EXISTS performance_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, dyelot TEXT NOT NULL, brand_name TEXT, machine TEXT NOT NULL,
                machine_group TEXT, max_capacity_pct REAL NOT NULL DEFAULT 0, capacity REAL NOT NULL DEFAULT 0,
                dyelot_ref_no TEXT, fabric_type TEXT, program TEXT,
                redye TEXT, sap_no TEXT, pth REAL NOT NULL DEFAULT 0, start_time TEXT NOT NULL, end_time TEXT,
                performance REAL NOT NULL DEFAULT 0,
                speed REAL NOT NULL DEFAULT 0, loading REAL NOT NULL DEFAULT 0, output_kg REAL NOT NULL DEFAULT 0,
                output_kgh REAL NOT NULL DEFAULT 0, output_max_load_kgh REAL NOT NULL DEFAULT 0,
                running_time REAL NOT NULL DEFAULT 0, running_time_kgh REAL NOT NULL DEFAULT 0, import_log_id INTEGER,
                created_at TEXT NOT NULL DEFAULT (datetime('now')), UNIQUE(dyelot, machine, start_time)
            );
        """)
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(availability_logs)")}
    for old_name, new_name in _AVAILABILITY_COLUMN_RENAMES.items():
        if old_name in existing and new_name not in existing:
            conn.execute(f"ALTER TABLE availability_logs RENAME COLUMN {old_name} TO {new_name}")
            existing.discard(old_name)
            existing.add(new_name)
    additions = {
        "availability_pct": "REAL NOT NULL DEFAULT 0",
        **{field: "REAL NOT NULL DEFAULT 0" for field in AVAILABILITY_COLUMNS.values() if field.endswith(("_hour", "_kgh"))},
        "production_date": "TEXT", "week_label": "TEXT", "month_label": "TEXT",
        "ach_load": "INTEGER", "ach_unload": "INTEGER", "ach_sample_check": "INTEGER",
        "ach_ph": "INTEGER", "ach_chemical": "INTEGER", "ach_color": "INTEGER",
        "ach_evaluated": "INTEGER NOT NULL DEFAULT 0", "ach_passed": "INTEGER NOT NULL DEFAULT 0",
        "ach_all_items": "INTEGER NOT NULL DEFAULT 0",
    }
    for column, definition in additions.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE availability_logs ADD COLUMN {column} {definition}")
    conn.execute("UPDATE availability_logs SET batch_ref_no = batch WHERE batch_ref_no IS NULL OR TRIM(batch_ref_no) = ''")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_availability_batch_ref_machine_start ON availability_logs (batch_ref_no, machine, start_time)")

    performance_existing = {row["name"] for row in conn.execute("PRAGMA table_info(performance_logs)")}
    performance_additions = {
        "max_capacity_pct": "REAL NOT NULL DEFAULT 0", "pth": "REAL NOT NULL DEFAULT 0",
        "output_max_load_kgh": "REAL NOT NULL DEFAULT 0", "running_time_kgh": "REAL NOT NULL DEFAULT 0",
    }
    for column, definition in performance_additions.items():
        if column not in performance_existing:
            conn.execute(f"ALTER TABLE performance_logs ADD COLUMN {column} {definition}")
    conn.commit()


def save_to_db(df: Any, file_type: str, db_connection: Any, import_log_id: int | None = None) -> int:
    """Bulk UPSERT normalized records in one SQLite transaction."""
    if file_type not in {"AVAILABILITY", "PERFORMANCE"}:
        raise ValueError("file_type phải là AVAILABILITY hoặc PERFORMANCE.")
    rows = df.get("rows", []) if isinstance(df, dict) else list(df)
    if not rows:
        return 0
    _ensure_raw_tables(db_connection)
    fields = list(AVAILABILITY_DB_FIELDS) if file_type == "AVAILABILITY" else list(PERFORMANCE_COLUMNS.values())
    table = "availability_logs" if file_type == "AVAILABILITY" else "performance_logs"
    key_fields = ("batch_ref_no", "machine", "start_time") if file_type == "AVAILABILITY" else ("dyelot", "machine", "start_time")
    fields_with_log = fields + ["import_log_id"]
    placeholders = ", ".join("?" for _ in fields_with_log)
    updates = ", ".join(f"{field}=excluded.{field}" for field in fields if field not in key_fields)
    sql = f"INSERT INTO {table} ({', '.join(fields_with_log)}) VALUES ({placeholders}) ON CONFLICT ({', '.join(key_fields)}) DO UPDATE SET {updates}, import_log_id=excluded.import_log_id"
    invalid_rows = [
        index + 1
        for index, row in enumerate(rows)
        if any(row.get(field) is None or not str(row.get(field, "")).strip() for field in key_fields)
    ]
    if invalid_rows:
        raise ValueError(f"Dữ liệu có khóa bắt buộc rỗng tại dòng: {invalid_rows[:10]}")
    values = [
        tuple(row.get(field, 0.0 if field in _NUMERIC_FIELDS else None) for field in fields)
        + (import_log_id,)
        for row in rows
    ]
    try:
        db_connection.execute("BEGIN")
        cursor = db_connection.executemany(sql, values)
        count = cursor.rowcount
        db_connection.commit()
        return len(rows) if count < 0 else len(rows)
    except Exception:
        db_connection.rollback()
        raise


# ---------------------------------------------------------------------------
# Raw Data Viewer: lưu snapshot raw data + trạng thái từng dòng của mọi lần
# import (Availability/Performance/Batch) để xem lại/lọc/sửa mà không cần
# upload lại file. Không có tầng lưu trữ này trước đây — mọi thứ bị huỷ ngay
# sau khi response HTTP được gửi đi.
# ---------------------------------------------------------------------------


def _ensure_import_log_rows_table(conn: Any) -> None:
    """CHỈ chạy CREATE TABLE ở SQLite — ở Postgres bảng đã có sẵn qua `supabase/schema.sql`."""
    if get_dialect() == "sqlite":
        conn.execute("""
            CREATE TABLE IF NOT EXISTS import_log_rows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                import_log_id INTEGER NOT NULL,
                row_number INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'valid',
                error_message TEXT,
                row_data TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_import_log_rows_log_id ON import_log_rows (import_log_id)")


def record_import_rows(conn: Any, import_log_id: int, row_details: list[dict[str, Any]]) -> None:
    """Ghi snapshot raw data + trạng thái từng dòng vào `import_log_rows` sau một lần import."""
    _ensure_import_log_rows_table(conn)
    if not row_details:
        conn.commit()
        return
    conn.executemany(
        "INSERT INTO import_log_rows (import_log_id, row_number, status, error_message, row_data) VALUES (?, ?, ?, ?, ?)",
        [
            (import_log_id, detail["row_number"], detail["status"], detail.get("error"), json.dumps(detail["data"], ensure_ascii=False))
            for detail in row_details
        ],
    )
    conn.commit()
