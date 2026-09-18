-- migrate_batch_day_trend_brand_program.sql
-- Chạy 1 LẦN thủ công qua Supabase SQL Editor trên project PRODUCTION đã có sẵn
-- bảng `batch_day_trend_daily_summary` (Daily Rollup của tab "Batch/Day Trend").
--
-- Lý do: thêm filter mới "Brand Program" vào tab Batch/Day Trend (2026-09-17, đồng bộ
-- với Downtime/Fabric-Color Matrix/Batch Per Day by Machine/Right First Time/%Tank
-- Loading). AN TOÀN thêm thẳng cột này (không đổi PRIMARY KEY) vì grain của bảng này là
-- 1 dòng = 1 mẻ đã resolve (không phải machine-hours dùng chung nhiều mẻ như
-- `batch_matrix_daily_summary.operating_hours`) — không có rủi ro cộng trùng khi lọc/gộp
-- theo brand_program.
--
-- AN TOÀN với dữ liệu cũ: các dòng đã có được gán brand_program='' (coi là "chưa phân
-- loại") — Total/Overview (không lọc Brand Program, tức "All") ra ĐÚNG số liệu cũ ngay
-- sau khi chạy migration này. Muốn tách đúng theo Brand Program cho dữ liệu LỊCH SỬ, chạy
-- lại `flask rebuild-summaries` sau khi áp migration này.
--
-- Idempotent: chạy lại nhiều lần không lỗi (IF NOT EXISTS).

begin;

alter table batch_day_trend_daily_summary
    add column if not exists brand_program text not null default '';

commit;

-- Sau khi chạy xong, backfill lại toàn bộ rollup để tách đúng theo Brand Program (chạy từ
-- máy có kết nối tới DATABASE_URL này):
--   flask rebuild-summaries
