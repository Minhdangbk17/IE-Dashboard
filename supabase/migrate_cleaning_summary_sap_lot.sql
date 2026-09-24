-- migrate_cleaning_summary_sap_lot.sql
-- Chạy 1 LẦN thủ công qua Supabase SQL Editor trên project PRODUCTION đã có sẵn
-- bảng `cleaning_mc_daily_summary`.
--
-- Lý do (2026-09-24): thêm bộ lọc "SapLot = 1"/"SapLot = 3" (SapLot bắt đầu bằng ký tự "1"
-- hoặc "3") cho CẢ 2 tab Detail/Summary của báo cáo "Batch Per Day by Machine" — người dùng
-- đã tự đối chiếu raw data và xác nhận công thức Normal/Rework hiện tại ĐÚNG, chỉ cần thêm
-- bộ lọc thu hẹp tập mẻ được tính theo SapLot, KHÔNG đổi cách phân loại is_rework (khác với
-- nút "Ignore SapLot" đã có, xem migrate_cleaning_summary_run_time.sql cho bối cảnh trước).
-- `SapLot` (text, VD "10123", "30456") đã có sẵn trong `batch_details` (cột `sap_lot`, import
-- từ file Batch Detail từ trước), nhưng bảng rollup `cleaning_mc_daily_summary` (đọc bởi cả
-- 2 tab) CHƯA từng lưu cột này — cần thêm cột mới rồi backfill lại toàn bộ lịch sử.
--
-- Idempotent: chạy lại nhiều lần không lỗi (IF NOT EXISTS).

begin;

alter table cleaning_mc_daily_summary add column if not exists sap_lot text;

commit;

-- Sau khi chạy xong, BẮT BUỘC backfill lại toàn bộ rollup để bộ lọc SapLot có giá trị thật
-- cho dữ liệu lịch sử (nếu không chạy, mọi ngày CŨ trước khi chạy lệnh này sẽ có sap_lot NULL
-- dù SapLot thật đã có sẵn trong batch_details, khiến bộ lọc loại bỏ nhầm các dòng đó) — chạy
-- từ máy có kết nối tới DATABASE_URL này:
--   flask rebuild-summaries
