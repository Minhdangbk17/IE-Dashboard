-- migrate_case_notes_context.sql
-- Chạy 1 LẦN thủ công qua Supabase SQL Editor trên project PRODUCTION đã có sẵn
-- bảng `downtime_case_notes` (đã có dữ liệu thật — hiện ~27 note nhập qua UI).
--
-- Lý do: bản đầu khoá UNIQUE(availability_log_id) — 1 note dùng CHUNG cho MỌI
-- category ("Downtime by Category") hoặc field ("Data Quality") mà mẻ đó xuất
-- hiện, dẫn tới bug thật: sửa note ở category này thì category khác của CÙNG
-- mẻ cũng bị đổi theo. Migration này thêm cột `context` và đổi UNIQUE constraint
-- thành (availability_log_id, context) để mỗi category/field có note riêng.
--
-- AN TOÀN với dữ liệu cũ: mọi note đã có được gán context='' (rỗng) — ứng dụng
-- coi đây là note "chung", vẫn hiển thị lại đúng nội dung cũ ở BẤT KỲ category/
-- field nào của đúng mẻ đó cho tới khi người dùng sửa lại theo 1 category cụ
-- thể (lúc đó ghi thành 1 dòng MỚI với context riêng, không ghi đè dòng context='').
-- Không xoá/mất dữ liệu nào trong quá trình này.
--
-- Idempotent: chạy lại nhiều lần không lỗi (IF NOT EXISTS / IF EXISTS ở mọi bước).

begin;

alter table downtime_case_notes
    add column if not exists context text not null default '';

-- Tên constraint mặc định Postgres tự sinh cho `unique (availability_log_id)`
-- khai báo trong supabase/schema.sql bản cũ (không đặt tên riêng).
alter table downtime_case_notes
    drop constraint if exists downtime_case_notes_availability_log_id_key;

alter table downtime_case_notes
    add constraint downtime_case_notes_log_context_key unique (availability_log_id, context);

commit;

-- Kiểm tra sau khi chạy (không bắt buộc, chỉ để xác nhận):
-- select availability_log_id, context, reason, detail from downtime_case_notes order by updated_at desc limit 10;
