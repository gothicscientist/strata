/**
 * Typed client for the Strata HTTP API (prefix /api/v1).
 *
 * Authentication: a bearer token is attached to every request. It is either a Supabase access
 * token (when Supabase auth is configured and the user signed in) or a signed guest token obtained
 * from POST /auth/guest and kept in localStorage until it expires.
 */

import { readSSE } from "./sse";
import type {
  Analysis,
  AnalysisCreate,
  AnalysisCreated,
  ChatEvent,
  ChatSession,
  ChatSessionCreate,
  ChatSessionDetail,
  CoordinateSpaceInfo,
  Dataset,
  ExampleDetail,
  ExampleSummary,
  GuestToken,
  Health,
  Job,
  Page,
  PopulationDetail,
  PopulationQuery,
  PopulationSummary,
  Publication,
  ReferencePanel,
} from "./types";

export const API_PREFIX = "/api/v1";

/** Resolve the API base from NEXT_PUBLIC_API_URL; tolerates a value that already ends in /api/v1. */
export function apiBase(raw: string | undefined = process.env.NEXT_PUBLIC_API_URL): string {
  const base = (raw ?? "").trim().replace(/\/+$/, "");
  if (base.endsWith(API_PREFIX)) return base;
  return `${base}${API_PREFIX}`;
}

export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;
  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
  /** True when the API could not be reached at all (network failure, CORS, DNS). */
  get unreachable(): boolean {
    return this.status === 0;
  }
}

/** Extract a readable message from a FastAPI error body ({detail: str | [{msg, loc}]}). */
export function errorMessage(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) {
      const parts = d
        .map((e) => {
          if (e && typeof e === "object" && "msg" in e) {
            const loc = Array.isArray((e as { loc?: unknown }).loc)
              ? ((e as { loc: unknown[] }).loc.filter((x) => x !== "body").join("."))
              : "";
            return loc ? `${loc}: ${(e as { msg: string }).msg}` : (e as { msg: string }).msg;
          }
          return typeof e === "string" ? e : "";
        })
        .filter(Boolean);
      if (parts.length) return parts.join("; ");
    }
    if (d && typeof d === "object" && "message" in d) return String((d as { message: unknown }).message);
  }
  return fallback;
}

/* ------------------------------------------------------------------ tokens */

const GUEST_KEY = "strata.guest";

interface StoredGuest {
  token: string;
  expires_at: string;
  owner_id: string;
}

function storage(): Storage | null {
  try {
    return typeof window !== "undefined" ? window.localStorage : null;
  } catch {
    return null;
  }
}

export function readGuest(now: number = Date.now()): StoredGuest | null {
  const raw = storage()?.getItem(GUEST_KEY);
  if (!raw) return null;
  try {
    const g = JSON.parse(raw) as StoredGuest;
    // Treat tokens within 60 s of expiry as expired to avoid mid-request failures.
    if (!g.token || Date.parse(g.expires_at) - 60_000 <= now) return null;
    return g;
  } catch {
    return null;
  }
}

export function writeGuest(g: GuestToken): void {
  const value: StoredGuest = { token: g.token, expires_at: g.expires_at, owner_id: g.owner_id };
  storage()?.setItem(GUEST_KEY, JSON.stringify(value));
}

export function clearGuest(): void {
  storage()?.removeItem(GUEST_KEY);
}

/** Optional external token source (Supabase). Returns null when not signed in. */
type TokenSource = () => Promise<string | null>;
let externalToken: TokenSource | null = null;
export function setExternalTokenSource(src: TokenSource | null): void {
  externalToken = src;
}

/* ------------------------------------------------------------------ client */

type Query = Record<string, string | number | boolean | null | undefined>;

export interface RequestOptions {
  method?: string;
  query?: Query;
  json?: unknown;
  form?: FormData;
  signal?: AbortSignal;
  /** Skip attaching a token (used for /health and /auth/guest). */
  anonymous?: boolean;
  accept?: string;
  /** Return the raw Response instead of parsing JSON. */
  raw?: boolean;
}

