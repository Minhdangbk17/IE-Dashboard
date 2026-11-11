from __future__ import annotations

import csv
import io
import json
import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Sequence

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.worksheet.worksheet import Worksheet

from core.database import execute_query, get_db, get_dialect
from core.production_time import get_production_date


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
for _hour_header, _hour_field in list(AVAILABILITY_COLUMNS.items()):
    if _hour_header.endswith(" (hour)") and _hour_field.endswith("_hour"):
        _kgh_header = _hour_header[: -len(" (hour)")] + " (Kg-H)"
        _kgh_field = _hour_field[: -len("_hour")] + "_kgh"
        AVAILABILITY_COLUMNS[_kgh_header] = _kgh_field
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
ACHIEVEMENT_STAGES: dict[str, str] = {
    "Load": "load_hour", "Unload": "unload_hour", "Sample Check": "sample_checking_hour",
    "pH Check": "ph_checking_hour", "Chemical": "wait_chemical_load_hour", "Color": "wait_color_load_hour",
}
ACHIEVEMENT_STAGE_ACH_FIELDS: dict[str, str] = {
    "Load": "ach_load", "Unload": "ach_unload", "Sample Check": "ach_sample_check",
    "pH Check": "ach_ph", "Chemical": "ach_chemical", "Color": "ach_color",
}
AVAILABILITY_DB_FIELDS = tuple(dict.fromkeys(AVAILABILITY_COLUMNS.values())) + (
    "production_date", "week_label", "month_label", *ACH_FIELDS,
    "ach_evaluated", "ach_passed", "ach_all_items", "blank_fields",
)


DATE_FORMATS: tuple[str, ...] = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y",
)


def calculate_production_date(value: Any) -> date | None:
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


def _add_availability_business_fields(record: dict[str, Any], standard_hours: dict[str, float] | None = None) -> None:
    standards = standard_hours or STANDARD_HOURS
    reference_time = record.get("end_time") or record.get("start_time")
    production = calculate_production_date(reference_time)
    if production is None:
        return
    record["production_date"] = production.isoformat()
    iso_year, iso_week, _ = production.isocalendar()
    record["week_label"] = f"{iso_year}-W{iso_week:02d}"
    record["month_label"] = production.strftime("%Y-%m")
    results = {
        "ach_load": _standard_result(record.get("load_hour"), standards.get("load_hour", STANDARD_HOURS["load_hour"])),
        "ach_unload": _standard_result(record.get("unload_hour"), standards.get("unload_hour", STANDARD_HOURS["unload_hour"])),
        "ach_sample_check": _standard_result(record.get("sample_checking_hour"), standards.get("sample_checking_hour", STANDARD_HOURS["sample_checking_hour"])),
        "ach_ph": _standard_result(record.get("ph_checking_hour"), standards.get("ph_checking_hour", STANDARD_HOURS["ph_checking_hour"])),
        "ach_chemical": _standard_result(record.get("wait_chemical_load_hour"), standards.get("wait_chemical_load_hour", STANDARD_HOURS["wait_chemical_load_hour"])),
        "ach_color": _standard_result(record.get("wait_color_load_hour"), standards.get("wait_color_load_hour", STANDARD_HOURS["wait_color_load_hour"])),
    }
    evaluated = [result for result in results.values() if result is not None]
    record.update(results)
    record["ach_evaluated"] = len(evaluated)
    record["ach_passed"] = sum(evaluated)
    record["ach_all_items"] = int(bool(evaluated) and record["ach_passed"] == record["ach_evaluated"])




