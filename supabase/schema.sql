-- biechile.com database schema
-- Run once in Supabase: SQL Editor -> paste -> Run

-- One row per notice record (Taiwan: one TFDA notice; US: one FDA refusal line)
create table if not exists records (
  id            text primary key,          -- 'TW-6264' or 'US-<ShipmentID>-<RefusalDate>'
  src           text not null,             -- 'TW' / 'US' (more sources later)
  pub_date      date not null,             -- publish date (TW) or refusal date (US)
  insp_date     date,                      -- inspection date, if given
  grp           text,                      -- 食品 / 膳食补充剂 / 食品接触材料 / 化妆品 / 药品 / 医疗器械 / 烟草 / ...
  ind           text,                      -- industry in Chinese (US only)
  product       text,                      -- product name in Simplified Chinese
  product_orig  text,                      -- product name as published
  problems      text[] not null default '{}',
  detail        text,                      -- finding / refusal reasons, in Chinese
  legal_limit   text,
  quantity      text,
  firm          text,                      -- manufacturer or foreign firm
  importer      text,
  lab_tested    boolean,
  entry_no      text,                      -- US customs entry number (to count shipments)
  action        text,
  url           text,                      -- official source page
  raw           jsonb,                     -- original fields as fetched
  first_seen    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create index if not exists records_pub_date_idx on records (pub_date desc);
create index if not exists records_src_idx on records (src);

-- One row per pipeline run, for checking the daily job
create table if not exists runs (
  id           bigserial primary key,
  started_at   timestamptz not null default now(),
  source       text not null,
  fetched      int,
  upserted     int,
  status       text,
  note         text
);

-- Only the service key (used by GitHub Actions) can read or write.
-- The website never talks to Supabase directly; it reads exported JSON files.
alter table records enable row level security;
alter table runs enable row level security;

-- New Supabase projects do not grant table access to API roles automatically.
-- Only service_role (GitHub Actions) gets access; anon/authenticated stay locked.
grant usage on schema public to service_role;
grant select, insert, update, delete on public.records to service_role;
grant select, insert, update, delete on public.runs to service_role;
grant usage, select on sequence public.runs_id_seq to service_role;

-- added for Japan, EU and Korea sources
alter table records add column if not exists ntype text;   -- notification type (EU), e.g. 边境拒绝
alter table records add column if not exists note text;    -- extra info: notifying country, risk, inspection office

-- Firm review (Nov 2026): Chinese address and a dissolved flag on verified firms; FDA English addresses by FEI.
alter table firm_zh add column if not exists zh_address text;
alter table firm_zh add column if not exists dissolved boolean not null default false;
create table if not exists firm_address (fei text primary key, address_en text not null, updated_at timestamptz not null default now());
alter table firm_address enable row level security;
grant select, insert, update, delete on firm_address to service_role;
-- admin_firms2 now also returns zh_address, dissolved, fda_address; admin_save_firm3 saves the new fields.

-- Admin firm list (Nov 2026): precomputed copy of firm_all, rebuilt by the daily run (refresh_firm_all);
-- admin_firms3 reads it and can sort by count or last date (p_sort: n_desc, n_asc, last_desc, last_asc).
-- See migration firm_all_cache_and_sort.

-- Admin "刷新网站数据" button (Nov 2026): edge function admin-refresh (supabase/functions/admin-refresh)
-- checks the login through admin_request_refresh (one request per 2 minutes, logged in admin_refresh_log)
-- and starts workflow update.yml with export_only=yes. Needs edge function secret GITHUB_DISPATCH_TOKEN.

-- holds: import hold lists (FDA import alert red list, Australian holding orders); see supabase/migration_holds.sql
