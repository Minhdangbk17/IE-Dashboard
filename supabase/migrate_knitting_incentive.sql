-- migrate_knitting_incentive.sql
-- Chạy 1 LẦN qua Supabase SQL Editor (SAU migrate_knitting_downtime.sql) — báo cáo Incentive Dệt
-- (Engine `knitting.incentive`, 2026-10-09). Ở SQLite app tự tạo/ALTER.
--
-- knitting_piece_rolls: thêm cột cho %Achieve = Σ(KNT N.W × Std.PTM) / Σ Available + production_date
--   (Record End kẹp vào khoảng sản xuất trong tên file). Dữ liệu cuộn ĐÃ import trước đó có các cột
--   này = NULL -> báo cáo cảnh báo; import lại file Piece Produced để điền.
-- knitting_incentive_bands: bậc đơn giá (From > , To <= , VND/kg), seed bảng người dùng.
-- Idempotent.

begin;

alter table knitting_piece_rolls add column if not exists std_ptm double precision;
alter table knitting_piece_rolls add column if not exists knt_nw_kg double precision;
alter table knitting_piece_rolls add column if not exists final_nw_kg double precision;
alter table knitting_piece_rolls add column if not exists operator_code text;
alter table knitting_piece_rolls add column if not exists production_date text;
create index if not exists idx_knitting_piece_rolls_production_date on knitting_piece_rolls (production_date);

create table if not exists knitting_incentive_bands (
    id               bigint generated always as identity primary key,
    from_pct         double precision not null,
    to_pct           double precision not null,
    unit_vnd_per_kg  double precision not null,
    updated_by       text,
    updated_at       text not null default to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

insert into knitting_incentive_bands (from_pct, to_pct, unit_vnd_per_kg, updated_by)
select v.from_pct, v.to_pct, v.unit, 'seed'
from (values (0.0, 82.0, 0), (82.0, 84.5, 15), (84.5, 87.0, 45), (87.0, 89.5, 60), (89.5, 92.0, 80),
             (92.0, 94.0, 104), (94.0, 96.0, 130), (96.0, 98.0, 162), (98.0, 100.0, 192)) as v (from_pct, to_pct, unit)
where not exists (select 1 from knitting_incentive_bands);

alter table knitting_incentive_bands enable row level security;

commit;
