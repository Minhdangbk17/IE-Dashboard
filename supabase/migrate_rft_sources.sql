-- migrate_rft_sources.sql
-- Chạy 1 LẦN thủ công qua Supabase SQL Editor trên project PRODUCTION (2026-10-08), TRƯỚC khi
-- deploy bản viết lại báo cáo Right First Time (RFT).
--
-- Báo cáo RFT không còn dùng file "RFT report.xlsx" (bảng `rft_dye_results`). Nguồn mới:
-- `batch_details` (đã có) + 2 bảng tra cứu nạp hằng ngày từ file thô:
--   - `dye_production_ops`: Production Report Dye (khoá batch_no + operation + op_start_time)
--   - `dye_nc_reports`: NC Report (khoá nc_no)
-- Target cũ của 6 tab (Lab to Lab ... Adjust Color, công thức ResultDYE cũ) bị xoá — người dùng
-- đã duyệt bỏ hẳn dữ liệu cũ; 5 tab mới nhập Target lại trên UI.
-- Idempotent: chạy lại không lỗi, không nhân bản, không xoá Target mới.

begin;

create table if not exists dye_production_ops (
    id bigint generated always as identity primary key,
    report_time text, department text, operation text not null, plant text, machine text,
    batch_no text not null, batch_status text, sap_lot text, so_no text, brand text,
    customer text, greige_code text, fabric_code text, recipe text, color_code text,
    output_qty double precision, shift text, op_start_time text not null default '', op_end_time text,
    batch_type text, import_log_id bigint,
    created_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS'),
    unique (batch_no, operation, op_start_time)
);
create index if not exists idx_dye_production_ops_batch_norm on dye_production_ops (lower(trim(batch_no)));
alter table dye_production_ops enable row level security;

create table if not exists dye_nc_reports (
    id bigint generated always as identity primary key,
    nc_no text not null unique, defect text, defect_qty double precision, operation_route text,
    status text, dept_report text, mp_no text, plant text, delivery_date text, customer text,
    sale_no text, batch_ref text not null, batch_qty double precision, colorist text, sap_lot text,
    color text, recipe text, fabric_code text, greige_code text, new_batch text,
    corrective text, reason text, dept_in_charge text, remark text,
    created_nc_at text, confirm_nc_at text, created_nb_at text, import_log_id bigint,
    created_at text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);
create index if not exists idx_dye_nc_reports_batch_ref_norm on dye_nc_reports (lower(trim(batch_ref)));
alter table dye_nc_reports enable row level security;

-- Chỉ xoá Target cũ ở LẦN CHẠY ĐẦU (bảng cũ còn tồn tại) — chạy lại sau khi người dùng đã nhập
-- Target mới sẽ không xoá mất.
do $$
begin
    if to_regclass('public.rft_dye_results') is not null then
        delete from rft_targets;
        drop table rft_dye_results;
    end if;
end $$;

commit;
