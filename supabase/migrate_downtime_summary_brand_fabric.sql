-- migrate_downtime_summary_brand_fabric.sql
-- Chạy 1 LẦN thủ công qua Supabase SQL Editor trên project PRODUCTION đã có sẵn
-- bảng `downtime_daily_summary` (Daily Rollup của báo cáo Downtime).
--
-- Lý do: thêm 2 filter mới "Fabric Type"/"Brand Program" vào báo cáo Downtime
-- (2026-09-17, đồng bộ với "Batch Per Day by Machine"/"Right First Time"/
-- "%Tank Loading") — grain của bảng rollup phải mở rộng từ
-- (production_date, capacity_kg, category) sang
-- (production_date, capacity_kg, fabric_type, brand_program, category) để lọc
-- đúng theo 2 chiều mới mà KHÔNG phải quét lại raw data mỗi lần đổi filter.
--
-- AN TOÀN với dữ liệu cũ: các dòng đã có được gán fabric_type=''/brand_program=''
-- (coi là "chưa phân loại") — Total/Overview (không lọc theo 2 chiều mới, tức
-- "All") vẫn ra ĐÚNG số liệu cũ ngay sau khi chạy migration này. Muốn tách đúng
-- theo Fabric Type/Brand Program cho dữ liệu LỊCH SỬ, BẮT BUỘC chạy lại
-- `flask rebuild-summaries` sau khi áp migration này (xoá + tính lại toàn bộ
-- downtime_daily_summary từ availability_logs, cùng lệnh đã dùng cho các lần
-- đổi công thức rollup trước đây).
--
-- Idempotent: chạy lại nhiều lần không lỗi (IF NOT EXISTS / IF EXISTS ở mọi bước).

begin;

alter table downtime_daily_summary
    add column if not exists fabric_type text not null default '';
alter table downtime_daily_summary
    add column if not exists brand_program text not null default '';

-- Tên constraint mặc định Postgres tự sinh cho `primary key (production_date,
-- capacity_kg, category)` khai báo trong supabase/schema.sql bản cũ (không đặt
-- tên riêng lúc tạo bảng).
alter table downtime_daily_summary
    drop constraint if exists downtime_daily_summary_pkey;

alter table downtime_daily_summary
    add constraint downtime_daily_summary_pkey
    primary key (production_date, capacity_kg, fabric_type, brand_program, category);

commit;

-- Sau khi chạy xong, backfill lại toàn bộ rollup để tách đúng theo Fabric Type/
-- Brand Program (chạy từ máy có kết nối tới DATABASE_URL này):
--   flask rebuild-summaries
--
-- Kiểm tra sau khi chạy (không bắt buộc, chỉ để xác nhận):
-- select production_date, capacity_kg, fabric_type, brand_program, category, hours
-- from downtime_daily_summary order by production_date desc limit 20;
