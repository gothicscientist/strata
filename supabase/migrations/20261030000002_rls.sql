-- Row-level security: every user-owned row is visible only to its owner (owner_id = auth.uid()).
-- The API connects with a privileged role (bypasses RLS) and enforces the same rule in code;
-- RLS is defence in depth for any direct Supabase (PostgREST / supabase-js) access.

alter table public.profiles          enable row level security;
alter table public.datasets          enable row level security;
alter table public.dataset_keys      enable row level security;
alter table public.analyses          enable row level security;
alter table public.jobs              enable row level security;
alter table public.chat_sessions     enable row level security;
alter table public.chat_messages     enable row level security;
alter table public.model_comparisons enable row level security;

alter table public.profiles          force row level security;
alter table public.datasets          force row level security;
alter table public.dataset_keys      force row level security;
alter table public.analyses          force row level security;
alter table public.jobs              force row level security;
alter table public.chat_sessions     force row level security;
alter table public.chat_messages     force row level security;
alter table public.model_comparisons force row level security;

do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then
    create role authenticated nologin;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'anon') then
    create role anon nologin;
  end if;
end $$;

-- profiles
drop policy if exists profiles_select_own on public.profiles;
create policy profiles_select_own on public.profiles for select to authenticated
  using (id = auth.uid());
drop policy if exists profiles_update_own on public.profiles;
create policy profiles_update_own on public.profiles for update to authenticated
  using (id = auth.uid()) with check (id = auth.uid());

-- datasets: owners may read metadata and delete; inserts go through the API (which encrypts).
drop policy if exists datasets_select_own on public.datasets;
create policy datasets_select_own on public.datasets for select to authenticated
  using (owner_id = auth.uid());
drop policy if exists datasets_delete_own on public.datasets;
create policy datasets_delete_own on public.datasets for delete to authenticated
  using (owner_id = auth.uid());

-- dataset_keys: no client access at all (wrapped keys are only for the API service role).
revoke all on public.dataset_keys from anon, authenticated;

-- analyses
drop policy if exists analyses_select_own on public.analyses;
create policy analyses_select_own on public.analyses for select to authenticated
  using (owner_id = auth.uid());
drop policy if exists analyses_delete_own on public.analyses;
create policy analyses_delete_own on public.analyses for delete to authenticated
  using (owner_id = auth.uid());

-- jobs: read-only status for owners
drop policy if exists jobs_select_own on public.jobs;
create policy jobs_select_own on public.jobs for select to authenticated
  using (owner_id = auth.uid());

-- chat
drop policy if exists chat_sessions_all_own on public.chat_sessions;
create policy chat_sessions_all_own on public.chat_sessions for all to authenticated
  using (owner_id = auth.uid()) with check (owner_id = auth.uid());
drop policy if exists chat_messages_select_own on public.chat_messages;
create policy chat_messages_select_own on public.chat_messages for select to authenticated
  using (owner_id = auth.uid());

-- saved comparisons
drop policy if exists model_comparisons_all_own on public.model_comparisons;
create policy model_comparisons_all_own on public.model_comparisons for all to authenticated
  using (owner_id = auth.uid()) with check (owner_id = auth.uid());

-- Column-level hardening: clients never read ciphertext or nonces even for their own rows.
revoke all on public.datasets from anon, authenticated;
grant select (id, owner_id, name, kind, original_filename, size_bytes, input_sha256,
              payload_format, qc_report, summary, panel_version, created_at, expires_at)
  on public.datasets to authenticated;
grant delete on public.datasets to authenticated;
grant select, update (display_name) on public.profiles to authenticated;
grant select, delete on public.analyses to authenticated;
grant select on public.jobs to authenticated;
grant select, insert, update, delete on public.chat_sessions to authenticated;
grant select on public.chat_messages to authenticated;
grant select, insert, update, delete on public.model_comparisons to authenticated;
revoke all on all tables in schema public from anon;
