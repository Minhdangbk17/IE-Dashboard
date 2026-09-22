"""
core/import_rows_service.py
----------------------------
Raw Data Viewer: điều phối xem/sửa/xoá dữ liệu raw đã lưu trong `import_log_rows`
cho một lần import (Availability / Performance / Batch). Route Flask chỉ gọi
thẳng 3 hàm ở đây, không tự viết SQL.
"""
from __future__ import annotations

import json
from typing import Any

from core.database import execute_one, execute_query, get_db
from core.excel_importer import revalidate_raw_row, save_to_db
from core.batch_importer import revalidate_batch_row, BATCH_DETAIL_FIELDS

# file_type (import_logs.file_type) -> tên bảng đích thật đã ghi dữ liệu.
_TARGET_TABLE = {"AVAILABILITY": "availability_logs", "PERFORMANCE": "performance_logs", "BATCH": "batch_details"}


def _get_import_log(log_id: int) -> dict[str, Any]:
    row = execute_one("SELECT id, file_name, file_type, total_rows, success_rows, error_rows FROM import_logs WHERE id = ?", (log_id,))
    if row is None:
        raise ValueError(f"Không tìm thấy lần import #{log_id}.")
    return dict(row)


def list_import_rows(log_id: int) -> dict[str, Any]:
    """Trả toàn bộ dòng raw (valid + invalid) của một lần import — client tự search/filter/phân trang."""
    log = _get_import_log(log_id)
    rows = execute_query(
        "SELECT id, row_number, status, error_message, row_data FROM import_log_rows WHERE import_log_id = ? ORDER BY row_number",
        (log_id,),
    )
    parsed_rows = [
        {"id": row["id"], "row_number": row["row_number"], "status": row["status"], "error": row["error_message"], "data": json.loads(row["row_data"])}
        for row in rows
    ]
    columns = list(parsed_rows[0]["data"].keys()) if parsed_rows else []
    return {
        "file_name": log["file_name"],
        "file_type": log["file_type"],
        "columns": columns,
        "total": len(parsed_rows),
        "rows": parsed_rows,
    }


def _revalidate(file_type: str, raw: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    if file_type == "BATCH":
        return revalidate_batch_row(raw)
    if file_type in ("AVAILABILITY", "PERFORMANCE"):
        return revalidate_raw_row(file_type, raw)
    raise ValueError(f"file_type '{file_type}' không hỗ trợ Inline Edit.")


def update_import_row(log_id: int, row_id: int, edited_data: dict[str, Any]) -> dict[str, Any]:
    """Sửa 1 dòng (Inline Edit) — revalidate bằng đúng logic của luồng import hàng loạt.

    Nếu hợp lệ sau khi sửa: ghi thẳng vào bảng đích thật (UPSERT, gắn `import_log_id`) và
    đánh dấu dòng là 'valid'. Nếu vẫn lỗi: giữ nguyên trạng thái 'invalid', cập nhật lại
    `row_data`/`error_message` theo bản người dùng vừa sửa (không mất thao tác của họ).
    """
    log = _get_import_log(log_id)
    row = execute_one("SELECT id, status FROM import_log_rows WHERE id = ? AND import_log_id = ?", (row_id, log_id))
    if row is None:
        raise ValueError(f"Không tìm thấy dòng #{row_id} trong lần import #{log_id}.")

    file_type = log["file_type"]
    record, error = _revalidate(file_type, edited_data)

    conn = get_db()
    was_valid = row["status"] == "valid"
    if error is not None:
        conn.execute(
            "UPDATE import_log_rows SET status='invalid', error_message=?, row_data=? WHERE id=?",
            (error, json.dumps(edited_data, ensure_ascii=False), row_id),
        )
        if was_valid:
            conn.execute("UPDATE import_logs SET success_rows = success_rows - 1, error_rows = error_rows + 1, status='partial' WHERE id=?", (log_id,))
        conn.commit()
        return {"id": row_id, "status": "invalid", "error": error, "data": edited_data}

    table = _TARGET_TABLE[file_type]
    if file_type == "BATCH":
        columns_with_log = BATCH_DETAIL_FIELDS + ("import_log_id",)
        placeholders = ",".join("?" for _ in columns_with_log)
        key_fields = ("dyelot", "machine", "start_time")
        updates = ",".join(f"{field}=excluded.{field}" for field in columns_with_log if field not in key_fields)
        sql = (
            f"INSERT INTO batch_details ({','.join(columns_with_log)}) VALUES ({placeholders}) "
            f"ON CONFLICT({','.join(key_fields)}) DO UPDATE SET {updates}"
        )
        conn.execute(sql, tuple(record[field] for field in BATCH_DETAIL_FIELDS) + (log_id,))
        conn.commit()
    else:
        save_to_db({"rows": [record]}, file_type, conn, import_log_id=log_id)

    conn.execute(
        "UPDATE import_log_rows SET status='valid', error_message=NULL, row_data=? WHERE id=?",
        (json.dumps(edited_data, ensure_ascii=False), row_id),
    )
    if not was_valid:
        remaining_errors = execute_one("SELECT COUNT(*) AS c FROM import_log_rows WHERE import_log_id=? AND status='invalid'", (log_id,))["c"]
        new_status = "completed" if remaining_errors == 0 else "partial"
        conn.execute(
            "UPDATE import_logs SET success_rows = success_rows + 1, error_rows = error_rows - 1, status=? WHERE id=?",
            (new_status, log_id),
        )
    conn.commit()
    return {"id": row_id, "status": "valid", "error": None, "data": edited_data}


def delete_import(log_id: int) -> dict[str, Any]:
    """"Xóa danh sách này": xoá dữ liệu đã ghi vào bảng đích (WHERE import_log_id = ?) +
    xoá toàn bộ `import_log_rows` + xoá luôn dòng `import_logs` — coi như chưa từng import."""
    log = _get_import_log(log_id)
    table = _TARGET_TABLE.get(log["file_type"])
    conn = get_db()
    deleted_target = 0
    try:
        if table:
            cursor = conn.execute(f"DELETE FROM {table} WHERE import_log_id = ?", (log_id,))
            deleted_target = cursor.rowcount
        conn.execute("DELETE FROM import_log_rows WHERE import_log_id = ?", (log_id,))
        conn.execute("DELETE FROM import_logs WHERE id = ?", (log_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"deleted_import_log_id": log_id, "deleted_target_rows": deleted_target}