def _ensure_achievement_standards_table(conn: Any) -> None:
    if get_dialect() == "sqlite":
        conn.execute("""
            CREATE TABLE IF NOT EXISTS downtime_achievement_standards (
                stage TEXT PRIMARY KEY,
                standard_hours REAL NOT NULL,
                updated_by INTEGER REFERENCES users (id),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
    existing = {row["stage"] for row in execute_query("SELECT stage FROM downtime_achievement_standards")}
    for stage, hour_field in ACHIEVEMENT_STAGES.items():
        if stage in existing:
            continue
        conn.execute(
            "INSERT INTO downtime_achievement_standards (stage, standard_hours) VALUES (?, ?) "
            "ON CONFLICT (stage) DO NOTHING",
            (stage, STANDARD_HOURS[hour_field]),
        )
    conn.commit()


def get_achievement_standards() -> dict[str, float]:
    conn = get_db()
    _ensure_achievement_standards_table(conn)
    rows = execute_query("SELECT stage, standard_hours FROM downtime_achievement_standards")
    result = {row["stage"]: float(row["standard_hours"]) for row in rows}
    for stage, hour_field in ACHIEVEMENT_STAGES.items():
        result.setdefault(stage, STANDARD_HOURS[hour_field])
    return result


def get_achievement_standard_hours_by_field() -> dict[str, float]:
    by_stage = get_achievement_standards()
    return {ACHIEVEMENT_STAGES[stage]: value for stage, value in by_stage.items()}


def _recompute_achievement_aggregates(conn: Any) -> None:
    ach_fields = list(ACHIEVEMENT_STAGE_ACH_FIELDS.values())
    evaluated_expr = " + ".join(f"(CASE WHEN {field} IS NOT NULL THEN 1 ELSE 0 END)" for field in ach_fields)
    passed_expr = " + ".join(f"COALESCE({field}, 0)" for field in ach_fields)
    conn.execute(f"UPDATE availability_logs SET ach_evaluated = {evaluated_expr}, ach_passed = {passed_expr}")
    conn.execute("UPDATE availability_logs SET ach_all_items = CASE WHEN ach_evaluated > 0 AND ach_passed = ach_evaluated THEN 1 ELSE 0 END")


def set_achievement_standard(stage: str, standard_hours: float, user_id: int) -> dict[str, Any]:
    if stage not in ACHIEVEMENT_STAGES:
        raise ValueError(f"Stage không hợp lệ: {stage}")
    if not standard_hours or standard_hours <= 0:
        raise ValueError("Standard phải là số dương.")
    hour_field = ACHIEVEMENT_STAGES[stage]
    ach_field = ACHIEVEMENT_STAGE_ACH_FIELDS[stage]

    conn = get_db()
    _ensure_achievement_standards_table(conn)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """
        INSERT INTO downtime_achievement_standards (stage, standard_hours, updated_by, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (stage) DO UPDATE SET standard_hours = excluded.standard_hours,
                                           updated_by = excluded.updated_by, updated_at = excluded.updated_at
        """,
        (stage, standard_hours, user_id, now_str),
    )
    conn.execute(
        f"""
        UPDATE availability_logs SET {ach_field} = CASE
            WHEN {hour_field} IS NULL OR {hour_field} <= 0 THEN NULL
            WHEN {hour_field} <= ? THEN 1 ELSE 0 END
        """,
        (standard_hours,),
    )
    _recompute_achievement_aggregates(conn)
    conn.commit()
    row = execute_query(
        """
        SELECT s.stage, s.standard_hours, s.updated_at, u.username AS updated_by_username
        FROM downtime_achievement_standards s LEFT JOIN users u ON u.id = s.updated_by
        WHERE s.stage = ?
        """,
        (stage,),
    )
    result_row = row[0] if row else None
    return {
        "stage": stage,
        "standard_hours": float(result_row["standard_hours"]) if result_row else standard_hours,
        "updated_by": result_row["updated_by_username"] if result_row else None,
        "updated_at": result_row["updated_at"] if result_row else now_str,
    }


def _parse_datetime(value: Any) -> datetime:
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




@dataclass(frozen=True)
class ColumnSpec:

    name: str
    dtype: str
    required: bool = True
    enum_values: tuple[str, ...] = ()
    description: str = ""

    def parser(self) -> Callable[[Any], Any]:
        if self.dtype == "enum":
            return _parse_enum(self.enum_values)
        return TYPE_PARSERS[self.dtype]


@dataclass(frozen=True)
class ImportSchema:

    key: str
    table_name: str
    columns: tuple[ColumnSpec, ...]
    insert_sql: str

    @property
    def required_columns(self) -> list[str]:
        return [c.name for c in self.columns if c.required]

    @property
    def column_names(self) -> list[str]:
        return [c.name for c in self.columns]




@dataclass
class RowError:
    row: int
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




def _read_rows_from_xlsx(file_stream: io.BytesIO) -> tuple[list[str], list[tuple[int, list[Any]]]]:
    workbook = load_workbook(filename=file_stream, data_only=True, read_only=True)
    sheet: Worksheet = workbook.worksheets[0]
    rows_iter = sheet.iter_rows(values_only=True)
    header = [str(h).strip() if h is not None else "" for h in next(rows_iter, [])]
    raw_rows: list[tuple[int, list[Any]]] = []
    for idx, row in enumerate(rows_iter, start=2):
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
    return all(v is None or str(v).strip() == "" for v in values)




def parse_file(
    filename: str, file_bytes: bytes, schema: ImportSchema
) -> tuple[list[dict[str, Any]], list[RowError]]:
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

    col_index: dict[str, int] = {name: header_lower.index(name.lower()) for name in schema.column_names if name.lower() in header_lower}

    parsed_rows: list[dict[str, Any]] = []
    errors: list[RowError] = []

    for row_number, values in raw_rows:
        if _is_blank_row(values):
            continue

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
    parsed_rows, errors = parse_file(filename, file_bytes, schema)
    return {
        "columns": schema.column_names,
        "preview_rows": parsed_rows[:limit],
        "total_valid_rows": len(parsed_rows),
        "errors": [e.to_dict() for e in errors[:20]],
        "error_count": len(errors),
    }




def export_template(schema: ImportSchema, sample_rows: list[tuple[Any, ...]] | None = None) -> bytes:
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


def export_rows_to_excel(headers: list[str], fields: list[str], rows: list[dict[str, Any]], sheet_title: str) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = sheet_title[:31]

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="24292F", end_color="24292F", fill_type="solid")
    for col_idx, header in enumerate(headers, start=1):
        cell = sheet.cell(row=1, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        sheet.column_dimensions[cell.column_letter].width = max(14, len(header) + 2)

    for row_idx, row in enumerate(rows, start=2):
        for col_idx, field in enumerate(fields, start=1):
            sheet.cell(row=row_idx, column=col_idx, value=row.get(field))

    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()


def allowed_file(filename: str, allowed_extensions: set[str]) -> bool:
    return "." in filename and filename.rsplit(".", 1)[-1].lower() in allowed_extensions



def _raw_cell(value: Any) -> Any:
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


_THOUSANDS_COMMA = re.compile(r"^[+-]?\d{1,3}(,\d{3})+(\.\d+)?$")


def _coerce_number_text(text: str) -> float:
    cleaned = text.replace("\u00a0", "").replace(" ", "").lstrip("'")
    if "," in cleaned:
        if "." in cleaned or _THOUSANDS_COMMA.match(cleaned):
            cleaned = cleaned.replace(",", "")
        else:
            cleaned = cleaned.replace(",", ".")
    number = float(cleaned)
    if math.isnan(number) or math.isinf(number):
        raise ValueError(cleaned)
    return number


def _raw_float(value: Any) -> float:
    value = _raw_cell(value)
    if value is None:
        return 0.0
    if isinstance(value, bool):
        raise ValueError(f"không phải số hợp lệ: {value}")
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return _coerce_number_text(str(value).strip())
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
    raw: dict[str, str] = {}
    for field in fields:
        idx = indexes.get(field)
        value = values[idx] if idx is not None and idx < len(values) else None
        cleaned = _raw_cell(value)
        raw[field] = "" if cleaned is None else str(cleaned)
    return raw


def _parse_raw_row(
    file_type: str, fields: list[str], required: set[str], raw: dict[str, Any],
    standard_hours: dict[str, float] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
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
        record["blank_fields"] = ",".join(sorted(
            field for field in fields if field in _NUMERIC_FIELDS and _raw_cell(raw.get(field)) is None
        ))
        if file_type == "AVAILABILITY" and not record.get("batch_ref_no"):
            record["batch_ref_no"] = record.get("batch", "")
        summary_key = "dyelot" if file_type == "PERFORMANCE" else "batch"
        if record.get(summary_key, "").strip().lower() == "all" or record.get("machine", "").strip().lower() == "all":
            return None, "Dòng tổng hợp 'All' — bị bỏ qua khi import (không phải dòng dữ liệu thật)."
        missing = [field for field in required if record.get(field) is None or not str(record.get(field, "")).strip()]
        if missing:
            return None, f"Thiếu giá trị bắt buộc: {', '.join(missing)}"
        if file_type == "AVAILABILITY":
            _add_availability_business_fields(record, standard_hours)
        return record, None
    except ValueError as exc:
        return None, str(exc)


def revalidate_raw_row(file_type: str, raw: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    if file_type == "AVAILABILITY":
        fields, required = list(AVAILABILITY_COLUMNS.values()), _AVAILABILITY_REQUIRED
    elif file_type == "PERFORMANCE":
        fields, required = list(PERFORMANCE_COLUMNS.values()), _PERFORMANCE_REQUIRED
    else:
        raise ValueError(f"file_type '{file_type}' không hỗ trợ revalidate.")
    standard_hours = get_achievement_standard_hours_by_field() if file_type == "AVAILABILITY" else None
    return _parse_raw_row(file_type, fields, required, raw, standard_hours)


def detect_and_parse_file(file_path: str) -> dict[str, Any]:
    headers, raw_rows = _read_raw_file(file_path)
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
    standard_hours = get_achievement_standard_hours_by_field() if file_type == "AVAILABILITY" else None
    for row_number, values in raw_rows:
        if _is_blank_row(values):
            continue
        raw = _build_raw_row_dict(fields, indexes, values)
        record, error = _parse_raw_row(file_type, fields, required, raw, standard_hours)
        if error is not None:
            errors.append({"row": row_number, "error": error})
            row_details.append({"row_number": row_number, "status": "invalid", "error": error, "data": raw})
            continue
        rows.append(record)
        row_details.append({"row_number": row_number, "status": "valid", "error": None, "data": raw})
    return {"file_type": file_type, "columns": fields, "rows": rows, "errors": errors, "row_details": row_details}


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
        "ach_all_items": "INTEGER NOT NULL DEFAULT 0", "blank_fields": "TEXT",
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
        "blank_fields": "TEXT",
    }
    for column, definition in performance_additions.items():
        if column not in performance_existing:
            conn.execute(f"ALTER TABLE performance_logs ADD COLUMN {column} {definition}")
    conn.commit()


def save_to_db(df: Any, file_type: str, db_connection: Any, import_log_id: int | None = None) -> int:
    if file_type not in {"AVAILABILITY", "PERFORMANCE"}:
        raise ValueError("file_type phải là AVAILABILITY hoặc PERFORMANCE.")
    rows = df.get("rows", []) if isinstance(df, dict) else list(df)
    if not rows:
        return 0
    _ensure_raw_tables(db_connection)
    fields = list(AVAILABILITY_DB_FIELDS) if file_type == "AVAILABILITY" else [*PERFORMANCE_COLUMNS.values(), "blank_fields"]
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
    deduped_rows = {tuple(row.get(field) for field in key_fields): row for row in rows}.values()
    values = [
        tuple(row.get(field, 0.0 if field in _NUMERIC_FIELDS else None) for field in fields)
        + (import_log_id,)
        for row in deduped_rows
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




def _ensure_import_log_rows_table(conn: Any) -> None:
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
