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
