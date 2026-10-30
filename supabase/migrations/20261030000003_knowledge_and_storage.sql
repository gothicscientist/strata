-- RAG knowledge base (pgvector) and the private storage bucket for encrypted dataset blobs.

create extension if not exists vector;

-- Chunks of docs/methods/*.md and population/publication metadata (public, non-personal).
-- Embedding width 1536 matches OpenAI text-embedding-3-small (STRATA_EMBEDDINGS=openai).
create table if not exists public.knowledge_chunks (
  id              text primary key,
  source          text not null,
  title           text not null,
  content         text not null,
  metadata        jsonb not null default '{}'::jsonb,
  embedding_model text,
  embedding       vector(1536),
  content_sha256  text not null,
  updated_at      timestamptz not null default now()
);
create index if not exists ix_knowledge_chunks_embedding
  on public.knowledge_chunks using hnsw (embedding vector_cosine_ops);
create index if not exists ix_knowledge_chunks_fts
  on public.knowledge_chunks using gin (to_tsvector('english', title || ' ' || content));

alter table public.knowledge_chunks enable row level security;
drop policy if exists knowledge_chunks_read on public.knowledge_chunks;
create policy knowledge_chunks_read on public.knowledge_chunks for select
  to anon, authenticated using (true);
grant select on public.knowledge_chunks to anon, authenticated;

-- Cosine-similarity search used by strata.agent.rag.DenseRetriever(pg_search=...).
create or replace function public.match_knowledge_chunks(query vector(1536), k integer default 5)
returns table (id text, similarity double precision)
language sql stable as $$
  select c.id, 1 - (c.embedding <=> query) as similarity
  from public.knowledge_chunks c
  where c.embedding is not null
  order by c.embedding <=> query
  limit greatest(1, least(k, 50))
$$;

-- Supabase Storage: private bucket; objects are AES-256-GCM ciphertext written by the API's
-- service role under "<owner_id>/<dataset_id>.bin". Clients get no direct access: without
-- the wrapped key (dataset_keys, service-role only) a blob is undecryptable anyway.
do $$
begin
  if exists (select 1 from information_schema.tables
             where table_schema = 'storage' and table_name = 'buckets') then
    insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
    values ('encrypted-datasets', 'encrypted-datasets', false, 104857600,
            array['application/octet-stream'])
    on conflict (id) do update set public = false;

    execute 'drop policy if exists encrypted_datasets_no_client_access on storage.objects';
    -- Restrictive policy: deny anon/authenticated everything on this bucket. The service role
    -- bypasses RLS and is the only writer/reader.
    execute $p$
      create policy encrypted_datasets_no_client_access on storage.objects
      as restrictive for all to anon, authenticated
      using (bucket_id <> 'encrypted-datasets')
      with check (bucket_id <> 'encrypted-datasets')
    $p$;
  end if;
end $$;
