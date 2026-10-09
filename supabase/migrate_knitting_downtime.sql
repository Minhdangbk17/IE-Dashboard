-- migrate_knitting_downtime.sql
-- Chạy 1 LẦN thủ công qua Supabase SQL Editor trên project PRODUCTION — tạo 2 bảng của Engine
-- mới `knitting.downtime` (file "CET-Stop Reason Analysis by Machine"). Ở SQLite app tự tạo
-- (`modules/knitting/engines/downtime/service.py::ensure_tables()`).
--
-- knitting_machine_daily: 1 dòng = 1 máy x 1 production_date (Efficiency/Times/Rev/Output).
-- knitting_stop_details:  1 dòng = 1 máy x 1 mã dừng x 1 production_date.
-- knitting_stop_category_map: Stop Code -> nhóm downtime do admin ghi đè.
-- knitting_downtime_targets:  Before / Target % theo nhóm (seed bên dưới).
-- knitting_piece_rolls: Piece Produced report (1 dòng = 1 cuộn, khoá Roll No) — nguồn Greige ID
--   của từng máy-ngày cho bộ lọc Program.
-- knitting_greige_programs / knitting_core_programs: file Knitting program.xlsx.
--
-- Không đụng bảng nào đã có, không cần `flask rebuild-summaries`. Idempotent.

begin;

create table if not exists knitting_machine_daily (
    id                   bigint generated always as identity primary key,
    production_date      text not null,
    machine_code         text not null,
    job_mc_spec          text,
    knitting_structure   text,
    machine_efficiency   double precision,
    operator_efficiency  double precision,
    available_time       double precision,
    run_time             double precision,
    total_stop_time      double precision,
    revolutions          double precision,
    actual_speed         double precision,
    total_production     double precision,
    period_start         text not null,
    period_end           text not null,
    import_log_id        bigint,
    created_at           text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
    unique (production_date, machine_code)
);

create table if not exists knitting_stop_details (
    id                bigint generated always as identity primary key,
    production_date   text not null,
    machine_code      text not null,
    stop_code         text not null,
    stop_description  text,
    stop_color        bigint,
    stop_time         double precision,
    stop_count        double precision,
    loss_ratio        double precision,
    avg_stop_time     double precision,
    import_log_id     bigint,
    created_at        text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
    unique (production_date, machine_code, stop_code)
);
create index if not exists idx_knitting_stop_details_code on knitting_stop_details (stop_code, production_date);

create table if not exists knitting_stop_category_map (
    stop_code   text primary key,
    category    text not null,
    updated_by  text,
    updated_at  text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

create table if not exists knitting_downtime_targets (
    category    text primary key,
    before_pct  double precision,
    target_pct  double precision,
    updated_by  text,
    updated_at  text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

-- Before / 2026 Target (%) theo bảng người dùng 2026-10-09 (app SQLite tự seed khi bảng rỗng).
insert into knitting_downtime_targets (category, before_pct, target_pct, updated_by) values
    ('Doffing + Cleaning', 7.5, 5.5, 'seed'), ('Yarn Broken', 6.5, 4.5, 'seed'),
    ('No Material', 0.8, 0.4, 'seed'), ('Loading/Unloading Yarn', 0.6, 0.5, 'seed'),
    ('Needle Broken', 0.6, 0.4, 'seed'), ('MC Part Broken', 0.4, 0.3, 'seed'),
    ('MC Adjustment', 0.4, 0.3, 'seed'), ('Needle Cleaning', 0.8, 0.5, 'seed'),
    ('Safe Door', 5.0, 1.5, 'seed'), ('MC Set Up', 2.0, 0.5, 'seed'),
    ('Cleaning (Scheduled)', 0.0, 0.8, 'seed'), ('Drop stitch', 0.0, 0.3, 'seed'),
    ('Others', 1.0, 0.8, 'seed')
on conflict (category) do nothing;

create table if not exists knitting_piece_rolls (
    roll_no             text primary key,
    machine_group       text,
    machine             text,
    machine_code        text not null,
    job_id              text,
    sap_lot             text,
    sale_order          text,
    material_type       text,
    knitting_structure  text,
    greige_id           text not null,
    available           double precision,
    running             double precision,
    stopped             double precision,
    total_qty           double precision,
    good_qty            double precision,
    record_start        text not null,
    record_end          text not null,
    import_log_id       bigint,
    updated_at          text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);
create index if not exists idx_knitting_piece_rolls_span on knitting_piece_rolls (record_end, record_start);

create table if not exists knitting_greige_programs (
    greige_code    text primary key,
    program        text not null,
    program_key    text not null,
    import_log_id  bigint
);

create table if not exists knitting_core_programs (
    program_key    text primary key,
    program        text not null,
    import_log_id  bigint
);

alter table knitting_machine_daily enable row level security;
alter table knitting_stop_details enable row level security;
alter table knitting_stop_category_map enable row level security;
alter table knitting_downtime_targets enable row level security;
alter table knitting_piece_rolls enable row level security;
alter table knitting_greige_programs enable row level security;
alter table knitting_core_programs enable row level security;

commit;
