from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response

from strata.api.deps import SettingsDep
from strata.api.errors import not_found
from strata.api.examples_store import get_example, list_examples
from strata.api.schemas import ExampleDetail, ExampleSummary

router = APIRouter(prefix="/examples", tags=["examples"])

_SUMMARY_KEYS = set(ExampleSummary.model_fields)


@router.get("", response_model=list[ExampleSummary], summary="Precomputed example analyses")
def examples(settings: SettingsDep, response: Response) -> list[dict[str, Any]]:
    """Real analyses computed by the data pipeline from public ancient DNA (with provenance)."""
    response.headers["Cache-Control"] = "public, max-age=300"
    return [{k: v for k, v in ex.items() if k in _SUMMARY_KEYS}
            for ex in list_examples(settings.examples_dir)]


@router.get("/{slug}", response_model=ExampleDetail, summary="Example detail with full result")
def example(slug: str, settings: SettingsDep, response: Response) -> dict[str, Any]:
    ex = get_example(settings.examples_dir, slug)
    if ex is None:
        raise not_found("example")
    response.headers["Cache-Control"] = "public, max-age=300"
    return ex
