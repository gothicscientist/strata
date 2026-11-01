"""Test fixtures for the research agent.

``ScriptedProvider`` is a TEST DOUBLE. It emits a predetermined sequence of text and tool
calls instead of contacting an LLM, so the loop can be driven end to end through the real tool
implementations. Reference data here is a small SYNTHETIC fixture, not real population data.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pytest

from strata.agent.events import (
    AssistantMessage,
    ConvMessage,
    ErrorEvent,
    MessageDone,
    ProviderEvent,
    StopReason,
    TextDelta,
    ToolCall,
    ToolCallEvent,
    ToolSpec,
    Usage,
)
from strata.agent.providers import LLMProvider, ProviderSettings
from strata.agent.rag import KnowledgeBase, chunk_markdown
from strata.agent.tools import ToolContext


@dataclass
class ScriptedTurn:
    """One model turn: some text, then zero or more tool calls."""

    text: str = ""
    tool_calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    stop_reason: StopReason | None = None
    raise_error: Exception | None = None
    error_event: str | None = None


class ScriptedProvider(LLMProvider):
    """Test double: replays scripted turns and records the requests it was given."""

    name = "scripted"

    def __init__(self, turns: Sequence[ScriptedTurn], model: str = "scripted-1") -> None:
        self.settings = ProviderSettings(model=model, retries_before_output=1)
        self._turns = list(turns)
        self.calls: list[dict[str, Any]] = []
        self.turn_index = 0

    def stream(
        self, *, system: str, tools: Sequence[ToolSpec], messages: Sequence[ConvMessage]
    ) -> AsyncIterator[ProviderEvent | ToolCallEvent]:
        self.calls.append({"system": system, "tools": list(tools), "messages": list(messages)})
        return self._attempt()

    async def _attempt(self) -> AsyncIterator[ProviderEvent | ToolCallEvent]:
        if self.turn_index >= len(self._turns):
            yield MessageDone(
                stop_reason="end_turn", usage=Usage(), message=AssistantMessage(text="")
            )
            return
        turn = self._turns[self.turn_index]
        self.turn_index += 1
        if turn.raise_error is not None:
            raise turn.raise_error
        if turn.error_event is not None:
            yield ErrorEvent(message=turn.error_event, retryable=False)
            return
        for piece in turn.text.split(" "):
            if piece:
                yield TextDelta(text=piece + " ")
        calls = [
            ToolCall(id=f"call_{self.turn_index}_{i}", name=name, arguments=args)
            for i, (name, args) in enumerate(turn.tool_calls)
        ]
        stop: StopReason = turn.stop_reason or ("tool_use" if calls else "end_turn")
        for c in calls:
            yield ToolCallEvent(id=c.id, name=c.name, arguments=c.arguments)
        yield MessageDone(
            stop_reason=stop,
            usage=Usage(input_tokens=100, output_tokens=20, cost_usd=0.001),
            model=self.settings.model,
            message=AssistantMessage(
                text=turn.text.strip(), tool_calls=calls if stop == "tool_use" else []
            ),
        )


# ---- synthetic reference fixture -------------------------------------------------------------

# SYNTHETIC fixture data. Names resemble real population labels so schema/flow tests are
# realistic, but all coordinates and metadata are invented and must never be presented as real.
SYNTHETIC_POPULATIONS: list[dict[str, Any]] = [
    {
        "id": "Onge.SG",
        "name": "Onge",
        "region": "South Asia",
        "period": "Present",
        "date_bp": 0,
        "n_samples": 5,
        "lat": 10.7,
        "lon": 92.6,
        "publication": "synthetic-fixture-2020",
    },
    {
        "id": "Iran_GanjDareh_N",
        "name": "Iran Ganj Dareh Neolithic",
        "region": "Near East",
        "period": "Neolithic",
        "date_bp": 9800,
        "n_samples": 8,
        "lat": 34.3,
        "lon": 47.5,
        "publication": "synthetic-fixture-2020",
    },
    {
        "id": "Russia_Steppe_MLBA",
        "name": "Steppe MLBA",
        "region": "Steppe",
        "period": "Bronze Age",
        "date_bp": 3500,
        "n_samples": 20,
        "lat": 52.0,
        "lon": 60.0,
        "publication": "synthetic-fixture-2020",
    },
    {
        "id": "India_IVC_periphery",
        "name": "Indus periphery",
        "region": "South Asia",
        "period": "Bronze Age",
        "date_bp": 4300,
        "n_samples": 4,
        "lat": 29.0,
        "lon": 76.0,
        "publication": "synthetic-fixture-2020",
    },
    {
        "id": "Mbuti.DG",
        "name": "Mbuti",
        "region": "Africa",
        "period": "Present",
        "date_bp": 0,
        "n_samples": 10,
        "lat": 1.0,
        "lon": 29.0,
        "publication": "synthetic-fixture-2020",
    },
    {
        "id": "Han.DG",
        "name": "Han",
        "region": "East Asia",
        "period": "Present",
        "date_bp": 0,
        "n_samples": 12,
        "lat": 35.0,
        "lon": 110.0,
        "publication": "synthetic-fixture-2020",
    },
    {
        "id": "Modern_Punjabi",
        "name": "Punjabi (synthetic)",
        "region": "South Asia",
        "period": "Present",
        "date_bp": 0,
        "n_samples": 15,
        "lat": 31.0,
        "lon": 74.0,
        "publication": "synthetic-fixture-2020",
    },
    {
        "id": "Tiny_Pop",
        "name": "Under-sampled population",
        "region": "South Asia",
        "period": "Present",
        "date_bp": 0,
        "n_samples": 1,
        "lat": 25.0,
        "lon": 80.0,
        "publication": "synthetic-fixture-2020",
    },
]

_DIM = 25


def _synthetic_coords() -> tuple[list[str], np.ndarray]:
    rng = np.random.default_rng(20240101)
    names = [p["id"] for p in SYNTHETIC_POPULATIONS]
    base = {
        "Onge.SG": 0.0,
        "Iran_GanjDareh_N": 1.0,
        "Russia_Steppe_MLBA": 2.0,
        "India_IVC_periphery": 0.4,
        "Mbuti.DG": -3.0,
        "Han.DG": -1.5,
        "Modern_Punjabi": 0.9,
        "Tiny_Pop": 0.5,
    }
    mat = np.zeros((len(names), _DIM))
    for i, n in enumerate(names):
        mat[i, 0] = base[n]
        mat[i, 1:] = rng.normal(0, 0.05, _DIM - 1) + base[n] * 0.1
    return names, mat


class FakeReference:
    """In-memory ReferenceBackend over the synthetic fixture."""

    #: Overridden per test; the shape the pipeline writes into MANIFEST.json.
    panel_record: dict[str, Any] = {
        "right_set": ["SYNTH_outgroup"],
        "limits": [],
        "matched_groups": len(SYNTHETIC_POPULATIONS),
        "roles": {"context": len(SYNTHETIC_POPULATIONS)},
        "unavailable_labels": {},
    }

    def __init__(self) -> None:
        self._pops = SYNTHETIC_POPULATIONS
        self._names, self._mat = _synthetic_coords()

    def search(
        self, query: str | None, region: str | None, period: str | None, limit: int
    ) -> list[dict[str, Any]]:
        out = []
        for p in self._pops:
            blob = " ".join(str(v) for v in p.values()).lower()
            if query and query.lower() not in blob:
                continue
            if region and region.lower() not in p["region"].lower():
                continue
            if period and period.lower() not in p["period"].lower():
                continue
            out.append(p)
        return out[:limit]

    def get(self, population_id: str) -> dict[str, Any] | None:
        return next((p for p in self._pops if p["id"] == population_id), None)

    def coordinates(self, space: str) -> tuple[list[str], np.ndarray]:
        if space not in ("g25", "strata-pca-v1"):
            raise KeyError(f"unknown space {space}")
        return list(self._names), self._mat.copy()

    def all_metadata(self) -> list[dict[str, Any]]:
        return [{"kind": "population", **p} for p in self._pops]

    def panel(self) -> dict[str, Any]:
        return dict(self.panel_record)


@pytest.fixture
def fake_reference() -> FakeReference:
    return FakeReference()


@pytest.fixture
def knowledge_base(tmp_path) -> KnowledgeBase:
    """A small corpus so retrieval tests do not depend on docs/methods content."""
    doc = tmp_path / "qpadm.md"
    doc.write_text(
        "# qpWave and qpAdm\n\n"
        "## Interpreting p-values\n\n"
        "A p-value above the threshold means the model is not rejected, not proven. "
        "Several models can pass.\n\n"
        "## Choice of right populations\n\n"
        "Right populations must be differentially related to the sources and must not share "
        "drift with the target that the sources lack.\n",
        encoding="utf-8",
    )
    doc2 = tmp_path / "pca.md"
    doc2.write_text(
        "# PCA\n\n## Projection and shrinkage\n\n"
        "Projected low-coverage samples are pulled toward the origin, which biases distances. "
        "smartpca lsqproject fits on observed SNPs.\n",
        encoding="utf-8",
    )
    chunks = chunk_markdown(doc) + chunk_markdown(doc2)
    return KnowledgeBase(chunks)


@pytest.fixture
def tool_ctx(fake_reference: FakeReference, knowledge_base: KnowledgeBase) -> ToolContext:
    datasets = [
        {
            "id": "ds-1",
            "kind": "g25",
            "name": "my-kit",
            "created_at": "2026-01-01T00:00:00Z",
            "qc": {"call_rate": 0.98, "n_snps": 630000, "overlap_1240k": 142000},
            # Fields the tool must not pass on to the model:
            "genotypes": [0, 1, 2, 0],
            "owner_email": "someone@example.com",
        }
    ]

    def list_datasets(user_id: str) -> list[dict[str, Any]]:
        return datasets

    def get_coords(dataset_id: str, space: str) -> dict[str, Any] | None:
        if dataset_id != "ds-1" or space != "g25":
            return None
        rng = np.random.default_rng(7)
        coords = np.zeros(_DIM)
        coords[0] = 0.75
        coords[1:] = rng.normal(0, 0.05, _DIM - 1)
        return {"space": space, "name": "my-kit", "coords": coords.tolist()}

    return ToolContext(
        user_id="user-1",
        list_datasets=list_datasets,
        get_dataset_coordinates=get_coords,
        reference=fake_reference,
        knowledge=knowledge_base,
    )
