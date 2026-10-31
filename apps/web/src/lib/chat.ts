/** Reducer that folds streamed agent events into a renderable assistant turn. */

import type { ChatEvent, ChatMessage, Grounding } from "./types";

export interface ToolPart {
  kind: "tool";
  id: string;
  name: string;
  input: Record<string, unknown>;
  status: "running" | "ok" | "error";
  result: Record<string, unknown> | null;
  error: string | null;
  durationMs: number | null;
  /** 1-based footnote number in order of appearance. */
  n: number;
}

export interface TextPart {
  kind: "text";
  text: string;
}

export type Part = TextPart | ToolPart;

export interface AssistantTurn {
  role: "assistant";
  parts: Part[];
  done: boolean;
  grounding: Grounding | null;
  citations: string[];
  error: string | null;
  cancelled: boolean;
  messageId: string | null;
}

export interface UserTurn {
  role: "user";
  content: string;
}

export type Turn = UserTurn | AssistantTurn;

export function emptyAssistant(): AssistantTurn {
  return {
    role: "assistant",
    parts: [],
    done: false,
    grounding: null,
    citations: [],
    error: null,
    cancelled: false,
    messageId: null,
  };
}

export function applyEvent(turn: AssistantTurn, ev: ChatEvent): AssistantTurn {
  switch (ev.type) {
    case "text_delta": {
      const parts = [...turn.parts];
      const last = parts[parts.length - 1];
      if (last && last.kind === "text") parts[parts.length - 1] = { kind: "text", text: last.text + ev.text };
      else parts.push({ kind: "text", text: ev.text });
      return { ...turn, parts };
    }
    case "tool_call": {
      const n = turn.parts.filter((p) => p.kind === "tool").length + 1;
      const part: ToolPart = {
        kind: "tool",
        id: ev.id,
        name: ev.name,
        input: ev.arguments ?? {},
        status: "running",
        result: null,
        error: null,
        durationMs: null,
        n,
      };
      return { ...turn, parts: [...turn.parts, part] };
    }
    case "tool_result": {
      const parts = turn.parts.map((p) =>
        p.kind === "tool" && p.id === ev.id
          ? {
              ...p,
              status: ev.ok ? ("ok" as const) : ("error" as const),
              result: ev.result,
              error: ev.error,
              durationMs: ev.duration_ms ?? null,
            }
          : p,
      );
      return { ...turn, parts };
    }
    case "saved":
      return { ...turn, messageId: ev.message_id };
    case "error":
      return { ...turn, error: ev.message };
    case "done":
      return {
        ...turn,
        done: true,
        grounding: ev.grounding ?? null,
        citations: ev.citations ?? [],
        cancelled: Boolean(ev.cancelled),
        // If no deltas were streamed (non-streaming provider), fall back to the final answer.
        parts:
          turn.parts.some((p) => p.kind === "text") || !ev.answer
            ? turn.parts
            : [...turn.parts, { kind: "text", text: ev.answer }],
      };
    case "message_done":
    default:
      return turn;
  }
}

/** Split answer text into plain runs and [chunk-id] citation markers. */
export type Inline =
  | { t: "text"; v: string }
  | { t: "cite"; id: string }
  | { t: "code"; v: string }
  | { t: "strong"; v: string }
  | { t: "em"; v: string };

const CITE = /\[([a-z0-9_\-./]+\.md(?:#[a-z0-9_\-]+)?)\]/gi;

export function parseInline(s: string): Inline[] {
  const out: Inline[] = [];
  const re = new RegExp(`${CITE.source}|\`([^\`]+)\`|\\*\\*([^*]+)\\*\\*|\\*([^*\\s][^*]*)\\*`, "gi");
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(s))) {
    if (m.index > last) out.push({ t: "text", v: s.slice(last, m.index) });
    if (m[1]) out.push({ t: "cite", id: m[1] });
    else if (m[2]) out.push({ t: "code", v: m[2] });
    else if (m[3]) out.push({ t: "strong", v: m[3] });
    else if (m[4]) out.push({ t: "em", v: m[4] });
    last = m.index + m[0].length;
  }
  if (last < s.length) out.push({ t: "text", v: s.slice(last) });
  return out;
}

export type Block = { t: "p"; v: string } | { t: "ul"; items: string[] } | { t: "ol"; items: string[] } | { t: "h"; v: string };

/** A deliberately small Markdown subset: paragraphs, headings, bullet and numbered lists. */
export function parseBlocks(text: string): Block[] {
  const blocks: Block[] = [];
  for (const chunk of text.split(/\n{2,}/)) {
    const lines = chunk.split("\n").filter((l) => l.trim() !== "");
    if (!lines.length) continue;
    if (lines.every((l) => /^\s*[-*]\s+/.test(l))) {
      blocks.push({ t: "ul", items: lines.map((l) => l.replace(/^\s*[-*]\s+/, "")) });
    } else if (lines.every((l) => /^\s*\d+[.)]\s+/.test(l))) {
      blocks.push({ t: "ol", items: lines.map((l) => l.replace(/^\s*\d+[.)]\s+/, "")) });
    } else if (lines.length === 1 && /^#{1,4}\s+/.test(lines[0]!)) {
      blocks.push({ t: "h", v: lines[0]!.replace(/^#{1,4}\s+/, "") });
    } else {
      blocks.push({ t: "p", v: lines.join(" ") });
    }
  }
  return blocks;
}

/** Map a citation id like "methods/qpadm.md#choice-of-right-populations" to its anchor on /methods. */
export function citationHref(id: string): string {
  const [file = "", anchor] = id.split("#");
  const slug = file.replace(/^.*\//, "").replace(/\.md$/, "");
  return `/methods/#${anchor ? `${slug}--${anchor}` : slug}`;
}

/** Rebuild rendered turns from a persisted session (tool events are stored as emitted). */
export function turnsFromHistory(messages: ChatMessage[]): Turn[] {
  return [...messages]
    .sort((a, b) => a.seq - b.seq)
    .map((m): Turn => {
      if (m.role === "user") return { role: "user", content: m.content };
      let t = emptyAssistant();
      for (const c of m.tool_calls) t = applyEvent(t, { ...(c as object), type: "tool_call" } as ChatEvent);
      for (const r of m.tool_results) t = applyEvent(t, { ...(r as object), type: "tool_result" } as ChatEvent);
      if (m.content) t = { ...t, parts: [...t.parts, { kind: "text", text: m.content }] };
      return {
        ...t,
        done: true,
        grounding: m.grounding,
        citations: m.citations ?? [],
        error: m.error,
        messageId: m.id,
      };
    });
}
