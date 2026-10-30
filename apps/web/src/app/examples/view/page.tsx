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
import { Empty, ErrorNote, KindMark, Loading, PageHeader, Section } from "@/components/typography";

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
  const params = describeParams(e.params);

  return (
    <article>
      <p className="mb-6 text-small">
        <Link href="/examples/">Examples</Link>
      </p>
      <PageHeader
        kicker={analysisLabel(e.kind)}
        title={e.title}
        lede={e.summary}
        aside={
          <p>
            <KindMark kind={e.result_kind} />
          </p>
        }
      />
      {e.description ? (
        <div className="measure prose-journal mb-12">
          {e.description.split(/\n{2,}/).map((para, i) => (
            <p key={i}>{para}</p>
          ))}
        </div>
      ) : null}
      <Section n={1} title="Inputs and parameters">
        <dl className="grid max-w-[48rem] grid-cols-[minmax(8rem,auto)_1fr] gap-x-6 gap-y-1 text-small">
          {[...inputs, ...params].map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="text-ink-3">{k}</dt>
              <dd className="num break-words">{v}</dd>
            </div>
          ))}
        </dl>
      </Section>
      <Section n={2} title="Results">
        {result ? <ResultView result={result} /> : <Empty>This example has no displayable result.</Empty>}
      </Section>
      <Section n={3} title="Provenance">
        <ProvenanceList provenance={e.provenance} />
      </Section>
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
