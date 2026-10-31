import { describe, expect, it } from "vitest";
import { SSEParser } from "@/lib/sse";
import { bp, bpRange, fixed, int, pct, pValue, weightSe } from "@/lib/format";
import { parseG25 } from "@/lib/g25";
import { asAnalysisResult, inferResultType, qpadmNotes } from "@/lib/results";
import { buildAnalysisRequest, type ComposerState } from "@/lib/composer";
import { applyEvent, citationHref, emptyAssistant, parseBlocks, parseInline, turnsFromHistory } from "@/lib/chat";
import { comparisonTable } from "@/lib/compare";
import { shortCitation, doiUrl } from "@/lib/citation";
import { regionSlots, sourceColor, OTHER, SERIES } from "@/lib/palette";
import { synthAnalysis, synthDataset, synthFit, synthNearest, synthQpAdm } from "./fixtures";

describe("SSEParser", () => {
  it("parses events split across chunks and CRLF line endings", () => {
    const p = new SSEParser();
    expect(p.feed("event: text_delta\r\ndata: {\"type\":\"text_")).toEqual([]);
    const out = p.feed("delta\",\"text\":\"Hi\"}\r\n\r\n: ping\n\nevent: done\ndata: {}\n\n");
    expect(out).toEqual([
      { event: "text_delta", data: '{"type":"text_delta","text":"Hi"}' },
      { event: "done", data: "{}" },
    ]);
  });
  it("joins multi-line data and defaults the event name", () => {
    const p = new SSEParser();
    expect(p.feed("data: a\ndata: b\nid: 7\n\n")).toEqual([{ event: "message", data: "a\nb", id: "7" }]);
  });
  it("flushes a final event without trailing blank line", () => {
    const p = new SSEParser();
    p.feed("event: x\ndata: 1");
    expect(p.end()).toEqual([{ event: "x", data: "1" }]);
  });
});

describe("format", () => {
  it("formats numbers typographically", () => {
    expect(fixed(-0.5, 2)).toBe("−0.50");
    expect(int(12345)).toBe("12 345");
    expect(int(1234)).toBe("1234");
    expect(pct(0.4213)).toBe("42.1%");
    expect(weightSe(0.421, 0.034)).toBe("42.1 ± 3.4");
    expect(fixed(null)).toBe("—");
  });
  it("formats p-values with scientific notation below 0.001", () => {
    expect(pValue(0.0423)).toBe("0.0423");
    expect(pValue(0.5)).toBe("0.5");
    expect(pValue(3.2e-5)).toBe("3.2 × 10⁻⁵");
  });
  it("formats BP dates and ranges oldest first", () => {
    expect(bp(4500)).toBe("4500 BP");
    expect(bpRange(4800, 5200)).toBe("5200–4800 BP");
    expect(bpRange(null, null, 12000)).toBe("12 000 BP");
    expect(bpRange(3000, 3000)).toBe("3000 BP");
  });
});

describe("parseG25", () => {
  const row = (name: string, v = 0.01) => [name, ...Array(25).fill(v)].join(",");
  it("accepts rows with a header and reports counts", () => {
    const header = ["Name", ...Array.from({ length: 25 }, (_, i) => `PC${i + 1}`)].join(",");
    const r = parseG25(`${header}\n${row("A")}\n${row("B")}`);
    expect(r.hadHeader).toBe(true);
    expect(r.rows.map((x) => x.name)).toEqual(["A", "B"]);
    expect(r.errors).toEqual([]);
  });
  it("reports wrong column counts, non-numeric values and duplicates", () => {
    const r = parseG25(`A,0.1,0.2\n${row("B").replace(/,0\.01$/, ",abc")}\n${row("C")}\n${row("C")}`);
    expect(r.errors.map((e) => e.line)).toEqual([1, 2, 4]);
    expect(r.errors[0]!.message).toMatch(/expected 25/);
    expect(r.errors[1]!.message).toMatch(/PC25/);
    expect(r.errors[2]!.message).toMatch(/duplicate/);
  });
  it("warns on unscaled values and accepts tabs", () => {
    const r = parseG25(["X", ...Array(25).fill(3)].join("\t"));
    expect(r.rows).toHaveLength(1);
    expect(r.warnings).toHaveLength(1);
  });
});

