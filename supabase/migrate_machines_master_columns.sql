-- migrate_machines_master_columns.sql
-- Chạy 1 LẦN thủ công qua Supabase SQL Editor trên project PRODUCTION đã có sẵn
-- bảng `machines`.
--
-- Lý do (2026-09-22): báo cáo "Batch Per Day by Machine" đổi thiết kế — TRƯỚC ĐÂY danh
-- sách máy hiển thị tự phát hiện từ dữ liệu batch thật (availability_logs/batch_details),
-- khiến máy chưa có capacity_kg trong dữ liệu import bị ẩn khỏi báo cáo dù đã chạy mẻ
-- thật. `machines` giờ là "Machine Master" quản lý thủ công qua UI (nút "Add Machine" +
-- inline edit), cần thêm 4 cột mới: group_mc, status, production_status, orgatex.
--
-- Idempotent: chạy lại nhiều lần không lỗi (IF NOT EXISTS ở mọi bước).

begin;

alter table machines add column if not exists group_mc text;
alter table machines add column if not exists status text;
alter table machines add column if not exists production_status text;
alter table machines add column if not exists orgatex integer not null default 0;

commit;

-- Giá trị hợp lệ (production_status/orgatex validate ở tầng Python, status là text tự do —
-- xem PRODUCTION_STATUS_VALUES trong modules/dyeing/engines/reports/cleaning_matrix.py):
--   status:             text tự do (dữ liệu thật có Running/Will be removed/Uninstall/
--                       Removed/"Grouped to <machine>"/"Splitted into ...")
--   production_status:  'Sample' | 'Bulk' | 'No production'
--   orgatex:            0 (No) | 1 (Yes)