export function buildUrl(path: string, query?: Query, base: string = apiBase()): string {
  const url = `${base}${path.startsWith("/") ? path : `/${path}`}`;
  if (!query) return url;
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v === undefined || v === null || v === "") continue;
    params.set(k, String(v));
  }
  const qs = params.toString();
  return qs ? `${url}?${qs}` : url;
}

let guestInflight: Promise<string> | null = null;

/** Return a bearer token, creating a guest workspace on first use. */
export async function ensureToken(): Promise<string> {
  if (externalToken) {
    const t = await externalToken();
    if (t) return t;
  }
  const g = readGuest();
  if (g) return g.token;
  guestInflight ??= createGuest()
    .then((tok) => tok.token)
    .finally(() => {
      guestInflight = null;
    });
  return guestInflight;
}

async function fetchOrThrow(url: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(url, init);
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw new ApiError(0, "The Strata API could not be reached.", String(e));
  }
}

export async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: opts.accept ?? "application/json" };
  let body: BodyInit | undefined;
  if (opts.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.json);
  } else if (opts.form) {
    body = opts.form;
  }
  if (!opts.anonymous) headers.Authorization = `Bearer ${await ensureToken()}`;

  const url = buildUrl(path, opts.query);
  const init: RequestInit = { method: opts.method ?? (body ? "POST" : "GET"), headers };
  if (body !== undefined) init.body = body;
  if (opts.signal) init.signal = opts.signal;
  let res = await fetchOrThrow(url, init);

  // An expired or revoked guest token: issue a fresh guest workspace once and retry.
  if (res.status === 401 && !opts.anonymous && readGuest()) {
    clearGuest();
    const retryHeaders = { ...headers, Authorization: `Bearer ${await ensureToken()}` };
    res = await fetchOrThrow(url, { ...init, headers: retryHeaders });
  }

  if (!res.ok) {
    let parsed: unknown = null;
    try {
      parsed = await res.json();
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, errorMessage(parsed, `${res.status} ${res.statusText}`), parsed);
  }
  if (opts.raw) return res as unknown as T;
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/* --------------------------------------------------------------- endpoints */

export async function createGuest(): Promise<GuestToken> {
  const tok = await request<GuestToken>("/auth/guest", { method: "POST", anonymous: true });
  writeGuest(tok);
  return tok;
}

export const api = {
  health: (signal?: AbortSignal) => request<Health>("/health", { anonymous: true, signal }),

  populations: (q: PopulationQuery = {}, signal?: AbortSignal) =>
    request<Page<PopulationSummary>>("/reference/populations", { query: { ...q }, signal }),
  population: (id: string, signal?: AbortSignal) =>
    request<PopulationDetail>(`/reference/populations/${encodeURIComponent(id)}`, { signal }),
  spaces: (signal?: AbortSignal) =>
    request<CoordinateSpaceInfo[]>("/reference/spaces", { signal }),
  publications: (signal?: AbortSignal) =>
    request<Publication[]>("/reference/publications", { signal }),
  panel: (signal?: AbortSignal) => request<ReferencePanel>("/reference/panel", { signal }),

  datasets: (signal?: AbortSignal) => request<Dataset[]>("/datasets", { signal }),
  dataset: (id: string, signal?: AbortSignal) =>
    request<Dataset>(`/datasets/${encodeURIComponent(id)}`, { signal }),
  deleteDataset: (id: string) =>
    request<void>(`/datasets/${encodeURIComponent(id)}`, { method: "DELETE" }),
  uploadG25: (text: string, name?: string) => {
    const form = new FormData();
    form.set("kind", "g25");
    form.set("g25_text", text);
    if (name) form.set("name", name);
    return request<Dataset>("/datasets", { form });
  },
  uploadFile: (file: File, name?: string) => {
    const form = new FormData();
    // The server autodetects G25 CSV, 23andMe, AncestryDNA, FTDNA/MyHeritage and VCF.
    form.set("kind", "auto");
    form.set("file", file, file.name);
    if (name) form.set("name", name);
    return request<Dataset>("/datasets", { form });
  },

  analyses: (signal?: AbortSignal) => request<Analysis[]>("/analyses", { signal }),
  analysis: (id: string, signal?: AbortSignal) =>
    request<Analysis>(`/analyses/${encodeURIComponent(id)}`, { signal }),
  createAnalysis: (body: AnalysisCreate) =>
    request<AnalysisCreated>("/analyses", { json: body }),
  job: (id: string, signal?: AbortSignal) =>
    request<Job>(`/jobs/${encodeURIComponent(id)}`, { signal }),
  report: (id: string, format: "html" | "json") =>
    request<Response>(`/analyses/${encodeURIComponent(id)}/report`, {
      query: { format },
      raw: true,
      accept: format === "html" ? "text/html" : "application/json",
    }),

  examples: (signal?: AbortSignal) => request<ExampleSummary[]>("/examples", { signal }),
  example: (slug: string, signal?: AbortSignal) =>
    request<ExampleDetail>(`/examples/${encodeURIComponent(slug)}`, { signal }),

  chatSessions: (signal?: AbortSignal) => request<ChatSession[]>("/chat/sessions", { signal }),
  chatSession: (id: string, signal?: AbortSignal) =>
    request<ChatSessionDetail>(`/chat/sessions/${encodeURIComponent(id)}`, { signal }),
  createChat: (body: ChatSessionCreate = {}) =>
    request<ChatSession>("/chat/sessions", { method: "POST", json: body }),
};

