"""End-to-end research loop driven by the scripted provider test double."""

from __future__ import annotations

import asyncio
from typing import Any

from conftest import ScriptedProvider, ScriptedTurn

from strata.agent.agent import AgentConfig, ResearchAgent, grounding_check, stream_chat
from strata.agent.events import DoneEvent, ErrorEvent, TextDelta, ToolCallEvent, ToolResultEvent
from strata.agent.tools import ToolContext


async def collect(agent: ResearchAgent, prompt: str, **kw: Any) -> list[Any]:
    return [ev async for ev in agent.run([{"role": "user", "content": prompt}], **kw)]


def done_of(events: list[Any]) -> DoneEvent:
    final = events[-1]
    assert isinstance(final, DoneEvent)
    return final


async def test_loop_runs_tools_and_finishes(tool_ctx: ToolContext) -> None:
    provider = ScriptedProvider(
        [
            ScriptedTurn(
                text="Let me look at the datasets and the method notes.",
                tool_calls=[
                    ("list_user_datasets", {}),
                    ("retrieve_knowledge", {"query": "choice of right populations", "k": 1}),
                ],
            ),
            ScriptedTurn(
                text="Now the nearest populations.",
                tool_calls=[("nearest_populations", {"target": {"dataset_id": "ds-1"}, "k": 2})],
            ),
            ScriptedTurn(text="Exploratory screening only, so no formal claim yet."),
        ]
    )
    agent = ResearchAgent(provider=provider, ctx=tool_ctx)
    events = await collect(agent, "where does my kit sit?")

    assert any(isinstance(e, TextDelta) for e in events)
    calls = [e for e in events if isinstance(e, ToolCallEvent)]
    results = [e for e in events if isinstance(e, ToolResultEvent)]
    assert [c.name for c in calls] == [
        "list_user_datasets",
        "retrieve_knowledge",
        "nearest_populations",
    ]
    assert all(r.ok for r in results), [r.error for r in results]
    final = done_of(events)
    assert final.steps == 3
    assert not final.cancelled
    assert final.answer.startswith("Exploratory screening only")
    # Three model turns were sent, each carrying the growing conversation.
    assert provider.turn_index == 3
    assert len(provider.calls[-1]["messages"]) == 5  # user + 2 x (assistant + tool results)


async def test_transcript_records_every_call_and_result(tool_ctx: ToolContext) -> None:
    provider = ScriptedProvider(
        [
            ScriptedTurn(tool_calls=[("get_population", {"population_id": "Onge.SG"})]),
            ScriptedTurn(text="Done."),
        ]
    )
    agent = ResearchAgent(provider=provider, ctx=tool_ctx)
    final = done_of(await collect(agent, "tell me about the Onge"))

    kinds = [e["kind"] for e in final.transcript]
    assert kinds[0] == "start" and kinds[-1] == "final"
    assert kinds.count("tool_call") == 1
    assert kinds.count("tool_result") == 1
    assert kinds.count("model_turn") == 2
    tool_result = next(e for e in final.transcript if e["kind"] == "tool_result")
    assert tool_result["ok"] and tool_result["name"] == "get_population"
    assert tool_result["result"]["population"]["id"] == "Onge.SG"
    # The transcript is JSON-serialisable for audit storage.
    import json

    json.dumps(final.transcript, default=str)


async def test_failed_tool_is_returned_to_the_model_not_raised(tool_ctx: ToolContext) -> None:
    provider = ScriptedProvider(
        [
            ScriptedTurn(tool_calls=[("get_population", {"population_id": "Does_Not_Exist"})]),
            ScriptedTurn(text="That population is not in the library."),
        ]
    )
    agent = ResearchAgent(provider=provider, ctx=tool_ctx)
    events = await collect(agent, "look up a bogus population")

    failed = [e for e in events if isinstance(e, ToolResultEvent) and not e.ok]
    assert len(failed) == 1 and "not found" in failed[0].error
    final = done_of(events)
    assert final.stop_reason == "end_turn"
    # The error text reached the provider as a tool result message.
    last_messages = provider.calls[-1]["messages"]
    assert any(
        getattr(r, "is_error", False) for m in last_messages for r in getattr(m, "results", [])
    )


async def test_parallel_tool_calls_run_concurrently(tool_ctx: ToolContext) -> None:
    order: list[str] = []

    async def slow_list(user_id: str) -> list[dict[str, Any]]:
        order.append("list_start")
        await asyncio.sleep(0.05)
        order.append("list_end")
        return []

    tool_ctx.list_datasets = slow_list
    provider = ScriptedProvider(
        [
            ScriptedTurn(
                tool_calls=[
                    ("list_user_datasets", {}),
                    ("get_population", {"population_id": "Mbuti.DG"}),
                ]
            ),
            ScriptedTurn(text="Both done."),
        ]
    )
    agent = ResearchAgent(provider=provider, ctx=tool_ctx)
    events = await collect(agent, "two things at once")
    results = [e for e in events if isinstance(e, ToolResultEvent)]
    assert len(results) == 2 and all(r.ok for r in results)
    # The fast tool finished while the slow one was still running.
    assert order == ["list_start", "list_end"]
    assert len([e for e in events if isinstance(e, ToolCallEvent)]) == 2


