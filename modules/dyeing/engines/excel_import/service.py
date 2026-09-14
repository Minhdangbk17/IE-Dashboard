"""
modules/dyeing/engines/excel_import/service.py
--------------------------------------------------
Service layer của Engine "excel_import": định nghĩa Schema cho từng loại
import (Telemetry, Downtime), điều phối `core.excel_importer.run_import()`,
và ghi lại lịch sử vào bảng `import_logs`.
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from core.database import execute_query, get_db, get_dialect, insert_returning_id, sql_datetime
from core.excel_importer import AVAILABILITY_COLUMNS, PERFORMANCE_COLUMNS, ColumnSpec, ImportResult, ImportSchema, run_import
from core.excel_importer import detect_and_parse_file, save_to_db, record_import_rows, export_rows_to_excel
from core.batch_importer import parse_batch_file, sync_batch_details
from core.production_time import get_production_date, production_bounds
from core.rollup import trigger_recompute
from models.dyeing import BATCH_DETAIL_FIELDS

# ---------------------------------------------------------------------------
# Schema Definitions
# ---------------------------------------------------------------------------

TELEMETRY_SCHEMA = ImportSchema(
    key="telemetry",
    table_name="machine_telemetry",
    columns=(
        ColumnSpec("timestamp", "datetime", required=True, description="Thời điểm ghi nhận (YYYY-MM-DD HH:MM)"),
        ColumnSpec("machine_id", "str", required=True, description="Mã máy, vd DY-01"),
        ColumnSpec(
            "status", "enum", required=True, enum_values=("RUNNING", "STOPPED", "MAINTENANCE"),
            description="Trạng thái máy: RUNNING / STOPPED / MAINTENANCE",
        ),
        ColumnSpec("actual_speed", "float", required=True, description="Tốc độ thực tế (m/phút)"),
        ColumnSpec("standard_speed", "float", required=True, description="Tốc độ tiêu chuẩn (m/phút)"),
        ColumnSpec("output_meters", "float", required=True, description="Sản lượng (mét)"),
    ),
    insert_sql=(
        "INSERT INTO machine_telemetry "
        "(timestamp, machine_id, status, actual_speed, standard_speed, output_meters, import_log_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)"
    ),
)

DOWNTIME_SCHEMA = ImportSchema(
    key="downtime",
    table_name="downtime_logs",
    columns=(
        ColumnSpec("timestamp", "datetime", required=True, description="Thời điểm dừng máy (YYYY-MM-DD HH:MM)"),
        ColumnSpec("machine_id", "str", required=True, description="Mã máy, vd DY-01"),
        ColumnSpec("reason_code", "str", required=True, description="Mã lý do dừng máy, vd DT01"),
        ColumnSpec("reason_name", "str", required=True, description="Tên lý do dừng máy"),
        ColumnSpec("duration_minutes", "float", required=True, description="Thời lượng dừng máy (phút)"),
        ColumnSpec("detail", "str", required=False, description="Ghi chú tự do của operator (không bắt buộc)"),
    ),
    insert_sql=(
        "INSERT INTO downtime_logs "
        "(timestamp, machine_id, reason_code, reason_name, duration_minutes, detail, import_log_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)"
    ),
)

SCHEMAS: dict[str, ImportSchema] = {
    TELEMETRY_SCHEMA.key: TELEMETRY_SCHEMA,
    DOWNTIME_SCHEMA.key: DOWNTIME_SCHEMA,
}

SAMPLE_ROWS: dict[str, list[tuple[Any, ...]]] = {
    "telemetry": [
        ("2026-09-01 08:00", "DY-01", "RUNNING", 118.5, 120.0, 950.0),
        ("2026-09-01 09:00", "DY-01", "STOPPED", 0, 120.0, 0),
    ],
    "downtime": [
        ("2026-09-01 10:15", "DY-01", "DT01", "Chờ nguyên liệu", 45.0, "Kho chưa cấp đủ hoá chất."),
    ],
}


def _parse_flexible_datetime(value: Any) -> datetime | None:
    """Parse mốc thời gian đọc lại từ DB (có thể là chuỗi ISO với/không mili-giây tuỳ
    driver sqlite3 lưu) — dùng khi tính affected_dates cho Daily Rollup, không raise."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def get_schema(schema_key: str) -> ImportSchema:
    schema = SCHEMAS.get(schema_key)
    if schema is None:
        raise ValueError(
            f"Không tìm thấy schema import '{schema_key}'. Các schema hợp lệ: {list(SCHEMAS)}"
        )
    return schema