describe("results", () => {
  it("infers result types for agent payloads without `type`", () => {
    expect(inferResultType({ hits: [] })).toBe("nearest");
    expect(inferResultType({ kind: "formal", weights: [], p_value: 0.1 })).toBe("qpadm");
    expect(inferResultType({ kind: "exploratory", weights: [] })).toBe("admixture_fit");
    expect(inferResultType({ models: [], right: [] })).toBe("qpadm_rotate");
    expect(inferResultType({ models: [] })).toBe("admixture_rotate");
    expect(inferResultType({ targets: [] })).toBe("pca_project");
    expect(inferResultType({ exploratory_table: [] })).toBeNull();
    expect(asAnalysisResult({ hits: [] })?.type).toBe("nearest");
  });
  it("writes conservative qpAdm notes (rejection, infeasibility)", () => {
    const notes = qpadmNotes(synthQpAdm);
    expect(notes[0]!.level).toBe("reject");
    expect(notes.some((n) => /Infeasible/.test(n.text))).toBe(true);
    const ok = qpadmNotes({ ...synthQpAdm, p_value: 0.3, feasible: true, weights: [{ source: "A", weight: 1, se: 0.01, z: 100 }], left: ["A"] });
    expect(ok[0]!.text).toMatch(/not rejected/);
    expect(ok[0]!.text).toMatch(/not proof/);
  });
});

describe("composer", () => {
  const base: ComposerState = {
    method: "admixture_fit",
    datasetId: synthDataset.id,
    sample: "SYNTH_1",
    targetPopulation: [],
    space: "strata-pca-v1",
    k: 20,
    sources: [{ id: "A", name: "A" }],
    bootstrap: 500,
    seed: 1,
    sensitivity: true,
    minSources: 1,
    maxSources: 3,
    maxModels: 100,
    left: [],
    right: [],
    allsnps: false,
    title: " ",
  };
  it("requires two sources for a fit", () => {
    const r = buildAnalysisRequest(base, synthDataset);
    expect(r.ok).toBe(false);
  });
  it("builds a fit request", () => {
    const r = buildAnalysisRequest({ ...base, sources: [{ id: "A", name: "A" }, { id: "B", name: "B" }] }, synthDataset);
    expect(r).toEqual({
      ok: true,
      request: {
        kind: "admixture_fit",
        dataset_id: synthDataset.id,
        target: "SYNTH_1",
        params: { space: "strata-pca-v1", sources: ["A", "B"], bootstrap: 500, seed: 1, sensitivity: true },
      },
    });
  });
  it("rejects G25 datasets for qpAdm and needs more right than left", () => {
    const g25 = { ...synthDataset, kind: "g25" as const };
    const r = buildAnalysisRequest({ ...base, method: "qpadm", left: [{ id: "A", name: "A" }], right: [{ id: "R", name: "R" }] }, g25);
    expect(r.ok).toBe(false);
    if (!r.ok) {
      expect(r.problems.join(" ")).toMatch(/G25/);
      expect(r.problems.join(" ")).toMatch(/at least two right/);
    }
  });
  it("uses a library population as qpAdm target", () => {
    const r = buildAnalysisRequest(
      {
        ...base,
        method: "qpadm",
        targetPopulation: [{ id: "T", name: "T" }],
        left: [{ id: "A", name: "A" }],
        right: [{ id: "R1", name: "R1" }, { id: "R2", name: "R2" }],
      },
      null,
    );
    expect(r.ok && r.request).toMatchObject({ kind: "qpadm", dataset_id: null, target: "T", params: { left: ["A"], right: ["R1", "R2"], target_population: "T" } });
  });
});

