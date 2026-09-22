"""
init_db.py
----------
Script khởi tạo Database Schema + Seed Data mẫu cho toàn bộ ứng dụng.

Chạy độc lập (không cần Flask app context):

    python init_db.py            # tạo DB mới (bỏ qua nếu đã tồn tại dữ liệu)
    python init_db.py --reset    # XÓA DB cũ và tạo lại từ đầu

Tạo các bảng:
    - users              : tài khoản đăng nhập (admin/operator)
    - machines           : danh mục máy nhuộm
    - machine_telemetry  : dữ liệu vận hành máy (nạp từ Excel hoặc IoT)
    - downtime_logs      : lịch sử dừng máy
    - import_logs        : lịch sử các lần import file Excel/CSV
"""
from __future__ import annotations

import argparse
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import Config  # noqa: E402
from core.auth import hash_password  # noqa: E402
from core.database import get_raw_connection  # noqa: E402

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    full_name     TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('admin', 'operator')),
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Phân quyền Xem/Sửa/Xoá RIÊNG CHO TỪNG ENGINE (không phải theo cả domain gộp) — chỉ áp
-- dụng cho role='operator'. admin luôn superuser cố định, KHÔNG đi qua bảng này (xem
-- core/auth.py::has_permission()). (domain, engine_name) phải khớp đúng BaseEngine.domain/
-- .name lấy ĐỘNG từ core/engine_registry.py::discover_engines() — không hardcode danh sách
-- Engine ở đây hay ở bất kỳ đâu khác.
CREATE TABLE IF NOT EXISTS user_permissions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    domain        TEXT NOT NULL,
    engine_name   TEXT NOT NULL,
    can_view      INTEGER NOT NULL DEFAULT 0 CHECK (can_view IN (0,1)),
    can_edit      INTEGER NOT NULL DEFAULT 0 CHECK (can_edit IN (0,1)),
    can_delete    INTEGER NOT NULL DEFAULT 0 CHECK (can_delete IN (0,1)),
    UNIQUE(user_id, domain, engine_name)
);

CREATE TABLE IF NOT EXISTS machines (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    machine_id   TEXT NOT NULL UNIQUE,
    machine_name TEXT NOT NULL,
    domain       TEXT NOT NULL DEFAULT 'dyeing',
    standard_speed REAL NOT NULL DEFAULT 100.0,
    machine_code TEXT,
    mc_brand TEXT,
    tank_type TEXT,
    mc_quantity INTEGER NOT NULL DEFAULT 1,
    tube_no INTEGER,
    capacity_kg REAL,
    group_mc TEXT,
    status TEXT,
    production_status TEXT,
    orgatex INTEGER NOT NULL DEFAULT 0,
    is_active    INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_machines_code_norm ON machines (LOWER(TRIM(COALESCE(machine_code, machine_id))));

CREATE TABLE IF NOT EXISTS machine_telemetry (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp      TEXT NOT NULL,
    machine_id     TEXT NOT NULL,
    status         TEXT NOT NULL CHECK (status IN ('RUNNING', 'STOPPED', 'MAINTENANCE')),
    actual_speed   REAL NOT NULL DEFAULT 0,
    standard_speed REAL NOT NULL DEFAULT 0,
    output_meters  REAL NOT NULL DEFAULT 0,
    import_log_id  INTEGER,
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (import_log_id) REFERENCES import_logs (id)
);
CREATE INDEX IF NOT EXISTS idx_telemetry_machine_time
    ON machine_telemetry (machine_id, timestamp);

CREATE TABLE IF NOT EXISTS downtime_logs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp        TEXT NOT NULL,
    machine_id       TEXT NOT NULL,
    reason_code      TEXT NOT NULL,
    reason_name      TEXT NOT NULL,
    duration_minutes REAL NOT NULL,
    detail           TEXT,
    import_log_id    INTEGER,
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (import_log_id) REFERENCES import_logs (id)
);
CREATE INDEX IF NOT EXISTS idx_downtime_machine_time
    ON downtime_logs (machine_id, timestamp);

