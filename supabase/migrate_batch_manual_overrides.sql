-- migrate_batch_manual_overrides.sql
-- Chạy 1 LẦN thủ công qua Supabase SQL Editor trên project PRODUCTION (2026-11-08), TRƯỚC khi deploy.
-- Bảng lưu BatchType / FabricType / Shade người dùng tự nhập cho mẻ có BatchType trống hoặc
-- "Unknown" (tab Data Quality của Batch Per Day by Machine), khoá theo (dyelot, machine, start_time).
-- Idempotent. Sau khi deploy chạy thêm `flask rebuild-summaries` (hoặc /admin/data-tools).

begin;

create table if not exists batch_manual_overrides (
    id bigserial primary key,
    dyelot text not null,
    machine text not null,
    start_time text not null,
    batch_type text not null,
    fabric_type text not null,
    shade text not null,
    updated_by text,
    updated_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
    unique (dyelot, machine, start_time)
);
alter table batch_manual_overrides enable row level security;

commit;
