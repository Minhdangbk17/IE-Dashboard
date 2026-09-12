-- =============================================================================
-- supabase/schema.sql — PostgreSQL translation of the MES Dashboard schema
-- =============================================================================
-- REFERENCE ONLY — NOT YET EXECUTED BY THE APPLICATION.
--
-- The running app (init_db.py + core/database.py) currently targets SQLite
-- exclusively: every query in every Engine's service.py uses the sqlite3
-- module directly with "?" placeholders, SQLite-only functions (PRAGMA
-- table_info, the datetime()/julianday() family), and SQLite's dynamic typing.
-- This file is a faithful structural translation of that schema (see
-- init_db.py::SCHEMA_SQL, the single source of truth) so the database
-- definition lives in version control and can be applied to a Supabase
-- project ahead of an actual data-access-layer migration.
--
-- Applying this file to Supabase does NOT make the Flask app work against it.
-- That requires rewriting core/database.py's connection layer plus every
-- raw-SQL query across modules/*/engines/*/service.py (placeholder style,
-- PRAGMA-based introspection, SQLite string functions) to a Postgres client
-- (e.g. psycopg2/asyncpg) — a separate, much larger piece of work.
--
-- Timestamps are kept as TEXT in "YYYY-MM-DD HH:MM:SS" format (via
-- to_char(now(), ...)) instead of native TIMESTAMPTZ, to match the string
-- format the Python code parses today (datetime.strptime with that exact
-- format) — this avoids silently changing comparison/parsing semantics if
-- this schema is adopted before the query layer is rewritten.
-- =============================================================================