async def test_max_steps_budget_stops_the_loop(tool_ctx: ToolContext) -> None:
    looping = [
        ScriptedTurn(tool_calls=[("get_population", {"population_id": "Han.DG"})])
        for _ in range(10)
    ]
    agent = ResearchAgent(
        provider=ScriptedProvider(looping), ctx=tool_ctx, config=AgentConfig(max_steps=3)
    )
    events = await collect(agent, "loop forever")
    errors = [e for e in events if isinstance(e, ErrorEvent)]
    assert errors and "Step budget" in errors[0].message
    final = done_of(events)
    assert final.steps == 3
    assert any(e["kind"] == "budget_exhausted" for e in final.transcript)


async def test_cancellation_stops_before_the_next_turn(tool_ctx: ToolContext) -> None:
    cancel = asyncio.Event()
    provider = ScriptedProvider(
        [
            ScriptedTurn(tool_calls=[("get_population", {"population_id": "Han.DG"})]),
            ScriptedTurn(tool_calls=[("get_population", {"population_id": "Mbuti.DG"})]),
            ScriptedTurn(text="never reached"),
        ]
    )
    agent = ResearchAgent(provider=provider, ctx=tool_ctx)
    events: list[Any] = []
    async for ev in agent.run([{"role": "user", "content": "go"}], cancel=cancel):
        events.append(ev)
        if isinstance(ev, ToolResultEvent):
            cancel.set()
    final = done_of(events)
    assert final.cancelled and final.stop_reason == "cancelled"
    assert provider.turn_index == 1


async def test_provider_error_is_streamed_and_ends_the_run(tool_ctx: ToolContext) -> None:
    provider = ScriptedProvider([ScriptedTurn(error_event="upstream 529 overloaded")])
    agent = ResearchAgent(provider=provider, ctx=tool_ctx)
    events = await collect(agent, "hello")
    errors = [e for e in events if isinstance(e, ErrorEvent)]
    assert errors and "529" in errors[0].message
    final = done_of(events)
    assert final.stop_reason == "error"
    assert any(e["kind"] == "error" for e in final.transcript)


async def test_usage_and_cost_accumulate(tool_ctx: ToolContext) -> None:
    provider = ScriptedProvider(
        [
            ScriptedTurn(tool_calls=[("get_population", {"population_id": "Han.DG"})]),
            ScriptedTurn(text="Done."),
        ]
    )
    agent = ResearchAgent(provider=provider, ctx=tool_ctx)
    final = done_of(await collect(agent, "go"))
    assert final.usage.input_tokens == 200
    assert final.usage.output_tokens == 40
    assert final.usage.cost_usd == 0.002


async def test_system_prompt_and_tools_are_sent(tool_ctx: ToolContext) -> None:
    provider = ScriptedProvider([ScriptedTurn(text="hi")])
    agent = ResearchAgent(provider=provider, ctx=tool_ctx)
    await collect(agent, "hello")
    sent = provider.calls[0]
    assert "population geneticist" in sent["system"]
    assert "never state a number" in sent["system"].lower()
    names = {t.name for t in sent["tools"]}
    assert {"run_qpadm", "fit_admixture", "retrieve_knowledge", "compare_models"} <= names


async def test_tool_allowlist_restricts_the_tool_set(tool_ctx: ToolContext) -> None:
    provider = ScriptedProvider([ScriptedTurn(text="hi")])
    agent = ResearchAgent(
        provider=provider,
        ctx=tool_ctx,
        config=AgentConfig(tools=["retrieve_knowledge", "get_population"]),
    )
    await collect(agent, "hello")
    assert {t.name for t in provider.calls[0]["tools"]} == {
        "retrieve_knowledge",
        "get_population",
    }


async def test_result_ids_flow_into_compare_models(tool_ctx: ToolContext) -> None:
    """The second turn compares the first turn's stored results, not restated numbers."""
    provider = ScriptedProvider(
        [
            ScriptedTurn(
                tool_calls=[
                    (
                        "fit_admixture",
                        {
                            "target": {"dataset_id": "ds-1"},
                            "sources": ["Onge.SG", "Iran_GanjDareh_N"],
                        },
                    ),
                    (
                        "fit_admixture",
                        {
                            "target": {"dataset_id": "ds-1"},
                            "sources": ["Onge.SG", "Russia_Steppe_MLBA"],
                        },
                    ),
                ]
            ),
            ScriptedTurn(tool_calls=[("compare_models", {"result_ids": ["r1", "r2"]})]),
            ScriptedTurn(text="Both are exploratory; neither is a formal test."),
        ]
    )
    agent = ResearchAgent(provider=provider, ctx=tool_ctx)
    events = await collect(agent, "compare two source sets")
    results = [e for e in events if isinstance(e, ToolResultEvent)]
    assert all(r.ok for r in results), [r.error for r in results]
    table = results[-1].result
    assert len(table["exploratory_table"]) == 2
    assert table["formal_table"] == []
    assert any("never ranked together" in n for n in table["notes"])


