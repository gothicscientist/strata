import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  api,
  apiBase,
  buildUrl,
  clearGuest,
  decodeChatEvent,
  errorMessage,
  pollJob,
  readGuest,
  request,
  setExternalTokenSource,
  streamChat,
} from "@/lib/api";
import type { Job } from "@/lib/types";

const BASE = "http://api.test";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const future = () => new Date(Date.now() + 3600_000).toISOString();

describe("api client", () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  beforeEach(() => {
    vi.stubEnv("NEXT_PUBLIC_API_URL", BASE);
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    clearGuest();
    setExternalTokenSource(null);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("resolves the base URL with or without the /api/v1 suffix", () => {
    expect(apiBase("http://x/")).toBe("http://x/api/v1");
    expect(apiBase("http://x/api/v1")).toBe("http://x/api/v1");
    expect(apiBase("")).toBe("/api/v1");
    expect(buildUrl("/reference/populations", { q: "Yam", page: 2, region: "", x: undefined }, "http://x/api/v1")).toBe(
      "http://x/api/v1/reference/populations?q=Yam&page=2",
    );
  });

  it("extracts FastAPI error details", () => {
    expect(errorMessage({ detail: "nope", code: "x" }, "f")).toBe("nope");
    expect(errorMessage({ detail: [{ loc: ["body", "params", "k"], msg: "too big" }] }, "f")).toBe("params.k: too big");
    expect(errorMessage(null, "fallback")).toBe("fallback");
  });

  it("creates a guest token on first use and sends it as a bearer token", async () => {
    fetchMock
      .mockResolvedValueOnce(json({ token: "g1", token_type: "bearer", expires_at: future(), owner_id: "o1" }, 201))
      .mockResolvedValueOnce(json([]));
    await expect(api.datasets()).resolves.toEqual([]);
    expect(fetchMock.mock.calls[0]![0]).toBe(`${BASE}/api/v1/auth/guest`);
    expect(fetchMock.mock.calls[0]![1].headers.Authorization).toBeUndefined();
    expect(fetchMock.mock.calls[1]![1].headers.Authorization).toBe("Bearer g1");
    expect(readGuest()?.owner_id).toBe("o1");
  });

  it("reuses a stored token and replaces it after a 401", async () => {
    localStorage.setItem("strata.guest", JSON.stringify({ token: "old", expires_at: future(), owner_id: "o" }));
    fetchMock
      .mockResolvedValueOnce(json({ detail: "expired" }, 401))
      .mockResolvedValueOnce(json({ token: "new", expires_at: future(), owner_id: "o2" }, 201))
      .mockResolvedValueOnce(json([]));
    await api.analyses();
    expect(fetchMock.mock.calls[0]![1].headers.Authorization).toBe("Bearer old");
    expect(fetchMock.mock.calls[2]![1].headers.Authorization).toBe("Bearer new");
  });

  it("ignores an expired stored token", () => {
    localStorage.setItem("strata.guest", JSON.stringify({ token: "t", expires_at: new Date(Date.now() - 1).toISOString(), owner_id: "o" }));
    expect(readGuest()).toBeNull();
  });

  it("prefers an external (Supabase) token", async () => {
    setExternalTokenSource(async () => "sb-token");
    fetchMock.mockResolvedValueOnce(json([]));
    await api.examples();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]![1].headers.Authorization).toBe("Bearer sb-token");
  });

  it("raises ApiError with status, message and detail", async () => {
    setExternalTokenSource(async () => "t");
    fetchMock.mockResolvedValueOnce(json({ detail: "reference library is not installed", code: "reference_unavailable" }, 503));
    const err = await api.populations({ q: "x" }).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(503);
    expect((err as ApiError).message).toMatch(/not installed/);
    expect((err as ApiError).detail).toMatchObject({ code: "reference_unavailable" });
  });

  it("reports an unreachable API as status 0", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    const err = await request("/health", { anonymous: true }).catch((e: unknown) => e);
    expect((err as ApiError).unreachable).toBe(true);
  });

  it("uploads G25 text as multipart form data", async () => {
    setExternalTokenSource(async () => "t");
    fetchMock.mockResolvedValueOnce(json({ id: "d" }, 201));
    await api.uploadG25("A,1", "mine");
    const body = fetchMock.mock.calls[0]![1].body as FormData;
    expect(body.get("kind")).toBe("g25");
    expect(body.get("g25_text")).toBe("A,1");
    expect(body.get("name")).toBe("mine");
  });

  it("polls a job until it is terminal", async () => {
    const states: Job["status"][] = ["queued", "running", "succeeded"];
    const seen: string[] = [];
    const job = await pollJob("j", {
      intervalMs: 1,
      fetchJob: async () => ({ id: "j", kind: "k", status: states.shift()!, error: null, created_at: "", started_at: null, finished_at: null }),
      onUpdate: (j) => seen.push(j.status),
    });
    expect(job.status).toBe("succeeded");
    expect(seen).toEqual(["queued", "running", "succeeded"]);
  });

  it("decodes chat events and ignores unknown ones", () => {
    expect(decodeChatEvent("text_delta", '{"type":"text_delta","text":"a"}')).toEqual({ type: "text_delta", text: "a" });
    expect(decodeChatEvent("saved", '{"message_id":"m"}')).toEqual({ type: "saved", message_id: "m" });
    expect(decodeChatEvent("ping", "{}")).toBeNull();
    expect(decodeChatEvent("text_delta", "not json")).toBeNull();
  });

  it("streams chat events from an SSE body", async () => {
    setExternalTokenSource(async () => "t");
    const enc = new TextEncoder();
    const chunks = ['event: text_delta\ndata: {"type":"text_delta","text":"Hel', 'lo"}\n\n', 'event: done\ndata: {"type":"done","answer":"Hello","grounding":{"ok":true,"ungrounded":[]},"citations":[]}\n\n'];
    const body = new ReadableStream<Uint8Array>({
      start(c) {
        for (const ch of chunks) c.enqueue(enc.encode(ch));
        c.close();
      },
    });
    fetchMock.mockResolvedValueOnce(new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } }));
    const events = [];
    for await (const e of streamChat("s1", "hi")) events.push(e.type);
    expect(events).toEqual(["text_delta", "done"]);
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe(`${BASE}/api/v1/chat/sessions/s1/messages`);
    expect(JSON.parse(init.body)).toEqual({ content: "hi" });
    expect(init.headers.Accept).toBe("text/event-stream");
  });
});
