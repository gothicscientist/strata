"use client";

import Link from "next/link";
import { useId, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import { parseG25 } from "@/lib/g25";
import { relativeExpiry } from "@/lib/format";
import type { Dataset } from "@/lib/types";
import { QcReport } from "@/components/QcReport";
import { useSession } from "@/components/SessionProvider";
import { Caveat, ErrorNote, PageHeader, Section } from "@/components/typography";

const MAX_BYTES = 60 * 1e6;
const ACCEPT = ".txt,.csv,.tsv,.zip,.gz,.vcf,.vcf.gz";

export default function UploadPage() {
  const { session } = useSession();
  const [g25, setG25] = useState("");
  const [name, setName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [dataset, setDataset] = useState<Dataset | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const ids = { name: useId(), g25: useId(), file: useId() };

  const preview = useMemo(() => (g25.trim() ? parseG25(g25) : null), [g25]);

  async function submit(kind: "g25" | "file") {
    setBusy(true);
    setError(null);
    setDataset(null);
    try {
      const ds =
        kind === "g25" ? await api.uploadG25(g25, name || undefined) : await api.uploadFile(file!, name || undefined);
      setDataset(ds);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  function pick(f: File | undefined | null) {
    setError(null);
    if (!f) return;
    if (f.size > MAX_BYTES) {
      setError(new Error(`${f.name} is ${(f.size / 1e6).toFixed(0)} MB; the limit is 60 MB.`));
      return;
    }
    setFile(f);
  }

  return (
    <>
      <PageHeader
        kicker="Datasets"
        title="Upload a dataset"
        lede="Add a raw genotype file from a consumer test or a single-sample VCF, or paste Global25-style coordinates."
      />

      <Caveat title="How your genetic data is handled">
        Files are parsed in memory on the Strata server. Only genotypes at SNPs on the reference panel
        are kept, encrypted with a key unique to this dataset; deleting the dataset destroys the key.
        {session.status === "guest" ? (
          <> Guest datasets are deleted automatically after 24 hours ({relativeExpiry(session.expiresAt)} for this workspace).</>
        ) : null}{" "}
        Genotypes are never written to logs and never sent to the research assistant&rsquo;s language
        model, which sees only derived coordinates and identifiers. See <Link href="/data/">Data</Link>.
      </Caveat>

      <div className="mb-10 max-w-[24rem]">
        <label htmlFor={ids.name} className="label">
          Dataset name (optional)
        </label>
        <input
          id={ids.name}
          className="field"
          value={name}
          maxLength={120}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. My 23andMe v5"
        />
      </div>

      <div className="grid gap-x-14 gap-y-4 lg:grid-cols-2">
        <Section title="Raw genotype file" id="raw">
          <p className="mb-3 text-small text-ink-2">
            23andMe (v3 to v5), AncestryDNA (v1, v2), FamilyTreeDNA and MyHeritage CSV, or a
            single-sample VCF. Plain text, .zip or .gz, up to 60&nbsp;MB.
          </p>
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              pick(e.dataTransfer.files[0]);
            }}
            className={`flex h-56 flex-col items-center justify-center rounded-[var(--radius-panel)] border-2 border-dashed px-6 text-center text-small transition-colors ${
              dragging ? "border-malachite bg-malachite-soft" : "border-rule bg-panel"
            }`}
          >
            {file ? (
              <>
                <p className="font-medium">{file.name}</p>
                <p className="num mt-1 text-caption text-ink-3">{(file.size / 1e6).toFixed(1)} MB</p>
                <button type="button" className="linkish mt-3 text-caption" onClick={() => setFile(null)}>
                  Choose a different file
                </button>
              </>
            ) : (
              <>
                <p className="text-[1.2rem] font-semibold">Drop the file here</p>
                <p className="my-1 text-caption text-ink-3">or</p>
                <label htmlFor={ids.file} className="linkish cursor-pointer">
                  choose a file from your computer
                </label>
              </>
            )}
            <input
              ref={inputRef}
              id={ids.file}
              type="file"
              accept={ACCEPT}
              className="sr-only"
              onChange={(e) => pick(e.target.files?.[0])}
            />
          </div>
          <button type="button" className="btn mt-4" disabled={busy || !file} onClick={() => submit("file")}>
            {busy ? "Uploading and checking…" : "Upload file"}
          </button>
        </Section>

        <Section title="Or paste G25 coordinates" id="g25">
          <label htmlFor={ids.g25} className="label">
            One sample per line: a name, then 25 comma-separated coordinates. A header row is optional.
          </label>
          <textarea
            id={ids.g25}
            className="field h-56 resize-y"
            spellCheck={false}
            value={g25}
            onChange={(e) => setG25(e.target.value)}
            placeholder={"Sample_1,0.1234,0.0456,-0.0210, … (25 values)"}
            aria-describedby={`${ids.g25}-status`}
          />
          <div id={`${ids.g25}-status`} className="mt-2 min-h-[1.5rem] text-caption" aria-live="polite">
            {preview ? (
              preview.errors.length ? (
                <ul className="space-y-0.5 text-alert">
                  {preview.errors.slice(0, 4).map((e) => (
                    <li key={e.line}>
                      Line {e.line}: {e.message}.
                    </li>
                  ))}
                  {preview.errors.length > 4 ? <li>and {preview.errors.length - 4} more problems.</li> : null}
                </ul>
              ) : (
                <p className="text-ink-2">
                  {preview.rows.length} sample{preview.rows.length === 1 ? "" : "s"} recognised
                  {preview.hadHeader ? ", header row skipped" : ""}.
                  {preview.warnings.length ? ` ${preview.warnings[0]!.message}.` : ""}
                </p>
              )
            ) : null}
          </div>
          <button
            type="button"
            className="btn mt-4"
            disabled={busy || !preview || preview.rows.length === 0 || preview.errors.length > 0}
            onClick={() => submit("g25")}
          >
            {busy ? "Uploading…" : "Upload coordinates"}
          </button>
        </Section>

      </div>

      {error ? <ErrorNote error={error} /> : null}

      {dataset ? (
        <Section n={3} title="Quality control" id="qc">
          <QcReport dataset={dataset} />
          <div className="mt-6 flex flex-wrap items-center gap-6 text-small">
            <Link className="btn no-underline" href={`/analyses/new/?dataset=${encodeURIComponent(dataset.id)}`}>
              Analyse this dataset
            </Link>
            <Link href="/workspace/">Go to workspace</Link>
          </div>
        </Section>
      ) : null}
    </>
  );
}
