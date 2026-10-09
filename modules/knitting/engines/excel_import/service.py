"""
modules/knitting/engines/excel_import/service.py
-----------------------------------------------
Engine Excel Import xưởng Dệt — tầng dữ liệu DÙNG CHUNG của Domain knitting: bảng + import 3 loại
file (Stop Reason Analysis by Machine / Piece Produced report / Knitting program) + lịch sử import.
Import gọi từ Modal trên Knitting Hub (giống Dyeing). Báo cáo đọc lại các bảng này (VD
`modules/knitting/engines/downtime/report.py`).

Bảng (SQLite tự tạo; Postgres tạo qua `supabase/migrate_knitting_downtime.sql`):
- `knitting_machine_daily`      — 1 dòng = 1 máy x 1 production_date (Efficiency, Times, Rev, Output).
- `knitting_stop_details`       — 1 dòng = 1 máy x 1 mã dừng x 1 production_date.
- `knitting_stop_category_map`  — Stop Code -> nhóm downtime do admin chỉnh tay (ghi đè mặc định
  trong `report.py`); áp ở READ TIME nên đổi nhóm không phải import lại.
- `knitting_downtime_targets`   — Before / Target % theo nhóm (seed theo bảng người dùng 2026-10-09).
- `knitting_piece_rolls`        — file "Piece Produced report", 1 dòng = 1 cuộn (khoá Roll No, UPSERT):
  nguồn biết máy nào dệt Greige ID nào ngày nào (bộ lọc Program, xem `downtime/programs.py`).
- `knitting_greige_programs` / `knitting_core_programs` — file "Knitting program.xlsx": Greige ->
  Program + danh sách Core program (import = thay thế toàn bộ).

Import 1 file = THAY THẾ toàn bộ dữ liệu của đúng production_date đó (file là ảnh chụp trọn 1
ngày; mã dừng biến mất ở bản xuất lại cũng phải biến mất trong DB — UPSERT không làm được điều
này). Không có rollup (`recompute_daily`): dữ liệu nguồn đã gộp sẵn theo ngày.

Đơn vị cột Times (Available/Run/Total Stop/Stop Time) CHƯA xác nhận — lưu nguyên giá trị file.
Báo cáo chỉ dùng TỈ LỆ Stop / Available (người dùng chốt: Plan PRD = cột Available) nên không phụ
thuộc đơn vị.
"""
from __future__ import annotations

from typing import Any

from core.database import get_dialect, insert_returning_id
from core.excel_importer import record_import_rows

from .importer import FILE_TYPE, MACHINE_FIELDS, STOP_FIELDS, parse_stop_reason_file
from .program_importer import (
    PIECE_FIELDS, PIECE_FILE_TYPE, PROGRAM_FILE_TYPE, parse_piece_produced_file, parse_program_file,
)


def _ensure_import_logs_table(conn: Any) -> None:
    """Duplicate có chủ đích của `core/rft_sources_importer.py::_ensure_import_logs_table()` —
    mỗi importer tự đảm bảo bảng chung tồn tại, không import chéo hàm private."""
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


