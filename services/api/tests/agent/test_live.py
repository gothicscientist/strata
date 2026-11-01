"""Opt-in live provider tests.

Skipped unless an API key is configured in the environment AND the ``live`` marker is
selected, because these tests make real, billed API calls:

    pytest tests/agent/test_live.py -m live

The key's value is never read, printed or asserted on - only its presence is checked.
"""

from __future__ import annotations

import os

import pytest

from strata.agent.agent import AgentConfig, ResearchAgent
from strata.agent.events import DoneEvent, MessageDone, TextDelta, ToolCallEvent, ToolResultEvent
from strata.agent.providers import AnthropicProvider, ProviderSettings
from strata.agent.tools import ToolContext

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")),
        reason="no Anthropic credentials configured",
    ),
]

MODEL = os.environ.get("STRATA_LLM_MODEL", "claude-opus-5-5")


def live_provider() -> AnthropicProvider:
    return AnthropicProvider(
        ProviderSettings(model=MODEL, max_tokens=4096, effort="low", timeout_s=120.0)
    )


async def test_live_text_stream() -> None:
    from strata.agent.events import UserMessage

    provider = live_provider()
    events = [
        ev
        async for ev in provider.stream(
            system="Answer in one short sentence.",
            tools=[],
            messages=[UserMessage(content="Reply with the single word: ready.")],
        )
    ]
    assert any(isinstance(e, TextDelta) for e in events)
    done = events[-1]
    assert isinstance(done, MessageDone)
    assert done.stop_reason in {"end_turn", "max_tokens"}
    assert done.usage.input_tokens > 0 and done.usage.output_tokens > 0
    assert done.message is not None and done.message.text.strip()


async def test_live_loop_uses_a_tool_and_grounds_its_numbers(tool_ctx: ToolContext) -> None:
    """The model must consult the library through tools rather than answering from memory."""
    agent = ResearchAgent(
        provider=live_provider(),
        ctx=tool_ctx,
        config=AgentConfig(
            max_steps=4, tools=["search_populations", "get_population", "retrieve_knowledge"]
        ),
    )
    events = [
        ev
        async for ev in agent.run(
            [
                {
                    "role": "user",
                    "content": (
                        "Using only the reference library tools, how many samples does the "
                        "population with id Iran_GanjDareh_N have, and what is its date in years "
                        "BP? Then state in one sentence why a qpAdm p-value above 0.05 does not "
                        "prove a model."
                    ),
                }
            ]
        )
    ]
    calls = [e for e in events if isinstance(e, ToolCallEvent)]
    results = [e for e in events if isinstance(e, ToolResultEvent)]
    assert calls, "the model answered without calling any tool"
    assert any(r.ok for r in results)

    final = events[-1]
    assert isinstance(final, DoneEvent)
    assert final.answer.strip()
    # Every number in the answer must trace back to a tool result.
    assert final.grounding.ok, [i.model_dump() for i in final.grounding.ungrounded]
    assert final.usage.input_tokens > 0


async def test_live_prompt_caching_reports_cache_activity(tool_ctx: ToolContext) -> None:
    """A second identical request should read the cached system + tool prefix."""
    provider = live_provider()
    from strata.agent.events import UserMessage
    from strata.agent.tools import tool_specs

    specs = tool_specs(["search_populations", "get_population"])
    system = "You are a terse assistant. " + "Reply with the single word: ok. " * 200
    messages = [UserMessage(content="Reply with the single word: ok.")]

    totals = []
    for _ in range(2):
        async for ev in provider.stream(system=system, tools=specs, messages=messages):
            if isinstance(ev, MessageDone):
                totals.append(ev.usage)
    assert len(totals) == 2
    cache_activity = sum(u.cache_creation_input_tokens + u.cache_read_input_tokens for u in totals)
    assert cache_activity > 0, "no cache writes or reads were reported"
