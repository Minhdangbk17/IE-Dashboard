-- migrate_cleaning_summary_redye.sql
-- Chạy 1 LẦN thủ công qua Supabase SQL Editor trên project PRODUCTION đã có sẵn
-- bảng `cleaning_mc_daily_summary`.
--
-- Lý do (2026-09-25): thay THẾ HOÀN TOÀN công thức phân loại CM/Normal/Rework của báo cáo
-- "Batch Per Day by Machine" (CẢ 2 tab Detail/Summary) — Normal dyeing batch giờ đòi hỏi
-- Dyelot kết thúc "0" + SapLot bắt đầu "1"/"3" + (tuỳ chọn qua checkbox "ReDye = 0" trên UI,
-- mặc định BẬT) ReDye = 0. `ReDye` (số, đã có sẵn trong `batch_details.redye` từ import Batch
-- Detail trước đó) trước đây CHƯA từng được đưa vào rollup `cleaning_mc_daily_summary` — cần
-- thêm cột mới để checkbox có thể TẮT/BẬT điều kiện này NGAY TẠI READ TIME (không phải chạy
-- lại recompute_daily(), tốn kém/dễ timeout serverless) rồi backfill lại toàn bộ lịch sử.
--
-- Idempotent: chạy lại nhiều lần không lỗi (IF NOT EXISTS).

begin;

alter table cleaning_mc_daily_summary add column if not exists redye double precision not null default 0;

commit;

-- Sau khi chạy xong, BẮT BUỘC backfill lại toàn bộ rollup — nếu không, mọi ngày CŨ trước khi
-- chạy migration này sẽ có `badge`/`is_rework` tính theo QUY TẮC CŨ (Dyelot/SapLot đơn thuần,
-- không CM theo "CL*", không có Sample, không có ReDye) thay vì quy tắc MỚI, VÀ có redye=0
-- mặc định dù ReDye thật trong batch_details có thể khác 0 — chạy từ máy có kết nối tới
-- DATABASE_URL này:
--   flask rebuild-summaries
-- Hoặc dùng trang /admin/data-tools (chạy trên server, không cần máy bạn kết nối thẳng DB) —
-- nếu dữ liệu lớn, giới hạn From/To Date để chạy theo từng đợt tránh timeout serverless.
