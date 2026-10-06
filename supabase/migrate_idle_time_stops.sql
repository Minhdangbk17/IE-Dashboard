-- migrate_idle_time_stops.sql
-- Chạy 1 LẦN thủ công qua Supabase SQL Editor trên project PRODUCTION (2026-10-05, bản 2 của
-- Engine `idle_time`). Chạy SAU `migrate_idle_time.sql`.
--
-- Đổi cách lưu nguyên nhân idle: từ note gắn theo khoảng idle (`idle_time_notes`, khoá
-- machine + gap_start — mất khớp khi import lại Batch) sang LẦN DỪNG dạng khoảng thời gian
-- (`idle_time_stops`) — nhập tay ở trang Idle Entry (ca đêm, trước khi upload Batch) hoặc Save
-- trong drawer báo cáo. App ghép lần dừng vào khoảng idle ở read time.
--
-- Note cũ được chép sang thành lần dừng source='report' có giờ = đúng khoảng idle lúc lưu.
-- KHÔNG xoá bảng `idle_time_notes` (app không còn đọc). Idempotent: chạy lại không nhân bản.

begin;

create table if not exists idle_time_stops (
    id          bigint generated always as identity primary key,
    machine     text not null,
    stop_start  text not null,
    stop_end    text,
    reason      text,
    detail      text,
    source      text not null default 'entry',
    created_by  bigint not null references users (id),
    created_at  text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
    updated_by  bigint not null references users (id),
    updated_at  text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);
create index if not exists idx_idle_time_stops_machine_start on idle_time_stops (machine, stop_start);
alter table idle_time_stops enable row level security;

-- Chỉ chép khi bảng bản 1 có tồn tại (DB tạo mới từ schema.sql không có `idle_time_notes`).
do $$
begin
    if to_regclass('public.idle_time_notes') is not null then
        insert into idle_time_stops (machine, stop_start, stop_end, reason, detail, source, created_by, created_at, updated_by, updated_at)
        select n.machine, n.gap_start, n.gap_end, n.reason, n.detail, 'report', n.updated_by, n.updated_at, n.updated_by, n.updated_at
        from idle_time_notes n
        where not exists (
            select 1 from idle_time_stops s
            where s.machine = n.machine and s.stop_start = n.gap_start and s.source = 'report'
        );
    end if;
end $$;

commit;

-- Kiểm tra sau khi chạy (số dòng note cũ đã chép):
-- select count(*) from idle_time_stops where source = 'report';
