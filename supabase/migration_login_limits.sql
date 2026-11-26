-- Admin login: CAPTCHA (Turnstile, checked in the admin-login Edge Function) and attempt limits.
-- Limits: 5 failed tries from one IP in 15 minutes -> that IP waits 15 minutes;
--         10 failed tries for one username in 1 hour (any IP) -> that username waits 1 hour.
create table if not exists admin_login_attempts (
  id bigserial primary key,
  at timestamptz not null default now(),
  username text not null,
  ip text not null default '',
  ok boolean not null
);
create index if not exists admin_login_attempts_ip on admin_login_attempts (ip, at);
create index if not exists admin_login_attempts_user on admin_login_attempts (username, at);
alter table admin_login_attempts enable row level security;
grant select, insert, delete on admin_login_attempts to service_role;
grant usage on sequence admin_login_attempts_id_seq to service_role;

-- returns {"token": ...} or {"error": ...}; it does not raise on a wrong password, because raising
-- would roll back the row that records the failed try
drop function if exists admin_login2(text, text, text);
create or replace function admin_login2(p_username text, p_password text, p_ip text)
returns jsonb language plpgsql security definer set search_path = public, extensions as $$
declare v_hash text; v_token text; v_ip_fails int; v_user_fails int;
begin
  select count(*) into v_ip_fails from admin_login_attempts
   where ip = coalesce(p_ip, '') and not ok and at > now() - interval '15 minutes';
  if v_ip_fails >= 5 then
    return jsonb_build_object('error', '尝试次数过多，请 15 分钟后再试');
  end if;
  select count(*) into v_user_fails from admin_login_attempts
   where username = p_username and not ok and at > now() - interval '1 hour';
  if v_user_fails >= 10 then
    return jsonb_build_object('error', '尝试次数过多，该账号暂时锁定，请 1 小时后再试');
  end if;

  select password_hash into v_hash from admin_users where username = p_username;
  if v_hash is null or crypt(p_password, v_hash) <> v_hash then
    insert into admin_login_attempts (username, ip, ok) values (p_username, coalesce(p_ip, ''), false);
    perform pg_sleep(1);
    return jsonb_build_object('error', '账号或密码错误');
  end if;

  insert into admin_login_attempts (username, ip, ok) values (p_username, coalesce(p_ip, ''), true);
  delete from admin_login_attempts where at < now() - interval '90 days';
  delete from admin_sessions where expires_at < now();
  v_token := encode(gen_random_bytes(32), 'hex');
  insert into admin_sessions values (v_token, p_username, now() + interval '12 hours');
  return jsonb_build_object('token', v_token);
end $$;
revoke all on function admin_login2(text, text, text) from public, anon, authenticated;
grant execute on function admin_login2(text, text, text) to service_role;

-- the old direct login (no CAPTCHA, no limits) is closed to the public
revoke execute on function admin_login(text, text) from public, anon, authenticated;
