from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING, Any

from flask import Blueprint, jsonify, render_template, request

from core.auth import permission_required
from core.database import get_db, get_dialect
from core.excel_importer import _add_availability_business_fields

if TYPE_CHECKING:
    from core.engine_base import BaseEngine

DOWNTIME_FIELDS = (
    "rework_hour", "adjust_color_hour", "bleaching_hour", "load_hour", "unload_hour", "sample_checking_hour",
    "ph_checking_hour", "wait_chemical_load_hour", "wait_color_load_hour", "wait_fabric_hour", "wait_water_hour",
    "wait_steam_hour", "cleaning_hour", "maintenance_hour", "others_hour",
)


def _number(value: Any) -> float:
    try:
        return max(0.0, float(value or 0))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid number: {value}") from exc


def _parse_datetime(value: str) -> datetime:
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError("Time must be in a valid format.")


def _ensure_columns(conn: Any) -> None:
    """Tự vá cột thiếu + dọn trùng lặp cho DB SQLite CŨ (trước khi các cột này được thêm vào
    schema chính thức). CHỈ chạy ở SQLite — dùng `rowid` (ngầm định riêng của SQLite, KHÔNG
    tồn tại ở Postgres) để xoá dòng trùng khoá. Ở Postgres, `availability_logs` đã có đủ cột
    VÀ đã có `UNIQUE INDEX uq_availability_batch_ref_machine_start` ngay từ
    `supabase/schema.sql` (deploy mới, không có dữ liệu cũ/trùng lặp cần dọn)."""
    if get_dialect() != "sqlite":
        return
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(availability_logs)")}
    additions = {
        "entry_type": "TEXT NOT NULL DEFAULT 'IMPORT'",
        "production_date": "TEXT", "week_label": "TEXT", "month_label": "TEXT",
        "ach_load": "INTEGER", "ach_unload": "INTEGER", "ach_sample_check": "INTEGER",
        "ach_ph": "INTEGER", "ach_chemical": "INTEGER", "ach_color": "INTEGER",
        "ach_evaluated": "INTEGER NOT NULL DEFAULT 0", "ach_passed": "INTEGER NOT NULL DEFAULT 0",
        "ach_all_items": "INTEGER NOT NULL DEFAULT 0",
    }
    for field in additions:
        if field not in columns:
            conn.execute(f"ALTER TABLE availability_logs ADD COLUMN {field} {additions[field]}")
    conn.execute("UPDATE availability_logs SET batch_ref_no = batch WHERE batch_ref_no IS NULL OR TRIM(batch_ref_no) = ''")
    conn.execute("""
        DELETE FROM availability_logs
        WHERE rowid NOT IN (
            SELECT MIN(rowid) FROM availability_logs
            GROUP BY batch_ref_no, machine, start_time
        )
    """)
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_availability_manual_key ON availability_logs (batch_ref_no, machine, start_time)")
    conn.commit()


def build_blueprint(_engine: "BaseEngine") -> Blueprint:
    bp = Blueprint("manual_entry", __name__, template_folder="templates", static_folder="static")

    @bp.route("/")
    @permission_required("dyeing", "manual_entry", "view")
    def view() -> Any:
        machines = get_db().execute("SELECT machine_id, machine_name FROM machines WHERE domain='dyeing' AND is_active=1 ORDER BY machine_id").fetchall()
        return render_template("manual_form.html", machines=[dict(row) for row in machines])

    @bp.route("/api/dyeing/availability/manual", methods=["POST"])
    @bp.route("/api/manual", methods=["POST"])
    @permission_required("dyeing", "manual_entry", "edit")
    def save_manual() -> Any:
        payload = request.get_json(silent=True) or {}
        try:
            machine = str(payload.get("machine", "")).strip()
            batch_ref_no = str(payload.get("batch_ref_no", "")).strip()
            start = _parse_datetime(str(payload.get("start_time", "")))
            end = _parse_datetime(str(payload.get("end_time", "")))
            if not machine or not batch_ref_no:
                raise ValueError("Machine and Batch Ref No are required.")
            if end <= start:
                raise ValueError("End Time must be after Start Time.")
            record = {
                "batch": str(payload.get("batch", batch_ref_no)).strip() or batch_ref_no,
                "batch_ref_no": batch_ref_no, "fabric_type": str(payload.get("fabric_type", "")).strip(),
                "brand_name": str(payload.get("brand_name", "")).strip(), "machine": machine,
                "capacity_kg": _number(payload.get("capacity_kg")), "program": str(payload.get("program", "")).strip(),
                "start_time": start.strftime("%Y-%m-%d %H:%M:%S"), "end_time": end.strftime("%Y-%m-%d %H:%M:%S"),
            }
            record.update({field: _number(payload.get(field)) for field in DOWNTIME_FIELDS})
            record["planned_prd_time_hour"] = round((end - start).total_seconds() / 3600, 4)
            record["running_time_hour"] = max(0.0, record["planned_prd_time_hour"] - sum(record[field] for field in DOWNTIME_FIELDS))
            record["total_downtime_hour"] = round(sum(record[field] for field in DOWNTIME_FIELDS), 4)
            _add_availability_business_fields(record)
            _ensure_columns(get_db())
            fields = tuple(record.keys()) + ("entry_type",)
            values = tuple(record.values()) + ("MANUAL",)
            update_fields = ",".join(f"{field}=excluded.{field}" for field in fields if field not in {"batch_ref_no", "machine", "start_time"})
            sql = f"INSERT INTO availability_logs ({','.join(fields)}) VALUES ({','.join('?' for _ in fields)}) ON CONFLICT(batch_ref_no,machine,start_time) DO UPDATE SET {update_fields}"
            conn = get_db()
            conn.execute(sql, values)
            conn.commit()
            return jsonify({"status": "success", "production_date": record["production_date"], "planned_prd_time": record["planned_prd_time_hour"], "total_downtime": record["total_downtime_hour"]})
        except ValueError as exc:
            return jsonify({"status": "error", "error": str(exc)}), 400

    return bp