CREATE TABLE IF NOT EXISTS import_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    file_name       TEXT NOT NULL,
    import_type     TEXT NOT NULL,          -- 'telemetry' | 'downtime'
    imported_by     TEXT NOT NULL,
    total_rows      INTEGER NOT NULL DEFAULT 0,
    success_rows    INTEGER NOT NULL DEFAULT 0,
    error_rows      INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'completed',  -- 'completed' | 'failed' | 'partial'
    error_detail    TEXT,
    imported_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS availability_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch TEXT NOT NULL,
    batch_ref_no TEXT NOT NULL,
    entry_type TEXT NOT NULL DEFAULT 'IMPORT',
    fabric_type TEXT,
    brand_name TEXT,
    machine TEXT NOT NULL,
    capacity_kg REAL NOT NULL DEFAULT 0,
    program TEXT,
    start_time TEXT NOT NULL,
    end_time TEXT,
    production_date TEXT,
    week_label TEXT,
    month_label TEXT,
    availability_pct REAL NOT NULL DEFAULT 0,
    -- Nhóm đơn vị Giờ (suffix _hour)
    total_op_time_cal_hour REAL NOT NULL DEFAULT 0,
    planned_prd_time_hour REAL NOT NULL DEFAULT 0,
    no_order_hour REAL NOT NULL DEFAULT 0,
    testing_sample_order_hour REAL NOT NULL DEFAULT 0,
    running_time_hour REAL NOT NULL DEFAULT 0,
    total_downtime_hour REAL NOT NULL DEFAULT 0,
    rework_hour REAL NOT NULL DEFAULT 0,
    adjust_color_hour REAL NOT NULL DEFAULT 0,
    bleaching_hour REAL NOT NULL DEFAULT 0,
    load_hour REAL NOT NULL DEFAULT 0,
    unload_hour REAL NOT NULL DEFAULT 0,
    testing_bulk_order_hour REAL NOT NULL DEFAULT 0,
    sample_checking_hour REAL NOT NULL DEFAULT 0,
    ph_checking_hour REAL NOT NULL DEFAULT 0,
    wait_chemical_load_hour REAL NOT NULL DEFAULT 0,
    wait_color_load_hour REAL NOT NULL DEFAULT 0,
    wait_fabric_hour REAL NOT NULL DEFAULT 0,
    wait_water_hour REAL NOT NULL DEFAULT 0,
    wait_steam_hour REAL NOT NULL DEFAULT 0,
    cleaning_hour REAL NOT NULL DEFAULT 0,
    maintenance_hour REAL NOT NULL DEFAULT 0,
    others_hour REAL NOT NULL DEFAULT 0,
    -- Nhóm đơn vị Sản lượng-Giờ (suffix _kgh) — song song với nhóm _hour ở trên
    total_op_time_cal_kgh REAL NOT NULL DEFAULT 0,
    planned_prd_time_kgh REAL NOT NULL DEFAULT 0,
    no_order_kgh REAL NOT NULL DEFAULT 0,
    testing_sample_order_kgh REAL NOT NULL DEFAULT 0,
    running_time_kgh REAL NOT NULL DEFAULT 0,
    total_downtime_kgh REAL NOT NULL DEFAULT 0,
    rework_kgh REAL NOT NULL DEFAULT 0,
    adjust_color_kgh REAL NOT NULL DEFAULT 0,
    bleaching_kgh REAL NOT NULL DEFAULT 0,
    load_kgh REAL NOT NULL DEFAULT 0,
    unload_kgh REAL NOT NULL DEFAULT 0,
    testing_bulk_order_kgh REAL NOT NULL DEFAULT 0,
    sample_checking_kgh REAL NOT NULL DEFAULT 0,
    ph_checking_kgh REAL NOT NULL DEFAULT 0,
    wait_chemical_load_kgh REAL NOT NULL DEFAULT 0,
    wait_color_load_kgh REAL NOT NULL DEFAULT 0,
    wait_fabric_kgh REAL NOT NULL DEFAULT 0,
    wait_water_kgh REAL NOT NULL DEFAULT 0,
    wait_steam_kgh REAL NOT NULL DEFAULT 0,
    cleaning_kgh REAL NOT NULL DEFAULT 0,
    maintenance_kgh REAL NOT NULL DEFAULT 0,
    others_kgh REAL NOT NULL DEFAULT 0,
    ach_load INTEGER,
    ach_unload INTEGER,
    ach_sample_check INTEGER,
    ach_ph INTEGER,
    ach_chemical INTEGER,
    ach_color INTEGER,
    ach_evaluated INTEGER NOT NULL DEFAULT 0,
    ach_passed INTEGER NOT NULL DEFAULT 0,
    ach_all_items INTEGER NOT NULL DEFAULT 0,
    import_log_id INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (batch, machine, start_time),
    FOREIGN KEY (import_log_id) REFERENCES import_logs (id)
);
CREATE INDEX IF NOT EXISTS idx_availability_start_time ON availability_logs (start_time);
CREATE UNIQUE INDEX IF NOT EXISTS uq_availability_batch_ref_machine_start
    ON availability_logs (batch_ref_no, machine, start_time);
