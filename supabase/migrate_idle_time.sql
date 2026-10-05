-- migrate_idle_time.sql
-- Chạy 1 LẦN thủ công qua Supabase SQL Editor trên project PRODUCTION (2026-10-05) — tạo 2
-- bảng của Engine mới `idle_time` (báo cáo Idle Time). Ở SQLite app tự tạo
-- (`modules/dyeing/engines/idle_time/service.py::_ensure_tables()`).
--
-- idle_time_notes: Reason/Detail nhập tay cho TỪNG khoảng idle (khoá machine + gap_start).
-- idle_time_settings: cấu hình dạng key/value — hiện chỉ có `target_idle_pct`.
--
-- Không đụng bảng nào đã có, không cần `flask rebuild-summaries` (báo cáo đọc lại
-- `batch_day_trend_daily_summary`). Idempotent: chạy lại nhiều lần không lỗi.

begin;

create table if not exists idle_time_notes (
    id               bigint generated always as identity primary key,
    machine          text not null,
    production_date  text not null,
    gap_start        text not null,
    gap_end          text not null,
    reason           text,
    detail           text,
    updated_by       bigint not null references users (id),
    updated_at       text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
    unique (machine, gap_start)
);
create index if not exists idx_idle_time_notes_date on idle_time_notes (production_date);

create table if not exists idle_time_settings (
    key         text primary key,
    value       double precision not null,
    updated_at  text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

alter table idle_time_notes enable row level security;
alter table idle_time_settings enable row level security;

commit;
