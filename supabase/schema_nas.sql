-- NAS agent in mainland China: it polls this database for jobs and sends results back.
-- The NAS never holds the service key. It calls only the nas_* functions below with its own token,
-- and those functions can do nothing except check in, take a job, finish a job, store a file and
-- read a code bundle. Jobs and code bundles are written by us with the service role.

create table if not exists nas_agents (
  name        text primary key,
  token_hash  text not null,                 -- sha256 hex of the agent token
  last_seen   timestamptz,
  version     text,                          -- code bundle version the agent is running
  info        jsonb,                         -- machine info, last error, etc.
  created_at  timestamptz not null default now()
);

create table if not exists nas_config (
  key   text primary key,
  value text not null
);
insert into nas_config (key, value) values ('code_version', ''), ('poll_seconds', '30')
on conflict (key) do nothing;

create table if not exists nas_code (
  version     text primary key,
  sha256      text not null,                 -- sha256 hex of the zip bytes
  zip_b64     text not null,                 -- zip of the jobs package, base64
  note        text,
  created_at  timestamptz not null default now()
);

create table if not exists nas_jobs (
  id           bigint generated always as identity primary key,
  kind         text not null,                -- must match a handler in the code bundle
  args         jsonb not null default '{}',
  status       text not null default 'queued' check (status in ('queued', 'running', 'done', 'failed')),
  agent        text,
  result       jsonb,
  log          text,
  created_at   timestamptz not null default now(),
  started_at   timestamptz,
  finished_at  timestamptz
);
create index if not exists nas_jobs_queue_idx on nas_jobs (status, id);

create table if not exists nas_files (
  id          bigint generated always as identity primary key,
  job_id      bigint references nas_jobs(id) on delete cascade,
  name        text not null,
  mime        text not null,
  b64         text not null,
  created_at  timestamptz not null default now()
);

alter table nas_agents enable row level security;
alter table nas_config enable row level security;
alter table nas_code   enable row level security;
alter table nas_jobs   enable row level security;
alter table nas_files  enable row level security;
-- No policies: the anon key cannot read or write these tables directly.

create or replace function _nas_check(p_token text, p_agent text)
returns void language plpgsql security definer set search_path = public as $$
begin
  if not exists (select 1 from nas_agents
                 where name = p_agent
                   and token_hash = encode(extensions.digest(coalesce(p_token, ''), 'sha256'), 'hex')) then
    raise exception 'nas: bad agent or token';
  end if;
end $$;

-- Heartbeat. Returns the code version the agent should run and how often to poll.
create or replace function nas_checkin(p_token text, p_agent text, p_version text, p_info jsonb)
returns jsonb language plpgsql security definer set search_path = public as $$
begin
  perform _nas_check(p_token, p_agent);
  update nas_agents set last_seen = now(), version = p_version, info = p_info where name = p_agent;
  -- a job left 'running' for over 2 hours means the agent restarted in the middle of it
  update nas_jobs set status = 'failed', finished_at = now(), log = coalesce(log, '') || E'\n[timed out or agent restarted]'
   where status = 'running' and agent = p_agent and started_at < now() - interval '2 hours';
  return jsonb_build_object(
    'code_version', (select value from nas_config where key = 'code_version'),
    'poll_seconds', (select value::int from nas_config where key = 'poll_seconds'));
end $$;

-- Take the oldest queued job, or null when there is none.
create or replace function nas_next_job(p_token text, p_agent text)
returns jsonb language plpgsql security definer set search_path = public as $$
declare j nas_jobs;
begin
  perform _nas_check(p_token, p_agent);
  select * into j from nas_jobs where status = 'queued' order by id limit 1 for update skip locked;
  if j.id is null then return null; end if;
  update nas_jobs set status = 'running', agent = p_agent, started_at = now() where id = j.id;
  return jsonb_build_object('id', j.id, 'kind', j.kind, 'args', j.args);
end $$;

create or replace function nas_finish_job(p_token text, p_agent text, p_id bigint, p_ok boolean,
                                          p_result jsonb, p_log text)
returns void language plpgsql security definer set search_path = public as $$
begin
  perform _nas_check(p_token, p_agent);
  update nas_jobs set status = case when p_ok then 'done' else 'failed' end,
                      result = p_result, log = left(p_log, 100000), finished_at = now()
   where id = p_id and agent = p_agent and status = 'running';
end $$;

-- Attach a file (for example a page screenshot) to a running job. Up to about 3 MB each.
create or replace function nas_put_file(p_token text, p_agent text, p_job bigint, p_name text,
                                        p_mime text, p_b64 text)
returns void language plpgsql security definer set search_path = public as $$
begin
  perform _nas_check(p_token, p_agent);
  if length(p_b64) > 4000000 then raise exception 'nas: file too large'; end if;
  if not exists (select 1 from nas_jobs where id = p_job and agent = p_agent and status = 'running') then
    raise exception 'nas: job not running';
  end if;
  insert into nas_files (job_id, name, mime, b64) values (p_job, left(p_name, 200), left(p_mime, 100), p_b64);
end $$;

create or replace function nas_get_code(p_token text, p_agent text, p_version text)
returns jsonb language plpgsql security definer set search_path = public as $$
begin
  perform _nas_check(p_token, p_agent);
  return (select jsonb_build_object('version', version, 'sha256', sha256, 'zip_b64', zip_b64)
            from nas_code where version = p_version);
end $$;

revoke all on function _nas_check(text, text) from public, anon, authenticated;
grant execute on function nas_checkin(text, text, text, jsonb), nas_next_job(text, text),
  nas_finish_job(text, text, bigint, boolean, jsonb, text), nas_put_file(text, text, bigint, text, text, text),
  nas_get_code(text, text, text) to anon;
