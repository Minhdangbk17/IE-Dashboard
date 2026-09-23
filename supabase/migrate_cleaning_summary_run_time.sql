-- migrate_cleaning_summary_run_time.sql
-- Chạy 1 LẦN thủ công qua Supabase SQL Editor trên project PRODUCTION đã có sẵn
-- bảng `cleaning_mc_daily_summary`.
--
-- Lý do (2026-09-24): thêm 2 dòng mới "Plan PRD time"/"Batch/day (Plan PRD)" vào tab
-- Summary ("Batch Per Day by Machine") — "Plan PRD time" = Sum(RunTime) của MỌI mẻ (CM/wash +
-- Normal + Rework) / 3600 quy đổi ra giờ. `RunTime` (giây) đã có sẵn trong `batch_details`
-- (cột `run_time`, import từ file Batch Detail từ trước), nhưng bảng rollup
-- `cleaning_mc_daily_summary` (đọc bởi cả 2 tab Detail/Summary) CHƯA từng lưu cột này —
-- cần thêm cột mới rồi backfill lại toàn bộ lịch sử.
--
-- Idempotent: chạy lại nhiều lần không lỗi (IF NOT EXISTS).

begin;

alter table cleaning_mc_daily_summary add column if not exists run_time double precision not null default 0;

commit;

-- Sau khi chạy xong, BẮT BUỘC backfill lại toàn bộ rollup để "Plan PRD time" có giá trị
-- thật cho dữ liệu lịch sử (nếu không chạy, mọi ngày CŨ trước khi chạy lệnh này sẽ hiện
-- Plan PRD time = 0 dù RunTime thật đã có sẵn trong batch_details) — chạy từ máy có kết nối
-- tới DATABASE_URL này:
--   flask rebuild-summaries
