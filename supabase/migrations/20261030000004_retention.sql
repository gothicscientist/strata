-- Retention: purge expired guest workspaces and expired rows.
-- Deleting dataset rows cascades to dataset_keys, which destroys the wrapped data keys
-- (crypto-shredding): any ciphertext copy in storage or backups becomes undecryptable.

create or replace function public.purge_expired_data() returns jsonb
language plpgsql security definer set search_path = public as $$
declare
  n_keys int; n_datasets int; n_analyses int; n_chats int; n_cmp int; n_guests int; n_jobs int;
begin
  -- Destroy keys first, explicitly, so shredding happens even if a cascade is ever removed.
  delete from dataset_keys k using datasets d
   where k.dataset_id = d.id
     and (d.expires_at < now()
          or d.owner_id in (select id from profiles where is_guest and expires_at < now()));
  get diagnostics n_keys = row_count;

  -- Storage objects of expired datasets (rows referenced by storage_path).
  if exists (select 1 from information_schema.tables
             where table_schema = 'storage' and table_name = 'objects') then
    execute $q$
      delete from storage.objects o using public.datasets d
       where o.bucket_id = 'encrypted-datasets' and o.name = d.storage_path
         and (d.expires_at < now()
              or d.owner_id in (select id from public.profiles
                                 where is_guest and expires_at < now()))
    $q$;
  end if;

  delete from datasets d
   where d.expires_at < now()
      or d.owner_id in (select id from profiles where is_guest and expires_at < now());
  get diagnostics n_datasets = row_count;
  delete from analyses where expires_at < now();          get diagnostics n_analyses = row_count;
  delete from chat_sessions where expires_at < now();     get diagnostics n_chats = row_count;
  delete from model_comparisons where expires_at < now(); get diagnostics n_cmp = row_count;
  delete from profiles where is_guest and expires_at < now(); get diagnostics n_guests = row_count;
  -- Finished jobs are kept 30 days for debugging, then removed.
  delete from jobs where status in ('succeeded','failed','cancelled')
     and finished_at < now() - interval '30 days';
  get diagnostics n_jobs = row_count;

  return jsonb_build_object('dataset_keys', n_keys, 'datasets', n_datasets,
    'analyses', n_analyses, 'chat_sessions', n_chats, 'comparisons', n_cmp,
    'guests', n_guests, 'jobs', n_jobs);
end $$;

revoke all on function public.purge_expired_data() from public, anon, authenticated;

-- Schedule with pg_cron when available (Supabase: enable the pg_cron extension).
do $$
begin
  if exists (select 1 from pg_available_extensions where name = 'pg_cron') then
    create extension if not exists pg_cron;
    perform cron.unschedule(jobid) from cron.job where jobname = 'strata-purge-expired';
    perform cron.schedule('strata-purge-expired', '*/15 * * * *',
                          'select public.purge_expired_data()');
  else
    raise notice 'pg_cron not available: run strata worker (it purges every minute) instead';
  end if;
end $$;
