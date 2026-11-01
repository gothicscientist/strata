# Strata web

Next.js 15 (App Router, React 19, TypeScript strict, Tailwind CSS v4), exported as a static
site for Cloudflare Pages. Every screen loads from the Strata API (`/api/v1`); there is no
bundled sample data.

## Run

```sh
pnpm install
cp .env.example .env.local          # NEXT_PUBLIC_API_URL=http://localhost:8000
pnpm dev                            # http://localhost:3000 (API must allow this origin: STRATA_CORS_ORIGINS)
```

Build and serve the static export exactly as Pages serves it (including `_headers`/CSP):

```sh
NEXT_PUBLIC_API_URL=https://api.example.org pnpm build   # writes out/ and out/_headers
pnpm start                                               # http://localhost:4173
```

`NEXT_PUBLIC_*` variables are baked in at build time. The CSP `connect-src` is generated from
`NEXT_PUBLIC_API_URL` (and `NEXT_PUBLIC_SUPABASE_URL`), so rebuild when the API origin changes.

## Test

```sh
pnpm test            # vitest: API client, SSE parser, parsing/format helpers, components
pnpm typecheck
pnpm build && pnpm test:e2e   # Playwright smoke test over out/ (uploads a synthetic G25 row if the API is up)
pnpm screenshots     # full-page screenshots of key pages into docs/screenshots (needs `pnpm start`)
```

Playwright uses the Chromium in `/opt/pw-browsers` when present, or `PLAYWRIGHT_CHROMIUM`.

## Deploy (Cloudflare Pages)

`wrangler.toml` points Pages at `out/`. Either connect the repository in the Pages dashboard
(build command `pnpm build`, output `out`, root `apps/web`, env `NEXT_PUBLIC_API_URL`) or run
`pnpm deploy`. Routes use query parameters (`/analysis/?id=…`) so no server is needed.

## Layout

- `src/lib/api.ts`, `types.ts` — typed client mirroring `services/api/strata/api/schemas.py`
  and `strata.reference.library`; guest tokens (`POST /auth/guest`) in localStorage, optional
  Supabase magic-link auth when `NEXT_PUBLIC_SUPABASE_URL`/`ANON_KEY` are set.
- `src/lib/sse.ts`, `chat.ts` — SSE parsing and the assistant event reducer.
- `src/components/charts` — Plotly PCA (client-only), SVG weight/residual figures, d3-geo map.
- `src/components/results` — result renderers shared by analyses, examples and the assistant.
- `/methods` and `/data` render `docs/methods/*.md`, `docs/DATA.md`/`docs/data/*.md`,
  `data/pipeline/README.md` and `data/derived/MANIFEST.json` at build time.
