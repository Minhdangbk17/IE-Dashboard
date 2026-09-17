-- migrate_batch_day_trend.sql
-- Chạy 1 LẦN thủ công qua Supabase SQL Editor trên project PRODUCTION đã deploy
-- TRƯỚC khi tab "Batch/Day Trend" (Engine batch_matrix) hoạt động đúng trên Postgres.
--
-- Ứng dụng KHÔNG tự CREATE TABLE trên Postgres theo quy ước dự án (xem
-- memory-bank/systemPatterns.md mục 5.1) — bảng mới `batch_day_trend_daily_summary`
-- phải được áp thủ công ở đây trước, nếu không route
-- GET /dyeing/batch_matrix/api/batch-day-trend sẽ lỗi "relation does not exist".
--
-- Idempotent: chạy lại nhiều lần không lỗi (IF NOT EXISTS ở mọi bước).

begin;

-- Grain = 1 dòng / 1 mẻ THẬT đã resolve (FabricType hợp lệ, đã cộng dồn carry-forward
-- từ các mẻ Unknown đứng trước cùng máy) — xem batch_day_trend.py module docstring để
-- biết vì sao không rollup được kiểu đếm đơn giản theo ngày như batch_matrix_daily_summary.
create table if not exists batch_day_trend_daily_summary (
    production_date text not null,
    machine text not null,
    start_time text not null,
    fabric_type text not null,
    capacity_kg double precision,
    hours double precision not null default 0,
    is_valid integer not null default 0,
    updated_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
    primary key (production_date, machine, start_time)
);
create index if not exists idx_batch_day_trend_daily_summary_date on batch_day_trend_daily_summary (production_date);

alter table batch_day_trend_daily_summary enable row level security;

commit;

-- Sau khi chạy xong, backfill dữ liệu lịch sử bằng 1 trong 2 cách:
--   1. Chạy `flask rebuild-summaries` từ máy có kết nối tới DATABASE_URL Supabase này, HOẶC
--   2. Gọi lại bất kỳ import Excel nào (Availability/Batch) trên môi trường đó — hook
--      trigger_recompute() sẽ tự tính lại đúng các production_date bị ảnh hưởng.
-- Trước khi chạy xong bước backfill, tab "Batch/Day Trend" sẽ hiển thị rỗng (không lỗi).

-- Kiểm tra sau khi chạy (không bắt buộc, chỉ để xác nhận):
-- select count(*) as total_rows, count(distinct production_date) as days from batch_day_trend_daily_summary;