async def test_citations_are_collected_from_the_answer(tool_ctx: ToolContext) -> None:
    provider = ScriptedProvider(
        [
            ScriptedTurn(
                text="Right-population choice matters [methods/qpadm#choice-of-right-populations] "
                "and projection shrinks coordinates [methods/pca#projection-and-shrinkage]."
            )
        ]
    )
    agent = ResearchAgent(provider=provider, ctx=tool_ctx)
    final = done_of(await collect(agent, "explain"))
    assert final.citations == [
        "methods/pca#projection-and-shrinkage",
        "methods/qpadm#choice-of-right-populations",
    ]


async def test_grounding_flags_a_number_no_tool_produced(tool_ctx: ToolContext) -> None:
    provider = ScriptedProvider(
        [
            ScriptedTurn(tool_calls=[("get_population", {"population_id": "Onge.SG"})]),
            # 0.37 appears in no tool result.
            ScriptedTurn(text="The Onge contribution is 0.37 of the target's ancestry."),
        ]
    )
    agent = ResearchAgent(provider=provider, ctx=tool_ctx)
    final = done_of(await collect(agent, "how much Onge?"))
    assert not final.grounding.ok
    assert [i.value for i in final.grounding.ungrounded] == ["0.37"]
    assert "0.37" in final.grounding.ungrounded[0].context


async def test_grounding_passes_when_numbers_come_from_tools(tool_ctx: ToolContext) -> None:
    provider = ScriptedProvider(
        [
            ScriptedTurn(tool_calls=[("get_population", {"population_id": "Iran_GanjDareh_N"})]),
            # 9800 and 34.3 are in the fixture's metadata for that population.
            ScriptedTurn(text="That population is dated 9800 BP at latitude 34.3."),
        ]
    )
    agent = ResearchAgent(provider=provider, ctx=tool_ctx)
    final = done_of(await collect(agent, "dates please"))
    assert final.grounding.ok, [i.model_dump() for i in final.grounding.ungrounded]


async def test_stream_chat_yields_plain_dicts(tool_ctx: ToolContext) -> None:
    provider = ScriptedProvider(
        [
            ScriptedTurn(tool_calls=[("get_population", {"population_id": "Han.DG"})]),
            ScriptedTurn(text="Done."),
        ]
    )
    events = [
        ev
        async for ev in stream_chat(
            [
                {"role": "user", "content": "earlier question"},
                {"role": "assistant", "content": "earlier answer"},
            ],
            "and now?",
            ctx=tool_ctx,
            provider=provider,
            config=AgentConfig(max_steps=4),
        )
    ]
    assert all(isinstance(e, dict) and "type" in e for e in events)
    types = [e["type"] for e in events]
    assert types[-1] == "done"
    assert "tool_call" in types and "tool_result" in types
    import json

    json.dumps(events, default=str)
    # History was passed through to the provider ahead of the new message.
    assert len(provider.calls[0]["messages"]) == 3


# ---- grounding check in isolation ------------------------------------------------------------

TOOL_OUTPUT = [
    {"weights": [{"left": "A", "weight": 0.4213, "se": 0.0517}], "p": 0.2134, "n_snps": 142318},
    {"fit": {"distance": 0.03621}},
]


def test_grounding_accepts_rounded_values() -> None:
    rep = grounding_check(
        "p = 0.21, weight 0.42 (SE 0.05), distance 0.036, on 142,318 SNPs.", TOOL_OUTPUT
    )
    assert rep.ok, [i.model_dump() for i in rep.ungrounded]
    assert rep.checked >= 4


def test_grounding_accepts_a_percentage_of_a_fraction() -> None:
    assert grounding_check("Roughly 42% of the ancestry.", TOOL_OUTPUT).ok


def test_grounding_rejects_a_wrong_digit() -> None:
    rep = grounding_check("The p-value was 0.57.", TOOL_OUTPUT)
    assert not rep.ok and rep.ungrounded[0].value == "0.57"


def test_grounding_ignores_small_integers_citations_and_identifiers() -> None:
    rep = grounding_check(
        "I tested 3 models using 2 sources, see [methods/qpadm#p-values], along PC1 and "
        "f4 statistics, as reported by Reich et al. 2009.",
        TOOL_OUTPUT,
    )
    assert rep.ok, [i.model_dump() for i in rep.ungrounded]


def test_grounding_reads_numbers_out_of_nested_tool_output() -> None:
    nested = [{"a": {"b": [{"c": 0.98765}]}}]
    assert grounding_check("The value is 0.9877.", nested).ok
    assert not grounding_check("The value is 0.5.", nested).ok


def test_grounding_with_no_numbers_is_ok() -> None:
    rep = grounding_check("No model was rejected, and no numbers are quoted here.", [])
    assert rep.ok and rep.checked == 0
