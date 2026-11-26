-- Import hold lists (FDA import alert red list, Australian holding orders). One row per list entry;
-- rows stay after removal with removed_on set, so the admin side keeps the history.
create table if not exists holds (
  src text not null,            -- US (FDA import alert) or AU (holding order)
  ref text not null,            -- import alert number or holding order number
  firm_key text not null,
  firm text not null,
  address text default '',
  groups text[] default '{}',
  products jsonb default '[]',
  products_zh text[] default '{}',
  reason text default '',
  listed_on date,
  url text default '',
  first_seen date default current_date,
  last_seen date,
  removed_on date,              -- FDA: day we noticed the firm was gone; AU: official revocation date
  primary key (src, ref, firm_key)
);
create index if not exists holds_active on holds (src) where removed_on is null;
alter table holds enable row level security;  -- service role only; the site reads the exported JSON
