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
