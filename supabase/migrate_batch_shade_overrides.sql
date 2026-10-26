-- migrate_batch_shade_overrides.sql
-- Chạy 1 LẦN thủ công qua Supabase SQL Editor trên project PRODUCTION (2026-10-26).
-- Bảng lưu Shade người dùng tự nhập cho mẻ "Unclassified" của Fabric/Color Matrix (Engine
-- `batch_matrix`), khoá theo Dyelot. Idempotent.

begin;

create table if not exists batch_shade_overrides (
    dyelot text primary key,
    shade text not null,
    updated_by text,
    updated_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);
alter table batch_shade_overrides enable row level security;

commit;
