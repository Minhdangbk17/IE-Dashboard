-- migrate_brand_program_mapping.sql
-- Chạy 1 LẦN thủ công qua Supabase SQL Editor trên project PRODUCTION đã deploy
-- TRƯỚC khi tính năng "Brand Program" (filter mới trên báo cáo Batch Per Day by
-- Machine) được thêm vào `supabase/schema.sql`.
--
-- Ứng dụng KHÔNG tự CREATE TABLE / ALTER TABLE trên Postgres theo quy ước dự án
-- (xem memory-bank/systemPatterns.md mục 5.1) — bảng mới `brand_program_mapping`
-- và 2 cột mới trên `cleaning_mc_daily_summary` phải được áp thủ công ở đây.
--
-- Idempotent: chạy lại nhiều lần không lỗi (IF NOT EXISTS / IF NOT EXISTS ở mọi bước).

begin;

create table if not exists brand_program_mapping (
    greige_code text primary key,
    item_code text,
    fabric_type text,
    brand_program text,
    brand text,
    import_log_id bigint,
    updated_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);
create index if not exists idx_brand_program_mapping_greige_norm on brand_program_mapping (lower(trim(greige_code)));

alter table cleaning_mc_daily_summary add column if not exists brand_program text;
alter table cleaning_mc_daily_summary add column if not exists brand text;

alter table brand_program_mapping enable row level security;

commit;

-- Kiểm tra sau khi chạy (không bắt buộc, chỉ để xác nhận):
-- select greige_code, brand, brand_program from brand_program_mapping order by updated_at desc limit 10;
