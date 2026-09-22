"""Batch detail Excel importer and transactional SQLite upsert."""
from __future__ import annotations

import io
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from flask import Flask
from openpyxl import load_workbook

try:
    import pandas as pd
except ImportError:  # pragma: no cover - dependency is declared in requirements.txt
    pd = None

from core.database import get_db, get_dialect, insert_returning_id
from core.excel_importer import record_import_rows
from core.production_time import normalize_production_date, production_date_sql_expr
from core.rollup import trigger_recompute
from models.dyeing import BATCH_DETAIL_FIELDS

BATCH_HEADER_MAP = {
    "Dyelot": "dyelot", "dyelot": "dyelot", "Dyelot No": "dyelot", "Customer": "customer", "brand_name": "customer", "Customer Name": "customer", "Color": "color", "OrderNo": "order_no", "Order No": "order_no",
    "GreigeCode": "greige_code",
    "RecipeNo": "recipe_no", "Recipe No": "recipe_no", "recipeno": "recipe_no", "ColourNo": "colour_no", "Colour No": "colour_no", "colour_no": "colour_no",
    "Shade": "shade", "shade": "shade", "CustomerColor": "customer_color", "Customer Color": "customer_color", "IsRework": "is_rework", "Is Rework": "is_rework",
    "MachineGroup": "machine_group",
    "FabricCode": "fabric_code", "Fabric Code": "fabric_code", "FabricType": "fabric_type", "FabricContent": "fabric_content",
    "Fabric Content": "fabric_content", "WOQty": "wo_qty", "WoQty": "wo_qty", "WO Qty": "wo_qty", "BatchType": "batch_type",
    "Batch Type": "batch_type", "BatchState": "batch_state", "Batch State": "batch_state",
    "FormulaCode": "formula_code", "Formula Code": "formula_code", "FormulaType": "formula_type",
    "Formula Type": "formula_type", "ProcessType": "process_type", "Process Type": "process_type", "TreatmentProgram": "program", "Program": "program", "Machine": "machine", "MC": "machine",
    "ReDye": "redye", "Re Dye": "redye", "redye": "redye", "re_dye": "redye",
    "Weight": "weight", "WeightPerArea": "weight_per_area", "GreigeWidth": "greige_width",
    "ReelSpeed": "reel_speed", "PumpSpeed": "pump_speed", "MaxReelSpeed": "max_reel_speed",
    "Absortion": "absorption", "Absorption": "absorption", "Nozzle": "nozzle",
    "SapLot": "sap_lot", "CustomerCode": "customer_code", "CustomerPO": "customer_po",
    "LiquorRatio": "liquor_ratio", "Liquor Ratio": "liquor_ratio",
    "LiquorQuantity": "liquor_quantity", "Liquor Quantity": "liquor_quantity", "SoftWater": "soft_water",
    "Soft Water": "soft_water", "HotWater": "hot_water", "Hot Water": "hot_water",
    "HardWater": "hard_water", "MixWater": "mix_water",
    "SumWater": "sum_water", "SumAllTypeWater": "sum_water",
    "Sum Water": "sum_water", "WaterxKg": "water_per_kg", "Water x Kg": "water_per_kg", "Power": "power",
    "PowerxKg": "power_per_kg", "Power x Kg": "power_per_kg", "HeatingEnergy": "heating_energy",
    "Heating Energy": "heating_energy", "SteamxKg": "steam_per_kg", "Steam x Kg": "steam_per_kg",
    "DyeCost": "dye_cost", "Dye Cost": "dye_cost", "ChemicalCost": "chemical_cost",
    "Chemical Cost": "chemical_cost", "CorrectionCnt": "correction_cnt", "Correction Cnt": "correction_cnt",
    "AlarmCnt": "alarm_cnt", "InterventionCnt": "intervention_cnt",
    "TotalCorrectionCnt": "total_correction_cnt", "Total Correction Cnt": "total_correction_cnt",
    "WashingCorrection": "washing_correction", "DyestuffCorrrection": "dyestuff_correction",
    "ChemicalCorrrection": "chemical_correction",
    "ScheduleTime": "schedule_time", "StartTime": "start_time", "EndTime": "end_time",
    "RunTime": "run_time", "SetTime": "set_time", "StopTime": "stop_time", "OperatorTime": "operator_time",
    "CorrectionTime": "correction_time", "ManualTime": "manual_time", "StopAlarmTime": "stop_alarm_time",
    "HoldAlarmTime": "hold_alarm_time", "DiffTime": "diff_time", "Percent": "percent",
    "FuyangRequest": "fuyang_request", "Fuyang Request": "fuyang_request",
    "Note1": "note1", "Note2": "note2", "Note3": "note3", "Note4": "note4", "Note5": "note5",
}
# wo_qty và order_no giữ nguyên dạng CHUỖI: trong thực tế các cột này có thể chứa mã lệnh/mã đơn
# hàng lẫn chữ cái (VD: "9V2607712", "9VS263114") chứ không phải số thuần túy — ép kiểu numeric
# ở đây từng khiến parse_safe_float/​_number() raise và làm rớt nguyên dòng dữ liệu.
NUMERIC_FIELDS = {field for field in BATCH_DETAIL_FIELDS if field in {
    "weight", "redye", "liquor_ratio", "liquor_quantity", "soft_water", "hot_water", "hard_water", "mix_water",
    "sum_water", "water_per_kg", "power", "power_per_kg", "heating_energy", "steam_per_kg", "dye_cost",
    "chemical_cost", "correction_cnt", "alarm_cnt", "intervention_cnt", "total_correction_cnt",
    "weight_per_area", "greige_width", "reel_speed", "pump_speed", "max_reel_speed", "absorption", "nozzle",
    "run_time", "set_time", "stop_time", "operator_time", "correction_time", "manual_time",
    "stop_alarm_time", "hold_alarm_time", "diff_time", "percent",
}}
SHADE_VALUES = {"LIGHT": "Light", "MEDIUM": "Medium", "DARK": "Dark", "BLACK": "Black", "WHITE": "White"}
BATCH_DATETIME_FIELDS = {"schedule_time", "start_time", "end_time"}
# Epoch chuẩn Excel/openpyxl cho số serial ngày (1899-12-30, đã bù lỗi năm nhuận 1900 của Excel).
_EXCEL_SERIAL_EPOCH = datetime(1899, 12, 30)


