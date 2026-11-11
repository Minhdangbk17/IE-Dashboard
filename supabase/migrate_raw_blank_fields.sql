begin;
alter table availability_logs add column if not exists blank_fields text;
alter table performance_logs add column if not exists blank_fields text;
alter table batch_details add column if not exists blank_fields text;
commit;
