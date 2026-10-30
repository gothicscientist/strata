-- Strata core schema. Mirrors services/api/strata/db/models.py (SQLAlchemy).
-- Applied by `supabase db push` / `supabase migration up`, or plain psql on vanilla Postgres
-- (the `auth` schema stub below keeps it runnable outside Supabase).

create extension if not exists pgcrypto;

-- Vanilla Postgres compatibility: Supabase provides auth.uid(); elsewhere we define one that
-- reads the `request.jwt.claim.sub` GUC (the same mechanism PostgREST uses).
create schema if not exists auth;
do $$
begin
  if not exists (
    select 1 from pg_proc p join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'auth' and p.proname = 'uid'
  ) then
    execute $f$
      create function auth.uid() returns uuid language sql stable as
      $b$ select nullif(coalesce(current_setting('request.jwt.claim.sub', true),
                 (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub')),
                 '')::uuid $b$
    $f$;
  end if;
end $$;

create table if not exists public.profiles (
  id            uuid primary key,
  email         varchar(320),
  display_name  varchar(200),
  is_guest      boolean not null default false,
  created_at    timestamptz not null default now(),
  last_seen_at  timestamptz not null default now(),
  expires_at    timestamptz
);
create index if not exists ix_profiles_guest_expiry on public.profiles (expires_at) where is_guest;

create table if not exists public.jobs (
  id            uuid primary key default gen_random_uuid(),
  kind          varchar(32) not null,
  status        varchar(16) not null default 'queued'
                check (status in ('queued','running','succeeded','failed','cancelled')),
  payload       jsonb not null default '{}'::jsonb,
  result        jsonb,
  error         text,
  owner_id      uuid references public.profiles(id) on delete cascade,
  priority      integer not null default 100,
  attempts      integer not null default 0,
  max_attempts  integer not null default 3,
  timeout_s     integer,
  run_after     timestamptz not null default now(),
  locked_by     varchar(128),
  heartbeat_at  timestamptz,
  created_at    timestamptz not null default now(),
  started_at    timestamptz,
  finished_at   timestamptz
);
create index if not exists ix_jobs_owner_id on public.jobs (owner_id);
-- Partial index keeps the SKIP LOCKED claim query an index scan over runnable jobs only.
create index if not exists ix_jobs_claim on public.jobs (priority, run_after, created_at)
  where status = 'queued';
create index if not exists ix_jobs_running_heartbeat on public.jobs (heartbeat_at)
  where status = 'running';

create table if not exists public.datasets (
  id                uuid primary key default gen_random_uuid(),
  owner_id          uuid not null references public.profiles(id) on delete cascade,
  name              varchar(200) not null,
  kind              varchar(16) not null check (kind in ('g25','raw_dna','vcf')),
  original_filename varchar(255),
  size_bytes        integer not null default 0,
  input_sha256      varchar(64) not null,
  payload_sha256    varchar(64) not null,
  payload_format    varchar(32) not null,
  qc_report         jsonb not null default '{}'::jsonb,
  summary           jsonb not null default '{}'::jsonb,
  ciphertext        bytea,
  storage_path      varchar(512),
  nonce             bytea not null,
  panel_version     varchar(64),
  created_at        timestamptz not null default now(),
  expires_at        timestamptz,
  constraint datasets_payload_location check (ciphertext is not null or storage_path is not null)
);
create index if not exists ix_datasets_owner_created on public.datasets (owner_id, created_at);
create index if not exists ix_datasets_expires_at on public.datasets (expires_at);

-- Wrapped per-dataset data keys, separate from ciphertext so deleting a row crypto-shreds it.
create table if not exists public.dataset_keys (
  dataset_id   uuid primary key references public.datasets(id) on delete cascade,
  owner_id     uuid not null references public.profiles(id) on delete cascade,
  wrapped_key  bytea not null,
  kek_id       varchar(32) not null,
  algorithm    varchar(32) not null default 'AES-256-GCM',
  created_at   timestamptz not null default now()
);
create index if not exists ix_dataset_keys_owner_id on public.dataset_keys (owner_id);

create table if not exists public.analyses (
  id           uuid primary key default gen_random_uuid(),
  owner_id     uuid not null references public.profiles(id) on delete cascade,
  kind         varchar(32) not null,
  title        varchar(200),
  params       jsonb not null default '{}'::jsonb,
  dataset_ids  jsonb not null default '[]'::jsonb,
  status       varchar(16) not null default 'queued',
  result       jsonb,
  error        text,
  provenance   jsonb not null default '{}'::jsonb,
  job_id       uuid references public.jobs(id) on delete set null,
  created_at   timestamptz not null default now(),
  finished_at  timestamptz,
  expires_at   timestamptz
);
create index if not exists ix_analyses_owner_created on public.analyses (owner_id, created_at);
create index if not exists ix_analyses_job_id on public.analyses (job_id);
create index if not exists ix_analyses_expires_at on public.analyses (expires_at);

create table if not exists public.chat_sessions (
  id           uuid primary key default gen_random_uuid(),
  owner_id     uuid not null references public.profiles(id) on delete cascade,
  title        varchar(200),
  dataset_ids  jsonb not null default '[]'::jsonb,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  expires_at   timestamptz
);
create index if not exists ix_chat_sessions_owner_id on public.chat_sessions (owner_id);
create index if not exists ix_chat_sessions_expires_at on public.chat_sessions (expires_at);

create table if not exists public.chat_messages (
  id            uuid primary key default gen_random_uuid(),
  session_id    uuid not null references public.chat_sessions(id) on delete cascade,
  owner_id      uuid not null references public.profiles(id) on delete cascade,
  seq           integer not null,
  role          varchar(16) not null check (role in ('user','assistant')),
  content       text not null default '',
  tool_calls    jsonb not null default '[]'::jsonb,   -- audit: every tool call the agent made
  tool_results  jsonb not null default '[]'::jsonb,   -- audit: every tool result it saw
  grounding     jsonb,
  citations     jsonb not null default '[]'::jsonb,
  usage         jsonb,
  error         text,
  created_at    timestamptz not null default now(),
  unique (session_id, seq)
);
create index if not exists ix_chat_messages_session_id on public.chat_messages (session_id);
create index if not exists ix_chat_messages_owner_id on public.chat_messages (owner_id);

create table if not exists public.model_comparisons (
  id            uuid primary key default gen_random_uuid(),
  owner_id      uuid not null references public.profiles(id) on delete cascade,
  name          varchar(200) not null,
  analysis_ids  jsonb not null default '[]'::jsonb,
  notes         text,
  summary       jsonb not null default '{}'::jsonb,
  created_at    timestamptz not null default now(),
  expires_at    timestamptz
);
create index if not exists ix_model_comparisons_owner_id on public.model_comparisons (owner_id);
create index if not exists ix_model_comparisons_expires_at on public.model_comparisons (expires_at);

-- Create a profile row automatically when a Supabase user signs up.
create or replace function public.handle_new_user() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (id, email) values (new.id, new.email)
  on conflict (id) do nothing;
  return new;
end $$;

do $$
begin
  if exists (select 1 from information_schema.tables
             where table_schema = 'auth' and table_name = 'users') then
    drop trigger if exists on_auth_user_created on auth.users;
    create trigger on_auth_user_created after insert on auth.users
      for each row execute function public.handle_new_user();
  end if;
end $$;
