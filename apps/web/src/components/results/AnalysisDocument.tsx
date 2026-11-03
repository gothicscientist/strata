"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { analysisLabel, dateTime, isFormal } from "@/lib/format";
import type { Analysis } from "@/lib/types";
import { ResultView } from "./ResultView";
import { ErrorNote, Fold, KindMark, PageHeader } from "@/components/typography";

/** Plain-language description of an analysis' parameters, in the voice of a methods section. */
export function describeParams(params: Record<string, unknown>): Array<[string, string]> {
  const out: Array<[string, string]> = [];
  for (const [k, v] of Object.entries(params)) {
    if (v === null || v === undefined || v === "") continue;
    const label = k.replace(/_/g, " ");
    const value = Array.isArray(v)
      ? v.join(", ")
      : typeof v === "object"
        ? JSON.stringify(v)
        : typeof v === "boolean"
          ? v
            ? "yes"
            : "no"
          : String(v);
    out.push([label.charAt(0).toUpperCase() + label.slice(1), value]);
  }
  return out;
}

async function download(id: string, format: "html" | "json") {
  const res = await api.report(id, format);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `strata-analysis-${id}.${format}`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function ReportButtons({ id }: { id: string }) {
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const run = async (f: "html" | "json") => {
    setBusy(f);
    setError(null);
    try {
      await download(id, f);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(null);
    }
  };
  return (
    <div>
      <div className="flex flex-wrap gap-3">
        <button type="button" className="btn" onClick={() => run("html")} disabled={busy !== null}>
          {busy === "html" ? "Preparing report…" : "Download report (HTML)"}
        </button>
        <button type="button" className="btn btn-quiet" onClick={() => run("json")} disabled={busy !== null}>
          {busy === "json" ? "Preparing…" : "Download data (JSON)"}
        </button>
      </div>
      {error ? <ErrorNote error={error} /> : null}
    </div>
  );
}

export function ProvenanceList({ provenance }: { provenance: Record<string, unknown> | null | undefined }) {
  if (!provenance || Object.keys(provenance).length === 0) return null;
  return (
    <dl className="kv max-w-[48rem]">
      {describeParams(provenance).map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-ink-3">{k}</dt>
          <dd className="num min-w-0 [overflow-wrap:anywhere]">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function AnalysisDocument({ analysis }: { analysis: Analysis }) {
  const formal = isFormal(analysis.kind);
  const params = describeParams(analysis.params);
  return (
    <article>
      <PageHeader
        kicker={analysisLabel(analysis.kind)}
        title={analysis.title ?? `${analysisLabel(analysis.kind)}${analysis.params.target ? ` of ${String(analysis.params.target)}` : ""}`}
        aside={
          <p className="flex flex-wrap items-center gap-2">
            <KindMark kind={formal ? "formal" : "exploratory"} />
            <span className="text-ink-3">{dateTime(analysis.finished_at ?? analysis.created_at)}</span>
          </p>
        }
      />

      <section className="mb-12" aria-label="Results">
        {analysis.result ? (
          <ResultView result={analysis.result} />
        ) : (
          <ErrorNote error={new Error(analysis.error ?? "The analysis produced no result.")} />
        )}
      </section>

      <Fold title="Parameters">
        {params.length ? (
          <dl className="kv max-w-[48rem]">
            {params.map(([k, v]) => (
              <div key={k} className="contents">
                <dt className="text-ink-3">{k}</dt>
                <dd className="num min-w-0 [overflow-wrap:anywhere]">{v}</dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className="text-small text-ink-2 italic">Default parameters.</p>
        )}
      </Fold>

      {analysis.provenance ? (
        <Fold title="Provenance">
          <ProvenanceList provenance={analysis.provenance} />
        </Fold>
      ) : null}

      <div className="mt-8">
        <ReportButtons id={analysis.id} />
      </div>
    </article>
  );
}
