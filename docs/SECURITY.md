# Strata security and privacy

Strata processes personal genetic data: consumer raw DNA exports (23andMe, AncestryDNA,
FTDNA, MyHeritage), single-sample VCFs and G25 coordinates. Genotypes are identifying, they
are permanent, and they reveal information about relatives who never consented. This document
describes the threat model and the controls in the code. File references are relative to
`services/api/strata/` unless stated otherwise.

## Assets

| Asset | Sensitivity | Where it lives |
|---|---|---|
| Uploaded raw DNA file | Highest | Request memory only, never persisted |
| Harmonised dosages (panel SNPs) / G25 rows | High | `datasets.ciphertext` or a storage blob, AES-256-GCM |
| Per-dataset data keys (DEKs) | High | `dataset_keys.wrapped_key`, wrapped by the KEK |
| Key-encryption key (`STRATA_DATA_KEY`) | Critical | Secret store / environment, never in the DB |
| Analysis results (projections, weights, p-values) | Medium (derived, still personal) | `analyses.result` |
| Chat transcripts with tool audit | Medium | `chat_messages` |
| Reference library (AADR-derived) | Public | `data/derived` |

## Adversaries and threats

1. **Another user / guest** reads or alters someone else's data (IDOR, guessed ids).
2. **Network attacker** intercepts traffic or forges tokens.
3. **Database / backup leak** (stolen dump, misconfigured Supabase, leaked backup).
4. **Operator or log-pipeline exposure**: genotypes end up in logs, traces or error reports.
5. **LLM provider exposure**: genotypes sent to a third-party model.
6. **Malicious upload**: zip/gzip bombs, path traversal, oversized bodies, binary payloads.
7. **Abuse / denial of service**: floods of uploads, analyses or chat requests.
8. **Browser attacks** on the API or rendered reports: XSS, clickjacking, CORS misuse.

## Controls

### Authentication (`security/auth.py`, `api/deps.py`)
* Every data endpoint needs a bearer token: either a **Supabase access token** or a **Strata
  guest token**.
* Supabase tokens: asymmetric RS256/ES256 tokens are verified against the project JWKS (cached
  with a TTL). Legacy HS256 tokens are verified with `SUPABASE_JWT_SECRET`. The accepted
  algorithm is pinned to the key type, so an HS256 token cannot be checked with a public key.
  `alg=none`, missing `exp`/`sub`, a wrong audience, a wrong issuer (when `SUPABASE_URL` is
  set), anon-role keys and non-UUID subjects are all rejected.
* Guest tokens: HS256 JWTs with issuer `strata-guest`, a 24 h expiry (`STRATA_GUEST_TTL_HOURS`)
  and a random `jti`. They are signed with `STRATA_GUEST_TOKEN_SECRET`, which by default is
  derived from the KEK through HMAC. A valid signature is not enough: the guest profile must
  still exist server side and must not be expired. Once retention purges a workspace, its
  token is void. A guest token can never authenticate a non-guest profile, and the reverse
  also holds.

### Authorisation and isolation
* Every query is scoped by `owner_id`. A resource owned by someone else returns **404**, the
  same response as a missing one, so ids cannot be probed (`api/routers/*`, `_owned` helpers).
* Job handlers re-check ownership before decrypting a dataset (`jobs/handlers.py::_open_dataset`).
  A forged job payload therefore cannot read another user's data.
* Supabase **row-level security** is enabled on every user table, with `owner_id = auth.uid()`
  (`supabase/migrations/*_rls.sql`). The API's service connection bypasses RLS and enforces
  the same rule in code. RLS protects direct PostgREST / supabase-js access. Clients get no
  access at all to `dataset_keys`, and they cannot select the `ciphertext`/`nonce` columns of
  their own rows. Tests: `tests/security/test_rls_postgres.py`.

### Data minimisation
* Uploads are parsed **in memory**. Starlette's multipart spooling is raised above the upload
  limit, so files are never written to a temp file. The original file is discarded after
  parsing; only its SHA-256 is kept, for provenance.
* Raw DNA is harmonised to the reference SNP panel. Only the panel-aligned dosage vector is
  kept (int8, about 1 byte per panel SNP). Vendor metadata, indels, no-calls and off-panel
  SNPs are dropped. If no panel is installed, only biallelic called SNVs are kept (encrypted),
  so the dataset can be harmonised later. Re-uploading is the recommended path.
* The research agent sees **derived** data only: dataset metadata and coordinates (G25 rows or
  PCA projections). It never sees dosages or calls (`api/routers/chat.py::_tool_context`).
  Every tool call and tool result is persisted with the assistant message for audit.

### Encryption at rest (`security/crypto.py`, `security/vault.py`)
* **Envelope encryption.** Each dataset gets a fresh 256-bit DEK. The payload is encrypted with
  AES-256-GCM using a random 96-bit nonce. The associated data binds the ciphertext to its
  `dataset_id` and `owner_id`, so swapping ciphertexts between rows fails authentication.