def do_import(
    schema_key: str, filename: str, file_bytes: bytes, imported_by: str, strict_mode: bool
) -> ImportResult:
    """
    Orchestrator chính cho API `/api/import/<schema_key>`:

      1. Ghi một dòng `import_logs` trạng thái 'processing' TRƯỚC để lấy `id`
         (dùng làm khoá ngoại `import_log_id` gắn vào từng dòng dữ liệu import).
      2. Gọi `run_import()` (parse + validate + bulk insert trong 1 transaction).
      3. Cập nhật lại dòng `import_logs` với kết quả cuối cùng (tổng dòng,
         số dòng thành công/lỗi, trạng thái, chi tiết lỗi).
    """
    schema = get_schema(schema_key)
    conn = get_db()

    log_id = insert_returning_id(
        conn,
        "INSERT INTO import_logs (file_name, import_type, imported_by, status) VALUES (?, ?, ?, 'processing')",
        (filename, schema_key, imported_by),
    )
    conn.commit()

    result = run_import(
        conn, filename, file_bytes, schema, strict_mode=strict_mode, extra_params=(log_id,)
    )

    if not result.committed:
        status = "failed"
    elif result.errors:
        status = "partial"
    else:
        status = "completed"

    error_detail = "; ".join(f"Dòng {e.row}: {e.error}" for e in result.errors[:20]) or None

    conn.execute(
        """
        UPDATE import_logs
        SET total_rows = ?, success_rows = ?, error_rows = ?, status = ?, error_detail = ?
        WHERE id = ?
        """,
        (result.total_rows, result.inserted_rows, result.skipped_rows, status, error_detail, log_id),
    )
    conn.commit()

    if result.committed and result.inserted_rows:
        # Daily Rollup Pattern: schema Telemetry/Downtime hiện không Engine rollup nào phụ
        # thuộc trực tiếp (downtime/batch_matrix nguồn từ availability_logs), nhưng vẫn gọi
        # trigger_recompute() đầy đủ ở mọi điểm commit import theo đúng thiết kế chung —
        # vô hại (no-op với Engine không liên quan) và nhất quán nếu sau này có Engine mới
        # dùng machine_telemetry/downtime_logs.
        rows = conn.execute(f"SELECT timestamp FROM {schema.table_name} WHERE import_log_id = ?", (log_id,)).fetchall()
        affected_dates = set()
        for row in rows:
            parsed_timestamp = _parse_flexible_datetime(row["timestamp"])
            if parsed_timestamp is not None:
                affected_dates.add(get_production_date(parsed_timestamp))
        trigger_recompute(affected_dates)

    return result


def get_history(limit: int = 20) -> list[dict[str, Any]]:
    """Lấy N lần import gần nhất — dùng cho tab "Lịch sử Import" trên UI."""
    rows = execute_query(
        "SELECT id, file_name, import_type, imported_by, total_rows, success_rows, "
        "error_rows, status, imported_at FROM import_logs ORDER BY imported_at DESC LIMIT ?",
        (limit,),
    )
    return [dict(row) for row in rows]


