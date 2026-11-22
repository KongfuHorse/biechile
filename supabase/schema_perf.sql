-- Export reads records page by page, continuing from the last (pub_date, id); this index serves that order.
create index if not exists records_pub_date_id_idx on public.records (pub_date desc, id asc);
