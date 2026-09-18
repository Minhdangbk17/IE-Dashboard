-- migrate_cleaning_matrix_fabric_type.sql
-- Chạy 1 LẦN thủ công qua Supabase SQL Editor trên project PRODUCTION đã có sẵn
-- bảng `cleaning_mc_daily_summary` (Daily Rollup của báo cáo "Batch Per Day by Machine").
--
-- Lý do: thêm filter mới "Fabric Type" vào báo cáo này (2026-09-17, đồng bộ với Downtime/
-- Batch/Day/Right First Time/%Tank Loading). AN TOÀN thêm thẳng cột này (không đổi
-- PRIMARY KEY) vì grain của bảng này là 1 dòng = 1 mẻ (không phải số liệu đã gộp) — không
-- có rủi ro cộng trùng khi lọc theo fabric_type.
--
-- AN TOÀN với dữ liệu cũ: các dòng đã có được gán fabric_type=NULL — Total/Overview
-- (không lọc Fabric Type, tức "All") ra ĐÚNG số liệu cũ ngay sau khi chạy migration này.
-- Muốn tách đúng theo Fabric Type cho dữ liệu LỊCH SỬ, chạy lại `flask rebuild-summaries`
-- sau khi áp migration này.
--
-- Idempotent: chạy lại nhiều lần không lỗi (IF NOT EXISTS).

begin;

alter table cleaning_mc_daily_summary
    add column if not exists fabric_type text;

commit;

-- Sau khi chạy xong, backfill lại toàn bộ rollup để tách đúng theo Fabric Type (chạy từ
-- máy có kết nối tới DATABASE_URL này):
--   flask rebuild-summaries