def ensure_tables(conn: Any) -> None:
    if get_dialect() == "sqlite":
        conn.execute("""
            CREATE TABLE IF NOT EXISTS knitting_machine_daily (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                production_date TEXT NOT NULL,
                machine_code TEXT NOT NULL,
                job_mc_spec TEXT, knitting_structure TEXT,
                machine_efficiency REAL, operator_efficiency REAL,
                available_time REAL, run_time REAL, total_stop_time REAL,
                revolutions REAL, actual_speed REAL, total_production REAL,
                period_start TEXT NOT NULL, period_end TEXT NOT NULL,
                import_log_id INTEGER,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE (production_date, machine_code)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS knitting_stop_details (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                production_date TEXT NOT NULL,
                machine_code TEXT NOT NULL,
                stop_code TEXT NOT NULL,
                stop_description TEXT, stop_color INTEGER,
                stop_time REAL, stop_count REAL, loss_ratio REAL, avg_stop_time REAL,
                import_log_id INTEGER,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE (production_date, machine_code, stop_code)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS knitting_stop_category_map (
                stop_code TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                updated_by TEXT,
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS knitting_downtime_targets (
                category TEXT PRIMARY KEY,
                before_pct REAL,
                target_pct REAL,
                updated_by TEXT,
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS knitting_piece_rolls (
                roll_no TEXT PRIMARY KEY,
                machine_group TEXT, machine TEXT, machine_code TEXT NOT NULL, job_id TEXT, sap_lot TEXT,
                sale_order TEXT, material_type TEXT, knitting_structure TEXT, greige_id TEXT NOT NULL,
                available REAL, running REAL, stopped REAL, total_qty REAL, good_qty REAL,
                record_start TEXT NOT NULL, record_end TEXT NOT NULL,
                import_log_id INTEGER,
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS knitting_greige_programs (
                greige_code TEXT PRIMARY KEY,
                program TEXT NOT NULL,
                program_key TEXT NOT NULL,
                import_log_id INTEGER
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS knitting_core_programs (
                program_key TEXT PRIMARY KEY,
                program TEXT NOT NULL,
                import_log_id INTEGER
            )
        """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_knitting_stop_details_code ON knitting_stop_details (stop_code, production_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_knitting_piece_rolls_span ON knitting_piece_rolls (record_end, record_start)")


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


def import_stop_reason_file(conn: Any, file_bytes: bytes, filename: str, imported_by: str | None) -> dict[str, Any]:
    """Parse + thay thế dữ liệu của production_date trong tên file. Lỗi cấp file -> ValueError
    (không ghi gì vào DB, kể cả import_logs)."""
    result = parse_stop_reason_file(file_bytes, filename)
    production_date = result["production_date"]

    ensure_tables(conn)
    _ensure_import_logs_table(conn)
    conn.commit()

    log_id = insert_returning_id(
        conn,
        "INSERT INTO import_logs (file_name, import_type, file_type, imported_by, total_rows, error_rows, status) VALUES (?, ?, ?, ?, ?, ?, 'processing')",
        (filename, FILE_TYPE.lower(), FILE_TYPE, imported_by or "unknown", result["total_rows"], len(result["errors"])),
    )
    conn.commit()

    replaced = conn.execute(
        "SELECT COUNT(*) AS n FROM knitting_machine_daily WHERE production_date = ?", (production_date,)
    ).fetchone()["n"]
    try:
        conn.execute("BEGIN")
        conn.execute("DELETE FROM knitting_stop_details WHERE production_date = ?", (production_date,))
        conn.execute("DELETE FROM knitting_machine_daily WHERE production_date = ?", (production_date,))
        machine_cols = ("production_date",) + MACHINE_FIELDS + ("period_start", "period_end", "import_log_id")
        conn.executemany(
            f"INSERT INTO knitting_machine_daily ({','.join(machine_cols)}) VALUES ({','.join('?' for _ in machine_cols)})",
            [
                (production_date,) + tuple(m[f] for f in MACHINE_FIELDS) + (result["period_start"], result["period_end"], log_id)
                for m in result["machines"]
            ],
        )
        stop_cols = ("production_date",) + STOP_FIELDS + ("import_log_id",)
        conn.executemany(
            f"INSERT INTO knitting_stop_details ({','.join(stop_cols)}) VALUES ({','.join('?' for _ in stop_cols)})",
            [(production_date,) + tuple(s[f] for f in STOP_FIELDS) + (log_id,) for s in result["stops"]],
        )
        conn.commit()
        record_import_rows(conn, log_id, result["row_details"])
    except Exception as exc:
        conn.rollback()
        conn.execute("UPDATE import_logs SET status='failed', error_detail=? WHERE id=?", (str(exc), log_id))
        conn.commit()
        raise

    imported_rows = result["total_rows"] - len(result["errors"])
    status = "completed" if imported_rows and not result["errors"] else "partial" if imported_rows else "failed"
    error_detail = "; ".join(f"Dòng {e['row']}: {e['error']}" for e in result["errors"][:20]) or None
    conn.execute(
        "UPDATE import_logs SET imported_rows=?, success_rows=?, status=?, error_detail=? WHERE id=?",
        (imported_rows, imported_rows, status, error_detail, log_id),
    )
    conn.commit()

    return {
        "status": status,
        "file_type": FILE_TYPE,
        "production_date": production_date,
        "period_start": result["period_start"],
        "period_end": result["period_end"],
        "machines": len(result["machines"]),
        "stops": len(result["stops"]),
        "replaced_existing": replaced > 0,
        "total_rows": result["total_rows"],
        "imported_rows": imported_rows,
        "errors": result["errors"],
        "warnings": result["warnings"],
        "import_log_id": log_id,
    }


def _start_log(conn: Any, filename: str, file_type: str, imported_by: str | None, total_rows: int, error_rows: int) -> int:
    ensure_tables(conn)
    _ensure_import_logs_table(conn)
    conn.commit()
    log_id = insert_returning_id(
        conn,
        "INSERT INTO import_logs (file_name, import_type, file_type, imported_by, total_rows, error_rows, status) VALUES (?, ?, ?, ?, ?, ?, 'processing')",
        (filename, file_type.lower(), file_type, imported_by or "unknown", total_rows, error_rows),
    )
    conn.commit()
    return log_id


def _finish_log(conn: Any, log_id: int, imported_rows: int, errors: list[dict[str, Any]]) -> str:
    status = "completed" if imported_rows and not errors else "partial" if imported_rows else "failed"
    error_detail = "; ".join(f"Dòng {e['row']}: {e['error']}" for e in errors[:20]) or None
    conn.execute(
        "UPDATE import_logs SET imported_rows=?, success_rows=?, status=?, error_detail=? WHERE id=?",
        (imported_rows, imported_rows, status, error_detail, log_id),
    )
    conn.commit()
    return status


def _fail_log(conn: Any, log_id: int, exc: Exception) -> None:
    conn.rollback()
    conn.execute("UPDATE import_logs SET status='failed', error_detail=? WHERE id=?", (str(exc), log_id))
    conn.commit()


def import_piece_produced_file(conn: Any, file_bytes: bytes, filename: str, imported_by: str | None) -> dict[str, Any]:
    """UPSERT cuộn theo Roll No. Chỉ ghi dòng LỖI vào `import_log_rows` (file ~10k dòng/tháng,
    knitting không có Raw Data Viewer — không lưu snapshot mọi dòng)."""
    result = parse_piece_produced_file(file_bytes)
    log_id = _start_log(conn, filename, PIECE_FILE_TYPE, imported_by, result["total_rows"], len(result["errors"]))
    try:
        columns = PIECE_FIELDS + ("import_log_id",)
        updates = ",".join(f"{c}=excluded.{c}" for c in columns if c != "roll_no")
        conn.execute("BEGIN")
        conn.executemany(
            f"INSERT INTO knitting_piece_rolls ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)}) "
            f"ON CONFLICT (roll_no) DO UPDATE SET {updates}",
            [tuple(r[c] for c in PIECE_FIELDS) + (log_id,) for r in result["rolls"]],
        )
        conn.commit()
        record_import_rows(conn, log_id, [
            {"row_number": e["row"], "status": "invalid", "error": e["error"], "data": {}} for e in result["errors"]
        ])
    except Exception as exc:
        _fail_log(conn, log_id, exc)
        raise
    known = {r["greige_code"] for r in conn.execute("SELECT greige_code FROM knitting_greige_programs")}
    status = _finish_log(conn, log_id, len(result["rolls"]), result["errors"])
    missing = [g for g in result["greige_ids"] if g not in known]
    return {
        "status": status, "file_type": PIECE_FILE_TYPE, "rolls": len(result["rolls"]),
        "date_from": result["date_from"], "date_to": result["date_to"], "machines": result["machines"],
        "greige_not_in_program_list": missing, "errors": result["errors"],
        "warnings": [f"Greige ID chưa có trong danh mục Program: {', '.join(missing)}"] if known and missing else [],
        "import_log_id": log_id,
    }


def import_program_file(conn: Any, file_bytes: bytes, filename: str, imported_by: str | None) -> dict[str, Any]:
    """THAY THẾ toàn bộ danh mục Greige -> Program + Core program."""
    result = parse_program_file(file_bytes)
    total = len(result["greige_programs"])
    log_id = _start_log(conn, filename, PROGRAM_FILE_TYPE, imported_by, total, 0)
    try:
        conn.execute("BEGIN")
        conn.execute("DELETE FROM knitting_greige_programs")
        conn.execute("DELETE FROM knitting_core_programs")
        conn.executemany(
            "INSERT INTO knitting_greige_programs (greige_code, program, program_key, import_log_id) VALUES (?, ?, ?, ?)",
            [(r["greige_code"], r["program"], r["program_key"], log_id) for r in result["greige_programs"]],
        )
        conn.executemany(
            "INSERT INTO knitting_core_programs (program_key, program, import_log_id) VALUES (?, ?, ?)",
            [(r["program_key"], r["program"], log_id) for r in result["core_programs"]],
        )
        conn.commit()
    except Exception as exc:
        _fail_log(conn, log_id, exc)
        raise
    status = _finish_log(conn, log_id, total, [])
    return {
        "status": status, "file_type": PROGRAM_FILE_TYPE, "greige_codes": total, "programs": result["programs"],
        "core_programs": [r["program"] for r in result["core_programs"]],
        "conflicts": result["conflicts"], "errors": [],
        "warnings": [f"Greige {c['greige_code']} có nhiều Program ({' / '.join(c['programs'])}) — dùng '{c['used']}' (dòng cuối)."
                     for c in result["conflicts"]],
        "import_log_id": log_id,
    }


def get_program_sources(conn: Any) -> dict[str, Any]:
    """Tình trạng 2 nguồn của bộ lọc Program — hiện ở tab Import Data."""
    ensure_tables(conn)
    rolls = conn.execute(
        "SELECT COUNT(*) AS n, MIN(record_end) AS d1, MAX(record_end) AS d2, COUNT(DISTINCT machine_code) AS m FROM knitting_piece_rolls"
    ).fetchone()
    greige = conn.execute("SELECT COUNT(*) AS n, COUNT(DISTINCT program_key) AS p FROM knitting_greige_programs").fetchone()
    core = [r["program"] for r in conn.execute("SELECT program FROM knitting_core_programs ORDER BY program")]
    return {
        "rolls": rolls["n"], "rolls_from": rolls["d1"], "rolls_to": rolls["d2"], "roll_machines": rolls["m"],
        "greige_codes": greige["n"], "programs": greige["p"], "core_programs": core,
    }


# ---------------------------------------------------------------------------
# Danh sách ngày đã import
# ---------------------------------------------------------------------------


def list_imported_days(conn: Any, limit: int = 60) -> list[dict[str, Any]]:
    ensure_tables(conn)
    rows = conn.execute(
        """
        SELECT m.production_date, COUNT(*) AS machines, MAX(m.period_start) AS period_start,
               MAX(m.period_end) AS period_end, MAX(l.file_name) AS file_name,
               MAX(l.imported_by) AS imported_by, MAX(l.imported_at) AS imported_at
        FROM knitting_machine_daily m
        LEFT JOIN import_logs l ON l.id = m.import_log_id
        GROUP BY m.production_date
        ORDER BY m.production_date DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Điều phối import theo loại file + lịch sử (Modal Import trên Knitting Hub)
# ---------------------------------------------------------------------------

DATA_TYPES: dict[str, str] = {
    "stop_reason": FILE_TYPE,
    "piece_produced": PIECE_FILE_TYPE,
    "program": PROGRAM_FILE_TYPE,
}
KNITTING_FILE_TYPES = tuple(DATA_TYPES.values())


def import_file(conn: Any, file_bytes: bytes, filename: str, data_type: str, imported_by: str | None) -> dict[str, Any]:
    """`data_type` = "auto" (nhận theo đuôi + header) hoặc 1 khoá của `DATA_TYPES`."""
    from .program_importer import detect_file_type

    if data_type in (None, "", "auto"):
        file_type = detect_file_type(filename, file_bytes)
    elif data_type in DATA_TYPES:
        file_type = DATA_TYPES[data_type]
    else:
        raise ValueError(f"Data Type không hợp lệ: {data_type}")
    if file_type == FILE_TYPE:
        return import_stop_reason_file(conn, file_bytes, filename, imported_by)
    if file_type == PIECE_FILE_TYPE:
        return import_piece_produced_file(conn, file_bytes, filename, imported_by)
    return import_program_file(conn, file_bytes, filename, imported_by)


def list_recent_imports(conn: Any, limit: int = 30) -> list[dict[str, Any]]:
    ensure_tables(conn)
    _ensure_import_logs_table(conn)
    placeholders = ",".join("?" for _ in KNITTING_FILE_TYPES)
    rows = conn.execute(
        f"""
        SELECT id, file_name, file_type, imported_by, imported_at, status, total_rows, imported_rows, error_rows, error_detail
        FROM import_logs WHERE file_type IN ({placeholders})
        ORDER BY id DESC LIMIT ?
        """,
        (*KNITTING_FILE_TYPES, limit),
    ).fetchall()
    return [dict(row) for row in rows]
