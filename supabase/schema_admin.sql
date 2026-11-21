-- ============================================
-- 后台：登录、企业中文名核实、AI 候选、翻译核对
-- 用法：先运行 schema.sql，再运行这个文件
-- 安全说明（和 Subdeals 后台相同的做法）：
--   - 网页只能调用下面的 admin_ 函数，函数里先检查登录令牌，再读写数据
--   - 管理员密码用 bcrypt 加密保存
--   - 管理员账号在最下面单独创建，密码不写在这个文件里
-- ============================================

create extension if not exists pgcrypto with schema extensions;

-- ---------- 管理员和登录 ----------
create table if not exists admin_users (
  username text primary key,
  password_hash text not null
);
alter table admin_users enable row level security;

create table if not exists admin_sessions (
  token text primary key,
  username text not null references admin_users(username) on delete cascade,
  expires_at timestamptz not null
);
alter table admin_sessions enable row level security;

-- ---------- 企业中文名（只放人工核实过的） ----------
create table if not exists firm_names (
  fei          text primary key,        -- FDA 企业编号
  firm_en      text not null,           -- FDA 原文英文名
  zh_name      text not null,           -- 核实过的中文全称
  credit_code  text,                    -- 统一社会信用代码
  source_url   text,                    -- 核实来源链接
  note         text,
  verified_by  text,
  verified_at  timestamptz not null default now()
);
alter table firm_names enable row level security;

-- ---------- AI 候选中文名（只在后台显示，不上网站） ----------
create table if not exists firm_candidates (
  fei          text primary key,
  firm_en      text,
  address      text,                    -- FDA 登记的英文地址
  candidates   jsonb not null default '[]',  -- [{name, reason}]
  model        text,
  created_at   timestamptz not null default now()
);
alter table firm_candidates enable row level security;

-- ---------- 企业拒收统计（给后台和每日任务用） ----------
create or replace view firm_stats with (security_invoker = true) as
select r.raw->>'FEINumber' as fei,
       max(r.firm) as firm_en,
       max(r.raw->>'City') as city,
       max(r.url) as profile_url,
       count(*) as lines,
       count(distinct r.entry_no) as shipments,
       max(r.pub_date) as last_date,
       (array_agg(r.product order by r.pub_date desc))[1] as last_product
from records r
where r.src = 'US' and coalesce(r.raw->>'FEINumber', '') <> ''
group by r.raw->>'FEINumber';

grant select, insert, update, delete on firm_names, firm_candidates to service_role;
grant select on firm_stats to service_role;

-- ============================================
-- 函数
-- ============================================

create or replace function admin_login(p_username text, p_password text)
returns text language plpgsql security definer set search_path = public, extensions as $$
declare v_hash text; v_token text;
begin
  select password_hash into v_hash from admin_users where username = p_username;
  if v_hash is null or crypt(p_password, v_hash) <> v_hash then
    perform pg_sleep(1);                      -- 放慢猜密码
    raise exception '账号或密码错误';
  end if;
  delete from admin_sessions where expires_at < now();
  v_token := encode(gen_random_bytes(32), 'hex');
  insert into admin_sessions values (v_token, p_username, now() + interval '12 hours');
  return v_token;
end $$;

create or replace function _admin_check(p_token text)
returns text language plpgsql security definer set search_path = public as $$
declare v_user text;
begin
  select username into v_user from admin_sessions where token = p_token and expires_at > now();
  if v_user is null then raise exception '登录已过期，请重新登录'; end if;
  return v_user;
end $$;

create or replace function admin_logout(p_token text)
returns void language sql security definer set search_path = public as $$
  delete from admin_sessions where token = p_token;
$$;

create or replace function admin_change_password(p_token text, p_old text, p_new text)
returns void language plpgsql security definer set search_path = public, extensions as $$
declare v_user text; v_hash text;
begin
  v_user := _admin_check(p_token);
  select password_hash into v_hash from admin_users where username = v_user;
  if crypt(p_old, v_hash) <> v_hash then raise exception '原密码不对'; end if;
  if length(p_new) < 8 then raise exception '新密码至少 8 位'; end if;
  update admin_users set password_hash = crypt(p_new, gen_salt('bf')) where username = v_user;