describe("chat", () => {
  it("folds a stream of events into a turn", () => {
    let t = emptyAssistant();
    t = applyEvent(t, { type: "text_delta", text: "Hello " });
    t = applyEvent(t, { type: "text_delta", text: "world" });
    t = applyEvent(t, { type: "tool_call", id: "c1", name: "fit_admixture", arguments: { target: "X" } });
    t = applyEvent(t, { type: "tool_result", id: "c1", name: "fit_admixture", ok: true, result: { hits: [] }, error: null, duration_ms: 12 });
    t = applyEvent(t, { type: "saved", message_id: "m1" });
    t = applyEvent(t, { type: "done", answer: "Hello world", grounding: { ok: false, ungrounded: [{ value: "12.3", context: "c" }] }, citations: ["methods/qpadm.md#x"] });
    expect(t.parts).toHaveLength(2);
    expect(t.parts[0]).toEqual({ kind: "text", text: "Hello world" });
    expect(t.parts[1]).toMatchObject({ kind: "tool", n: 1, status: "ok", durationMs: 12 });
    expect(t.done).toBe(true);
    expect(t.messageId).toBe("m1");
    expect(t.grounding?.ok).toBe(false);
  });
  it("uses the final answer when nothing was streamed", () => {
    const t = applyEvent(emptyAssistant(), { type: "done", answer: "Only answer", grounding: { ok: true, ungrounded: [] }, citations: [] });
    expect(t.parts).toEqual([{ kind: "text", text: "Only answer" }]);
  });
  it("parses inline markup and citations", () => {
    expect(parseInline("See [methods/qpadm.md#right-set] and `code`, **b** *i*.")).toEqual([
      { t: "text", v: "See " },
      { t: "cite", id: "methods/qpadm.md#right-set" },
      { t: "text", v: " and " },
      { t: "code", v: "code" },
      { t: "text", v: ", " },
      { t: "strong", v: "b" },
      { t: "text", v: " " },
      { t: "em", v: "i" },
      { t: "text", v: "." },
    ]);
    expect(citationHref("methods/qpadm.md#right-set")).toBe("/methods/#qpadm--right-set");
    expect(citationHref("methods/pca.md")).toBe("/methods/#pca");
  });
  it("splits blocks into paragraphs and lists", () => {
    expect(parseBlocks("A\nB\n\n- x\n- y\n\n1. one\n2. two\n\n## H")).toEqual([
      { t: "p", v: "A B" },
      { t: "ul", items: ["x", "y"] },
      { t: "ol", items: ["one", "two"] },
      { t: "h", v: "H" },
    ]);
  });
  it("rebuilds turns from persisted history", () => {
    const turns = turnsFromHistory([
      { id: "2", seq: 2, role: "assistant", content: "A", tool_calls: [{ id: "c", name: "n", arguments: {} }], tool_results: [{ id: "c", name: "n", ok: true, result: {}, error: null }], grounding: null, citations: [], usage: null, error: null, created_at: "" },
      { id: "1", seq: 1, role: "user", content: "Q", tool_calls: [], tool_results: [], grounding: null, citations: [], usage: null, error: null, created_at: "" },
    ]);
    expect(turns[0]).toEqual({ role: "user", content: "Q" });
    expect(turns[1]).toMatchObject({ role: "assistant", done: true });
  });
});

describe("compare", () => {
  it("builds a side-by-side table across exploratory and formal models", () => {
    const t = comparisonTable([
      synthAnalysis(synthFit, "a", "admixture_fit"),
      synthAnalysis(synthQpAdm, "b", "qpadm"),
      synthAnalysis(synthNearest, "c", "nearest"),
    ]);
    expect(t.columns.map((c) => c.kind)).toEqual(["exploratory", "formal"]);
    expect(t.rows.map((r) => r.source)).toEqual(["Synthetic A", "Synthetic B"]);
    expect(t.rows[0]!.cells[0]).toBe("30.0% [20.0%, 40.0%]");
    expect(t.stats.map((s) => s.label)).toEqual(["Target", "Residual distance", "qpAdm p"]);
  });
});

describe("citation and palette", () => {
  it("shortens citations", () => {
    expect(shortCitation({ id: "p", year: 2015, citation: "Haak, W., Lazaridis, I., et al. Massive migration" })).toBe("Haak et al. 2015");
    expect(shortCitation({ id: "p", year: null, citation: "Smith (2019) Title" })).toBe("Smith 2019");
    expect(doiUrl("https://doi.org/10.1/x")).toBe("https://doi.org/10.1/x");
    expect(doiUrl(null)).toBeNull();
  });
  it("assigns fixed slots by size and folds the rest into grey", () => {
    const regions = ["a", "b", "c", "d", "e", "f", "g"].flatMap((r, i) => Array(10 - i).fill({ region: r }));
    const s = regionSlots(regions);
    expect(s.get("a")!.color).toBe(SERIES[0]);
    expect(s.get("g")!.color).toBe(OTHER);
    expect(sourceColor(6)).toBe(OTHER);
  });
});
