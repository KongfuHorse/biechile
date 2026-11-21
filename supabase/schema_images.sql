-- Product photos for EU RASFF records (collected from linked warning pages, approved in the admin page)
-- Applied to the database as migration "record_images".
create table if not exists record_images (
  id bigserial primary key,
  record_id text not null references records(id) on delete cascade,
  page_url text,
  img_url text not null,
  path text,                       -- file in storage bucket "rasff"
  width int, height int, bytes int,
  ai_ok boolean, ai_note text,
  status text not null default 'candidate',   -- candidate / approved / rejected
  reviewed_by text, reviewed_at timestamptz,
  created_at timestamptz not null default now(),
  unique (record_id, img_url)
);
create index if not exists record_images_status on record_images(status);
create table if not exists image_pages (
  record_id text not null references records(id) on delete cascade,
  page_url text not null,
  status text not null,            -- ok / http_404 / no_images / error / skipped
  candidates int not null default 0,
  fetched_at timestamptz not null default now(),
  primary key (record_id, page_url)
);
alter table record_images enable row level security;
alter table image_pages enable row level security;
grant select, insert, update, delete on record_images, image_pages to service_role;
grant usage, select on sequence record_images_id_seq to service_role;

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('rasff', 'rasff', true, 2097152, array['image/webp','image/jpeg','image/png'])
on conflict (id) do nothing;

-- admin_images(p_token, p_status) and admin_set_images(p_token, p_ids, p_status): see migration "record_images"
