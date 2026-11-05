# Deploying Strata

Strata has four runtime pieces. Each can be hosted separately.

| Piece | What it is | Suggested host |
|---|---|---|
| Web | Next.js static export (`apps/web/out`) | Cloudflare Pages |
| API | FastAPI (`strata.api.main:app`), `services/api/Dockerfile` | Any container host (Fly.io, Render, Cloud Run, a VM) |
| Worker | Job runner with R 4.5 + ADMIXTOOLS 2, `services/worker/Dockerfile` | Same container host; give it CPU and RAM (qpAdm on large f2 caches benefits from 4+ cores, 8 GB) |
| Database | Postgres 16 with `pgvector` (+ `pg_cron` for retention) | Supabase |

Reference data (`data/derived/`, the f2 cache) is built separately by the data
pipeline; see [Reference data](#4-reference-data).

## 1. Local development

```bash
# Backend
cd services/api
uv venv --python 3.12 .venv && uv pip install -p .venv/bin/python -e ".[dev]"
STRATA_JOB_MODE=inline .venv/bin/uvicorn strata.api.main:app --reload --port 8000

# Optional: formal qpAdm locally (R 4.5 + ADMIXTOOLS 2 from conda-forge + GitHub)
export STRATA_RSCRIPT="$(bash services/worker/r/install_env.sh)"

# Web
cd apps/web
cp .env.example .env.local   # NEXT_PUBLIC_API_URL=http://localhost:8000
pnpm install && pnpm dev
```

With `STRATA_JOB_MODE=inline` and the default SQLite database nothing else is
needed. The research assistant is enabled once `ANTHROPIC_API_KEY` (or
`OPENAI_API_KEY` with `STRATA_LLM_PROVIDER=openai`) is set.

## 2. Full stack with Docker Compose

```bash
cp .env.example .env
# set at least STRATA_DATA_KEY:  openssl rand -base64 32
docker compose -f infra/docker-compose.yml --env-file .env up --build
```

This starts Postgres with pgvector (migrations in `supabase/migrations/` run on
first start), the API on `127.0.0.1:8000`, the queue worker and the web app on
`127.0.0.1:8080`.

## 3. Production

### 3.1 Supabase

1. Create a project. Under **Database → Extensions** enable `vector` and `pg_cron`.
2. Apply the schema: `supabase link --project-ref <ref> && supabase db push`
   (or paste `supabase/migrations/*.sql` into the SQL editor, in order).
   This creates the tables, row-level security (`owner_id = auth.uid()`), the
   `encrypted-datasets` storage bucket policy and the purge job for expired guest data.
3. Under **Authentication → Providers** enable Email (magic link). Add the web
   origin to the redirect allow-list.
4. Collect: project URL, anon key (web), service-role key (API, only if
   `STRATA_STORAGE_BACKEND=supabase`), the JWT secret (legacy HS256) or nothing
   (asymmetric keys are discovered from `$SUPABASE_URL/auth/v1/.well-known/jwks.json`),
   and the Postgres connection string.

### 3.2 API and worker

Build and push both images from the repository root:

```bash
docker build -f services/api/Dockerfile -t ghcr.io/<you>/strata-api .
docker build -f services/worker/Dockerfile -t ghcr.io/<you>/strata-worker .
```

Environment for both (full list with comments in `.env.example`):

| Variable | Notes |
|---|---|
| `STRATA_ENV=prod` | Refuses to start without a data key or on SQLite |
| `DATABASE_URL` | `postgresql+psycopg://...` from Supabase |
| `STRATA_DATA_KEY` | 32 random bytes, base64. **Losing it makes stored datasets unreadable.** Keep it in a secret manager |
| `STRATA_JOB_MODE=queue` | API enqueues; the worker executes |
| `SUPABASE_URL`, `SUPABASE_JWT_SECRET` or JWKS | Token verification |
| `STRATA_CORS_ORIGINS` | The Cloudflare Pages origin(s) |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`, `STRATA_LLM_PROVIDER` | Research assistant |
| `STRATA_DERIVED_DIR`, `STRATA_F2_DIR` | Where the reference artefacts and f2 cache are mounted |

Run the API with `uvicorn strata.api.main:app --host 0.0.0.0 --port 8000` (the
image's default) and one or more workers (`python -m strata.jobs.worker
--concurrency N`). Workers claim jobs with `FOR UPDATE SKIP LOCKED`, so scaling
out is just running more replicas.

### 3.3 Web on Cloudflare Pages

```bash
cd apps/web
NEXT_PUBLIC_API_URL=https://api.your-domain \
NEXT_PUBLIC_SUPABASE_URL=https://<ref>.supabase.co \
NEXT_PUBLIC_SUPABASE_ANON_KEY=<anon key> \
pnpm build
npx wrangler pages deploy out --project-name strata-web
```

Or connect the repository in the Pages dashboard with root directory
`apps/web`, build command `pnpm build`, output directory `out`, and the three
variables above. `scripts/write-headers.mjs` writes `out/_headers` with a
per-page CSP whose `connect-src` is derived from these variables, so changing
the API origin requires a rebuild.

**Automatic deploys.** The live site (`strata-web`, served at stratalab.cc) is a
direct-upload Pages project, so Cloudflare does not watch this repository.
`.github/workflows/deploy-web.yml` does: every push to `main` that changes
`apps/web/` is typechecked, tested, built and deployed to the project's
production branch. It needs two repository secrets, `CLOUDFLARE_API_TOKEN`
(a token with *Account → Cloudflare Pages → Edit*) and `CLOUDFLARE_ACCOUNT_ID`.
The three `NEXT_PUBLIC_*` values default to the live origins and can be
overridden with repository variables of the same names. Run it by hand from the
Actions tab to redeploy without a change.

## 4. Reference data

The reference library (populations, samples, PCA space, SNP panel) and the f2
cache used by qpAdm are derived from the Allen Ancient DNA Resource by
`data/pipeline`. They are not checked into git in full; see
`docs/DATA_PROVENANCE.md` for what may be redistributed.

* **On GitHub:** run the **Build reference data** workflow
  (`.github/workflows/build-reference.yml`, manual dispatch). It downloads AADR
  on the runner, builds the artefacts, and opens a PR with the small derived
  files; large artefacts are uploaded as workflow artefacts / release assets.
* **On your own machine:** `cd data/pipeline && make all` (needs
  `dataverse.harvard.edu` and, for the f2 stage, `STRATA_RSCRIPT`).
* **For a deployment that only runs analyses:** `cd data/pipeline &&
  make fetch-f2`. The derived metadata and PCA coordinates are already in the
  repository; this adds the f2 cache from the release the workflow published,
  verified against its checksum and against the committed `MANIFEST.json`. It
  needs neither Dataverse nor R, so it is the step to run in an image build or
  an init container.

Mount the results at `STRATA_DERIVED_DIR` (and the f2 cache at `STRATA_F2_DIR`)
for the API and worker. `/api/v1/health` reports whether each piece loaded.

## 5. Operations

* **Retention:** guest workspaces expire after `STRATA_GUEST_TTL_HOURS` (24 h);
  `pg_cron` runs `purge_expired_data()` and the queue worker also purges on a timer.
* **Key rotation:** set the new key as `STRATA_DATA_KEY` and the old one in
  `STRATA_DATA_KEY_PREVIOUS` so existing data keys still unwrap. `Keyring.rewrap` (`strata/security/crypto.py`) re-wraps a data key under the new key.
* **Health:** `GET /api/v1/health` (capabilities), worker heartbeat file
  (`STRATA_WORKER_HEALTH_FILE`).