* The DEK is wrapped (AES-256-GCM) with the KEK `STRATA_DATA_KEY`. Wrapped keys are stored in
  `dataset_keys`, a separate table from the ciphertext, and are tagged with a non-secret KEK id.
  To rotate: set a new `STRATA_DATA_KEY`, move the old one to `STRATA_DATA_KEY_PREVIOUS`,
  then re-wrap with `Keyring.rewrap`.
* A SHA-256 of the plaintext is checked after decryption.
* Ciphertext blobs can live in the DB (`bytea`), on local disk (0600 files) or in a private
  Supabase Storage bucket. That bucket has a restrictive policy that denies all
  anon/authenticated access.

### Deletion and retention
* `DELETE /datasets/{id}` **crypto-shreds**. It zeroes, then deletes, the wrapped DEK, then
  deletes the ciphertext blob and the row. Any copy of the ciphertext that survives in backups
  or object storage is then undecryptable. This holds as long as wrapped keys are not restored
  from an older backup, so keep `dataset_keys` backups short-lived, or keep the KEK out of
  long-term backups.
* Guest workspaces expire after 24 h. Every row a guest owns carries the same `expires_at`.
  Purging runs in the worker loop every minute (`security/retention.py`), and with pg_cron
  every 15 minutes (`purge_expired_data()` in `supabase/migrations/*_retention.sql`). Keys are
  destroyed first. Finished jobs are deleted after 30 days.

### Logging (`security/logging.py`)
* A root-logger filter **refuses genotype-like payloads**: rsID + call rows, VCF records, runs
  of diploid calls and long dosage vectors. Such a record's message is replaced with
  `[redacted: genotype-like payload]`, and its args and traceback are dropped.
* Request validation errors never echo submitted values. Unhandled errors return a generic
  500 and log only the exception type and path. Job errors store only the exception message,
  never tracebacks or locals.

### Upload hardening (`security/uploads.py`, `api/main.py::BodySizeLimit`)
* The request body is limited (`STRATA_MAX_UPLOAD_MB`, default 64 MB) before parsing. The
  limit checks both `Content-Length` and streamed bytes.
* There is an extension allow-list (`.txt .csv .tsv .vcf .gz .zip`). Content is sniffed: no NUL
  bytes, valid UTF-8 or mostly-printable text.
* gzip/zip input is decompressed with a 256 MB cap (bomb protection). A zip must hold exactly
  one file.
* Filenames are normalised (NFKC). Directories, control characters and unusual characters are
  stripped and the length is capped. The sanitised name is metadata only and is never used as
  a path.

### Abuse controls (`security/ratelimit.py`)
* An in-process token bucket limits each client IP (all routes). A stricter bucket limits each
  user on expensive routes: uploads, analyses and chat. Issuing guest tokens has its own
  per-IP bucket. `STRATA_TRUST_PROXY_HEADERS` must be enabled only behind a trusted proxy
  (Cloudflare). For multi-instance deployments, also add edge rate-limiting rules.
* Jobs have per-kind timeouts. A handler that overruns marks its job failed, and the worker
  exits (code 3) so the orchestrator restarts a clean process.
* Clients cannot point the R bridge at arbitrary server paths. `f2_dir` and `geno_prefix` are
  restricted to the configured reference cache.

### HTTP and browser (`security/headers.py`)
* API responses carry `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`,
  `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`,
  HSTS, COOP/CORP and a restrictive `Permissions-Policy`. User-data responses are sent with
  `Cache-Control: no-store`.
* HTML reports are rendered with Jinja2 autoescaping and served as attachments with a CSP that
  allows only inline styles (no scripts).
* CORS is an explicit allow-list (`STRATA_CORS_ORIGINS`) with credentials disabled. The bearer
  token is sent in a header, never in cookies, so the API has no CSRF surface.

## Operational requirements
* Generate the KEK with `openssl rand -base64 32` and keep it in a secret manager. Losing it
  loses all datasets; leaking it together with a DB dump exposes them. `STRATA_ENV=prod`
  refuses to start without it.
* Use TLS everywhere (Cloudflare to the API, the API to Postgres with `sslmode=require`).
* The service-role key and the DB password are server-side only. The web app receives only the
  Supabase anon key.
* Never enable `STRATA_DB_ECHO` in production (SQL parameters could include ciphertext).

## Known limitations
* Rate limiting is per process. Run an edge limiter in front of horizontally scaled APIs.
* In-memory parsing means a ~30 MB raw file transiently occupies a few hundred MB of RAM, which
  bounds concurrency per instance.
* Python cannot reliably wipe secrets from memory. Plaintext exists in process memory while a
  request or job is running.
* Results (projections, weights) are personal data in their own right. They are not encrypted
  at the application layer; they rely on RLS, ownership checks and database encryption at rest.

## Reporting a vulnerability
Please report security issues privately to the maintainers (see README) rather than in public
issues.