CREATE INDEX IF NOT EXISTS idx_availability_batch_norm ON availability_logs (LOWER(TRIM(batch)));
CREATE INDEX IF NOT EXISTS idx_availability_batch_ref_norm ON availability_logs (LOWER(TRIM(batch_ref_no)));

CREATE TABLE IF NOT EXISTS batch_details (
    dyelot TEXT PRIMARY KEY,
    customer TEXT, color TEXT, order_no TEXT, greige_code TEXT, recipe_no TEXT, colour_no TEXT,
    shade TEXT, customer_color TEXT, is_rework INTEGER NOT NULL DEFAULT 0, machine TEXT, machine_group TEXT,
    fabric_code TEXT, fabric_type TEXT, fabric_content TEXT,
    wo_qty TEXT,
    batch_type TEXT, batch_state TEXT, formula_code TEXT, formula_type TEXT,
    process_type TEXT, weight REAL NOT NULL DEFAULT 0, redye REAL NOT NULL DEFAULT 0, liquor_ratio REAL NOT NULL DEFAULT 0,
    liquor_quantity REAL NOT NULL DEFAULT 0,
    weight_per_area REAL NOT NULL DEFAULT 0, greige_width REAL NOT NULL DEFAULT 0,
    reel_speed REAL NOT NULL DEFAULT 0, pump_speed REAL NOT NULL DEFAULT 0, max_reel_speed REAL NOT NULL DEFAULT 0,
    absorption REAL NOT NULL DEFAULT 0, nozzle REAL NOT NULL DEFAULT 0,
    sap_lot TEXT, customer_code TEXT, customer_po TEXT,
    soft_water REAL NOT NULL DEFAULT 0,
    hot_water REAL NOT NULL DEFAULT 0, hard_water REAL NOT NULL DEFAULT 0, mix_water REAL NOT NULL DEFAULT 0,
    sum_water REAL NOT NULL DEFAULT 0,
    water_per_kg REAL NOT NULL DEFAULT 0, power REAL NOT NULL DEFAULT 0,
    power_per_kg REAL NOT NULL DEFAULT 0, heating_energy REAL NOT NULL DEFAULT 0,
    steam_per_kg REAL NOT NULL DEFAULT 0, dye_cost REAL NOT NULL DEFAULT 0,
    chemical_cost REAL NOT NULL DEFAULT 0, correction_cnt INTEGER NOT NULL DEFAULT 0,
    alarm_cnt REAL NOT NULL DEFAULT 0, intervention_cnt REAL NOT NULL DEFAULT 0,
    total_correction_cnt INTEGER NOT NULL DEFAULT 0,
    washing_correction TEXT, dyestuff_correction TEXT, chemical_correction TEXT,
    schedule_time TEXT, start_time TEXT, end_time TEXT, run_time REAL NOT NULL DEFAULT 0,
    set_time REAL NOT NULL DEFAULT 0, stop_time REAL NOT NULL DEFAULT 0, operator_time REAL NOT NULL DEFAULT 0,
    correction_time REAL NOT NULL DEFAULT 0, manual_time REAL NOT NULL DEFAULT 0,
    stop_alarm_time REAL NOT NULL DEFAULT 0, hold_alarm_time REAL NOT NULL DEFAULT 0,
    diff_time REAL NOT NULL DEFAULT 0, percent REAL NOT NULL DEFAULT 0,
    fuyang_request TEXT,
    note1 TEXT, note2 TEXT, note3 TEXT, note4 TEXT, note5 TEXT,
    import_log_id INTEGER, created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_batch_details_dyelot_norm ON batch_details (LOWER(TRIM(dyelot)));

CREATE TABLE IF NOT EXISTS performance_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dyelot TEXT NOT NULL,
    brand_name TEXT,
    machine TEXT NOT NULL,
    machine_group TEXT,
    max_capacity_pct REAL NOT NULL DEFAULT 0,
    capacity REAL NOT NULL DEFAULT 0,
    dyelot_ref_no TEXT,
    fabric_type TEXT,
    program TEXT,
    redye TEXT,
    sap_no TEXT,
    pth REAL NOT NULL DEFAULT 0,
    start_time TEXT NOT NULL,
    end_time TEXT,
    performance REAL NOT NULL DEFAULT 0,
    speed REAL NOT NULL DEFAULT 0,
    loading REAL NOT NULL DEFAULT 0,
    output_kg REAL NOT NULL DEFAULT 0,
    output_kgh REAL NOT NULL DEFAULT 0,
    output_max_load_kgh REAL NOT NULL DEFAULT 0,
    running_time REAL NOT NULL DEFAULT 0,
    running_time_kgh REAL NOT NULL DEFAULT 0,
    import_log_id INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (dyelot, machine, start_time),
    FOREIGN KEY (import_log_id) REFERENCES import_logs (id)
);
CREATE INDEX IF NOT EXISTS idx_performance_start_time ON performance_logs (start_time);

