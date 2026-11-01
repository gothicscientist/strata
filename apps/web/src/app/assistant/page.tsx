"use client";

import Link from "next/link";
import { Fragment, useEffect, useRef, useState } from "react";
import { api, streamChat } from "@/lib/api";
import {
  applyEvent,
  citationHref,
  emptyAssistant,
  parseBlocks,
  parseInline,
  turnsFromHistory,
  type AssistantTurn,
  type ToolPart,
  type Turn,
} from "@/lib/chat";
import { asAnalysisResult } from "@/lib/results";
import { useResource } from "@/lib/useResource";
import { ResultView } from "@/components/results/ResultView";
import { useSession } from "@/components/SessionProvider";
import { Caveat, ErrorNote, PageHeader } from "@/components/typography";

const SESSION_KEY = "strata.chat.session";

function safeSession(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

function InlineText({ text, citations }: { text: string; citations: string[] }) {
  return (
    <>
      {parseInline(text).map((n, i) => {
        switch (n.t) {
          case "text":
            return <Fragment key={i}>{n.v}</Fragment>;
          case "code":
            return (
              <code key={i} className="bg-wash px-1">
                {n.v}
              </code>
            );
          case "strong":
            return <strong key={i} className="font-semibold">{n.v}</strong>;
          case "em":
            return <em key={i}>{n.v}</em>;
          case "cite": {
            const idx = citations.indexOf(n.id);
            return (
              <a key={i} href={citationHref(n.id)} className="no-underline" title={n.id}>
                <sup className="num ml-px text-[0.68em] text-blue">[{idx >= 0 ? idx + 1 : n.id.replace(/^.*\//, "")}]</sup>
              </a>
            );
          }
        }
      })}
    </>
  );
}

function Prose({ text, citations }: { text: string; citations: string[] }) {
  return (
    <>
      {parseBlocks(text).map((b, i) => {
        if (b.t === "p")
          return (
            <p key={i} className="my-2.5 leading-[1.6]">
              <InlineText text={b.v} citations={citations} />
            </p>
          );
        if (b.t === "h")
          return (
            <h3 key={i} className="mt-5 mb-1 text-h3 italic">
              <InlineText text={b.v} citations={citations} />
            </h3>
          );
        const L = b.t === "ul" ? "ul" : "ol";
        return (
          <L key={i} className={`my-2.5 space-y-1 pl-6 ${b.t === "ul" ? "list-disc" : "list-decimal"} marker:text-ink-3`}>
            {b.items.map((it, j) => (
              <li key={j}>
                <InlineText text={it} citations={citations} />
              </li>
            ))}
          </L>
        );
      })}
    </>
  );
}

function MethodNote({ part }: { part: ToolPart }) {
  return (
    <details id={`method-${part.id}`} className="group border-b border-rule-soft py-1.5 text-caption">
      <summary className="cursor-pointer list-none text-ink-2 marker:hidden">
        <sup className="num mr-1.5 text-ink">{part.n}</sup>
        <span className="font-mono text-[0.72rem] text-ink">{part.name}</span>
        <span className="ml-2">
          {part.status === "running"
            ? "running…"
            : part.status === "error"
              ? <span className="text-alert">failed: {part.error}</span>
              : `completed${part.durationMs ? ` in ${part.durationMs} ms` : ""}`}
        </span>
        <span className="ml-2 text-ink-3 group-open:hidden">(show inputs and result)</span>
      </summary>
      <div className="mt-2 grid gap-3 md:grid-cols-2">
        <div>
          <p className="mb-1 italic">Input</p>
          <pre className="max-h-60 overflow-auto border border-rule bg-wash p-2 text-[0.7rem] leading-[1.5]">
            {JSON.stringify(part.input, null, 2)}
          </pre>
        </div>
        <div>
          <p className="mb-1 italic">Result</p>
          <pre className="max-h-60 overflow-auto border border-rule bg-wash p-2 text-[0.7rem] leading-[1.5]">
            {part.status === "running" ? "…" : JSON.stringify(part.result ?? part.error, null, 2)}
          </pre>
        </div>
      </div>
    </details>
  );
}

function AssistantAnswer({ turn, index }: { turn: AssistantTurn; index: number }) {
  const tools = turn.parts.filter((p): p is ToolPart => p.kind === "tool");
  const figures = tools
    .filter((t) => t.status === "ok")
    .map((t) => ({ t, r: asAnalysisResult(t.result) }))
    .filter((x) => x.r !== null);
  return (
    <div>
      <div className="text-body">
        {turn.parts.map((p, i) =>
          p.kind === "text" ? (
            <Prose key={i} text={p.text} citations={turn.citations} />
          ) : (
            <a key={i} href={`#method-${p.id}`} className="no-underline" title={`Method ${p.n}: ${p.name}`}>
              {/* Separate a run of markers, or 29 tool calls read as one number. */}
              <sup className="num text-[0.7em]">{turn.parts[i - 1]?.kind === "tool" ? `,\u200b${p.n}` : p.n}</sup>
            </a>
          ),
        )}
        {!turn.done && !turn.error ? (
          <span className="ml-1 inline-block h-[1em] w-px animate-pulse bg-ink align-[-0.15em]" aria-hidden />
        ) : null}
      </div>

      {figures.map(({ t, r }) => (
        <figure key={t.id} className="my-6 border-y border-rule py-4">
          <ResultView result={r!} compact />
          <figcaption className="mt-2 text-caption text-ink-2">
            <span className="font-semibold text-ink">
              Result {index}.{t.n}.
            </span>{" "}
            Output of <span className="font-mono text-[0.72rem]">{t.name}</span>
            {typeof t.result?.analysis_id === "string" ? (
              <>
                ; <Link href={`/analysis/?id=${encodeURIComponent(t.result.analysis_id)}`}>open the full analysis</Link>
              </>
            ) : null}
            .
          </figcaption>
        </figure>
      ))}

      {turn.grounding && !turn.grounding.ok ? (
        <Caveat title="Some numbers in this answer could not be traced to a tool result">
          <ul className="list-disc pl-5">
            {turn.grounding.ungrounded.map((u, i) => (
              <li key={i}>
                <span className="num font-medium text-ink">{u.value}</span> in &ldquo;{u.context}&rdquo;
              </li>
            ))}
          </ul>
          <p className="mt-1">Treat these values as unverified.</p>
        </Caveat>
      ) : null}

      {turn.error ? <ErrorNote error={new Error(turn.error)} /> : null}
      {turn.cancelled ? <p className="text-caption text-ink-3 italic">Stopped before completion.</p> : null}

      {tools.length || turn.citations.length ? (
        <div className="mt-4 border-t border-ink pt-2">
          {tools.length ? (
            <>
              <p className="smallcaps mb-1 text-ink-3">Methods</p>
              {tools.map((t) => (
                <MethodNote key={t.id} part={t} />
              ))}
            </>
          ) : null}
          {turn.citations.length ? (
            <>
              <p className="smallcaps mt-3 mb-1 text-ink-3">References</p>
              <ol className="list-decimal space-y-0.5 pl-5 text-caption text-ink-2">
                {turn.citations.map((c) => (
                  <li key={c}>
                    <a href={citationHref(c)}>{c}</a>
                  </li>
                ))}
              </ol>
            </>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export default function AssistantPage() {
  const { health, session } = useSession();
  const datasets = useResource(session.status === "connecting" || session.status === "offline" ? null : (s) => api.datasets(s), [session.status]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [shared, setShared] = useState<string[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [provider, setProvider] = useState<"anthropic" | "openai">("openai");
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("");
  const abortRef = useRef<AbortController | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  const configured = Boolean(health?.capabilities.llm_configured || apiKey.trim().length >= 8);
  const connected = session.status === "guest" || session.status === "signed-in";

  // Restore the conversation from this tab's previous visit.
  useEffect(() => {
    if (session.status !== "guest" && session.status !== "signed-in") return;
    const id = safeSession()?.getItem(SESSION_KEY);
    if (!id) return;
    api
      .chatSession(id)
      .then((d) => {
        setSessionId(d.id);
        setShared(d.dataset_ids);
        setTurns(turnsFromHistory(d.messages));
      })
      .catch(() => safeSession()?.removeItem(SESSION_KEY));
  }, [session.status]);

  useEffect(() => {
    if (streaming) endRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [turns, streaming]);

  async function send() {
    const content = input.trim();
    if (!content || streaming || !configured || !connected) return;
    setError(null);
    setStreaming(true);
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      let sid = sessionId;
      if (!sid) {
        const s = await api.createChat({ title: content.slice(0, 80), dataset_ids: shared });
        sid = s.id;
        setSessionId(sid);
        safeSession()?.setItem(SESSION_KEY, sid);
      }
      setInput("");
      setTurns((t) => [...t, { role: "user", content }, emptyAssistant()]);
      const credentials = apiKey.trim()
        ? { provider, api_key: apiKey.trim(), ...(model.trim() ? { model: model.trim() } : {}) }
        : undefined;
      for await (const ev of streamChat(sid, content, ctrl.signal, credentials)) {
        setTurns((t) => {
          const last = t[t.length - 1];
          if (!last || last.role !== "assistant") return t;
          return [...t.slice(0, -1), applyEvent(last, ev)];
        });
      }
    } catch (e) {
      if (!(e instanceof DOMException && e.name === "AbortError")) setError(e);
    } finally {
      setTurns((t) => {
        const last = t[t.length - 1];
        if (last && last.role === "assistant" && !last.done) {
          return [...t.slice(0, -1), { ...last, done: true, cancelled: ctrl.signal.aborted }];
        }
        return t;
      });
      setStreaming(false);
      abortRef.current = null;
    }
  }

  function reset() {
    abortRef.current?.abort();
    safeSession()?.removeItem(SESSION_KEY);
    setSessionId(null);
    setTurns([]);
    setError(null);
  }

  let answerNo = 0;

  return (
    <>
      <PageHeader
        kicker="Research assistant"
        title="Ask a question"
        lede="The assistant answers by running Strata's analyses and reading the methods documentation. Each tool it runs is listed as a numbered method beneath the answer, with its inputs and results."
        aside={
          <p>
            It sees population identifiers and derived coordinates, never genotypes. Numbers it
            states are checked against tool results; unverified values are flagged.
          </p>
        }
      />

      <div className="max-w-[46rem]">
        <fieldset className="mb-8 border-b border-rule pb-6" disabled={streaming}>
          <legend className="text-h3 italic">Use your own API key</legend>
          <p id="api-key-help" className="mb-4 mt-2 text-small text-ink-2">
            Your provider bills your API account. The key stays in this page's memory and is
            sent securely to Strata for each request, then to your selected provider. It is
            never saved. Reloading the page clears it. All analyses also work without AI in
            the <Link href="/analyses/new/">composer</Link>.
          </p>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block">
              <span className="label">Provider</span>
              <select className="field" value={provider} onChange={(e) => {
                setProvider(e.target.value as "anthropic" | "openai");
                setApiKey("");
                setModel("");
              }}>
                <option value="openai">OpenAI</option>
                <option value="anthropic">Anthropic</option>
              </select>
            </label>
            <label className="block">
              <span className="label">Model (optional)</span>
              <input className="field" value={model} maxLength={120}
                placeholder={provider === "openai" ? "gpt-5" : "claude-opus-5-5"}
                onChange={(e) => setModel(e.target.value)} />
            </label>
          </div>
          <label className="mt-4 block">
            <span className="label">API key</span>
            <input className="field" type="password" autoComplete="off" spellCheck={false}
              aria-describedby="api-key-help" value={apiKey} maxLength={4096}
              onChange={(e) => setApiKey(e.target.value)} placeholder="Paste your provider API key" />
          </label>
          {apiKey ? <button type="button" className="linkish mt-3 text-small"
            onClick={() => setApiKey("")}>Clear API key</button> : null}
        </fieldset>
        {turns.length === 0 ? (
          <div className="mb-10 text-small text-ink-2">
            <p className="mb-2 italic text-ink">For example</p>
            <ul className="space-y-1.5">
              {[
                "Which reference populations are closest to Yamnaya Samara in the Strata PCA?",
                "Fit Corded Ware as a mixture of Yamnaya and Globular Amphora, with intervals.",
                "What does a qpAdm p-value of 0.2 tell me, and what does it not?",
              ].map((q) => (
                <li key={q}>
                  <button type="button" className="linkish text-left" onClick={() => setInput(q)}>
                    {q}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        <ol className="space-y-10">
          {turns.map((t, i) => {
            if (t.role === "user")
              return (
                <li key={i} className="grid grid-cols-[3.5rem_1fr] gap-2 border-t border-rule pt-4">
                  <span className="smallcaps pt-1 text-ink-3">Q.</span>
                  <p className="whitespace-pre-wrap italic">{t.content}</p>
                </li>
              );
            answerNo += 1;
            return (
              <li key={i} className="grid grid-cols-[3.5rem_1fr] gap-2" aria-live={i === turns.length - 1 && streaming ? "polite" : undefined}>
                <span className="smallcaps pt-1.5 text-ink-3">A.</span>
                <div className="min-w-0">
                  <AssistantAnswer turn={t} index={answerNo} />
                </div>
              </li>
            );
          })}
        </ol>
        <div ref={endRef} />

        {error ? <ErrorNote error={error} /> : null}

        <form
          className="mt-10 border-t border-ink pt-5"
          onSubmit={(e) => {
            e.preventDefault();
            void send();
          }}
        >
          {!sessionId && datasets.data?.length ? (
            <fieldset className="mb-4 text-small">
              <legend className="label">Let the assistant use derived coordinates from</legend>
              <div className="flex flex-wrap gap-x-6 gap-y-1">
                {datasets.data.map((d) => (
                  <label key={d.id} className="flex items-baseline gap-2">
                    <input
                      type="checkbox"
                      className="accent-black"
                      checked={shared.includes(d.id)}
                      onChange={(e) =>
                        setShared((s) => (e.target.checked ? [...s, d.id] : s.filter((x) => x !== d.id)))
                      }
                    />
                    {d.name}
                  </label>
                ))}
              </div>
            </fieldset>
          ) : null}
          <label htmlFor="question" className="label">
            Your question
          </label>
          <textarea
            id="question"
            className="field h-28 resize-y !font-serif !text-body !leading-[1.5]"
            value={input}
            maxLength={8000}
            disabled={!connected || streaming}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                void send();
              }
            }}
            placeholder="Enter to send, Shift+Enter for a new line"
          />
          <div className="mt-3 flex flex-wrap items-center gap-4">
            {streaming ? (
              <button type="button" className="btn btn-quiet" onClick={() => abortRef.current?.abort()}>
                Stop
              </button>
            ) : (
              <button type="submit" className="btn" disabled={!input.trim() || !configured || !connected}>
                Ask
              </button>
            )}
            {turns.length ? (
              <button type="button" className="linkish text-small" onClick={reset}>
                Start a new conversation
              </button>
            ) : null}
          </div>
          {!configured ? <p className="mt-3 text-small text-ink-2">Enter an API key above to ask the assistant.</p> : null}
        </form>
      </div>
    </>
  );
}
