"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { analysisLabel, dateTime, isFormal, relativeExpiry } from "@/lib/format";
import { comparisonTable } from "@/lib/compare";
import { useResource } from "@/lib/useResource";
import type { Analysis, Dataset } from "@/lib/types";
import { QcReport } from "@/components/QcReport";
import { useSession } from "@/components/SessionProvider";
import { Empty, ErrorNote, Footnote, KindMark, Loading, PageHeader, Section, TableFigure } from "@/components/typography";

const MAX_COMPARE = 4;

function Comparison({ ids }: { ids: string[] }) {
  const [items, setItems] = useState<Analysis[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    const ctrl = new AbortController();
    setError(null);
    Promise.all(ids.map((id) => api.analysis(id, ctrl.signal)))
      .then(setItems)
      .catch((e: unknown) => {
        if (!ctrl.signal.aborted) setError(e);
      });
    return () => ctrl.abort();
  }, [ids]);
  if (error) return <ErrorNote error={error} />;
  if (!items) return <Loading what="the selected models" />;
  const t = comparisonTable(items);
  if (!t.columns.length) return <Empty>The selected analyses have no mixture weights to compare.</Empty>;
  const mixed = new Set(t.columns.map((c) => c.kind)).size > 1;
  return (
    <TableFigure
      n={3}
      caption="Selected models side by side. Exploratory weights are percentages with the 95% bootstrap interval where available; qpAdm weights are unconstrained proportions ± SE."
      notes={
        mixed
          ? "Exploratory distances and qpAdm tail probabilities measure different things and cannot be ranked against each other."
          : undefined
      }
    >
      <table className="booktabs">
        <thead>
          <tr>
            <th>Source</th>
            {t.columns.map((c) => (
              <th key={c.id} className="r">
                <Link href={`/analysis/?id=${encodeURIComponent(c.id)}`} className="font-medium">
                  {c.title}
                </Link>
                <span className="mt-0.5 block">
                  <KindMark kind={c.kind} />
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {t.rows.map((r) => (
            <tr key={r.source}>
              <td>{r.source}</td>
              {r.cells.map((c, i) => (
                <td key={i} className="r num">
                  {c ?? "—"}
                </td>
              ))}
            </tr>
          ))}
          {t.stats.map((s) => (
            <tr key={s.label}>
              <td className="italic">{s.label}</td>
              {s.cells.map((c, i) => (
                <td key={i} className="r num">
                  {c ?? "—"}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </TableFigure>
  );
}

function DatasetRow({ d, onDeleted }: { d: Dataset; onDeleted: () => void }) {
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<unknown>(null);
  return (
    <>
      <tr>
        <td>
          <button type="button" className="linkish text-left" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
            {d.name}
          </button>
        </td>
        <td>{d.kind === "g25" ? "G25 coordinates" : d.kind === "vcf" ? "VCF" : (d.qc.vendor ?? "Raw genotypes")}</td>
        <td className="r num">{d.sample_names.length}</td>
        <td>{dateTime(d.created_at)}</td>
        <td className="text-ink-2">{relativeExpiry(d.expires_at)}</td>
        <td className="r whitespace-nowrap">
          {confirm ? (
            <span className="text-caption">
              Delete permanently?{" "}
              <button
                type="button"
                className="linkish text-alert"
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  try {
                    await api.deleteDataset(d.id);
                    onDeleted();
                  } catch (e) {
                    setError(e);
                    setBusy(false);
                  }
                }}
              >
                {busy ? "Deleting…" : "Delete"}
              </button>{" "}
              <button type="button" className="linkish" onClick={() => setConfirm(false)}>
                Keep
              </button>
            </span>
          ) : (
            <button type="button" className="linkish text-caption" onClick={() => setConfirm(true)}>
              Delete
            </button>
          )}
        </td>
      </tr>
      {open || error ? (
        <tr>
          <td colSpan={6} className="bg-wash/40">
            {error ? <ErrorNote error={error} /> : null}
            {open ? <QcReport dataset={d} n="2a" /> : null}
          </td>
        </tr>
      ) : null}
    </>
  );
}

export default function WorkspacePage() {
  const { session } = useSession();
  const analyses = useResource((s) => api.analyses(s), []);
  const datasets = useResource((s) => api.datasets(s), []);
  const [selected, setSelected] = useState<string[]>([]);

  const toggle = (id: string) =>
    setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : s.length >= MAX_COMPARE ? s : [...s, id]));

  const comparable = (a: Analysis) =>
    a.status === "succeeded" && ["admixture_fit", "qpadm"].includes(a.kind);

  return (
    <>
      <PageHeader
        kicker="Workspace"
        title="Your analyses and datasets"
        lede={
          session.status === "guest"
            ? "This is a guest workspace. Everything here is deleted 24 hours after it was created."
            : "Analyses and datasets you have created. Deleting a dataset destroys its encryption key."
        }
      />

      <Section n={1} title="Analyses">
        {analyses.loading ? (
          <Loading what="analyses" />
        ) : analyses.error ? (
          <ErrorNote error={analyses.error} retry={analyses.reload} />
        ) : !analyses.data?.length ? (
          <Empty>
            No analyses yet. <Link href="/analyses/new/">Compose one</Link>, or start from an{" "}
            <Link href="/examples/">example</Link>.
          </Empty>
        ) : (
          <TableFigure
            n={1}
            caption={`Analyses in this workspace. Select up to ${MAX_COMPARE} completed mixture models to compare them in Table 3.`}
          >
            <table className="booktabs">
              <thead>
                <tr>
                  <th className="w-8">
                    <span className="sr-only">Compare</span>
                  </th>
                  <th>Title</th>
                  <th>Method</th>
                  <th>Kind</th>
                  <th>Status</th>
                  <th>Created</th>
                </tr>
              </thead>
              <tbody>
                {analyses.data.map((a) => (
                  <tr key={a.id}>
                    <td>
                      <input
                        type="checkbox"
                        className=""
                        aria-label={`Compare ${a.title ?? analysisLabel(a.kind)}`}
                        disabled={!comparable(a) || (!selected.includes(a.id) && selected.length >= MAX_COMPARE)}
                        checked={selected.includes(a.id)}
                        onChange={() => toggle(a.id)}
                      />
                    </td>
                    <td>
                      <Link href={`/analysis/?id=${encodeURIComponent(a.id)}`}>{a.title ?? analysisLabel(a.kind)}</Link>
                    </td>
                    <td>{analysisLabel(a.kind)}</td>
                    <td>
                      <KindMark kind={isFormal(a.kind) ? "formal" : "exploratory"} />
                    </td>
                    <td className={a.status === "failed" ? "text-alert" : a.status === "succeeded" ? "" : "italic"}>
                      {a.status}
                    </td>
                    <td className="whitespace-nowrap">{dateTime(a.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableFigure>
        )}
      </Section>

      <Section n={2} title="Datasets">
        {datasets.loading ? (
          <Loading what="datasets" />
        ) : datasets.error ? (
          <ErrorNote error={datasets.error} retry={datasets.reload} />
        ) : !datasets.data?.length ? (
          <Empty>
            No datasets. <Link href="/upload/">Upload one</Link>.
          </Empty>
        ) : (
          <TableFigure n={2} caption="Datasets in this workspace. Select a name to show its quality-control report.">
            <table className="booktabs">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Format</th>
                  <th className="r">Samples</th>
                  <th>Uploaded</th>
                  <th>Retention</th>
                  <th className="r">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {datasets.data.map((d) => (
                  <DatasetRow key={d.id} d={d} onDeleted={datasets.reload} />
                ))}
              </tbody>
            </table>
          </TableFigure>
        )}
        <Footnote mark="*">
          Deletion is immediate and cannot be undone. Analyses already computed from a deleted dataset
          keep their results but can no longer be re-run.
        </Footnote>
      </Section>

      <Section n={3} title="Model comparison">
        {selected.length < 2 ? (
          <Empty>Select two or more completed mixture models in Table 1 to compare their weights.</Empty>
        ) : (
          <Comparison ids={selected} />
        )}
      </Section>
    </>
  );
}
