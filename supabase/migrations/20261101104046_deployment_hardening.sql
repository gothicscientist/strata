-- Trigger functions are internal; they must not be exposed as client RPCs.
revoke execute on function public.handle_new_user() from public, anon, authenticated;
alter function public.handle_new_user() set search_path = '';

-- Keep extension objects outside the exposed application schema.
create schema if not exists extensions;
alter extension vector set schema extensions;
grant usage on schema extensions to anon, authenticated;
alter function public.match_knowledge_chunks(extensions.vector, integer)
  set search_path = public, extensions;
