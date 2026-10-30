"""Provider-agnostic conversation and event types for the research agent.

Every event is a pydantic model with a ``type`` discriminator so it can be serialised directly
into an SSE frame (``event.model_dump(mode="json")``).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

StopReason = Literal["end_turn", "tool_use", "max_tokens", "refusal", "error", "cancelled"]


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cost_usd: float | None = None

    def add(self, other: Usage) -> Usage:
        cost: float | None
        if self.cost_usd is None and other.cost_usd is None:
            cost = None
        else:
            cost = (self.cost_usd or 0.0) + (other.cost_usd or 0.0)
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_input_tokens=self.cache_read_input_tokens + other.cache_read_input_tokens,
            cache_creation_input_tokens=(
                self.cache_creation_input_tokens + other.cache_creation_input_tokens
            ),
            cost_usd=cost,
        )


class ToolSpec(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    # Set by a provider when the model emitted arguments that could not be parsed as JSON.
    parse_error: str | None = None


# ---- conversation messages -------------------------------------------------------------------


class UserMessage(BaseModel):
    role: Literal["user"] = "user"
    content: str


class AssistantMessage(BaseModel):
    role: Literal["assistant"] = "assistant"
    text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    # Provider-native content (e.g. Anthropic content blocks incl. thinking signatures) so the
    # same provider can replay the turn byte-for-byte. Other providers rebuild from text/tools.
    native_provider: str | None = None
    native: Any = None


class ToolResult(BaseModel):
    tool_call_id: str
    name: str
    content: str  # JSON-encoded tool output
    is_error: bool = False


class ToolResultsMessage(BaseModel):
    role: Literal["tool"] = "tool"
    results: list[ToolResult]


ConvMessage = UserMessage | AssistantMessage | ToolResultsMessage


# ---- streamed events -------------------------------------------------------------------------


class TextDelta(BaseModel):
    type: Literal["text_delta"] = "text_delta"
    text: str


class ToolCallEvent(BaseModel):
    type: Literal["tool_call"] = "tool_call"
    id: str
    name: str
    arguments: dict[str, Any]


class ToolResultEvent(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    id: str
    name: str
    ok: bool
    result: Any = None
    error: str | None = None
    duration_ms: int = 0


class MessageDone(BaseModel):
    type: Literal["message_done"] = "message_done"
    stop_reason: StopReason
    usage: Usage = Field(default_factory=Usage)
    model: str | None = None
    # The completed assistant turn; excluded from SSE payloads (it is internal state).
    message: AssistantMessage | None = Field(default=None, exclude=True)


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    message: str
    retryable: bool = False


class GroundingIssue(BaseModel):
    value: str
    context: str


class GroundingReport(BaseModel):
    ok: bool
    checked: int
    ungrounded: list[GroundingIssue] = Field(default_factory=list)


class DoneEvent(BaseModel):
    type: Literal["done"] = "done"
    answer: str
    grounding: GroundingReport
    citations: list[str] = Field(default_factory=list)
    transcript: list[dict[str, Any]] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    steps: int = 0
    cancelled: bool = False
    stop_reason: StopReason = "end_turn"


ProviderEvent = TextDelta | MessageDone | ErrorEvent
AgentEvent = TextDelta | ToolCallEvent | ToolResultEvent | MessageDone | ErrorEvent | DoneEvent