-- Daily Rollup Pattern (xem memory-bank/systemPatterns.md) — mỗi Engine sở hữu 1 bảng
-- summary riêng, tính trước theo production_date qua recompute_daily(), đọc báo cáo chỉ
-- SELECT từ đây thay vì quét lại raw data mỗi lần đổi filter.
CREATE TABLE IF NOT EXISTS downtime_daily_summary (
    production_date TEXT NOT NULL,
    capacity_kg REAL NOT NULL,
    fabric_type TEXT NOT NULL DEFAULT '',
    brand_program TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL,
    hours REAL NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (production_date, capacity_kg, fabric_type, brand_program, category)
);
CREATE INDEX IF NOT EXISTS idx_downtime_daily_summary_date ON downtime_daily_summary (production_date);

-- Annotation THỦ CÔNG riêng cho 1 mẻ (case) trong danh sách drill-down "Downtime by
-- Category" — KHÔNG ghi đè dữ liệu gốc (`availability_logs`), chỉ lưu Reason/Detail người
-- dùng tự nhập. Khoá theo `availability_logs.id` (mẻ trong danh sách drill-down lấy từ
-- `availability_logs`, KHÔNG phải `downtime_logs` — bảng đó chưa được nối vào pipeline
-- báo cáo thật, xem systemPatterns.md). Tối đa 1 note/mẻ (UNIQUE), sửa lại thì UPSERT,
-- KHÔNG lưu lịch sử nhiều phiên bản.
CREATE TABLE IF NOT EXISTS downtime_case_notes (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    availability_log_id  INTEGER NOT NULL REFERENCES availability_logs (id) ON DELETE CASCADE,
    reason               TEXT,
    detail               TEXT,
    updated_by           INTEGER NOT NULL REFERENCES users (id),
    updated_at           TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (availability_log_id)
);
CREATE INDEX IF NOT EXISTS idx_downtime_case_notes_log ON downtime_case_notes (availability_log_id);

