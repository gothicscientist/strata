"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { api } from "@/lib/api";
import { analysisLabel } from "@/lib/format";
import { asAnalysisResult } from "@/lib/results";
import { useResource } from "@/lib/useResource";
import { ResultView } from "@/components/results/ResultView";
import { describeParams, ProvenanceList } from "@/components/results/AnalysisDocument";
import { Empty, ErrorNote, Fold, KindMark, Loading, PageHeader } from "@/components/typography";

function ExampleInner() {
  const slug = useSearchParams().get("slug");
  const ex = useResource(slug ? (s) => api.example(slug, s) : null, [slug]);
  if (!slug)
    return (
      <Empty>
        No example was specified. See the <Link href="/examples/">list of examples</Link>.
      </Empty>
    );
  if (ex.loading) return <Loading what="the example" />;
  if (ex.error) return <ErrorNote error={ex.error} retry={ex.reload} />;
  const e = ex.data;
  if (!e) return null;
  const result = asAnalysisResult(e.result);
  const inputs = describeParams(e.inputs);
  // Machine-local paths (e.g. a temporary f2 directory) carry no information for the reader.
  const params = describeParams(Object.fromEntries(Object.entries(e.params).filter(([k]) => k !== "f2_dir")));

  return (
    <article>
      <p className="mb-6 text-small">
        <Link href="/examples/">Examples</Link>
      </p>
      <PageHeader
        kicker={analysisLabel(e.kind)}
        title={e.title}
        aside={
          <p>
            <KindMark kind={e.result_kind} />
          </p>
        }
      />
      <section className="mb-12" aria-label="Results">
        {result ? <ResultView result={result} /> : <Empty>This example has no displayable result.</Empty>}
      </section>
      <Fold title="About this example">
        {e.description ? (
          <div className="measure prose-journal">
            {e.description.split(/\n{2,}/).map((para, i) => (
              <p key={i}>{para}</p>
            ))}
          </div>
        ) : null}
        {e.caveats?.map((c, i) => (
          <p key={i} className="measure mt-3 text-small text-ink-2">
            {c}
          </p>
        ))}
      </Fold>
      <Fold title="Inputs and parameters">
        <dl className="kv max-w-[48rem]">
          {[...inputs, ...params].map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="text-ink-3">{k}</dt>
              <dd className="num break-words">{v}</dd>
            </div>
          ))}
        </dl>
      </Fold>
      <Fold title="Provenance">
        <ProvenanceList provenance={e.provenance} />
      </Fold>
    </article>
  );
}

export default function ExampleViewPage() {
  return (
    <Suspense fallback={<Loading what="the example" />}>
      <ExampleInner />
    </Suspense>
  );
}
