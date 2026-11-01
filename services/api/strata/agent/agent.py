"""The Strata research loop.

``ResearchAgent.run`` alternates model turns and tool execution until the model stops calling
tools, the step budget is exhausted, or the caller cancels. Every tool call and result is
appended to an audit transcript. After the final answer a deterministic numeric grounding check
flags numbers in the answer that do not appear in any tool result.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from strata.agent.events import (
    AgentEvent,
    AssistantMessage,
    ConvMessage,
    DoneEvent,
    ErrorEvent,
    GroundingIssue,
    GroundingReport,
    MessageDone,
    StopReason,
    TextDelta,
    ToolCallEvent,
    ToolResult,
    ToolResultEvent,
    ToolResultsMessage,
    Usage,
    UserMessage,
)
from strata.agent.providers import LLMProvider, get_provider
from strata.agent.tools import ToolContext, execute_tool, tool_specs

SYSTEM_PROMPT = """\
You are Strata's research assistant: a careful computational population geneticist. You help \
users investigate ancestry questions with the analyses available as tools, and you report what \
the evidence does and does not support.

How you work
1. Clarify the question and state explicit, testable hypotheses (for example, competing source \
models for a target).
2. Choose references deliberately. Use search_populations, get_population and \
propose_reference_sets; justify sources and right (outgroup) populations by geography, date and \
genetic distance. Prefer sources that are not younger than the target.
3. Run analyses through tools. Exploratory coordinate fits (nearest_populations, fit_admixture, \
rotate_sources, sensitivity_analysis) are fast and useful for screening. Formal tests \
(run_qpadm, run_qpadm_rotate, run_f4) use f-statistics and are the evidence for admixture \
claims. If formal tools are unavailable, say so and keep conclusions exploratory.
4. Compare alternatives with compare_models, using result_ids from earlier tools.
5. Test robustness: rotate sources, run sensitivity analysis, and for qpAdm rotate right sets. \
A conclusion that depends on one reference choice is fragile; say so.
6. Use retrieve_knowledge for methodological points and cite the returned chunk ids in square \
brackets, e.g. [methods/qpadm#interpreting-p-values]. Only cite ids that a tool returned.

Rules
- Never state a number (weight, distance, p-value, SE, count, date) that did not come from a \
tool result in this conversation. If a number is not available, say it was not computed.
- Always label results as exploratory (G25/PCA coordinate fits) or formal (qpAdm/f-statistics). \
Never rank exploratory and formal scores together, and never describe a coordinate fit as \
proof of admixture.
- qpAdm p-values: a model with p above the threshold is "not rejected", not "proven"; several \
models can fit. Infeasible weights (negative or above one) mean the model is not supported.
- Report uncertainty: standard errors or bootstrap intervals, sensitivity to references, SNP \
overlap and data limitations of consumer genotype files.
- Ancestry proportions describe relationships to sampled reference populations; avoid \
ethnic, national or essentialist conclusions and avoid implying identity from genetics.
- You never see raw genotypes and must not ask for them.
- Be efficient: call independent tools in parallel in the same turn.

Final answer format: a short summary, then the evidence (with result types labelled), \
robustness checks performed, caveats and uncertainty, and suggested next steps.
"""


@dataclass
class AgentConfig:
    max_steps: int = 12
    max_parallel_tools: int = 6
    tool_timeout_s: float = 900.0
    system_prompt: str = SYSTEM_PROMPT
    tools: list[str] | None = None  # restrict to these tool names

    @classmethod
    def from_env(cls) -> AgentConfig:
        return cls(
            max_steps=int(os.environ.get("STRATA_AGENT_MAX_STEPS", "12")),
            max_parallel_tools=int(os.environ.get("STRATA_AGENT_MAX_PARALLEL_TOOLS", "6")),
            tool_timeout_s=float(os.environ.get("STRATA_AGENT_TOOL_TIMEOUT_S", "900")),
        )


# ---- numeric grounding -----------------------------------------------------------------------

_NUM_RE = re.compile(r"(?<![\w.])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][-+]?\d+)?%?")
_CITATION_RE = re.compile(r"\[([a-z]+/[A-Za-z0-9_.\-]+(?:#[A-Za-z0-9_\-]+)?)\]")


def _parse_number(tok: str) -> tuple[float, int, bool] | None:
    pct = tok.endswith("%")
    core = tok.rstrip("%").replace(",", "")
    try:
        val = float(core)
    except ValueError:
        return None
    m = re.search(r"\.(\d+)", core.split("e")[0].split("E")[0])
    decimals = len(m.group(1)) if m else 0
    return val, decimals, pct


def _collect_numbers(obj: Any, out: list[float]) -> None:
    if isinstance(obj, bool):
        return
    if isinstance(obj, int | float):
        out.append(float(obj))
    elif isinstance(obj, str):
        for tok in _NUM_RE.findall(obj):
            p = _parse_number(tok)
            if p:
                out.append(p[0])
    elif isinstance(obj, dict):
        for v in obj.values():
            _collect_numbers(v, out)
    elif isinstance(obj, list | tuple):
        for v in obj:
            _collect_numbers(v, out)


def _strip_ignored(text: str) -> str:
    text = _CITATION_RE.sub(" ", text)
    text = re.sub(r"`[^`]*`", " ", text)  # inline code (ids, names)
    # Identifiers with digits attached to letters (PC1, f4, K2, Iron_Age2) are not quantities.
    text = re.sub(r"\b[A-Za-z_]+[A-Za-z_\-]*\d+[A-Za-z0-9_\-]*\b", " ", text)
    # Ordered list markers and headings like "1." at line start.
    text = re.sub(r"(?m)^\s*\d+[.)]\s", " ", text)
    return text


def _matches(val: float, decimals: int, pct: bool, pool: Sequence[float]) -> bool:
    candidates = [val]
    if pct:
        candidates.append(val / 100.0)
    tol = 0.5 * 10 ** (-decimals) if decimals else 0.5
    for c in candidates:
        c_tol = tol / 100.0 if (pct and c is not val) else tol
        for p in pool:
            if abs(p - c) <= c_tol + 1e-12 * max(1.0, abs(p)):
                return True
            # Values reported as percentages of a fraction (0.42 -> 42%) without a % sign.
            if not pct and decimals <= 2 and 0 <= p <= 1 and abs(p * 100 - c) <= tol:
                return True
    return False


def grounding_check(
    answer: str,
    tool_results: Sequence[Any],
    *,
    allowed: Sequence[float] = (),
    small_int_exempt: int = 10,
) -> GroundingReport:
    """Flag numbers in ``answer`` that are not supported by any tool result.

    A number is grounded if it equals some number in the tool results up to the rounding
    implied by its printed precision (``0.42`` matches ``0.4213``; ``42%`` and ``42`` match
    ``0.4213``). Small integers (<= ``small_int_exempt``, e.g. "two sources", "step 3"),
    citation ids, inline code and alphanumeric identifiers are ignored. This is deterministic
    and conservative: it can miss a fabricated number that coincides with a real one, but
    every flagged number is genuinely absent from the tool outputs.
    """
    pool: list[float] = list(allowed)
    for r in tool_results:
        _collect_numbers(r, pool)
    text = _strip_ignored(answer)
    issues: list[GroundingIssue] = []
    checked = 0
    for m in _NUM_RE.finditer(text):
        tok = m.group(0)
        parsed = _parse_number(tok)
        if parsed is None:
            continue
        val, decimals, pct = parsed
        if not pct and decimals == 0 and abs(val) <= small_int_exempt:
            continue
        # Years in prose (e.g. "Reich et al. 2009") are bibliographic, not results.
        if not pct and decimals == 0 and 1900 <= val <= 2100 and "," not in tok:
            continue
        checked += 1
        if not _matches(val, decimals, pct, pool):
            lo, hi = max(0, m.start() - 40), min(len(text), m.end() + 40)
            ctx = " ".join(text[lo:hi].split())
            issues.append(GroundingIssue(value=tok, context=ctx))
    return GroundingReport(ok=not issues, checked=checked, ungrounded=issues)


# ---- the loop --------------------------------------------------------------------------------


@dataclass
class ResearchAgent:
    provider: LLMProvider
    ctx: ToolContext
    config: AgentConfig = field(default_factory=AgentConfig)
    transcript: list[dict[str, Any]] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)

    def _log(self, kind: str, **data: Any) -> None:
        self.transcript.append({"t": round(time.time(), 3), "kind": kind, **data})

    async def _run_tools(
        self, calls: Sequence[Any], cancel: asyncio.Event | None
    ) -> list[ToolResultEvent]:
        sem = asyncio.Semaphore(self.config.max_parallel_tools)

        async def one(call: Any) -> ToolResultEvent:
            async with sem:
                if cancel is not None and cancel.is_set():
                    return ToolResultEvent(id=call.id, name=call.name, ok=False, error="cancelled")
                try:
                    outcome = await asyncio.wait_for(
                        execute_tool(
                            call.name, call.arguments, self.ctx, parse_error=call.parse_error
                        ),
                        timeout=self.config.tool_timeout_s,
                    )
                except TimeoutError:
                    return ToolResultEvent(
                        id=call.id,
                        name=call.name,
                        ok=False,
                        error=f"tool timed out after {self.config.tool_timeout_s:.0f}s",
                    )
                return ToolResultEvent(
                    id=call.id,
                    name=call.name,
                    ok=outcome.ok,
                    result=outcome.result,
                    error=outcome.error,
                    duration_ms=outcome.duration_ms,
                )

        return list(await asyncio.gather(*(one(c) for c in calls)))

    async def run(
        self,
        messages: Sequence[dict[str, Any] | ConvMessage],
        *,
        cancel: asyncio.Event | None = None,
    ) -> AsyncIterator[AgentEvent]:
        conv: list[ConvMessage] = []
        for m in messages:
            if isinstance(m, dict):
                role, content = m.get("role"), str(m.get("content", ""))
                conv.append(
                    UserMessage(content=content)
                    if role == "user"
                    else AssistantMessage(text=content)
                )
            else:
                conv.append(m)
        specs = tool_specs(self.config.tools)
        self._log(
            "start",
            provider=self.provider.name,
            model=self.provider.model,
            tools=[s.name for s in specs],
        )

        tool_payloads: list[Any] = []
        final_text = ""
        stop: StopReason = "end_turn"
        steps = 0
        cancelled = False

        while True:
            if cancel is not None and cancel.is_set():
                cancelled, stop = True, "cancelled"
                break
            if steps >= self.config.max_steps:
                stop = "max_tokens"
                msg = (
                    f"Step budget of {self.config.max_steps} model turns reached; "
                    "stopping. Results so far are in the transcript."
                )
                self._log("budget_exhausted", max_steps=self.config.max_steps)
                yield ErrorEvent(message=msg, retryable=False)
                break
            steps += 1
            turn_text: list[str] = []
            done: MessageDone | None = None
            async for ev in self.provider.stream(
                system=self.config.system_prompt, tools=specs, messages=conv
            ):
                if cancel is not None and cancel.is_set():
                    cancelled = True
                    break
                if isinstance(ev, TextDelta):
                    turn_text.append(ev.text)
                    yield ev
                elif isinstance(ev, ToolCallEvent):
                    self._log("tool_call", id=ev.id, name=ev.name, arguments=ev.arguments)
                    yield ev
                elif isinstance(ev, MessageDone):
                    done = ev
                elif isinstance(ev, ErrorEvent):
                    self._log("error", message=ev.message, retryable=ev.retryable)
                    yield ev
            if cancelled:
                stop = "cancelled"
                break
            if done is None:
                stop = "error"
                break
            self.usage = self.usage.add(done.usage)
            self._log(
                "model_turn",
                step=steps,
                stop_reason=done.stop_reason,
                usage=done.usage.model_dump(),
                text="".join(turn_text),
            )
            yield done
            assistant = done.message or AssistantMessage(text="".join(turn_text))
            conv.append(assistant)
            final_text = assistant.text
            stop = done.stop_reason
            if done.stop_reason != "tool_use" or not assistant.tool_calls:
                break

            results = await self._run_tools(assistant.tool_calls, cancel)
            tr_msgs: list[ToolResult] = []
            for r in results:
                self._log(
                    "tool_result",
                    id=r.id,
                    name=r.name,
                    ok=r.ok,
                    result=r.result,
                    error=r.error,
                    duration_ms=r.duration_ms,
                )
                if r.ok:
                    tool_payloads.append(r.result)
                    content = json.dumps(r.result, default=str)
                else:
                    content = json.dumps({"error": r.error})
                tr_msgs.append(
                    ToolResult(tool_call_id=r.id, name=r.name, content=content, is_error=not r.ok)
                )
                yield r
            conv.append(ToolResultsMessage(results=tr_msgs))

        grounding = grounding_check(final_text, tool_payloads)
        citations = sorted(set(_CITATION_RE.findall(final_text)))
        self._log(
            "final",
            stop_reason=stop,
            grounding=grounding.model_dump(),
            citations=citations,
            usage=self.usage.model_dump(),
        )
        yield DoneEvent(
            answer=final_text,
            grounding=grounding,
            citations=citations,
            transcript=list(self.transcript),
            usage=self.usage,
            steps=steps,
            cancelled=cancelled,
            stop_reason=stop,
        )


async def stream_chat(
    history: Sequence[dict[str, Any]],
    user_message: str,
    *,
    ctx: ToolContext,
    config: AgentConfig | None = None,
    provider: LLMProvider | None = None,
    cancel: asyncio.Event | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Platform entry point: yields JSON-serialisable event dicts (see ``events.py``)."""
    agent = ResearchAgent(
        provider=provider or get_provider(), ctx=ctx, config=config or AgentConfig.from_env()
    )
    msgs = [*history, {"role": "user", "content": user_message}]
    try:
        async for ev in agent.run(msgs, cancel=cancel):
            yield ev.model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001 - surfaced to the client as an error event
        yield ErrorEvent(message=f"{type(exc).__name__}: {exc}", retryable=False).model_dump()