def import_raw_file(filename: str, file_bytes: bytes, imported_by: str) -> dict[str, Any]:
    """Nhận diện, làm sạch, UPSERT file Availability/Performance và ghi log."""
    suffix = Path(filename).suffix.lower()
    if suffix not in {".xlsx", ".xls", ".csv"}:
        raise ValueError("Chỉ hỗ trợ file .xlsx, .xls hoặc .csv.")

    temp_path: str | None = None
    conn = get_db()
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            temp_file.write(file_bytes)
            temp_path = temp_file.name
        parsed = detect_and_parse_file(temp_path)
        file_type = parsed["file_type"]
        columns = parsed["columns"]
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
        log_id = insert_returning_id(
            conn,
            "INSERT INTO import_logs (file_name, import_type, file_type, imported_by, total_rows, error_rows, status) VALUES (?, ?, ?, ?, ?, ?, 'processing')",
            (filename, file_type.lower(), file_type, imported_by, len(parsed["rows"]) + len(parsed["errors"]), len(parsed["errors"])),
        )
        conn.commit()
        imported_rows = save_to_db(parsed, file_type, conn, import_log_id=log_id)
        record_import_rows(conn, log_id, parsed.get("row_details", []))
        status = "partial" if parsed["errors"] else "completed"
        error_detail = "; ".join(f"Dòng {error['row']}: {error['error']}" for error in parsed["errors"][:20]) or None
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "UPDATE import_logs SET imported_rows=?, success_rows=?, status=?, error_detail=?, created_at=? WHERE id=?",
            (imported_rows, imported_rows, status, error_detail, now_str, log_id),
        )
        conn.commit()
        # Daily Rollup Pattern: chỉ recompute đúng các production_date bị ảnh hưởng bởi
        # batch dữ liệu vừa import (lấy từ end_time/start_time đã parse, không query lại
        # DB) — downtime/batch_matrix đều nguồn từ availability_logs, Performance thì không
        # Engine nào phụ thuộc nên bỏ qua để giữ import Performance nhanh.
        if file_type == "AVAILABILITY":
            affected_dates = set()
            for row in parsed["rows"]:
                parsed_timestamp = _parse_flexible_datetime(row.get("end_time") or row.get("start_time"))
                if parsed_timestamp is not None:
                    affected_dates.add(get_production_date(parsed_timestamp))
            trigger_recompute(affected_dates)
        return {"status": status, "file_type": file_type, "rows_imported": imported_rows, "total_rows": len(parsed["rows"]) + len(parsed["errors"]), "errors": parsed["errors"], "preview": parsed["rows"][:5], "columns": columns, "import_log_id": log_id}
    except Exception:
        conn.rollback()
        raise
    finally:
        if temp_path:
            try:
                os.unlink(temp_path)
            except OSError:
                pass


def preview_raw_file(filename: str, file_bytes: bytes) -> dict[str, Any]:
    """Parse raw file không ghi dữ liệu, phục vụ preview 5 dòng đầu."""
    suffix = Path(filename).suffix.lower()
    if suffix not in {".xlsx", ".xls", ".csv"}:
        raise ValueError("Chỉ hỗ trợ file .xlsx, .xls hoặc .csv.")
    temp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            temp_file.write(file_bytes)
            temp_path = temp_file.name
        parsed = detect_and_parse_file(temp_path)
        return {
            "status": "preview",
            "file_type": parsed["file_type"],
            "columns": parsed["columns"],
            "preview": parsed["rows"][:5],
            "total_rows": len(parsed["rows"]) + len(parsed["errors"]),
            "valid_rows": len(parsed["rows"]),
            "errors": parsed["errors"],
        }
    finally:
        if temp_path:
            try:
                os.unlink(temp_path)
            except OSError:
                pass


