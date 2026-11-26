-- Optional brand name for a verified firm (e.g. 伊利, Geekvape); shown on the site under the firm name.
alter table firm_zh add column if not exists brand text;

create or replace function admin_save_firm4(p_token text, p_key text, p_firm_en text, p_zh text, p_zh_address text,
  p_credit_code text, p_source_url text, p_note text, p_dissolved boolean, p_brand text)
returns void language plpgsql security definer set search_path = public as $$
declare v_user text;
begin
  v_user := _admin_check(p_token);
  if coalesce(trim(p_zh), '') = '' then raise exception '中文名不能为空'; end if;
  if coalesce(trim(p_source_url), '') = '' and coalesce(trim(p_credit_code), '') = '' then
    raise exception '请至少填写统一社会信用代码或来源或官网';
  end if;
  insert into firm_zh (firm_key, firm_en, zh_name, zh_address, credit_code, source_url, note, dissolved, brand, verified_by, verified_at)
  values (p_key, p_firm_en, trim(p_zh), nullif(trim(p_zh_address), ''), nullif(trim(p_credit_code), ''), nullif(trim(p_source_url), ''),
          nullif(trim(p_note), ''), coalesce(p_dissolved, false), nullif(trim(p_brand), ''), v_user, now())
  on conflict (firm_key) do update set firm_en = excluded.firm_en, zh_name = excluded.zh_name, zh_address = excluded.zh_address,
    credit_code = excluded.credit_code, source_url = excluded.source_url, note = excluded.note, dissolved = excluded.dissolved,
    brand = excluded.brand, verified_by = excluded.verified_by, verified_at = excluded.verified_at;
end $$;
revoke all on function admin_save_firm4(text, text, text, text, text, text, text, text, boolean, text) from public;
grant execute on function admin_save_firm4(text, text, text, text, text, text, text, text, boolean, text) to anon, authenticated;

-- admin_firms3: also return the brand, and let the search box find it
create or replace function admin_firms3(p_token text, p_status text default 'todo', p_q text default '', p_offset integer default 0,
  p_limit integer default 10, p_sort text default 'n_desc')
returns jsonb language plpgsql security definer set search_path = public as $$
begin
  perform _admin_check(p_token);
  return (
    with base as (
      select a.*, z.zh_name, z.zh_address, z.dissolved, z.brand, z.credit_code, z.source_url, z.note, z.verified_by, z.verified_at,
             ai.candidates, fa.address_en as fda_address
      from firm_all_mv a
      left join firm_zh z on z.firm_key = a.firm_key
      left join firm_ai ai on ai.firm_key = a.firm_key
      left join firm_address fa on fa.fei = a.fei
      where (coalesce(p_q, '') = '' or a.firm_en ilike '%' || p_q || '%' or z.zh_name ilike '%' || p_q || '%' or z.brand ilike '%' || p_q || '%')
        and case coalesce(p_status, 'todo')
              when 'todo' then z.firm_key is null
              when 'ai' then z.firm_key is null and jsonb_array_length(coalesce(ai.candidates, '[]')) > 0
              when 'known' then z.firm_key is null and coalesce(ai.candidates, '[]') @> '[{"basis":"known"}]'
              when 'done' then z.firm_key is not null
              else true end
    ), page as (
      select * from base
      order by case when p_sort = 'n_asc' then n end asc,
               case when p_sort = 'last_desc' then last_date end desc nulls last,
               case when p_sort = 'last_asc' then last_date end asc nulls last,
               case when p_sort not in ('n_asc', 'last_desc', 'last_asc') then n end desc,
               firm_key
      offset greatest(0, p_offset) limit greatest(1, least(p_limit, 100))
    )
    select jsonb_build_object(
      'total', (select count(*) from base),
      'items', coalesce((select jsonb_agg(to_jsonb(p) order by
                 case when p_sort = 'n_asc' then p.n end asc,
                 case when p_sort = 'last_desc' then p.last_date end desc nulls last,
                 case when p_sort = 'last_asc' then p.last_date end asc nulls last,
                 case when p_sort not in ('n_asc', 'last_desc', 'last_asc') then p.n end desc,
                 p.firm_key) from page p), '[]'))
  );
end $$;