def _parse_batch_datetime(value: Any) -> str:
    """Ép kiểu 1 cell ScheduleTime/StartTime/EndTime sang chuỗi 'YYYY-MM-DD HH:MM:SS'.

    Một số file Batch thật lưu các cột này dưới dạng số serial Excel thô (cell không có
    number_format kiểu ngày) khiến openpyxl trả về float thay vì `datetime` (VD:
    46273.52385416667 thay vì 2026-09-06 10:24:38) — không có fallback này, dữ liệu ngày
    giờ bị lưu sai hàng loạt và `production_date` sẽ không tính được cho bất kỳ dòng nào.
    """
    value = _clean(value)
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    try:
        serial = float(str(value).strip())
    except (TypeError, ValueError):
        return str(value).strip()
    if not (1.0 <= serial <= 100000.0):  # phạm vi hợp lý cho ngày Excel (~1900-2173)
        return str(value).strip()
    try:
        return (_EXCEL_SERIAL_EPOCH + timedelta(days=serial)).strftime("%Y-%m-%d %H:%M:%S")
    except OverflowError:
        return str(value).strip()

IDENTIFIER_COLUMNS = {
    "Dyelot", "SapLot", "OrderNo", "RecipeNo", "ColourNo", "CustomerCode", "CustomerPO",
    "Machine", "Shade",
}
BATCH_PRODUCTION_MAP = {
    "Dyelot": "dyelot", "SapLot": "sap_lot", "OrderNo": "order_no", "RecipeNo": "recipe_no",
    "ColourNo": "colour_no", "CustomerCode": "customer_code", "CustomerPO": "customer_po",
    "Customer": "customer", "FabricType": "fabric_type", "Machine": "machine_code",
    "Shade": "shade", "BatchType": "batch_type", "ProcessType": "process_type",
    "Weight": "weight_kg", "ScheduleTime": "schedule_time", "StartTime": "start_time",
    "EndTime": "end_time", "RunTime": "run_time_sec",
}
BATCH_PRODUCTION_NUMERIC = {"weight_kg", "run_time_sec"}
BATCH_PRODUCTION_DATETIME = {"schedule_time", "start_time", "end_time"}


