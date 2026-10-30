"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { analysisLabel, dateTime, isFormal } from "@/lib/format";
import type { Analysis } from "@/lib/types";
import { ResultView } from "./ResultView";
import { ErrorNote, KindMark, PageHeader, Section } from "@/components/typography";

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
    <dl className="grid max-w-[48rem] grid-cols-[minmax(8rem,auto)_1fr] gap-x-6 gap-y-1 text-small">
      {describeParams(provenance).map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-ink-3">{k}</dt>
          <dd className="num break-words">{v}</dd>
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
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
            <dt className="text-ink-3">Kind</dt>
            <dd>
              <KindMark kind={formal ? "formal" : "exploratory"} />
            </dd>
            <dt className="text-ink-3">Created</dt>
            <dd>{dateTime(analysis.created_at)}</dd>
            <dt className="text-ink-3">Finished</dt>
            <dd>{dateTime(analysis.finished_at)}</dd>
            <dt className="text-ink-3">Identifier</dt>
            <dd className="font-mono text-[0.72rem] break-all">{analysis.id}</dd>
          </dl>
        }
      />

      <Section n={1} title="Methods">
        {params.length ? (
          <dl className="grid max-w-[48rem] grid-cols-[minmax(8rem,auto)_1fr] gap-x-6 gap-y-1 text-small">
            {params.map(([k, v]) => (
              <div key={k} className="contents">
                <dt className="text-ink-3">{k}</dt>
                <dd className="num break-words">{v}</dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className="text-small text-ink-2 italic">Default parameters.</p>
        )}
      </Section>

      <Section n={2} title="Results">
        {analysis.result ? (
          <ResultView result={analysis.result} />
        ) : (
          <ErrorNote error={new Error(analysis.error ?? "The analysis produced no result.")} />
        )}
      </Section>

      {analysis.provenance ? (
        <Section n={3} title="Provenance">
          <ProvenanceList provenance={analysis.provenance} />
        </Section>
      ) : null}

      <Section n={analysis.provenance ? 4 : 3} title="Report">
        <p className="measure mb-4 text-small text-ink-2">
          The report records inputs, parameters, software and reference versions and every number
          shown above, so the analysis can be reproduced.
        </p>
        <ReportButtons id={analysis.id} />
      </Section>
    </article>
  );
}