end $$;

-- 企业列表：按拒收行数排序，附带已核实中文名和 AI 候选
create or replace function admin_firms(p_token text, p_limit int default 200)
returns jsonb language plpgsql security definer set search_path = public as $$
begin
  perform _admin_check(p_token);
  return (
    select coalesce(jsonb_agg(x order by x.lines desc, x.fei), '[]') from (
      select s.*, n.zh_name, n.credit_code, n.source_url, n.note, n.verified_by, n.verified_at,
             c.candidates, c.address, c.created_at as candidates_at
      from firm_stats s
      left join firm_names n on n.fei = s.fei
      left join firm_candidates c on c.fei = s.fei
      order by s.lines desc, s.fei
      limit greatest(1, least(p_limit, 2000))
    ) x
  );
end $$;

create or replace function admin_save_firm(p_token text, p_fei text, p_firm_en text, p_zh text,
                                           p_credit_code text, p_source_url text, p_note text)
returns void language plpgsql security definer set search_path = public as $$
declare v_user text;
begin
  v_user := _admin_check(p_token);
  if coalesce(trim(p_zh), '') = '' then raise exception '中文名不能为空'; end if;
  if coalesce(trim(p_source_url), '') = '' and coalesce(trim(p_credit_code), '') = '' then
    raise exception '请至少填写统一社会信用代码或来源链接';
  end if;
  insert into firm_names (fei, firm_en, zh_name, credit_code, source_url, note, verified_by, verified_at)
  values (p_fei, p_firm_en, trim(p_zh), nullif(trim(p_credit_code), ''), nullif(trim(p_source_url), ''),
          nullif(trim(p_note), ''), v_user, now())
  on conflict (fei) do update set firm_en = excluded.firm_en, zh_name = excluded.zh_name,
    credit_code = excluded.credit_code, source_url = excluded.source_url, note = excluded.note,
    verified_by = excluded.verified_by, verified_at = excluded.verified_at;
end $$;

create or replace function admin_delete_firm(p_token text, p_fei text)
returns void language plpgsql security definer set search_path = public as $$
begin perform _admin_check(p_token); delete from firm_names where fei = p_fei; end $$;

-- 翻译核对
create or replace function admin_terms(p_token text, p_status text default 'machine')
returns jsonb language plpgsql security definer set search_path = public as $$
begin
  perform _admin_check(p_token);
  return (select coalesce(jsonb_agg(t order by t.status, t.kind, t.source), '[]')
          from term_translations t where p_status = 'all' or t.status = p_status);
end $$;

create or replace function admin_save_term(p_token text, p_kind text, p_source text, p_zh text)
returns void language plpgsql security definer set search_path = public as $$
begin
  perform _admin_check(p_token);
  if coalesce(trim(p_zh), '') = '' then raise exception '译文不能为空'; end if;
  update term_translations set zh = trim(p_zh), status = 'verified' where kind = p_kind and source = p_source;
  if not found then raise exception '找不到这条翻译'; end if;
end $$;

-- 网页（公开 key）只能调用这些函数，读不到任何表
revoke execute on function _admin_check(text) from public, anon, authenticated;
grant execute on function admin_login(text, text), admin_logout(text), admin_change_password(text, text, text),
  admin_firms(text, int), admin_save_firm(text, text, text, text, text, text, text), admin_delete_firm(text, text),
  admin_terms(text, text), admin_save_term(text, text, text, text)
  to anon;

-- ---------- 创建管理员账号（单独运行，把密码换成你自己的） ----------
-- insert into admin_users (username, password_hash)
-- values ('admin', crypt('你的密码', gen_salt('bf')))
-- on conflict (username) do update set password_hash = excluded.password_hash;
