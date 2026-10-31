import type { Metadata } from "next";
import { Markdown } from "@/components/Markdown";
import { Empty, PageHeader, Section, TableFigure } from "@/components/typography";
import { readDocs, readJson, readOptional } from "@/lib/server/docs";
import { PublicationsTable } from "./PublicationsTable";

export const metadata: Metadata = { title: "Data" };

interface ManifestEntry {
  path?: string;
  file?: string;
  sha256?: string;
  bytes?: number;
  size_bytes?: number;
  description?: string;
  source?: string;
  license?: string;
}

function manifestEntries(m: unknown): ManifestEntry[] {
  if (!m || typeof m !== "object") return [];
  const o = m as Record<string, unknown>;
  const files = o.files ?? o.artifacts ?? o.entries;
  if (Array.isArray(files)) return files as ManifestEntry[];
  if (files && typeof files === "object")
    return Object.entries(files as Record<string, ManifestEntry>).map(([path, e]) => ({ path, ...e }));
  return [];
}

export default function DataPage() {
  const docs = [
    readOptional("docs/DATA.md"),
    readOptional("docs/data-provenance.md"),
    ...readDocs("docs/data"),
    readOptional("data/pipeline/README.md"),
  ].filter((d): d is NonNullable<typeof d> => d !== null);
  const manifest = readJson<Record<string, unknown>>("data/derived/MANIFEST.json");
  const entries = manifestEntries(manifest);
  let n = 0;

  return (
    <>
      <PageHeader
        kicker="Provenance"
        title="Data sources and licences"
        lede="Where the reference data come from, how they were processed, and the terms under which they may be reused."
      />

      <Section n={++n} title="Principles" aside="Strata does not redistribute raw genotype data from the Allen Ancient DNA Resource; the pipeline downloads it from its original source.">
        <div className="measure prose-journal">
          <p>
            Every reference population is traceable to the individuals that compose it and to the
            publications that reported them. Derived artefacts committed to the repository carry a
            SHA-256 checksum, and each analysis records the version of the reference library it
            used.
          </p>
          <p>
            Data uploaded by users are not reference data. They are never added to the library,
            never shared, and are deleted on request or, for guests, after 24 hours.
          </p>
        </div>
      </Section>

      {docs.map((d) => (
        <Section key={d.file} n={++n} title={d.title}>
          <div className="max-w-[40rem]">
            <Markdown idPrefix={`${d.slug}--`}>{d.body}</Markdown>
            <p className="mt-4 text-caption text-ink-3">
              Source: <code>{d.file}</code>
            </p>
          </div>
        </Section>
      ))}

      <Section n={++n} title="Derived artefacts">
        {entries.length === 0 ? (
          <Empty>
            No derived-artefact manifest was present when this site was built
            (<code>data/derived/MANIFEST.json</code>). Run the data pipeline to produce it.
          </Empty>
        ) : (
          <TableFigure n={1} caption="Derived files shipped with this build, from data/derived/MANIFEST.json.">
            <table className="booktabs">
              <thead>
                <tr>
                  <th>File</th>
                  <th>Description</th>
                  <th className="r">Size</th>
                  <th>SHA-256</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((e) => {
                  const bytes = e.bytes ?? e.size_bytes;
                  return (
                    <tr key={e.path ?? e.file}>
                      <td className="font-mono text-[0.75rem]">{e.path ?? e.file}</td>
                      <td>{[e.description, e.source, e.license].filter(Boolean).join("; ") || "—"}</td>
                      <td className="r num whitespace-nowrap">
                        {bytes !== undefined ? `${(bytes / 1024).toFixed(1)} KB` : "—"}
                      </td>
                      <td className="font-mono text-[0.7rem] text-ink-2">{e.sha256 ? `${e.sha256.slice(0, 16)}…` : "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </TableFigure>
        )}
      </Section>

      <Section n={++n} title="Publications">
        <p className="measure mb-4 text-small text-ink-2">
          The publications whose samples make up the reference library, as reported by the API.
          Cite them when you use results that depend on their data.
        </p>
        <PublicationsTable />
      </Section>
    </>
  );
}