-- Tử số: đếm số mẻ theo (production_date, fabric_type, color_group, capacity_kg).
-- Mẫu số (operating_hours, bản THỨ 3 — xem systemPatterns.md mục 6.2): giờ hoạt động của
-- ĐÚNG TẬP MÁY đã chạy các mẻ thuộc ô này (bao gồm cả giờ chạy màu/vải KHÁC của chính các
-- máy đó trong ngày, prorate theo ranh giới 7h sáng) — KHÔNG phải giờ dùng chung toàn bảng.
-- Total(Fabric)/Grand Total KHÔNG được cộng thẳng cột này qua nhiều dòng ColorGroup (đếm
-- trùng giờ nếu 1 máy chạy nhiều màu/ngày) — build_matrix() phải truy vấn lại raw data để
-- khử trùng máy ở 2 cấp gộp đó.
CREATE TABLE IF NOT EXISTS batch_matrix_daily_summary (
    production_date TEXT NOT NULL,
    fabric_type TEXT NOT NULL,
    color_group TEXT NOT NULL,
    capacity_kg REAL NOT NULL,
    batch_count INTEGER NOT NULL DEFAULT 0,
    operating_hours REAL NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (production_date, fabric_type, color_group, capacity_kg)
);
CREATE INDEX IF NOT EXISTS idx_batch_matrix_daily_summary_date ON batch_matrix_daily_summary (production_date);

CREATE TABLE IF NOT EXISTS batch_matrix_targets (
    fabric_type TEXT NOT NULL,
    color_group TEXT NOT NULL,
    target_value REAL NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (fabric_type, color_group)
);

-- Grain theo TỪNG MẺ (1 dòng = 1 availability_logs.id đã JOIN + phân loại badge sẵn) —
-- KHÁC downtime/batch_matrix: Cleaning MC hiển thị chi tiết từng mẻ theo trình tự (lịch
-- máy dạng chuỗi badge), không phải số liệu đã gộp, nên không rollup được dưới dạng đếm.
CREATE TABLE IF NOT EXISTS cleaning_mc_daily_summary (
    production_date TEXT NOT NULL,
    availability_log_id INTEGER NOT NULL,
    machine TEXT NOT NULL,
    capacity_kg REAL NOT NULL DEFAULT 0,
    configured_capacity_kg REAL,
    machine_code TEXT,
    mc_brand TEXT,
    tank_type TEXT,
    mc_quantity INTEGER,
    tube_no TEXT,
    sequence_order TEXT,
    batch_no TEXT,
    dyelot_ref TEXT,
    shade_raw TEXT,
    colour_no TEXT,
    batch_type TEXT,
    start_time TEXT,
    end_time TEXT,
    program TEXT,
    badge TEXT NOT NULL,
    is_rework INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (production_date, availability_log_id)
);
CREATE INDEX IF NOT EXISTS idx_cleaning_mc_daily_summary_date ON cleaning_mc_daily_summary (production_date);

