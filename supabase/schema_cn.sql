-- Mainland food sampling results, one row per product listed in an official notice.
create table if not exists cn_checks (
  id bigint generated always as identity primary key,
  notice_url text not null,
  notice_title text,
  notice_no text,
  notice_date date,
  item_no int,
  maker text,
  maker_role text,
  product text,
  problem text,
  seller text,
  platform text,
  origin text,
  disputed boolean not null default false,
  dispute_note text,
  raw text not null,
  unique (notice_url, item_no)
);
create index if not exists cn_checks_maker_idx on cn_checks (maker);
alter table cn_checks enable row level security;
grant select, insert, update, delete on cn_checks to service_role;

-- Excel tables attached to the notices give more detail than the notice text.
alter table cn_checks
  add column if not exists source text not null default 'text',
  add column if not exists maker_addr text,
  add column if not exists seller_addr text,
  add column if not exists spec text,
  add column if not exists brand text,
  add column if not exists prod_date text,
  add column if not exists test_value text,
  add column if not exists standard_value text,
  add column if not exists lab text,
  add column if not exists category text,
  add column if not exists sample_no text,
  add column if not exists attachment text;
create index if not exists cn_checks_sample_idx on cn_checks (sample_no);

-- Which programme a row comes from: samr_food (SAMR food sampling), samr_quality (SAMR national
-- product quality spot checks), sz_food / sz_quality (Shenzhen market regulator).
alter table cn_checks add column if not exists program text not null default 'samr_food';
create index if not exists cn_checks_program_idx on cn_checks (program);
