-- migrate_batch_details_primary_key.sql
-- Chạy 1 LẦN thủ công qua Supabase SQL Editor trên project PRODUCTION đã có sẵn
-- bảng `batch_details` (đã có dữ liệu thật). Chạy TRƯỚC khi deploy code app mới sử dụng
-- ON CONFLICT(dyelot, machine, start_time).
--
-- Lý do: bản đầu khoá `dyelot text primary key` — chỉ giữ được 1 dòng/Dyelot, nên khi 1 Dyelot
-- chạy lại thật (VD mẻ gốc bị NG rồi redye) thì lần import sau ghi đè MẤT dữ liệu lần chạy
-- trước (RecipeNo/FormulaCode/Weight/DyeCost...) thay vì lưu cả 2 lần chạy như 2 bản ghi riêng
-- (bug thật phát hiện qua mẻ C260659920 — xem memory-bank/activeContext.md). Migration này đổi
-- sang `id` surrogate primary key + UNIQUE(dyelot, machine, start_time) — mỗi lần chạy thật của
-- 1 Dyelot (khác machine hoặc khác start_time) giờ là 1 dòng riêng, không còn ghi đè nhau.
--
-- AN TOÀN với dữ liệu cũ: mọi dòng hiện có được GIỮ NGUYÊN (chỉ thêm cột `id` mới, không xoá
-- dòng nào) — vì trước đây `dyelot` là PRIMARY KEY nên mỗi dyelot chỉ có ĐÚNG 1 dòng sẵn, không
-- có xung đột nào khi thêm UNIQUE(dyelot, machine, start_time) mới.
--
-- Idempotent: chạy lại nhiều lần không lỗi (IF NOT EXISTS / IF EXISTS ở mọi bước).

begin;

alter table batch_details
    add column if not exists id bigint generated always as identity;

-- Tên constraint mặc định Postgres tự sinh cho `dyelot text primary key`
-- khai báo trong supabase/schema.sql bản cũ (không đặt tên riêng).
alter table batch_details
    drop constraint if exists batch_details_pkey;

alter table batch_details
    add constraint batch_details_pkey primary key (id);

alter table batch_details
    alter column dyelot set not null;

create unique index if not exists uq_batch_details_dyelot_machine_start
    on batch_details (dyelot, machine, start_time);

commit;

-- Kiểm tra sau khi chạy (không bắt buộc, chỉ để xác nhận):
-- select id, dyelot, machine, start_time, end_time from batch_details order by id desc limit 10;