CREATE TABLE IF NOT EXISTS import_log_rows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    import_log_id INTEGER NOT NULL,
    row_number INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'valid',
    error_message TEXT,
    row_data TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (import_log_id) REFERENCES import_logs (id)
);
CREATE INDEX IF NOT EXISTS idx_import_log_rows_log_id ON import_log_rows (import_log_id);
"""

MACHINES = [
    ("DY-01", "Máy Nhuộm Jet #1", 120.0),
    ("DY-02", "Máy Nhuộm Jet #2", 120.0),
    ("DY-03", "Máy Nhuộm Cao Áp #1", 100.0),
    ("DY-04", "Máy Nhuộm Cao Áp #2", 100.0),
    ("DY-05", "Máy Nhuộm Winch #1", 90.0),
]

DOWNTIME_REASONS = [
    ("DT01", "Chờ nguyên liệu", "Kho chưa cấp đủ hoá chất/thuốc nhuộm cho mẻ tiếp theo."),
    ("DT02", "Bảo trì đột xuất", "Máy báo lỗi cảm biến nhiệt độ, kỹ thuật xử lý tại chỗ."),
    ("DT03", "Đổi màu / vệ sinh máy", "Vệ sinh bồn trước khi chạy mẻ màu sáng."),
    ("DT04", "Mất điện", "Mất điện lưới khu vực, không có máy phát dự phòng."),
    ("DT05", "Chờ nhân công", "Thiếu ca trực do đổi ca."),
]


def create_schema(conn) -> None:
    conn.executescript(SCHEMA_SQL)
    # Các cột này bổ sung cho database Phase 1 đã tồn tại.
    import_log_columns = {row["name"] for row in conn.execute("PRAGMA table_info(import_logs)")}
    if "imported_rows" not in import_log_columns:
        conn.execute("ALTER TABLE import_logs ADD COLUMN imported_rows INTEGER NOT NULL DEFAULT 0")
    if "file_type" not in import_log_columns:
        conn.execute("ALTER TABLE import_logs ADD COLUMN file_type TEXT")
    if "created_at" not in import_log_columns:
        conn.execute("ALTER TABLE import_logs ADD COLUMN created_at TEXT")
    availability_columns = {row["name"] for row in conn.execute("PRAGMA table_info(availability_logs)")}
    machine_columns = {row["name"] for row in conn.execute("PRAGMA table_info(machines)")}
    machine_additions = {
        "machine_code": "TEXT", "mc_brand": "TEXT", "tank_type": "TEXT",
        "mc_quantity": "INTEGER NOT NULL DEFAULT 1", "tube_no": "INTEGER", "capacity_kg": "REAL",
    }
    for column, definition in machine_additions.items():
        if column not in machine_columns:
            conn.execute(f"ALTER TABLE machines ADD COLUMN {column} {definition}")
    conn.execute("UPDATE machines SET machine_code = machine_id WHERE machine_code IS NULL OR TRIM(machine_code) = ''")
    if "entry_type" not in availability_columns:
        conn.execute("ALTER TABLE availability_logs ADD COLUMN entry_type TEXT NOT NULL DEFAULT 'IMPORT'")
    additions = {
        "production_date": "TEXT", "week_label": "TEXT", "month_label": "TEXT",
        "ach_load": "INTEGER", "ach_unload": "INTEGER", "ach_sample_check": "INTEGER",
        "ach_ph": "INTEGER", "ach_chemical": "INTEGER", "ach_color": "INTEGER",
        "ach_evaluated": "INTEGER NOT NULL DEFAULT 0", "ach_passed": "INTEGER NOT NULL DEFAULT 0",
        "ach_all_items": "INTEGER NOT NULL DEFAULT 0",
    }
    for column, definition in additions.items():
        if column not in availability_columns:
            conn.execute(f"ALTER TABLE availability_logs ADD COLUMN {column} {definition}")
        batch_columns = {row["name"] for row in conn.execute("PRAGMA table_info(batch_details)")}
        if "is_rework" not in batch_columns:
            conn.execute("ALTER TABLE batch_details ADD COLUMN is_rework INTEGER NOT NULL DEFAULT 0")
    conn.execute("UPDATE availability_logs SET batch_ref_no = batch WHERE batch_ref_no IS NULL OR TRIM(batch_ref_no) = ''")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_availability_batch_ref_machine_start ON availability_logs (batch_ref_no, machine, start_time)")
    conn.execute("UPDATE import_logs SET imported_rows = success_rows WHERE imported_rows = 0 AND success_rows > 0")
    conn.execute("UPDATE import_logs SET file_type = upper(import_type) WHERE file_type IS NULL")
    conn.execute("UPDATE import_logs SET created_at = imported_at WHERE created_at IS NULL")
    conn.commit()


def seed_users(conn) -> None:
    existing = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
    if existing:
        return
    conn.execute(
        "INSERT INTO users (username, password_hash, full_name, role) VALUES (?, ?, ?, ?)",
        ("admin", hash_password("admin123"), "Administrator", "admin"),
    )
    conn.execute(
        "INSERT INTO users (username, password_hash, full_name, role) VALUES (?, ?, ?, ?)",
        ("operator", hash_password("operator123"), "Operator", "operator"),
    )
    conn.commit()
    print("  - Seed users: admin/admin123, operator/operator123")


def seed_machines(conn) -> None:
    existing = conn.execute("SELECT COUNT(*) AS c FROM machines").fetchone()["c"]
    if existing:
        return
    conn.executemany(
        "INSERT INTO machines (machine_id, machine_name, domain, standard_speed) VALUES (?, ?, 'dyeing', ?)",
        MACHINES,
    )
    conn.commit()
    print(f"  - Seed {len(MACHINES)} máy nhuộm")


def seed_telemetry(conn, days: int = 7) -> None:
    existing = conn.execute("SELECT COUNT(*) AS c FROM machine_telemetry").fetchone()["c"]
    if existing:
        return

    rows: list[tuple] = []
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    start = now - timedelta(days=days)

    for machine_id, _name, std_speed in MACHINES:
        ts = start
        status = "RUNNING"
        while ts <= now:
            roll = random.random()
            if roll < 0.75:
                status = "RUNNING"
                actual_speed = round(std_speed * random.uniform(0.75, 1.05), 1)
                output = round(actual_speed * random.uniform(0.9, 1.1), 1)
            elif roll < 0.92:
                status = "STOPPED"
                actual_speed = 0.0
                output = 0.0
            else:
                status = "MAINTENANCE"
                actual_speed = 0.0
                output = 0.0

            rows.append(
                (ts.strftime("%Y-%m-%d %H:%M:%S"), machine_id, status, actual_speed, std_speed, output, None)
            )
            ts += timedelta(hours=1)

    conn.executemany(
        """
        INSERT INTO machine_telemetry
            (timestamp, machine_id, status, actual_speed, standard_speed, output_meters, import_log_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    print(f"  - Seed {len(rows)} dòng machine_telemetry ({days} ngày x {len(MACHINES)} máy)")


def seed_downtime(conn, count: int = 40) -> None:
    existing = conn.execute("SELECT COUNT(*) AS c FROM downtime_logs").fetchone()["c"]
    if existing:
        return

    now = datetime.now()
    rows = []
    for _ in range(count):
        machine_id = random.choice(MACHINES)[0]
        reason_code, reason_name, detail = random.choice(DOWNTIME_REASONS)
        ts = now - timedelta(hours=random.randint(1, 24 * 7))
        duration = round(random.uniform(10, 180), 1)
        rows.append((ts.strftime("%Y-%m-%d %H:%M:%S"), machine_id, reason_code, reason_name, duration, detail, None))

    conn.executemany(
        """
        INSERT INTO downtime_logs (timestamp, machine_id, reason_code, reason_name, duration_minutes, detail, import_log_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    print(f"  - Seed {count} dòng downtime_logs")


def seed_import_logs(conn) -> None:
    existing = conn.execute("SELECT COUNT(*) AS c FROM import_logs").fetchone()["c"]
    if existing:
        return
    conn.execute(
        """
        INSERT INTO import_logs (file_name, import_type, imported_by, total_rows, success_rows, error_rows, status)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("telemetry_template_demo.xlsx", "telemetry", "admin", 100, 98, 2, "partial"),
    )
    conn.commit()
    print("  - Seed 1 dòng import_logs mẫu")


def reset_database(db_path: Path) -> None:
    if db_path.exists():
        db_path.unlink()
        print(f"Đã xóa Database cũ: {db_path}")
    for suffix in ("-wal", "-shm"):
        side_file = db_path.with_name(db_path.name + suffix)
        if side_file.exists():
            side_file.unlink()


def main(reset: bool = False) -> None:
    Config.ensure_directories()
    db_path = Config.DATABASE_PATH

    if reset:
        reset_database(db_path)

    print(f"Khởi tạo Database tại: {db_path}")
    conn = get_raw_connection(db_path, pragmas=Config.SQLITE_PRAGMAS)
    try:
        create_schema(conn)
        print("Đã tạo schema (users, machines, machine_telemetry, downtime_logs, import_logs).")
        seed_users(conn)
        seed_machines(conn)
        seed_telemetry(conn)
        seed_downtime(conn)
        seed_import_logs(conn)
    finally:
        conn.close()

    print("Hoàn tất khởi tạo Database.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Khởi tạo Database cho CETVN IE DASHBOARD")
    parser.add_argument("--reset", action="store_true", help="Xóa Database cũ và tạo lại từ đầu")
    args = parser.parse_args()
    main(reset=args.reset)
