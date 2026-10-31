# Web workstream notes (apps/web)

Contract points agreed with the platform and agent workstreams, as implemented by the web client:

- `GET /reference/populations` returns `{items, total, page, page_size, facets}` where `facets`
  lists `region`, `period`, `country`, `source_dataset` over the whole library. Filters:
  `q, region, period, country, source_dataset, min_bp, max_bp, space, page, page_size`.
- `POST /datasets` multipart: `kind` (`g25|raw_dna|vcf|auto`), `file` or `g25_text`, `name`.
  The web client sends `kind=auto` for files.
- `POST /analyses` params per kind (see `apps/web/src/lib/composer.ts`):
  `pca_project {space}`, `nearest {space,k,metric}`,
  `admixture_fit {space,sources,bootstrap,seed,sensitivity}`,
  `admixture_rotate {space,candidates,min_sources,max_sources,max_models,seed}`,
  `qpadm {left,right,allsnps,target_population?}`,
  `qpadm_rotate {candidates,right,max_sources,allsnps,target_population?}`.
  `dataset_id` is null and `target` is the population id when the target is a library population.
- Result payloads are rendered by `result.type` (or inferred from shape for agent tool results);
  field names follow `apps/web/src/lib/types.ts`.
- Chat SSE: `event:` equals `data.type`; types `text_delta, tool_call, tool_result,
  message_done, saved, error, done`. Citation ids `methods/<file>.md#<anchor>` link to
  `/methods/#<file>--<anchor>` (headings on /methods are slugged with the doc prefix).
- Error bodies `{detail, code}`; codes `reference_unavailable`, `llm_unavailable`,
  `qpadm_unavailable` are shown as expected states rather than failures.