def preview_import_file(filename: str, file_bytes: bytes, requested_type: str = "auto") -> dict[str, Any]:
    """Preview Availability/Performance/Batch with explicit type mismatch feedback."""
    if requested_type == "batch":
        parsed = parse_batch_file(file_bytes)
        return {"status": "preview", "file_type": "BATCH", "columns": list(parsed["rows"][0]) if parsed["rows"] else [], "preview": parsed["rows"][:5], "valid_rows": len(parsed["rows"]), "total_rows": parsed["total_records"], "errors": parsed["errors"]}
    result = preview_raw_file(filename, file_bytes)
    if requested_type not in {"", "auto"} and result["file_type"].lower() != requested_type.lower():
        result["type_mismatch"] = True
        result["type_mismatch_message"] = f"File uploaded thuộc dạng {result['file_type']} Data, vui lòng chuyển loại dữ liệu sang {result['file_type'].title()} hoặc chọn Auto-detect."
    return result


def import_selected_file(filename: str, file_bytes: bytes, imported_by: str, requested_type: str = "auto") -> dict[str, Any]:
    if requested_type == "batch":
        return sync_batch_details(file_bytes, imported_by, filename)
    if requested_type == "auto":
        detected = preview_import_file(filename, file_bytes, "auto")
        if detected.get("file_type") == "BATCH":
            return sync_batch_details(file_bytes, imported_by, filename)
    result = import_raw_file(filename, file_bytes, imported_by)
    if requested_type not in {"", "auto"} and result["file_type"].lower() != requested_type.lower():
        raise ValueError(f"File uploaded thuộc dạng {result['file_type']} Data, vui lòng chuyển loại dữ liệu sang {result['file_type'].title()} hoặc chọn Auto-detect.")
    return result


# ---------------------------------------------------------------------------
# Export Data: xuất lại Availability/Performance/Batch đã import, lọc theo
# khoảng ngày — chiều ngược lại của Import, dùng CHUNG tên cột Excel gốc
# (AVAILABILITY_COLUMNS/PERFORMANCE_COLUMNS/BATCH_EXPORT_HEADERS) để file xuất
# ra giữ đúng định dạng người dùng đã quen, xem lại được bằng Excel bình
# thường (không nhằm để re-import lại, dù cấu trúc cột tương thích).
# ---------------------------------------------------------------------------

# Chọn 1 tên cột "đẹp" duy nhất cho mỗi field batch_details (BATCH_HEADER_MAP ở
# core/batch_importer.py có nhiều alias/field để IMPORT linh hoạt — export thì chỉ cần
# đúng 1 tên/cột, chọn alias tự nhiên nhất, giữ đúng thứ tự BATCH_DETAIL_FIELDS).
BATCH_EXPORT_HEADERS: dict[str, str] = {
    "dyelot": "Dyelot", "customer": "Customer", "color": "Color", "order_no": "OrderNo",
    "greige_code": "GreigeCode", "recipe_no": "RecipeNo", "colour_no": "ColourNo", "shade": "Shade",
    "customer_color": "CustomerColor", "is_rework": "IsRework", "machine": "Machine", "machine_group": "MachineGroup",
    "fabric_code": "FabricCode", "fabric_type": "FabricType", "fabric_content": "FabricContent", "wo_qty": "WOQty",
    "batch_type": "BatchType", "batch_state": "BatchState", "formula_code": "FormulaCode", "formula_type": "FormulaType",
    "process_type": "ProcessType", "weight": "Weight", "redye": "ReDye", "liquor_ratio": "LiquorRatio",
    "liquor_quantity": "LiquorQuantity", "weight_per_area": "WeightPerArea", "greige_width": "GreigeWidth",
    "reel_speed": "ReelSpeed", "pump_speed": "PumpSpeed", "max_reel_speed": "MaxReelSpeed", "absorption": "Absorption",
    "nozzle": "Nozzle", "sap_lot": "SapLot", "customer_code": "CustomerCode", "customer_po": "CustomerPO",
    "soft_water": "SoftWater", "hot_water": "HotWater", "hard_water": "HardWater", "mix_water": "MixWater",
    "sum_water": "SumWater", "water_per_kg": "WaterxKg", "power": "Power", "power_per_kg": "PowerxKg",
    "heating_energy": "HeatingEnergy", "steam_per_kg": "SteamxKg", "dye_cost": "DyeCost", "chemical_cost": "ChemicalCost",
    "correction_cnt": "CorrectionCnt", "alarm_cnt": "AlarmCnt", "intervention_cnt": "InterventionCnt",
    "total_correction_cnt": "TotalCorrectionCnt", "washing_correction": "WashingCorrection",
    "dyestuff_correction": "DyestuffCorrrection", "chemical_correction": "ChemicalCorrrection",
    "schedule_time": "ScheduleTime", "start_time": "StartTime", "end_time": "EndTime", "run_time": "RunTime",
    "set_time": "SetTime", "stop_time": "StopTime", "operator_time": "OperatorTime", "correction_time": "CorrectionTime",
    "manual_time": "ManualTime", "stop_alarm_time": "StopAlarmTime", "hold_alarm_time": "HoldAlarmTime",
    "diff_time": "DiffTime", "percent": "Percent", "fuyang_request": "FuyangRequest",
    "note1": "Note1", "note2": "Note2", "note3": "Note3", "note4": "Note4", "note5": "Note5",
}