create table if not exists users (
    id            bigint generated always as identity primary key,
    username      text not null unique,
    password_hash text not null,
    full_name     text not null,
    role          text not null check (role in ('admin', 'operator')),
    created_at    text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

-- Per-Engine Xem/Sửa/Xoá permissions for role='operator'. admin is always a
-- fixed superuser and never goes through this table (see core/auth.py).
create table if not exists user_permissions (
    id            bigint generated always as identity primary key,
    user_id       bigint not null references users(id) on delete cascade,
    domain        text not null,
    engine_name   text not null,
    can_view      integer not null default 0 check (can_view in (0,1)),
    can_edit      integer not null default 0 check (can_edit in (0,1)),
    can_delete    integer not null default 0 check (can_delete in (0,1)),
    unique (user_id, domain, engine_name)
);

create table if not exists machines (
    id             bigint generated always as identity primary key,
    machine_id     text not null unique,
    machine_name   text not null,
    domain         text not null default 'dyeing',
    standard_speed double precision not null default 100.0,
    machine_code   text,
    mc_brand       text,
    tank_type      text,
    mc_quantity    integer not null default 1,
    tube_no        integer,
    capacity_kg    double precision,
    is_active      integer not null default 1
);
create index if not exists idx_machines_code_norm on machines (lower(trim(coalesce(machine_code, machine_id))));

-- Note: import_logs is created here (ahead of machine_telemetry/downtime_logs,
-- which reference it) because — unlike SQLite's executescript(), which does not
-- validate FK targets at CREATE TABLE time — Postgres requires the referenced
-- table to already exist.
create table if not exists import_logs (
    id              bigint generated always as identity primary key,
    file_name       text not null,
    import_type     text not null,          -- 'telemetry' | 'downtime'
    imported_by     text not null,
    total_rows      integer not null default 0,
    success_rows    integer not null default 0,
    error_rows      integer not null default 0,
    status          text not null default 'completed',  -- 'completed' | 'failed' | 'partial'
    error_detail    text,
    imported_at     text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
    imported_rows   integer not null default 0,
    file_type       text,
    created_at      text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

create table if not exists machine_telemetry (
    id             bigint generated always as identity primary key,
    timestamp      text not null,
    machine_id     text not null,
    status         text not null check (status in ('RUNNING', 'STOPPED', 'MAINTENANCE')),
    actual_speed   double precision not null default 0,
    standard_speed double precision not null default 0,
    output_meters  double precision not null default 0,
    import_log_id  bigint,
    created_at     text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
    foreign key (import_log_id) references import_logs (id)
);
create index if not exists idx_telemetry_machine_time on machine_telemetry (machine_id, timestamp);

create table if not exists downtime_logs (
    id               bigint generated always as identity primary key,
    timestamp        text not null,
    machine_id       text not null,
    reason_code      text not null,
    reason_name      text not null,
    duration_minutes double precision not null,
    detail           text,
    import_log_id    bigint,
    created_at       text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
    foreign key (import_log_id) references import_logs (id)
);
create index if not exists idx_downtime_machine_time on downtime_logs (machine_id, timestamp);

create table if not exists availability_logs (
    id bigint generated always as identity primary key,
    batch text not null,
    batch_ref_no text not null,
    entry_type text not null default 'IMPORT',
    fabric_type text,
    brand_name text,
    machine text not null,
    capacity_kg double precision not null default 0,
    program text,
    start_time text not null,
    end_time text,
    production_date text,
    week_label text,
    month_label text,
    availability_pct double precision not null default 0,
    -- Hour-unit group (suffix _hour)
    total_op_time_cal_hour double precision not null default 0,
    planned_prd_time_hour double precision not null default 0,
    no_order_hour double precision not null default 0,
    testing_sample_order_hour double precision not null default 0,
    running_time_hour double precision not null default 0,
    total_downtime_hour double precision not null default 0,
    rework_hour double precision not null default 0,
    adjust_color_hour double precision not null default 0,
    bleaching_hour double precision not null default 0,
    load_hour double precision not null default 0,
    unload_hour double precision not null default 0,
    testing_bulk_order_hour double precision not null default 0,
    sample_checking_hour double precision not null default 0,
    ph_checking_hour double precision not null default 0,
    wait_chemical_load_hour double precision not null default 0,
    wait_color_load_hour double precision not null default 0,
    wait_fabric_hour double precision not null default 0,
    wait_water_hour double precision not null default 0,
    wait_steam_hour double precision not null default 0,
    cleaning_hour double precision not null default 0,
    maintenance_hour double precision not null default 0,
    others_hour double precision not null default 0,
    -- Output-per-hour group (suffix _kgh) — parallel to the _hour group above
    total_op_time_cal_kgh double precision not null default 0,
    planned_prd_time_kgh double precision not null default 0,
    no_order_kgh double precision not null default 0,
    testing_sample_order_kgh double precision not null default 0,
    running_time_kgh double precision not null default 0,
    total_downtime_kgh double precision not null default 0,
    rework_kgh double precision not null default 0,
    adjust_color_kgh double precision not null default 0,
    bleaching_kgh double precision not null default 0,
    load_kgh double precision not null default 0,
    unload_kgh double precision not null default 0,
    testing_bulk_order_kgh double precision not null default 0,
    sample_checking_kgh double precision not null default 0,
    ph_checking_kgh double precision not null default 0,
    wait_chemical_load_kgh double precision not null default 0,
    wait_color_load_kgh double precision not null default 0,
    wait_fabric_kgh double precision not null default 0,
    wait_water_kgh double precision not null default 0,
    wait_steam_kgh double precision not null default 0,
    cleaning_kgh double precision not null default 0,
    maintenance_kgh double precision not null default 0,
    others_kgh double precision not null default 0,
    ach_load integer,
    ach_unload integer,
    ach_sample_check integer,
    ach_ph integer,
    ach_chemical integer,
    ach_color integer,
    ach_evaluated integer not null default 0,
    ach_passed integer not null default 0,
    ach_all_items integer not null default 0,
    import_log_id bigint,
    created_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
    unique (batch, machine, start_time),
    foreign key (import_log_id) references import_logs (id)
);
create index if not exists idx_availability_start_time on availability_logs (start_time);
create unique index if not exists uq_availability_batch_ref_machine_start
    on availability_logs (batch_ref_no, machine, start_time);
create index if not exists idx_availability_batch_norm on availability_logs (lower(trim(batch)));
create index if not exists idx_availability_batch_ref_norm on availability_logs (lower(trim(batch_ref_no)));

create table if not exists batch_details (
    dyelot text primary key,
    customer text, color text, order_no text, greige_code text, recipe_no text, colour_no text,
    shade text, customer_color text, is_rework integer not null default 0, machine text, machine_group text,
    fabric_code text, fabric_type text, fabric_content text,
    wo_qty text,
    batch_type text, batch_state text, formula_code text, formula_type text,
    process_type text, weight double precision not null default 0, redye double precision not null default 0,
    liquor_ratio double precision not null default 0,
    liquor_quantity double precision not null default 0,
    weight_per_area double precision not null default 0, greige_width double precision not null default 0,
    reel_speed double precision not null default 0, pump_speed double precision not null default 0,
    max_reel_speed double precision not null default 0,
    absorption double precision not null default 0, nozzle double precision not null default 0,
    sap_lot text, customer_code text, customer_po text,
    soft_water double precision not null default 0,
    hot_water double precision not null default 0, hard_water double precision not null default 0,
    mix_water double precision not null default 0,
    sum_water double precision not null default 0,
    water_per_kg double precision not null default 0, power double precision not null default 0,
    power_per_kg double precision not null default 0, heating_energy double precision not null default 0,
    steam_per_kg double precision not null default 0, dye_cost double precision not null default 0,
    chemical_cost double precision not null default 0, correction_cnt integer not null default 0,
    alarm_cnt double precision not null default 0, intervention_cnt double precision not null default 0,
    total_correction_cnt integer not null default 0,
    washing_correction text, dyestuff_correction text, chemical_correction text,
    schedule_time text, start_time text, end_time text, run_time double precision not null default 0,
    set_time double precision not null default 0, stop_time double precision not null default 0,
    operator_time double precision not null default 0,
    correction_time double precision not null default 0, manual_time double precision not null default 0,
    stop_alarm_time double precision not null default 0, hold_alarm_time double precision not null default 0,
    diff_time double precision not null default 0, percent double precision not null default 0,
    fuyang_request text,
    note1 text, note2 text, note3 text, note4 text, note5 text,
    import_log_id bigint, created_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);
create index if not exists idx_batch_details_dyelot_norm on batch_details (lower(trim(dyelot)));

create table if not exists performance_logs (
    id bigint generated always as identity primary key,
    dyelot text not null,
    brand_name text,
    machine text not null,
    machine_group text,
    max_capacity_pct double precision not null default 0,
    capacity double precision not null default 0,
    dyelot_ref_no text,
    fabric_type text,
    program text,
    redye text,
    sap_no text,
    pth double precision not null default 0,
    start_time text not null,
    end_time text,
    performance double precision not null default 0,
    speed double precision not null default 0,
    loading double precision not null default 0,
    output_kg double precision not null default 0,
    output_kgh double precision not null default 0,
    output_max_load_kgh double precision not null default 0,
    running_time double precision not null default 0,
    running_time_kgh double precision not null default 0,
    import_log_id bigint,
    created_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
    unique (dyelot, machine, start_time),
    foreign key (import_log_id) references import_logs (id)
);
create index if not exists idx_performance_start_time on performance_logs (start_time);

-- Daily Rollup Pattern: each Engine owns its own summary table, precomputed
-- per production_date, so reports SELECT from here instead of rescanning raw
-- data on every filter change.
create table if not exists downtime_daily_summary (
    production_date text not null,
    capacity_kg double precision not null,
    category text not null,
    hours double precision not null default 0,
    updated_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
    primary key (production_date, capacity_kg, category)
);
create index if not exists idx_downtime_daily_summary_date on downtime_daily_summary (production_date);

-- Manual annotation (Reason/Detail) for a single case in the "Downtime by
-- Category" / "Data Quality" drill-down lists. Does NOT overwrite the source
-- row in availability_logs. Keyed by availability_logs.id — NOT
-- downtime_logs.id (downtime_logs is unpopulated/not wired into reporting).
-- At most one note per case (UNIQUE); editing again UPSERTs the same row.
-- context: category ("Downtime by Category", vd 'Rework') hoặc field ("Data Quality",
-- 'loading'/'unloading') mà note này thuộc về — 1 mẻ (availability_log_id) có thể xuất
-- hiện ở nhiều category/field khác nhau, mỗi nơi cần note ĐỘC LẬP (xem
-- downtime/service.py mục "Downtime Case Notes" để biết lý do đổi UNIQUE constraint).
-- DB ĐÃ CÓ DỮ LIỆU THẬT (production): áp thay đổi này qua
-- supabase/migrate_case_notes_context.sql, KHÔNG chạy lại CREATE TABLE này.
create table if not exists downtime_case_notes (
    id                   bigint generated always as identity primary key,
    availability_log_id  bigint not null references availability_logs (id) on delete cascade,
    context              text not null default '',
    reason               text,
    detail               text,
    updated_by           bigint not null references users (id),
    updated_at           text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
    unique (availability_log_id, context)
);
create index if not exists idx_downtime_case_notes_log on downtime_case_notes (availability_log_id);

-- Numerator: batch count by (production_date, fabric_type, color_group, capacity_kg).
-- Denominator (operating_hours): operating hours of the exact machine set that
-- ran the batches in this cell — NOT hours shared across the whole table.
-- Total(Fabric)/Grand Total must NOT sum this column across ColorGroup rows
-- directly (double-counts hours if one machine ran multiple colors/day) — the
-- application re-queries raw data to de-duplicate machines at those rollup
-- levels (see build_matrix() in batch_matrix/service.py).
create table if not exists batch_matrix_daily_summary (
    production_date text not null,
    fabric_type text not null,
    color_group text not null,
    capacity_kg double precision not null,
    batch_count integer not null default 0,
    operating_hours double precision not null default 0,
    updated_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
    primary key (production_date, fabric_type, color_group, capacity_kg)
);
create index if not exists idx_batch_matrix_daily_summary_date on batch_matrix_daily_summary (production_date);

create table if not exists batch_matrix_targets (
    fabric_type text not null,
    color_group text not null,
    target_value double precision not null default 0,
    updated_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
    primary key (fabric_type, color_group)
);

-- Grain = one row per source record (1 row = 1 availability_logs.id, already
-- joined + badge-classified). Unlike downtime/batch_matrix, Cleaning MC shows
-- per-batch detail in sequence (not aggregated numbers), so it cannot be
-- rolled up as a plain count.
create table if not exists cleaning_mc_daily_summary (
    production_date text not null,
    availability_log_id bigint not null,
    machine text not null,
    capacity_kg double precision not null default 0,
    configured_capacity_kg double precision,
    machine_code text,
    mc_brand text,
    tank_type text,
    mc_quantity integer,
    tube_no text,
    sequence_order text,
    batch_no text,
    dyelot_ref text,
    shade_raw text,
    colour_no text,
    batch_type text,
    start_time text,
    end_time text,
    program text,
    badge text not null,
    is_rework integer not null default 0,
    updated_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
    primary key (production_date, availability_log_id)
);
create index if not exists idx_cleaning_mc_daily_summary_date on cleaning_mc_daily_summary (production_date);

create table if not exists import_log_rows (
    id bigint generated always as identity primary key,
    import_log_id bigint not null,
    row_number integer not null,
    status text not null default 'valid',
    error_message text,
    row_data text not null,
    created_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
    foreign key (import_log_id) references import_logs (id)
);
create index if not exists idx_import_log_rows_log_id on import_log_rows (import_log_id);

-- =============================================================================
-- Row Level Security — lock every table out of Supabase's public PostgREST API
-- (the anon/authenticated roles used by the auto-generated REST API and any
-- client-side Supabase SDK), even though this app never uses that API.
--
-- This Flask app talks to Postgres directly via DATABASE_URL/psycopg2 (see
-- core/database.py), using the connection role from that string (typically
-- the `postgres` role when the string comes straight from the Supabase
-- dashboard, or the role that owns these tables since they were created
-- through the SQL Editor as that role). Postgres RLS does NOT apply to a
-- table's owner (or any role with BYPASSRLS) by default, so enabling RLS
-- here does not affect the app's own queries at all.
--
-- What it DOES do: every Supabase project exposes a public REST endpoint
-- (https://<project>.supabase.co/rest/v1/...) the moment it exists, callable
-- with the project's `anon` key. Without RLS, anyone who ever obtains that
-- key (client-side leak, shared by mistake, etc.) could read/write ANY row
-- in ANY of these tables directly — completely bypassing the app's own
-- login/session/permission system in core/auth.py. Enabling RLS with ZERO
-- policies defined means "deny all" for every role except the owner — the
-- correct default here, since nothing should ever reach this data except
-- through the Flask app. If a legitimate need for direct PostgREST/client
-- access ever comes up, add explicit `CREATE POLICY ...` statements then —
-- don't leave tables open by default in the meantime.
-- =============================================================================
alter table users enable row level security;
alter table user_permissions enable row level security;
alter table machines enable row level security;
alter table import_logs enable row level security;
alter table machine_telemetry enable row level security;
alter table downtime_logs enable row level security;
alter table availability_logs enable row level security;
alter table batch_details enable row level security;
alter table performance_logs enable row level security;
alter table downtime_daily_summary enable row level security;
alter table downtime_case_notes enable row level security;
alter table batch_matrix_daily_summary enable row level security;
alter table batch_matrix_targets enable row level security;
alter table cleaning_mc_daily_summary enable row level security;
alter table import_log_rows enable row level security;
