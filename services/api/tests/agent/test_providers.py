"""Provider request building, event normalisation, retries and cost accounting.

The SDK clients are replaced by stubs; no network calls are made.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from strata.agent.events import (
    AssistantMessage,
    ErrorEvent,
    MessageDone,
    TextDelta,
    ToolCall,
    ToolCallEvent,
    ToolResult,
    ToolResultsMessage,
    ToolSpec,
    Usage,
    UserMessage,
)
from strata.agent.providers import (
    AnthropicProvider,
    OpenAIProvider,
    ProviderSettings,
    estimate_cost,
    get_provider,
    llm_available,
)

TOOLS = [
    ToolSpec(
        name="get_population",
        description="Fetch one population",
        input_schema={"type": "object", "properties": {"population_id": {"type": "string"}}},
    )
]


# ---- Anthropic -------------------------------------------------------------------------------


class FakeAnthropicStream:
    def __init__(self, texts: list[str], final: Any) -> None:
        self._texts = texts
        self._final = final

    async def __aenter__(self) -> FakeAnthropicStream:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def __aiter__(self):  # noqa: ANN204 - async generator
        for t in self._texts:
            yield SimpleNamespace(type="text", text=t)

    async def get_final_message(self) -> Any:
        return self._final


class FakeBlock(SimpleNamespace):
    def model_dump(self, **kw: Any) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}


def anthropic_message(
    *, text: str = "", tool_uses: list[tuple[str, str, Any]] = (), stop: str = "end_turn"
) -> Any:
    content = []
    if text:
        content.append(FakeBlock(type="text", text=text))
    for tid, name, inp in tool_uses:
        content.append(FakeBlock(type="tool_use", id=tid, name=name, input=inp))
    return SimpleNamespace(
        content=content,
        stop_reason=stop,
        model="claude-opus-5-5",
        usage=SimpleNamespace(
            input_tokens=1000,
            output_tokens=50,
            cache_read_input_tokens=800,
            cache_creation_input_tokens=0,
        ),
    )


class FakeAnthropicClient:
    def __init__(
        self, messages: list[Any], error: Exception | None = None, fail_times: int = 0
    ) -> None:
        self._messages = messages
        self._error = error
        self._fail_times = fail_times
        self.requests: list[dict[str, Any]] = []
        self.beta = SimpleNamespace(messages=self)

    def stream(self, **kwargs: Any) -> FakeAnthropicStream:
        self.requests.append(kwargs)
        if self._fail_times > 0:
            self._fail_times -= 1
            assert self._error is not None
            raise self._error
        msg = self._messages[min(len(self.requests) - 1, len(self._messages) - 1)]
        texts = [b.text for b in msg.content if b.type == "text"]
        return FakeAnthropicStream(texts, msg)


def anthropic_provider(client: Any, **kw: Any) -> AnthropicProvider:
    settings = ProviderSettings(model="claude-opus-5-5", **kw)
    return AnthropicProvider(settings, client=client)


def test_anthropic_request_has_caching_tools_and_fallbacks() -> None:
    client = FakeAnthropicClient([anthropic_message(text="hi")])
    provider = anthropic_provider(client)
    kwargs = provider.request_kwargs(
        "SYSTEM",
        TOOLS,
        [
            UserMessage(content="first"),
            AssistantMessage(
                text="answer",
                tool_calls=[
                    ToolCall(id="t1", name="get_population", arguments={"population_id": "X"})
                ],
            ),
            ToolResultsMessage(
                results=[
                    ToolResult(tool_call_id="t1", name="get_population", content='{"ok":true}')
                ]
            ),
        ],
    )
    # System prompt carries the cache breakpoint (tools render before system).
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert kwargs["tools"][0]["name"] == "get_population"
    assert kwargs["tools"][0]["eager_input_streaming"] is True
    assert kwargs["output_config"] == {"effort": "high"}
    assert kwargs["fallbacks"] == "default"
    assert kwargs["betas"] == ["server-side-fallback-2026-07-01"]
    assert kwargs["max_tokens"] == provider.settings.max_tokens

    msgs = kwargs["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assert msgs[1]["content"][1]["type"] == "tool_use"
    assert msgs[2]["content"][0]["tool_use_id"] == "t1"
    # A moving breakpoint on the newest block keeps the prior prefix cached.
    assert msgs[-1]["content"][-1]["cache_control"] == {"type": "ephemeral"}


def test_anthropic_replays_native_blocks_for_its_own_turns() -> None:
    provider = anthropic_provider(FakeAnthropicClient([]))
    native = [
        {"type": "thinking", "thinking": "", "signature": "sig"},
        {"type": "text", "text": "answer"},
    ]
    msgs = provider.build_messages(
        [AssistantMessage(text="answer", native_provider="anthropic", native=native)]
    )
    assert msgs[0]["content"][0]["type"] == "thinking"

    # A turn produced by another provider is rebuilt from text and tool calls.
    msgs = provider.build_messages(
        [AssistantMessage(text="answer", native_provider="openai", native={"ignored": True})]
    )
    assert msgs[0]["content"][0] == {
        "type": "text",
        "text": "answer",
        "cache_control": {"type": "ephemeral"},
    }


def test_anthropic_settings_can_disable_effort_and_fallbacks() -> None:
    provider = anthropic_provider(FakeAnthropicClient([]), effort=None, fallbacks=False)
    kwargs = provider.request_kwargs("S", [], [UserMessage(content="x")])
    assert "output_config" not in kwargs and "fallbacks" not in kwargs
    assert "tools" not in kwargs


async def test_anthropic_stream_normalises_text_and_tool_calls() -> None:
    msg = anthropic_message(
        text="Looking it up. ",
        tool_uses=[("t1", "get_population", {"population_id": "Onge.SG"})],
        stop="tool_use",
    )
    provider = anthropic_provider(FakeAnthropicClient([msg]))
    events = [
        e
        async for e in provider.stream(
            system="S", tools=TOOLS, messages=[UserMessage(content="go")]
        )
    ]
    assert isinstance(events[0], TextDelta) and events[0].text == "Looking it up. "
    call = next(e for e in events if isinstance(e, ToolCallEvent))
    assert call.name == "get_population" and call.arguments == {"population_id": "Onge.SG"}
    done = events[-1]
    assert isinstance(done, MessageDone)
    assert done.stop_reason == "tool_use"
    assert done.message is not None and done.message.native_provider == "anthropic"
    assert done.message.tool_calls[0].id == "t1"
    # 1000 input @ $4, 800 cache reads @ $0.20, 50 output @ $20 per MTok.
    assert done.usage.cache_read_input_tokens == 800
    assert done.usage.cost_usd == pytest.approx((1000 * 4 + 50 * 20 + 800 * 0.2) / 1e6)


async def test_anthropic_maps_refusal_and_max_tokens() -> None:
    for raw, expected in [
        ("refusal", "refusal"),
        ("max_tokens", "max_tokens"),
        ("stop_sequence", "end_turn"),
        ("pause_turn", "end_turn"),
    ]:
        provider = anthropic_provider(FakeAnthropicClient([anthropic_message(text="x", stop=raw)]))
        events = [
            e
            async for e in provider.stream(
                system="S", tools=[], messages=[UserMessage(content="go")]
            )
        ]
        assert isinstance(events[-1], MessageDone)
        assert events[-1].stop_reason == expected


async def test_anthropic_retries_transient_errors_then_succeeds() -> None:
    import anthropic as anthropic_sdk

    err = anthropic_sdk.APIConnectionError(request=None)  # type: ignore[arg-type]
    client = FakeAnthropicClient([anthropic_message(text="recovered")], error=err, fail_times=1)
    provider = anthropic_provider(client, retries_before_output=2)
    events = [
        e async for e in provider.stream(system="S", tools=[], messages=[UserMessage(content="go")])
    ]
    assert not any(isinstance(e, ErrorEvent) for e in events)
    assert isinstance(events[-1], MessageDone)
    assert len(client.requests) == 2


async def test_anthropic_gives_up_and_emits_an_error_event() -> None:
    import anthropic as anthropic_sdk

    err = anthropic_sdk.APIConnectionError(request=None)  # type: ignore[arg-type]
    client = FakeAnthropicClient([], error=err, fail_times=99)
    provider = anthropic_provider(client, retries_before_output=1)
    events = [
        e async for e in provider.stream(system="S", tools=[], messages=[UserMessage(content="go")])
    ]
    assert len(events) == 1
    assert isinstance(events[0], ErrorEvent)
    assert events[0].retryable is True
    assert "APIConnectionError" in events[0].message


async def test_anthropic_does_not_retry_a_non_retryable_error() -> None:
    client = FakeAnthropicClient([], error=ValueError("bad request shape"), fail_times=99)
    provider = anthropic_provider(client, retries_before_output=3)
    events = [
        e async for e in provider.stream(system="S", tools=[], messages=[UserMessage(content="go")])
    ]
    assert isinstance(events[0], ErrorEvent) and events[0].retryable is False
    assert len(client.requests) == 1


# ---- OpenAI ----------------------------------------------------------------------------------


def chunk(
    *,
    text: str | None = None,
    tool: tuple[int, str | None, str | None, str | None] | None = None,
    finish: str | None = None,
    usage: Any = None,
) -> Any:
    tool_calls = None
    if tool is not None:
        idx, tid, name, args = tool
        tool_calls = [
            SimpleNamespace(
                index=idx,
                id=tid,
                function=SimpleNamespace(name=name, arguments=args),
            )
        ]
    delta = SimpleNamespace(content=text, tool_calls=tool_calls)
    return SimpleNamespace(
        model="gpt-5",
        usage=usage,
        choices=[SimpleNamespace(delta=delta, finish_reason=finish)],
    )


class FakeOpenAIClient:
    def __init__(
        self, chunks: list[Any], error: Exception | None = None, fail_times: int = 0
    ) -> None:
        self._chunks = chunks
        self._error = error
        self._fail_times = fail_times
        self.requests: list[dict[str, Any]] = []
        self.chat = SimpleNamespace(completions=self)

    async def create(self, **kwargs: Any) -> Any:
        self.requests.append(kwargs)
        if self._fail_times > 0:
            self._fail_times -= 1
            assert self._error is not None
            raise self._error
        chunks = self._chunks

        async def gen():  # noqa: ANN202
            for c in chunks:
                yield c

        return gen()


def openai_provider(client: Any, **kw: Any) -> OpenAIProvider:
    return OpenAIProvider(
        ProviderSettings(model="gpt-5", effort=None, fallbacks=False, **kw), client=client
    )


def test_openai_message_and_tool_translation() -> None:
    provider = openai_provider(FakeOpenAIClient([]))
    msgs = provider.build_messages(
        "SYSTEM",
        [
            UserMessage(content="first"),
            AssistantMessage(
                text="partial",
                tool_calls=[
                    ToolCall(id="c1", name="get_population", arguments={"population_id": "X"})
                ],
            ),
            ToolResultsMessage(
                results=[
                    ToolResult(tool_call_id="c1", name="get_population", content='{"ok":true}'),
                    ToolResult(
                        tool_call_id="c2", name="get_population", content="boom", is_error=True
                    ),
                ]
            ),
        ],
    )
    assert msgs[0] == {"role": "system", "content": "SYSTEM"}
    assert msgs[2]["tool_calls"][0]["function"]["arguments"] == '{"population_id": "X"}'
    assert msgs[3] == {"role": "tool", "tool_call_id": "c1", "content": '{"ok":true}'}
    assert msgs[4]["content"] == '{"error": "boom"}'

    tools = provider.build_tools(TOOLS)
    assert tools[0]["type"] == "function"
    assert tools[0]["function"]["parameters"]["type"] == "object"


async def test_openai_stream_assembles_split_tool_arguments() -> None:
    usage = SimpleNamespace(
        prompt_tokens=500,
        completion_tokens=30,
        prompt_tokens_details=SimpleNamespace(cached_tokens=100),
    )
    client = FakeOpenAIClient(
        [
            chunk(text="Checking "),
            chunk(text="now. "),
            chunk(tool=(0, "c1", "get_population", '{"population')),
            chunk(tool=(0, None, None, '_id": "Onge.SG"}')),
            chunk(finish="tool_calls"),
            chunk(usage=usage),
        ]
    )
    provider = openai_provider(client)
    events = [
        e
        async for e in provider.stream(
            system="S", tools=TOOLS, messages=[UserMessage(content="go")]
        )
    ]
    texts = "".join(e.text for e in events if isinstance(e, TextDelta))
    assert texts == "Checking now. "
    call = next(e for e in events if isinstance(e, ToolCallEvent))
    assert call.id == "c1"
    assert call.arguments == {"population_id": "Onge.SG"}
    done = events[-1]
    assert isinstance(done, MessageDone) and done.stop_reason == "tool_use"
    assert done.usage.input_tokens == 400  # prompt minus cached
    assert done.usage.cache_read_input_tokens == 100
    assert client.requests[0]["stream_options"] == {"include_usage": True}
    assert client.requests[0]["max_completion_tokens"] == provider.settings.max_tokens


async def test_openai_reports_unparseable_tool_arguments() -> None:
    client = FakeOpenAIClient(
        [
            chunk(tool=(0, "c1", "get_population", '{"population_id": ')),
            chunk(finish="tool_calls"),
        ]
    )
    provider = openai_provider(client)
    events = [
        e
        async for e in provider.stream(
            system="S", tools=TOOLS, messages=[UserMessage(content="go")]
        )
    ]
    done = events[-1]
    assert isinstance(done, MessageDone)
    assert done.message is not None
    call = done.message.tool_calls[0]
    assert call.arguments == {}
    assert call.parse_error and "invalid JSON" in call.parse_error


async def test_openai_maps_finish_reasons() -> None:
    for finish, expected in [
        ("stop", "end_turn"),
        ("length", "max_tokens"),
        ("content_filter", "refusal"),
    ]:
        provider = openai_provider(FakeOpenAIClient([chunk(text="x", finish=finish)]))
        events = [
            e
            async for e in provider.stream(
                system="S", tools=[], messages=[UserMessage(content="go")]
            )
        ]
        assert isinstance(events[-1], MessageDone)
        assert events[-1].stop_reason == expected


async def test_openai_retries_rate_limit_errors() -> None:
    import httpx2
    import openai as openai_sdk

    response = httpx2.Response(429, request=httpx2.Request("POST", "https://api.openai.com"))
    err = openai_sdk.RateLimitError("slow down", response=response, body=None)
    client = FakeOpenAIClient([chunk(text="ok", finish="stop")], error=err, fail_times=1)
    provider = openai_provider(client, retries_before_output=2)
    events = [
        e async for e in provider.stream(system="S", tools=[], messages=[UserMessage(content="go")])
    ]
    assert not any(isinstance(e, ErrorEvent) for e in events)
    assert len(client.requests) == 2


# ---- cost accounting and factory --------------------------------------------------------------


def test_estimate_cost_uses_the_price_table() -> None:
    usage = Usage(input_tokens=1_000_000, output_tokens=1_000_000)
    assert estimate_cost("claude-opus-5-5", usage) == pytest.approx(24.0)
    assert estimate_cost("claude-sonnet-5-5", usage) == pytest.approx(12.0)
    assert estimate_cost("some-unpriced-model", usage) is None


def test_price_override_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STRATA_LLM_PRICE", "1,2")
    usage = Usage(input_tokens=1_000_000, output_tokens=1_000_000)
    assert estimate_cost("anything", usage) == pytest.approx(3.0)
    monkeypatch.setenv("STRATA_LLM_PRICE", "not,a,number")
    assert estimate_cost("anything", usage) is None


def test_usage_addition_handles_missing_costs() -> None:
    a = Usage(input_tokens=5, output_tokens=1, cost_usd=0.5)
    b = Usage(input_tokens=7, output_tokens=2)
    total = a.add(b)
    assert total.input_tokens == 12 and total.output_tokens == 3
    assert total.cost_usd == 0.5
    assert Usage().add(Usage()).cost_usd is None


def test_get_provider_defaults_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STRATA_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("STRATA_LLM_MODEL", raising=False)
    monkeypatch.setattr("anthropic.AsyncAnthropic", lambda **kw: object())
    provider = get_provider()
    assert provider.name == "anthropic"
    assert provider.model == "claude-opus-5-5"

    monkeypatch.setenv("STRATA_LLM_MODEL", "claude-sonnet-5-5")
    assert get_provider().model == "claude-sonnet-5-5"

    monkeypatch.setenv("STRATA_LLM_PROVIDER", "openai")
    monkeypatch.delenv("STRATA_LLM_MODEL", raising=False)
    monkeypatch.setenv("STRATA_OPENAI_MODEL", "gpt-5-mini")
    monkeypatch.setattr("openai.AsyncOpenAI", lambda **kw: object())
    provider = get_provider()
    assert provider.name == "openai" and provider.model == "gpt-5-mini"

    with pytest.raises(ValueError, match="unknown LLM provider"):
        get_provider("bedrock")


def test_llm_available_reports_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert llm_available() == {"anthropic": False, "openai": False}
    # Only presence is checked; the value is never read or logged.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "placeholder")
    assert llm_available()["anthropic"] is True