# field -> header, chuẩn hoá CÙNG 1 chiều cho cả 3 loại (AVAILABILITY_COLUMNS/
# PERFORMANCE_COLUMNS ở core/excel_importer.py khai báo ngược lại — header -> field —
# vì đó là chiều IMPORT cần; `setdefault` giữ đúng header ĐẦU TIÊN gặp cho field nào bị
# khai 2 header (VD field _hour và field _kgh KHÔNG trùng nên không mất dữ liệu ở đây).
def _invert_to_field_header(header_to_field: dict[str, str]) -> dict[str, str]:
    field_to_header: dict[str, str] = {}
    for header, field in header_to_field.items():
        field_to_header.setdefault(field, header)
    return field_to_header


_EXPORT_CONFIG: dict[str, tuple[str, dict[str, str]]] = {
    "availability": ("availability_logs", _invert_to_field_header(AVAILABILITY_COLUMNS)),
    "performance": ("performance_logs", _invert_to_field_header(PERFORMANCE_COLUMNS)),
    "batch": ("batch_details", BATCH_EXPORT_HEADERS),
}


def export_data(data_type: str, from_date: str | None, to_date: str | None) -> tuple[bytes, str]:
    """Xuất dữ liệu Availability/Performance/Batch đã import trong DB ra `.xlsx`, lọc theo
    khoảng `production_date` (cùng quy ước ca 07:00 dùng cho MỌI bộ lọc ngày khác trong dự
    án — xem `core/production_time.py::production_bounds()` — để nhất quán với các báo cáo
    Downtime/Batch Matrix/Cleaning MC, KHÔNG dùng ranh giới ngày dương lịch 00:00 riêng)."""
    config = _EXPORT_CONFIG.get(data_type)
    if config is None:
        raise ValueError(f"data_type không hợp lệ: {data_type!r}. Phải là 1 trong {list(_EXPORT_CONFIG)}.")
    if not from_date or not to_date:
        raise ValueError("Vui lòng chọn đủ Từ ngày và Đến ngày.")
    table, field_to_header = config
    field_order = BATCH_DETAIL_FIELDS if data_type == "batch" else field_to_header.keys()
    fields = [field for field in field_order if field in field_to_header]
    headers = [field_to_header[field] for field in fields]

    start_ts, end_ts = production_bounds(from_date, to_date)
    record_time = "COALESCE(end_time, start_time)"
    sql = (
        f"SELECT * FROM {table} WHERE {sql_datetime(record_time)} >= {sql_datetime('?')} "
        f"AND {sql_datetime(record_time)} < {sql_datetime('?')} ORDER BY {record_time}"
    )
    rows = [dict(row) for row in execute_query(sql, (start_ts, end_ts))]

    content = export_rows_to_excel(headers, fields, rows, sheet_title=data_type.title())
    filename = f"{data_type}_{from_date}_to_{to_date}.xlsx"
    return content, filename
