-- 企业中文名（第二版）：按归并后的英文名记录，覆盖所有来源，不再只限美国 FDA 企业编号。
-- 归并规则和网站企业排行一致：转大写，标点换成空格，COMPANY/LIMITED/CORPORATION 统一成 CO/LTD/CORP。

create or replace function firm_key(t text) returns text
language sql immutable parallel safe set search_path = public as $$
  select btrim(regexp_replace(
    regexp_replace(regexp_replace(regexp_replace(
      regexp_replace(upper(coalesce(t, '')), '[.,()（）"“”''’]', ' ', 'g'),
      '\mCOMPANY\M', 'CO', 'g'), '\mLIMITED\M', 'LTD', 'g'), '\mCORPORATION\M', 'CORP', 'g'),
    '\s+', ' ', 'g'))
$$;

-- 人工核实过的中文名（网站只显示这里的名字）
create table if not exists firm_zh (
  firm_key     text primary key,
  firm_en      text not null,
  zh_name      text not null,
  credit_code  text,
  source_url   text,
  note         text,
  verified_by  text,
  verified_at  timestamptz not null default now()
);
alter table firm_zh enable row level security;

-- AI 给的中文名（只在后台显示）。candidates: [{name, basis: known|guess, reason}]
create table if not exists firm_ai (
  firm_key     text primary key,
  firm_en      text,
  candidates   jsonb not null default '[]',
  model        text,
  created_at   timestamptz not null default now()
);
alter table firm_ai enable row level security;

-- 所有来源的企业，一个归并名一行（欧盟 RASFF、Safety Gate、新加坡不给企业名；本身是中文名的不用查）
create or replace view firm_all with (security_invoker = true) as
with f as (
  select firm_key(btrim(x)) as k, btrim(x) as name, r.src, r.pub_date, r.product,
         r.raw->>'City' as city, r.raw->>'FEINumber' as fei, case when r.src = 'US' then r.url end as us_url
  from records r cross join lateral unnest(string_to_array(r.firm, '；')) x
  where r.src not in ('EU', 'SG', 'SFA') and btrim(coalesce(x, '')) <> '' and x !~ '[一-龥]'
)
select k as firm_key,
       mode() within group (order by name) as firm_en,
       count(*) as n,
       array_agg(distinct src) as sources,
       max(pub_date) as last_date,
       (array_agg(product order by pub_date desc))[1] as last_product,
       max(city) as city,
       max(fei) as fei,
       max(us_url) as profile_url
from f
where k not in ('', 'UNKNOWN', 'N A', 'NA', 'NONE', '-')
group by k;

grant select, insert, update, delete on firm_zh, firm_ai to service_role;
grant select on firm_all to service_role;

-- 旧表里已有的内容搬过来（AI 候选按"推测"处理）
insert into firm_ai (firm_key, firm_en, candidates, model, created_at)
select firm_key(firm_en), firm_en,
       coalesce((select jsonb_agg(c || '{"basis":"guess"}'::jsonb) from jsonb_array_elements(candidates) c), '[]'),
       model, created_at
from firm_candidates where coalesce(firm_en, '') <> ''
on conflict (firm_key) do nothing;
insert into firm_zh (firm_key, firm_en, zh_name, credit_code, source_url, note, verified_by, verified_at)
select firm_key(firm_en), firm_en, zh_name, credit_code, source_url, note, verified_by, verified_at from firm_names
on conflict (firm_key) do nothing;

-- 后台列表。p_status: todo 未核实 / ai 有 AI 结果未核实 / known AI 认识的 / done 已核实 / all
create or replace function admin_firms2(p_token text, p_status text default 'todo', p_q text default '',
                                        p_offset int default 0, p_limit int default 10)
returns jsonb language plpgsql security definer set search_path = public as $$
begin
  perform _admin_check(p_token);
  return (
    with base as (
      select a.*, z.zh_name, z.credit_code, z.source_url, z.note, z.verified_by, z.verified_at, ai.candidates
      from firm_all a
      left join firm_zh z on z.firm_key = a.firm_key
      left join firm_ai ai on ai.firm_key = a.firm_key
      where (coalesce(p_q, '') = '' or a.firm_en ilike '%' || p_q || '%' or z.zh_name ilike '%' || p_q || '%')
        and case coalesce(p_status, 'todo')
              when 'todo' then z.firm_key is null
              when 'ai' then z.firm_key is null and jsonb_array_length(coalesce(ai.candidates, '[]')) > 0
              when 'known' then z.firm_key is null and coalesce(ai.candidates, '[]') @> '[{"basis":"known"}]'
              when 'done' then z.firm_key is not null
              else true end
    )
    select jsonb_build_object(
      'total', (select count(*) from base),
      'items', coalesce((select jsonb_agg(b order by b.n desc, b.firm_key)
                         from (select * from base order by n desc, firm_key
                               offset greatest(0, p_offset) limit greatest(1, least(p_limit, 100))) b), '[]'))
  );
end $$;

create or replace function admin_save_firm2(p_token text, p_key text, p_firm_en text, p_zh text,
                                            p_credit_code text, p_source_url text, p_note text)
returns void language plpgsql security definer set search_path = public as $$
declare v_user text;
begin
  v_user := _admin_check(p_token);
  if coalesce(trim(p_zh), '') = '' then raise exception '中文名不能为空'; end if;
  if coalesce(trim(p_source_url), '') = '' and coalesce(trim(p_credit_code), '') = '' then
    raise exception '请至少填写统一社会信用代码或来源链接';
  end if;
  insert into firm_zh (firm_key, firm_en, zh_name, credit_code, source_url, note, verified_by, verified_at)
  values (p_key, p_firm_en, trim(p_zh), nullif(trim(p_credit_code), ''), nullif(trim(p_source_url), ''),
          nullif(trim(p_note), ''), v_user, now())
  on conflict (firm_key) do update set firm_en = excluded.firm_en, zh_name = excluded.zh_name,
    credit_code = excluded.credit_code, source_url = excluded.source_url, note = excluded.note,
    verified_by = excluded.verified_by, verified_at = excluded.verified_at;
end $$;

create or replace function admin_delete_firm2(p_token text, p_key text)
returns void language plpgsql security definer set search_path = public as $$
begin perform _admin_check(p_token); delete from firm_zh where firm_key = p_key; end $$;

grant execute on function admin_firms2(text, text, text, int, int),
  admin_save_firm2(text, text, text, text, text, text, text), admin_delete_firm2(text, text) to anon;
