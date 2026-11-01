# Agent workstream notes

Owner: `services/api/strata/agent/`, `services/api/tests/agent/`, `docs/methods/`.

## Public surface (for the platform)

```python
from strata.agent import (
    AgentConfig, ResearchAgent, ToolContext, stream_chat, get_provider, llm_available,
)
```

* `stream_chat(history, user_message, *, ctx, config=None, provider=None, cancel=None)` is an
  async generator of JSON-serialisable event dicts. Event types: `text_delta`, `tool_call`,
  `tool_result`, `message_done` (one per model turn), `error`, and a final `done` carrying
  `answer`, `grounding`, `citations`, `transcript`, `usage`, `steps`, `cancelled`.
  Models are defined in `strata/agent/events.py`; persist `tool_call` / `tool_result` events or
  `done.transcript` for audit.
* `ToolContext` is a dataclass the platform constructs per request:
  `user_id`, `db`, `run_job((job_kind, payload) -> result dict, sync or async)`,
  `list_datasets(user_id)`, `get_dataset_coordinates(dataset_id, space)`, plus optional
  `reference` / `knowledge` overrides used by tests.
* `llm_available() -> {"anthropic": bool, "openai": bool}` for `/health`. It checks only for
  the presence of credentials and never reads their values.

Job kinds the agent submits through `run_job`: `qpadm`, `qpadm_rotate`, `f4`. The payload is an
already-validated `strata.qpadm` spec dumped with `model_dump(mode="json")`, so the worker can
reconstruct it with `QpAdmSpec.model_validate(payload)`.

## Contract changes made here

* `services/api/pyproject.toml`: added `jsonschema` to dependencies (tool-argument validation)
  and a `live` pytest marker with `addopts = "-m 'not live'"`, so the opt-in live LLM tests
  never run in a normal `pytest` invocation. Run them with `pytest -m live`.

## Boundaries respected

* The agent never receives raw genotypes. `list_user_datasets` returns an allow-listed subset
  of dataset fields (id, kind, name, created_at, QC summary) and drops everything else.
* Exploratory (`kind="exploratory"`, from `strata.analysis`) and formal (`kind="formal"`, from
  `strata.qpadm`) results are kept in separate tables by `compare_models` and are never ranked
  together.
* The f2 cache path is resolved server-side via `strata.qpadm.default_f2_dir()` and is not a
  tool parameter, so the model cannot select a different SNP panel.
* A deterministic post-hoc grounding check (`strata.agent.agent.grounding_check`) flags numbers
  in the final answer that appear in no tool result.

## Environment

`STRATA_LLM_PROVIDER` (anthropic|openai), `STRATA_LLM_MODEL` (default `claude-opus-5-5`),
`STRATA_OPENAI_MODEL`, `STRATA_LLM_MAX_TOKENS`, `STRATA_LLM_TIMEOUT_S`, `STRATA_LLM_EFFORT`,
`STRATA_ANTHROPIC_FALLBACKS`, `STRATA_LLM_PRICE` (cost override),
`STRATA_AGENT_MAX_STEPS`, `STRATA_AGENT_MAX_PARALLEL_TOOLS`, `STRATA_AGENT_TOOL_TIMEOUT_S`,
`STRATA_METHODS_DIR`, `STRATA_EMBEDDINGS` (openai|voyage, enables hybrid dense retrieval),
`STRATA_EMBEDDING_MODEL`.

## Known limitations

* `strata/agent/backends.py` is aligned with the real `strata.reference` API
  (`load_library`, `search(q, *, region, period, limit)`, `get_population`,
  `population_means`, `population_samples`, `populations`, `publications`) and checks
  `library.available` / `.missing` on every call, so an unbuilt reference surfaces as a tool
  error naming the missing files. It is the single place to change if that API moves.
* Population naming: coordinate tools take `id`; `run_qpadm`, `run_qpadm_rotate` and `run_f4`
  take `group_id`, which is what the f2 cache keys on. Both are returned by
  `search_populations` / `get_population`, and the tool descriptions tell the model which to
  use where.
* Bootstrap confidence intervals in `fit_admixture` use
  `reference.population_samples(space, ids)` for per-individual coordinates. A backend without
  that method gets a clear error instead of a point estimate dressed up as an interval.
* Dense retrieval is optional and best-effort: if embedding calls fail, retrieval falls back to
  BM25 rather than failing the tool.