/* --------------------------------------------------------------- polling */

export const TERMINAL: ReadonlySet<Job["status"]> = new Set(["succeeded", "failed", "cancelled"]);

export interface PollOptions {
  intervalMs?: number;
  maxIntervalMs?: number;
  signal?: AbortSignal;
  onUpdate?: (job: Job) => void;
  fetchJob?: (id: string, signal?: AbortSignal) => Promise<Job>;
}

/** Poll /jobs/{id} with gentle back-off until it reaches a terminal state. */
export async function pollJob(id: string, opts: PollOptions = {}): Promise<Job> {
  const fetchJob = opts.fetchJob ?? api.job;
  let delay = opts.intervalMs ?? 800;
  const max = opts.maxIntervalMs ?? 5000;
  for (;;) {
    const job = await fetchJob(id, opts.signal);
    opts.onUpdate?.(job);
    if (TERMINAL.has(job.status)) return job;
    await new Promise<void>((resolve, reject) => {
      const t = setTimeout(resolve, delay);
      opts.signal?.addEventListener("abort", () => {
        clearTimeout(t);
        reject(new DOMException("Aborted", "AbortError"));
      });
    });
    delay = Math.min(max, Math.round(delay * 1.5));
  }
}

/* --------------------------------------------------------------- chat */

/** Decode one SSE message into a typed ChatEvent; unknown events return null. */
export function decodeChatEvent(event: string, data: string): ChatEvent | null {
  let payload: unknown;
  try {
    payload = JSON.parse(data);
  } catch {
    return null;
  }
  if (!payload || typeof payload !== "object") return null;
  const obj = payload as Record<string, unknown>;
  const type = typeof obj.type === "string" ? obj.type : event;
  const known = [
    "text_delta",
    "tool_call",
    "tool_result",
    "message_done",
    "saved",
    "error",
    "done",
  ];
  if (!known.includes(type)) return null;
  return { ...obj, type } as ChatEvent;
}

/** POST a user message and stream the assistant's events. */
export async function* streamChat(
  sessionId: string,
  content: string,
  signal?: AbortSignal,
): AsyncGenerator<ChatEvent> {
  const res = await request<Response>(`/chat/sessions/${encodeURIComponent(sessionId)}/messages`, {
    json: { content },
    raw: true,
    accept: "text/event-stream",
    signal,
  });
  if (!res.body) throw new ApiError(res.status, "The assistant returned an empty stream.");
  for await (const msg of readSSE(res.body, signal)) {
    const ev = decodeChatEvent(msg.event, msg.data);
    if (ev) yield ev;
  }
}
