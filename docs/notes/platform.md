# Platform workstream notes (API, jobs, db, security, reports)

Additions to the ARCHITECTURE.md contract (all backwards compatible):

* Job kinds: besides the six listed, there are `nearest` (exploratory nearest populations) and
  `f4` (formal, via `strata.qpadm.run_f4`). Job payloads are `{"analysis_id"}` (API analyses)
  or `{"params": {...}}` (ad-hoc agent jobs, where the result is on `job.result.result`).
* Extra routes: `GET /auth/me`, `POST /jobs/{id}/cancel`, `DELETE /analyses/{id}`,
  `POST|GET /comparisons`, `DELETE /comparisons/{id}`, `GET|DELETE /chat/sessions/{id}`,
  `GET /chat/sessions`, and an unprefixed `GET /health` liveness probe with no DB access.
  Capability flags are at `/api/v1/health`.
* The chat SSE stream passes `strata.agent.stream_chat` events through unchanged. The `event:`
  name equals `type`. A `saved` event (`{message_id}`) is sent just before `done`. The `done`
  event omits `transcript`, which is persisted in `chat_messages.usage.transcript`.
* `POST /datasets` multipart fields are `kind` (g25|raw_dna|vcf|auto), `file`, `g25_text` and
  `name`.
* Analysis params accept web-composer aliases: `bootstrap` maps to `n_bootstrap`;
  `min_sources`/`max_sources` map to `k_min`/`k_max` (admixture_rotate only); and
  `target_population` maps to `target`. `source_dataset_id` (a user G25 sheet whose rows are
  named `Population:Sample`) supplies exploratory sources, with individuals kept for the
  bootstrap.
* qpAdm jobs map Strata population ids to `Population.group_id` (the AADR labels in the f2
  cache) and record the mapping in provenance. `f2_dir`/`geno_prefix` are restricted to
  `strata.qpadm.default_f2_dir()`.
* `GET /reference/populations` returns `facets` {region, period, country, source_dataset}.
* Settings: `STRATA_EXAMPLES_DIR` overrides `$STRATA_DATA_DIR/examples`.
* Docker: compose uses `services/api/Dockerfile` and `services/worker/Dockerfile` (owned by
  qpadm-data). The web image is `infra/docker/web.Dockerfile` (nginx serving the static
  export).
