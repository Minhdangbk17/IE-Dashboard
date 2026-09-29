-- migrate_batch_day_trend_redye.sql
-- Chạy 1 LẦN thủ công qua Supabase SQL Editor trên project PRODUCTION đã có sẵn
-- bảng `batch_day_trend_daily_summary`.
--
-- Lý do (2026-09-29): tab "Batch/Day Trend" thêm checkbox "ReDye = 0" (bật/tắt điều kiện
-- ReDye = 0 của Normal dyeing batch, giống báo cáo "Batch Per Day by Machine"). Cột mới
-- `is_valid_any_redye` lưu sẵn số mẻ Normal KHÔNG xét ReDye, để checkbox đổi NGAY TẠI READ TIME
-- (không phải chạy lại recompute, dễ timeout serverless).
--
-- Idempotent: chạy lại nhiều lần không lỗi (IF NOT EXISTS).

begin;

alter table batch_day_trend_daily_summary add column if not exists is_valid_any_redye integer not null default 0;

commit;

-- Sau khi chạy xong, BẮT BUỘC backfill lại toàn bộ rollup (cũng cần cho công thức Trend mới
-- 2026-09-29 — nguồn batch_details, Occupied Hours tách 07:00->07:00):
--   flask rebuild-summaries
-- Hoặc dùng trang /admin/data-tools (giới hạn From/To Date nếu dữ liệu lớn).
