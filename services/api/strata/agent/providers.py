"""LLM provider abstraction: Anthropic Messages API and OpenAI Chat Completions.

Both providers expose ``stream(...)`` yielding a normalised event stream:

* ``TextDelta``      - incremental assistant text
* ``ToolCallEvent``  - a complete, parsed tool call (emitted once the turn is complete)
* ``MessageDone``    - end of one model turn, with stop reason, usage/cost and the turn itself
* ``ErrorEvent``     - a failure; the stream ends after it

``tool_result`` events are produced by the agent loop, not by providers.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any

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
    ToolResultsMessage,
    ToolSpec,
    Usage,
    UserMessage,
)

DEFAULT_ANTHROPIC_MODEL = "claude-opus-5-5"
DEFAULT_OPENAI_MODEL = "gpt-5"

# USD per 1M tokens: (input, output, cache_read, cache_write_5m). Anthropic first-party rates.
_PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-opus-5-5": (4.00, 20.00, 0.20, 5.00),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20, 2.50),
    "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125),
}

# Models on which the server-side refusal fallback ("default" routing) is supported.
_FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"}
_FALLBACK_BETA = "server-side-fallback-2026-07-01"


def _price_for(model: str) -> tuple[float, float, float, float] | None:
    """Price table lookup; env STRATA_LLM_PRICE='in,out[,cache_read,cache_write]' overrides."""
    override = os.environ.get("STRATA_LLM_PRICE")
    if override:
        try:
            parts = [float(p) for p in override.split(",")]
        except ValueError:
            return None
        if len(parts) == 2:
            parts += [parts[0], parts[0]]
        if len(parts) == 4:
            return parts[0], parts[1], parts[2], parts[3]
        return None
    return _PRICES.get(model)


def estimate_cost(model: str, usage: Usage) -> float | None:
    price = _price_for(model)
    if price is None:
        return None
    p_in, p_out, p_read, p_write = price
    return (
        usage.input_tokens * p_in
        + usage.output_tokens * p_out
        + usage.cache_read_input_tokens * p_read
        + usage.cache_creation_input_tokens * p_write
    ) / 1_000_000


@dataclass
class ProviderSettings:
    model: str
    max_tokens: int = 32000
    timeout_s: float = 300.0
    sdk_max_retries: int = 2
    # Extra retries on transient failures that happen before any output was streamed.
    retries_before_output: int = 2
    effort: str | None = "high"  # Anthropic output_config.effort
    fallbacks: bool = True  # Anthropic server-side refusal fallback


class LLMProvider(ABC):
    name: str
    settings: ProviderSettings

    @property
    def model(self) -> str:
        return self.settings.model

    @abstractmethod
    def stream(
        self,
        *,
        system: str,
        tools: Sequence[ToolSpec],
        messages: Sequence[ConvMessage],
    ) -> AsyncIterator[ProviderEvent | ToolCallEvent]:
        """Run one model turn and stream normalised events."""

    async def _with_retries(
        self,
        attempt_fn: Any,
        is_retryable: Any,
    ) -> AsyncIterator[ProviderEvent | ToolCallEvent]:
        """Retry an attempt generator on transient errors as long as nothing was yielded."""
        attempt = 0
        while True:
            emitted = False
            try:
                async for ev in attempt_fn():
                    emitted = True
                    yield ev
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - normalised into an ErrorEvent
                retryable = bool(is_retryable(exc))
                if retryable and not emitted and attempt < self.settings.retries_before_output:
                    attempt += 1
                    await asyncio.sleep(min(8.0, 0.5 * 2**attempt) + random.random() * 0.25)
                    continue
                yield ErrorEvent(message=f"{type(exc).__name__}: {exc}", retryable=retryable)
                return


def _parse_args(raw: str) -> tuple[dict[str, Any], str | None]:
    if not raw or not raw.strip():
        return {}, None
    try:
        val = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {}, f"invalid JSON arguments: {exc}"
    if not isinstance(val, dict):
        return {}, "tool arguments must be a JSON object"
    return val, None


# ---- Anthropic -------------------------------------------------------------------------------


class AnthropicProvider(LLMProvider):
    """Anthropic Messages API (streaming, tool use, prompt caching on tools + system)."""

    name = "anthropic"

    def __init__(self, settings: ProviderSettings | None = None, client: Any = None) -> None:
        self.settings = settings or ProviderSettings(model=DEFAULT_ANTHROPIC_MODEL)
        if client is None:
            import anthropic

            client = anthropic.AsyncAnthropic(
                timeout=self.settings.timeout_s, max_retries=self.settings.sdk_max_retries
            )
        self._client = client

    # -- request building
    def build_tools(self, tools: Sequence[ToolSpec]) -> list[dict[str, Any]]:
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
                "eager_input_streaming": True,
            }
            for t in tools
        ]

    def build_system(self, system: str) -> list[dict[str, Any]]:
        # Render order is tools -> system -> messages, so this breakpoint caches both the tool
        # definitions and the (frozen) system prompt.
        return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]

    def build_messages(self, messages: Sequence[ConvMessage]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for m in messages:
            if isinstance(m, UserMessage):
                out.append({"role": "user", "content": [{"type": "text", "text": m.content}]})
            elif isinstance(m, AssistantMessage):
                if m.native_provider == self.name and m.native is not None:
                    content = m.native
                else:
                    content = []
                    if m.text:
                        content.append({"type": "text", "text": m.text})
                    for tc in m.tool_calls:
                        content.append(
                            {
                                "type": "tool_use",
                                "id": tc.id,
                                "name": tc.name,
                                "input": tc.arguments,
                            }
                        )
                out.append({"role": "assistant", "content": content})
            elif isinstance(m, ToolResultsMessage):
                out.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": r.tool_call_id,
                                "content": r.content,
                                "is_error": r.is_error,
                            }
                            for r in m.results
                        ],
                    }
                )
        # Moving cache breakpoint on the newest block: each loop step reuses the prior prefix.
        if out and out[-1]["content"]:
            last = dict(out[-1]["content"][-1])
            last["cache_control"] = {"type": "ephemeral"}
            out[-1] = {**out[-1], "content": [*out[-1]["content"][:-1], last]}
        return out

    def request_kwargs(
        self, system: str, tools: Sequence[ToolSpec], messages: Sequence[ConvMessage]
    ) -> dict[str, Any]:
        kw: dict[str, Any] = {
            "model": self.settings.model,
            "max_tokens": self.settings.max_tokens,
            "system": self.build_system(system),
            "messages": self.build_messages(messages),
        }
        if tools:
            kw["tools"] = self.build_tools(tools)
        if self.settings.effort:
            kw["output_config"] = {"effort": self.settings.effort}
        if self.settings.fallbacks and self.settings.model in _FALLBACK_MODELS:
            kw["betas"] = [_FALLBACK_BETA]
            kw["fallbacks"] = "default"
        return kw

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        import anthropic

        return isinstance(
            exc,
            anthropic.RateLimitError
            | anthropic.APIConnectionError
            | anthropic.InternalServerError
            | anthropic.OverloadedError,
        )

    def stream(
        self,
        *,
        system: str,
        tools: Sequence[ToolSpec],
        messages: Sequence[ConvMessage],
    ) -> AsyncIterator[ProviderEvent | ToolCallEvent]:
        kwargs = self.request_kwargs(system, tools, messages)
        return self._with_retries(lambda: self._attempt(kwargs), self._is_retryable)

    async def _attempt(
        self, kwargs: dict[str, Any]
    ) -> AsyncIterator[ProviderEvent | ToolCallEvent]:
        async with self._client.beta.messages.stream(**kwargs) as stream:
            async for event in stream:
                if event.type == "text":
                    yield TextDelta(text=event.text)
            final = await stream.get_final_message()

        texts: list[str] = []
        calls: list[ToolCall] = []
        for block in final.content:
            if block.type == "text":
                texts.append(block.text)
            elif block.type == "tool_use":
                args = block.input if isinstance(block.input, dict) else {}
                err = None if isinstance(block.input, dict) else "tool input is not an object"
                calls.append(
                    ToolCall(id=block.id, name=block.name, arguments=args, parse_error=err)
                )

        stop = _map_anthropic_stop(final.stop_reason)
        u = final.usage
        usage = Usage(
            input_tokens=u.input_tokens or 0,
            output_tokens=u.output_tokens or 0,
            cache_read_input_tokens=getattr(u, "cache_read_input_tokens", None) or 0,
            cache_creation_input_tokens=getattr(u, "cache_creation_input_tokens", None) or 0,
        )
        usage.cost_usd = estimate_cost(self.settings.model, usage)
        native = [
            b.model_dump(mode="json", by_alias=True, exclude_none=True) for b in final.content
        ]
        msg = AssistantMessage(
            text="".join(texts),
            tool_calls=calls if stop == "tool_use" else [],
            native_provider=self.name,
            native=native,
        )
        if stop == "tool_use":
            for c in calls:
                yield ToolCallEvent(id=c.id, name=c.name, arguments=c.arguments)
        yield MessageDone(stop_reason=stop, usage=usage, model=final.model, message=msg)


def _map_anthropic_stop(reason: str | None) -> StopReason:
    return {
        "end_turn": "end_turn",
        "stop_sequence": "end_turn",
        "tool_use": "tool_use",
        "max_tokens": "max_tokens",
        "refusal": "refusal",
        "pause_turn": "end_turn",
    }.get(reason or "", "end_turn")  # type: ignore[return-value]


# ---- OpenAI ----------------------------------------------------------------------------------


class OpenAIProvider(LLMProvider):
    """OpenAI Chat Completions with function calling and streaming."""

    name = "openai"

    def __init__(self, settings: ProviderSettings | None = None, client: Any = None) -> None:
        self.settings = settings or ProviderSettings(model=DEFAULT_OPENAI_MODEL)
        if client is None:
            import openai

            client = openai.AsyncOpenAI(
                timeout=self.settings.timeout_s, max_retries=self.settings.sdk_max_retries
            )
        self._client = client

    def build_tools(self, tools: Sequence[ToolSpec]) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.input_schema,
                },
            }
            for t in tools
        ]

    def build_messages(self, system: str, messages: Sequence[ConvMessage]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for m in messages:
            if isinstance(m, UserMessage):
                out.append({"role": "user", "content": m.content})
            elif isinstance(m, AssistantMessage):
                msg: dict[str, Any] = {"role": "assistant", "content": m.text or None}
                if m.tool_calls:
                    msg["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                        }
                        for tc in m.tool_calls
                    ]
                out.append(msg)
            elif isinstance(m, ToolResultsMessage):
                for r in m.results:
                    content = r.content if not r.is_error else json.dumps({"error": r.content})
                    out.append({"role": "tool", "tool_call_id": r.tool_call_id, "content": content})
        return out

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        import openai

        return isinstance(
            exc, openai.RateLimitError | openai.APIConnectionError | openai.InternalServerError
        )

    def stream(
        self,
        *,
        system: str,
        tools: Sequence[ToolSpec],
        messages: Sequence[ConvMessage],
    ) -> AsyncIterator[ProviderEvent | ToolCallEvent]:
        kwargs: dict[str, Any] = {
            "model": self.settings.model,
            "messages": self.build_messages(system, messages),
            "max_completion_tokens": self.settings.max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            kwargs["tools"] = self.build_tools(tools)
        return self._with_retries(lambda: self._attempt(kwargs), self._is_retryable)

    async def _attempt(
        self, kwargs: dict[str, Any]
    ) -> AsyncIterator[ProviderEvent | ToolCallEvent]:
        stream = await self._client.chat.completions.create(**kwargs)
        text_parts: list[str] = []
        partial: dict[int, dict[str, str]] = {}
        finish: str | None = None
        usage = Usage()
        model = kwargs["model"]
        async for chunk in stream:
            if getattr(chunk, "model", None):
                model = chunk.model
            if getattr(chunk, "usage", None):
                cu = chunk.usage
                cached = 0
                details = getattr(cu, "prompt_tokens_details", None)
                if details is not None:
                    cached = getattr(details, "cached_tokens", 0) or 0
                usage = Usage(
                    input_tokens=(cu.prompt_tokens or 0) - cached,
                    output_tokens=cu.completion_tokens or 0,
                    cache_read_input_tokens=cached,
                )
            for choice in chunk.choices or []:
                delta = choice.delta
                if delta is not None:
                    if delta.content:
                        text_parts.append(delta.content)
                        yield TextDelta(text=delta.content)
                    for tc in delta.tool_calls or []:
                        slot = partial.setdefault(tc.index, {"id": "", "name": "", "args": ""})
                        if tc.id:
                            slot["id"] = tc.id
                        if tc.function is not None:
                            if tc.function.name:
                                slot["name"] += tc.function.name
                            if tc.function.arguments:
                                slot["args"] += tc.function.arguments
                if choice.finish_reason:
                    finish = choice.finish_reason

        calls: list[ToolCall] = []
        for idx in sorted(partial):
            slot = partial[idx]
            args, err = _parse_args(slot["args"])
            calls.append(
                ToolCall(
                    id=slot["id"] or f"call_{idx}",
                    name=slot["name"],
                    arguments=args,
                    parse_error=err,
                )
            )
        stop: StopReason = {
            "stop": "end_turn",
            "tool_calls": "tool_use",
            "function_call": "tool_use",
            "length": "max_tokens",
            "content_filter": "refusal",
        }.get(finish or "stop", "end_turn")  # type: ignore[assignment]
        if calls and stop == "end_turn":
            stop = "tool_use"
        usage.cost_usd = estimate_cost(self.settings.model, usage)
        msg = AssistantMessage(
            text="".join(text_parts),
            tool_calls=calls if stop == "tool_use" else [],
            native_provider=self.name,
        )
        if stop == "tool_use":
            for c in calls:
                yield ToolCallEvent(id=c.id, name=c.name, arguments=c.arguments)
        yield MessageDone(stop_reason=stop, usage=usage, model=model, message=msg)


# ---- factory ---------------------------------------------------------------------------------


def llm_available() -> dict[str, bool]:
    """Which providers have credentials configured (without reading key values)."""
    return {
        "anthropic": bool(
            os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        ),
        "openai": bool(os.environ.get("OPENAI_API_KEY")),
    }


def get_provider(name: str | None = None, model: str | None = None) -> LLMProvider:
    """Construct the configured provider.

    Env: STRATA_LLM_PROVIDER (anthropic|openai), STRATA_LLM_MODEL, STRATA_LLM_MAX_TOKENS,
    STRATA_LLM_TIMEOUT_S, STRATA_LLM_EFFORT (Anthropic), STRATA_ANTHROPIC_FALLBACKS (on|off),
    STRATA_OPENAI_MODEL (used when provider is openai and STRATA_LLM_MODEL is unset).
    """
    name = (name or os.environ.get("STRATA_LLM_PROVIDER") or "anthropic").lower()
    env_model = os.environ.get("STRATA_LLM_MODEL")
    common: dict[str, Any] = {
        "max_tokens": int(os.environ.get("STRATA_LLM_MAX_TOKENS", "32000")),
        "timeout_s": float(os.environ.get("STRATA_LLM_TIMEOUT_S", "300")),
    }
    if name == "anthropic":
        settings = ProviderSettings(
            model=model or env_model or DEFAULT_ANTHROPIC_MODEL,
            effort=os.environ.get("STRATA_LLM_EFFORT", "high") or None,
            fallbacks=os.environ.get("STRATA_ANTHROPIC_FALLBACKS", "on").lower() != "off",
            **common,
        )
        return AnthropicProvider(settings)
    if name == "openai":
        settings = ProviderSettings(
            model=model
            or env_model
            or os.environ.get("STRATA_OPENAI_MODEL")
            or DEFAULT_OPENAI_MODEL,
            effort=None,
            fallbacks=False,
            **common,
        )
        return OpenAIProvider(settings)
    raise ValueError(f"unknown LLM provider {name!r} (expected 'anthropic' or 'openai')")