def _clean(value: Any) -> Any:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    text = str(value).strip()
    return None if not text or text.lower() in {"nan", "none", "nat"} else value


def _clean_identifier(value: Any) -> str | None:
    """Normalize Excel identifiers without allowing NaN/float artifacts."""
    value = _clean(value)
    if value is None:
        return None
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return text or None


def _is_wash_batch(value: Any) -> bool:
    return bool(_clean_identifier(value) and _clean_identifier(value).upper().endswith("-WA"))


def normalize_batch_production_dataframe(dataframe: Any) -> Any:
    """Normalize a Batch Production Report DataFrame for DB insertion.

    Identifier columns are kept as strings, empty/NaN values become None and
    datetime columns are coerced with invalid values becoming None. ``-WA``
    rows remain valid and their optional order fields stay SQL NULL.
    """
    if pd is None:
        raise RuntimeError("Pandas chưa được cài đặt. Chạy: pip install -r requirements.txt")
    frame = dataframe.copy()
    frame.columns = [str(column).strip() for column in frame.columns]
    missing = [column for column in ("Dyelot", "Machine") if column not in frame.columns]
    if missing:
        raise ValueError(f"File Batch thiếu cột bắt buộc: {', '.join(missing)}")
    for column in frame.columns:
        if column in IDENTIFIER_COLUMNS:
            frame[column] = frame[column].map(_clean_identifier)
        else:
            frame[column] = frame[column].map(_clean)
    for column in BATCH_PRODUCTION_DATETIME:
        if column in frame.columns:
            frame[column] = pd.to_datetime(frame[column], errors="coerce").where(lambda values: values.notna(), None)
    for column in ("Weight", "RunTime"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce").where(lambda values: values.notna(), None)
    if "Shade" in frame.columns:
        frame["Shade"] = frame["Shade"].map(lambda value: SHADE_VALUES.get(str(value).strip().upper(), _clean_identifier(value)))
    return frame


def read_batch_production_excel(source: str | Path | bytes) -> Any:
    """Read an Excel Batch Production Report with string-safe identifier columns."""
    if pd is None:
        raise RuntimeError("Pandas chưa được cài đặt. Chạy: pip install -r requirements.txt")
    string_columns = {column: "string" for column in IDENTIFIER_COLUMNS | set(BATCH_PRODUCTION_MAP)}
    options = {"dtype": string_columns, "keep_default_na": False}
    if isinstance(source, bytes):
        options["io"] = io.BytesIO(source)
        return normalize_batch_production_dataframe(pd.read_excel(**options))
    return normalize_batch_production_dataframe(pd.read_excel(source, **options))


def batch_production_records(dataframe: Any) -> list[dict[str, Any]]:
    """Map normalized Excel headers to nullable DB records."""
    if pd is None:
        raise RuntimeError("Pandas chưa được cài đặt.")
    frame = normalize_batch_production_dataframe(dataframe)
    records: list[dict[str, Any]] = []
    for row in frame.to_dict(orient="records"):
        record = {db_column: row.get(excel_column) for excel_column, db_column in BATCH_PRODUCTION_MAP.items() if excel_column in frame.columns}
        for field in BATCH_PRODUCTION_NUMERIC:
            if field in record and pd.notna(record[field]):
                record[field] = float(record[field])
        for field in BATCH_PRODUCTION_DATETIME:
            mapped = next((db for excel, db in BATCH_PRODUCTION_MAP.items() if excel == field), field)
            if mapped in record and pd.notna(record[mapped]):
                record[mapped] = record[mapped].to_pydatetime() if hasattr(record[mapped], "to_pydatetime") else record[mapped]
        record = {key: (None if pd.isna(value) else value) for key, value in record.items()}
        if record.get("dyelot"):
            records.append(record)
    return records


def upsert_batch_production_sqlalchemy(session: Any, dataframe: Any) -> int:
    """Dialect-aware SQLAlchemy Core UPSERT for PostgreSQL/MySQL/SQLite.

    ``session`` may be a SQLAlchemy Session or Connection. The target table
    must expose a unique/primary key on ``dyelot``.
    """
    try:
        from sqlalchemy import MetaData, Table, insert
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise RuntimeError("SQLAlchemy chưa được cài đặt. Chạy: pip install -r requirements.txt") from exc
    metadata = MetaData()
    table = Table("batch_details", metadata, autoload_with=session.bind if hasattr(session, "bind") else session)
    records = batch_production_records(dataframe)
    if not records:
        return 0
    dialect = session.bind.dialect.name if hasattr(session, "bind") else session.dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as dialect_insert
        statement = dialect_insert(table).values(records)
        statement = statement.on_conflict_do_update(index_elements=[table.c.dyelot], set_={column.name: getattr(statement.excluded, column.name) for column in table.columns if column.name != "dyelot" and column.name in records[0]})
    elif dialect == "mysql":
        from sqlalchemy.dialects.mysql import insert as dialect_insert
        statement = dialect_insert(table).values(records)
        statement = statement.on_duplicate_key_update(**{column.name: statement.inserted[column.name] for column in table.columns if column.name != "dyelot" and column.name in records[0]})
    else:
        from sqlalchemy.dialects.sqlite import insert as dialect_insert
        statement = dialect_insert(table).values(records)
        statement = statement.on_conflict_do_update(index_elements=[table.c.dyelot], set_={column.name: getattr(statement.excluded, column.name) for column in table.columns if column.name != "dyelot" and column.name in records[0]})
    result = session.execute(statement)
    session.commit()
    return int(result.rowcount or len(records))


def parse_safe_float(value: Any, default: float = 0.0) -> float:
    """Parse an toàn sang float — KHÔNG BAO GIỜ raise Exception.

    Trước đây một cell không parse được sang số (VD: mã lệnh lẫn chữ "9V2607712") sẽ làm
    raise ValueError và khiến CẢ DÒNG dữ liệu bị loại bỏ. Hàm này luôn trả về `default` khi
    không parse được, để một cell lỗi không còn làm mất toàn bộ dòng.
    """
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return default
    try:
        cleaned = str(value).strip().replace(",", ".")
        return float(cleaned) if cleaned else default
    except (TypeError, ValueError):
        return default


def _read_xlsx(file_bytes: bytes) -> tuple[list[str], list[list[Any]]]:
    workbook = load_workbook(io.BytesIO(file_bytes), data_only=True, read_only=True)
    try:
        rows = list(workbook.worksheets[0].iter_rows(values_only=True))
    finally:
        workbook.close()
    if not rows:
        return [], []
    return [str(value).strip() if value is not None else "" for value in rows[0]], [list(row) for row in rows[1:]]


def _build_batch_raw_row(indexes: dict[str, int], values: list[Any]) -> dict[str, str]:
    """Trích xuất {field: raw_value_str} từ 1 dòng sheet Batch — snapshot lưu vào
    `import_log_rows` để Raw Data Viewer hiển thị/sửa, độc lập với việc parse sau đó
    thành công hay không."""
    raw: dict[str, str] = {}
    for field in BATCH_DETAIL_FIELDS:
        index = indexes.get(field)
        value = values[index] if index is not None and index < len(values) else None
        if field in BATCH_DATETIME_FIELDS:
            raw[field] = _parse_batch_datetime(value)
        else:
            raw[field] = str(_clean(value) or "").strip()
    return raw


def _parse_batch_row(raw: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """Ép kiểu + áp business rule cho 1 dòng Batch Detail ở dạng raw dict.

    Dùng chung cho vòng lặp import hàng loạt (`parse_batch_file`) VÀ cho
    `revalidate_batch_row()` khi người dùng sửa 1 dòng lỗi trong Raw Data Viewer.
    """
    record: dict[str, Any] = {}
    try:
        for field in BATCH_DETAIL_FIELDS:
            value = raw.get(field)
            record[field] = parse_safe_float(value) if field in NUMERIC_FIELDS else str(_clean(value) or "").strip()
        if not record["dyelot"]:
            return None, "Thiếu giá trị bắt buộc: dyelot."
        record["shade"] = SHADE_VALUES.get(record["shade"].upper(), record["shade"].title())
        record["is_rework"] = int(str(record.get("is_rework", "")).strip().lower() in {"1", "true", "yes", "y"} or record.get("batch_type", "").strip().lower() == "rework")
        if record["shade"] not in set(SHADE_VALUES.values()):
            record["shade"] = ""
        return record, None
    except ValueError as exc:
        return None, str(exc)


def revalidate_batch_row(raw: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """Re-validate 1 dòng Batch Detail đã được sửa qua Inline Edit (Raw Data Viewer)."""
    return _parse_batch_row(raw)


def parse_batch_file(file_bytes: bytes) -> dict[str, Any]:
    headers, raw_rows = _read_xlsx(file_bytes)
    normalized = {header.lower(): index for index, header in enumerate(headers)}
    indexes = {field: normalized[header.lower()] for header, field in BATCH_HEADER_MAP.items() if header.lower() in normalized}
    if "dyelot" not in indexes:
        raise ValueError("File Batch thiếu cột bắt buộc Dyelot.")
    parsed: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    row_details: list[dict[str, Any]] = []
    for row_number, values in enumerate(raw_rows, start=2):
        if not any(_clean(value) is not None for value in values):
            continue
        raw = _build_batch_raw_row(indexes, values)
        record, error = _parse_batch_row(raw)
        if error is not None:
            errors.append({"row": row_number, "error": error})
            row_details.append({"row_number": row_number, "status": "invalid", "error": error, "data": raw})
            continue
        parsed.append(record)
        row_details.append({"row_number": row_number, "status": "valid", "error": None, "data": raw})
    return {"rows": parsed, "errors": errors, "total_records": len(parsed) + len(errors), "row_details": row_details}


def _ensure_import_logs_table(conn: Any) -> None:
    """Tạo/migrate bảng import_logs — cùng schema với luồng import Availability/Performance
    (xem `modules/dyeing/engines/excel_import/service.py::import_raw_file`) để lịch sử import
    Batch Detail dùng chung một bảng và hiện chung trên tab "Lịch sử Import"."""
    if get_dialect() == "sqlite":
        conn.execute("""
            CREATE TABLE IF NOT EXISTS import_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, file_name TEXT NOT NULL,
                import_type TEXT NOT NULL, imported_by TEXT NOT NULL,
                total_rows INTEGER NOT NULL DEFAULT 0, success_rows INTEGER NOT NULL DEFAULT 0,
                error_rows INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'completed',
                error_detail TEXT, imported_at TEXT NOT NULL DEFAULT (datetime('now')),
                imported_rows INTEGER NOT NULL DEFAULT 0, file_type TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(import_logs)")}
    for column, definition in (("imported_rows", "INTEGER NOT NULL DEFAULT 0"), ("file_type", "TEXT"), ("created_at", "TEXT")):
        if column not in existing:
            conn.execute(f"ALTER TABLE import_logs ADD COLUMN {column} {definition}")


def _migrate_batch_details_primary_key(conn: Any) -> None:
    """Đổi PRIMARY KEY của `batch_details` từ `dyelot` đơn sang `id` surrogate +
    UNIQUE(dyelot, machine, start_time) — cho phép 1 Dyelot có NHIỀU dòng (mẻ gốc + mẻ redye
    chạy lại), thay vì dòng sau ghi đè mất dòng trước như thiết kế cũ (xem
    memory-bank/activeContext.md, điều tra mẻ C260659920). SQLite không ALTER được PRIMARY KEY
    tại chỗ nên phải dựng lại bảng — cùng pattern `downtime/service.py::
    _migrate_case_notes_context_column()` (RENAME -> CREATE mới -> INSERT copy -> DROP ->
    commit tường minh; bài học đã ghi trong systemPatterns.md: thiếu commit ở bước này từng
    làm dữ liệu "biến mất" tạm thời với các connection khác)."""
    old_columns = {row["name"] for row in conn.execute("PRAGMA table_info(batch_details)")}
    if not old_columns or "id" in old_columns:
        return
    conn.execute("ALTER TABLE batch_details RENAME TO batch_details_pre_surrogate_id")
    conn.execute(
        "CREATE TABLE batch_details (id INTEGER PRIMARY KEY AUTOINCREMENT, dyelot TEXT NOT NULL, "
        "created_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    for field in BATCH_DETAIL_FIELDS:
        if field == "dyelot":
            continue
        definition = "REAL NOT NULL DEFAULT 0" if field in NUMERIC_FIELDS else "TEXT"
        conn.execute(f"ALTER TABLE batch_details ADD COLUMN {field} {definition}")
    conn.execute("ALTER TABLE batch_details ADD COLUMN import_log_id INTEGER")
    copy_columns = [c for c in ("dyelot", *BATCH_DETAIL_FIELDS[1:], "import_log_id", "created_at") if c in old_columns]
    columns_sql = ",".join(copy_columns)
    conn.execute(f"INSERT INTO batch_details ({columns_sql}) SELECT {columns_sql} FROM batch_details_pre_surrogate_id")
    conn.execute("DROP TABLE batch_details_pre_surrogate_id")
    conn.commit()


def sync_batch_details(file_bytes: bytes, imported_by: str | None = None, filename: str = "batch_detail.xlsx") -> dict[str, Any]:
    """Parse file Batch Detail và UPSERT vào batch_details.

    Viết lại theo đúng pattern của `import_raw_file()` (luồng import Availability/Performance):
    ghi một dòng `import_logs` trạng thái 'processing' TRƯỚC khi ghi dữ liệu, rồi cập nhật kết
    quả cuối cùng SAU — để mọi lần import, kể cả khi lỗi giữa chừng hoặc 0 dòng được lưu, đều
    để lại dấu vết tra cứu được thay vì âm thầm biến mất như trước.
    """
    result = parse_batch_file(file_bytes)
    total_rows = len(result["rows"]) + len(result["errors"])

    conn = get_db()
    if get_dialect() == "sqlite":
        conn.execute("""
            CREATE TABLE IF NOT EXISTS batch_details (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dyelot TEXT NOT NULL, customer TEXT, order_no TEXT, recipe_no TEXT, colour_no TEXT,
                shade TEXT, customer_color TEXT, fabric_code TEXT, fabric_content TEXT,
                is_rework INTEGER NOT NULL DEFAULT 0,
                wo_qty TEXT, batch_type TEXT, batch_state TEXT, formula_code TEXT,
                formula_type TEXT, process_type TEXT, weight REAL NOT NULL DEFAULT 0,
                redye REAL NOT NULL DEFAULT 0, liquor_ratio REAL NOT NULL DEFAULT 0, liquor_quantity REAL NOT NULL DEFAULT 0,
                soft_water REAL NOT NULL DEFAULT 0, hot_water REAL NOT NULL DEFAULT 0,
                sum_water REAL NOT NULL DEFAULT 0, water_per_kg REAL NOT NULL DEFAULT 0,
                power REAL NOT NULL DEFAULT 0, power_per_kg REAL NOT NULL DEFAULT 0,
                heating_energy REAL NOT NULL DEFAULT 0, steam_per_kg REAL NOT NULL DEFAULT 0,
                dye_cost REAL NOT NULL DEFAULT 0, chemical_cost REAL NOT NULL DEFAULT 0,
                correction_cnt INTEGER NOT NULL DEFAULT 0, total_correction_cnt INTEGER NOT NULL DEFAULT 0,
                fuyang_request TEXT, note1 TEXT, note2 TEXT, import_log_id INTEGER,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
    existing_columns = {row["name"] for row in conn.execute("PRAGMA table_info(batch_details)")}
    numeric_fields = NUMERIC_FIELDS
    for field in BATCH_DETAIL_FIELDS:
        if field not in existing_columns:
            definition = "REAL NOT NULL DEFAULT 0" if field in numeric_fields else "TEXT"
            conn.execute(f"ALTER TABLE batch_details ADD COLUMN {field} {definition}")
    if "import_log_id" not in existing_columns:
        conn.execute("ALTER TABLE batch_details ADD COLUMN import_log_id INTEGER")
    if get_dialect() == "sqlite":
        _migrate_batch_details_primary_key(conn)
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_batch_details_dyelot_machine_start "
            "ON batch_details(dyelot, machine, start_time)"
        )
    _ensure_import_logs_table(conn)
    conn.commit()

    log_id = insert_returning_id(
        conn,
        "INSERT INTO import_logs (file_name, import_type, file_type, imported_by, total_rows, error_rows, status) VALUES (?, ?, ?, ?, ?, ?, 'processing')",
        (filename, "batch", "BATCH", imported_by or "unknown", total_rows, len(result["errors"])),
    )
    conn.commit()

    imported_rows = 0
    try:
        if result["rows"]:
            columns_with_log = BATCH_DETAIL_FIELDS + ("import_log_id",)
            placeholders = ",".join("?" for _ in columns_with_log)
            key_fields = ("dyelot", "machine", "start_time")
            updates = ",".join(f"{field}=excluded.{field}" for field in columns_with_log if field not in key_fields)
            sql = (
                f"INSERT INTO batch_details ({','.join(columns_with_log)}) VALUES ({placeholders}) "
                f"ON CONFLICT({','.join(key_fields)}) DO UPDATE SET {updates}"
            )
            # Postgres bó TOÀN BỘ dòng của executemany() vào 1 câu INSERT...VALUES duy nhất
            # (xem `_PostgresConnCompat.executemany()`) — nếu file Excel có 2 dòng trùng
            # key_fields, câu lệnh ON CONFLICT DO UPDATE đó sẽ update trùng key 2 lần trong CÙNG 1
            # statement và Postgres từ chối thẳng (`CardinalityViolation`). SQLite không dính lỗi
            # này vì executemany() ở đó chạy tuần tự từng dòng một. Khử trùng theo
            # (dyelot, machine, start_time) — KHÔNG còn khử theo dyelot đơn, vì 1 dyelot giờ có
            # thể có nhiều lần chạy thật (mẻ gốc + mẻ redye) cần giữ RIÊNG, chỉ dòng trùng thật
            # 100% (cùng cả 3 khoá) mới coi là duplicate cần khử (giữ dòng CUỐI xuất hiện trong
            # file, giống hành vi "ghi đè" cũ khi đúng là cùng 1 lần chạy).
            deduped_rows = {tuple(row[field] for field in key_fields): row for row in result["rows"]}
            conn.execute("BEGIN")
            conn.executemany(sql, [tuple(row[field] for field in BATCH_DETAIL_FIELDS) + (log_id,) for row in deduped_rows.values()])
            conn.commit()
            imported_rows = len(result["rows"])
        record_import_rows(conn, log_id, result["row_details"])
        synced = conn.execute("SELECT COUNT(*) AS total FROM batch_details b JOIN availability_logs a ON a.batch = b.dyelot").fetchone()["total"]
    except Exception as exc:
        conn.rollback()
        conn.execute("UPDATE import_logs SET status='failed', error_detail=? WHERE id=?", (str(exc), log_id))
        conn.commit()
        raise

    status = "completed" if imported_rows and not result["errors"] else "partial" if imported_rows else "failed"
    error_detail = "; ".join(f"Dòng {error['row']}: {error['error']}" for error in result["errors"][:20]) or None
    conn.execute(
        "UPDATE import_logs SET imported_rows=?, success_rows=?, status=?, error_detail=? WHERE id=?",
        (imported_rows, imported_rows, status, error_detail, log_id),
    )
    conn.commit()

    if imported_rows:
        # Daily Rollup Pattern: import Batch Detail không tự có end_time riêng để suy ra
        # production_date — Batch chỉ CẬP NHẬT Shade/ColourNo/BatchType cho các dyelot đã
        # tồn tại trong availability_logs (nguồn production_date thật). Affected dates =
        # production_date của đúng các dòng availability_logs mà dyelot vừa upsert khớp tới.
        shifted_date = production_date_sql_expr("a.end_time")
        affected_rows = conn.execute(
            f"""
            SELECT DISTINCT {shifted_date} AS production_date
            FROM availability_logs a
            JOIN batch_details b ON lower(trim(a.batch)) = lower(trim(b.dyelot))
            WHERE b.import_log_id = ? AND a.end_time IS NOT NULL AND a.end_time != ''
            """,
            (log_id,),
        ).fetchall()
        affected_dates = {
            datetime.strptime(normalize_production_date(row["production_date"]), "%Y-%m-%d").date()
            for row in affected_rows if row["production_date"]
        }
        trigger_recompute(affected_dates)

    return {
        "status": status,
        "file_type": "BATCH",
        "rows_imported": imported_rows,
        "total_rows": total_rows,
        "errors": result["errors"],
        "preview": result["rows"][:5],
        "columns": list(result["rows"][0].keys()) if result["rows"] else [],
        "synced_with_availability_cnt": int(synced),
        "imported_rows": imported_rows,
        "import_log_id": log_id,
    }


def init_app(app: Flask) -> None:
    """Đảm bảo `batch_details` đã ở schema MỚI (id surrogate PK + UNIQUE(dyelot, machine,
    start_time)) NGAY LÚC APP KHỞI ĐỘNG — không chờ tới lần import Batch kế tiếp mới migrate
    lazy trong `sync_batch_details()`. Cần thiết vì NHIỀU Engine đọc `batch_details` qua
    `core/batch_details_match.py::batch_details_join_sql()` (tham chiếu cột `id`/`end_time`)
    mà KHÔNG bao giờ gọi `sync_batch_details()` trước — nếu chỉ migrate lazy trong đó, 1 DB cũ
    chưa từng import lại Batch sau bản cập nhật này sẽ lỗi "no such column: b.id" ngay khi mở
    báo cáo, thay vì chỉ khi import. CHỈ áp dụng SQLite — Postgres dùng migration thủ công
    riêng qua `supabase/migrate_batch_details_primary_key.sql` (app KHÔNG tự ALTER TABLE trên
    Postgres, xem CLAUDE.md/`systemPatterns.md` mục 5.1), cùng pattern `core/auth.py::
    init_app()` (bảng `user_permissions`)."""
    if app.config.get("DATABASE_URL"):
        return
    from core.database import get_raw_connection_for_app

    conn = get_raw_connection_for_app(app)
    try:
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(batch_details)")}
        if existing:
            _migrate_batch_details_primary_key(conn)
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_batch_details_dyelot_machine_start "
                "ON batch_details(dyelot, machine, start_time)"
            )
            conn.commit()
    finally:
        conn.close()
