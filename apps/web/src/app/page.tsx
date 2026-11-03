"use client";

import Link from "next/link";
import { useMemo } from "react";
import { api } from "@/lib/api";
import { useResource } from "@/lib/useResource";
import { analysisLabel, int } from "@/lib/format";
import { sortPeriods } from "@/lib/periods";
import type { CoordinateSpaceInfo, PopulationSummary } from "@/lib/types";
import { PcaPlot } from "@/components/charts/PcaPlot";
import { CoreSample, type Layer } from "@/components/charts/CoreSample";
import { useSession } from "@/components/SessionProvider";
import { Explainer } from "@/components/Explainer";
import { BuildDiagram } from "@/components/BuildDiagram";
import { Term } from "@/components/Term";
import { Empty, ErrorNote, KindMark, Loading } from "@/components/typography";

/** Every population in the library, fetched page by page (the API caps a page). */
async function allPopulations(signal: AbortSignal): Promise<PopulationSummary[]> {
  const out: PopulationSummary[] = [];
  for (let page = 1; page < 50; page++) {
    const res = await api.populations({ page, page_size: 200 }, signal);
    out.push(...res.items);
    if (out.length >= res.total || res.items.length === 0) break;
  }
  return out;
}

function toLayers(pops: PopulationSummary[]): Layer[] {
  const by = new Map<string, Layer>();
  for (const p of pops) {
    const key = p.period ?? "Undated";
    const l = by.get(key) ?? { period: key, populations: 0, individuals: 0, minBp: null, maxBp: null };
    l.populations += 1;
    l.individuals += p.n_samples ?? 0;
    const lo = p.date_min_bp ?? p.date_mean_bp;
    const hi = p.date_max_bp ?? p.date_mean_bp;
    if (lo !== null && lo !== undefined) l.minBp = l.minBp === null ? lo : Math.min(l.minBp, lo);
    if (hi !== null && hi !== undefined) l.maxBp = l.maxBp === null ? hi : Math.max(l.maxBp, hi);
    by.set(key, l);
  }
  return sortPeriods([...by.values()], (l) => l.period);
}

function LibraryCore() {
  const pops = useResource((s) => allPopulations(s), []);
  const layers = useMemo(() => toLayers(pops.data ?? []), [pops.data]);
  if (pops.loading) return <Loading what="the reference library" />;
  if (pops.error) return <ErrorNote error={pops.error} retry={pops.reload} />;
  if (!layers.length)
    return (
      <Empty>
        The reference library has not been built on this server yet. The data pipeline in{" "}
        <code>data/pipeline</code> builds it; see <Link href="/data/">Data</Link>.
      </Empty>
    );
  const total = pops.data!.length;
  const individuals = pops.data!.reduce((a, p) => a + (p.n_samples ?? 0), 0);
  return (
    <figure>
      <CoreSample layers={layers} height={540} />
      <figcaption className="mt-4 text-caption text-ink-3">
        <span className="num text-ink-2">{int(total)}</span> populations,{" "}
        <span className="num text-ink-2">{int(individuals)}</span> individuals. Click a layer to browse it.
      </figcaption>
    </figure>
  );
}

type SpacesResource = ReturnType<typeof useSpaces>;
function useSpaces() {
  return useResource((s) => api.spaces(s), []);
}
const firstSpace = (d: CoordinateSpaceInfo[] | null | undefined) => d?.find((s) => s.populations.length > 0);

function ReferenceSpace({ spaces }: { spaces: SpacesResource }) {
  if (spaces.loading) return <Loading what="the reference space" />;
  if (spaces.error) return <ErrorNote error={spaces.error} retry={spaces.reload} />;
  const space = firstSpace(spaces.data);
  if (!space)
    return <Empty>The reference space has not been built on this server yet, so there is nothing to plot.</Empty>;
  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_16rem] lg:gap-12">
      <figure className="panel min-w-0 p-3 sm:p-5">
        <PcaPlot space={space} compact height={430} />
      </figure>
      <div className="text-small leading-[1.6] text-ink-2 lg:pt-2">
        <p>
          Each mark is a population, placed by <Term k="pca" />. Close together means genetically similar.
        </p>
        <p className="mt-4">
          <Link href="/library/" className="font-semibold">
            Open the library
          </Link>
        </p>
      </div>
    </div>
  );
}

function TwoKinds() {
  const rows: Array<[string, string, string]> = [
    ["Asks", "Which mix of sources sits closest?", "Does this model survive the data?"],
    ["Remember", "A good fit is not proof of admixture.", "Not rejected is not the same as true."],
  ];
  const col = (k: 1 | 2) => (
    <dl className="space-y-4">
      {rows.map((r) => (
        <div key={r[0]}>
          <dt className="text-caption font-semibold text-ink-3">{r[0]}</dt>
          <dd className="mt-0.5 text-small leading-[1.55] text-ink">{r[k]}</dd>
        </div>
      ))}
    </dl>
  );
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <div className="rounded-[var(--radius-panel)] border border-dashed border-[#c08419] bg-loess-soft/60 p-5 sm:p-6">
        <p className="mb-4 flex items-center gap-2">
          <KindMark kind="exploratory" />
          <span className="text-small text-ink-2">
            <Term k="pca" />, nearest, mixture fits
          </span>
        </p>
        {col(1)}
      </div>
      <div className="rounded-[var(--radius-panel)] border border-malachite bg-malachite-soft/70 p-5 sm:p-6">
        <p className="mb-4 flex items-center gap-2">
          <KindMark kind="formal" />
          <span className="text-small text-ink-2">
            <Term k="qpadm" />, qpWave, <Term k="f4">f4</Term>
          </span>
        </p>
        {col(2)}
      </div>
    </div>
  );
}

function ExampleList() {
  const ex = useResource((s) => api.examples(s), []);
  if (ex.loading) return <Loading what="examples" />;
  if (ex.error) return <ErrorNote error={ex.error} retry={ex.reload} />;
  if (!ex.data?.length)
    return <Empty>No precomputed examples are published on this server yet.</Empty>;
  const notes = [...new Set(ex.data.map((e) => e.caveats?.[0]).filter((c): c is string => !!c))];
  return (
    <>
      <ul className="panel divide-y divide-rule-soft">
        {ex.data.slice(0, 5).map((e) => (
          <li key={e.slug}>
            <Link
              href={`/examples/view/?slug=${encodeURIComponent(e.slug)}`}
              className="group grid gap-x-6 gap-y-1 px-5 py-4 no-underline hover:bg-wash sm:grid-cols-[minmax(0,1fr)_auto]"
            >
              <span className="min-w-0">
                <span className="block text-[1.2rem] leading-snug font-semibold text-ink group-hover:text-malachite">
                  {e.title}
                </span>
              </span>
              <span className="flex items-start gap-2 sm:justify-end sm:pt-0.5">
                <span className="text-caption text-ink-3">{analysisLabel(e.kind)}</span>
                <KindMark kind={e.result_kind} />
              </span>
            </Link>
          </li>
        ))}
      </ul>
      {notes.length ? (
        <p className="mt-3 text-caption text-ink-3">Archaic demo data from ADMIXTOOLS 2, not South Asian samples.</p>
      ) : null}
    </>
  );
}

function Heading({ children, id }: { children: React.ReactNode; id: string }) {
  return (
    <h2 id={id} className="mb-6 text-h2">
      {children}
    </h2>
  );
}

function Built({ spaces }: { spaces: SpacesResource }) {
  const sp = firstSpace(spaces.data);
  const prov = (sp?.provenance ?? {}) as Record<string, unknown>;
  const num = (v: unknown) => (typeof v === "number" ? v : null);
  return (
    <BuildDiagram
      stats={{ snps: num(prov.n_snps), projected: num(prov.n_projected_individuals), populations: sp?.populations.length ?? null }}
    />
  );
}

export default function Home() {
  const { session } = useSession();
  const spaces = useSpaces();
  return (
    <article>
      <header className="mb-20 grid gap-12 lg:grid-cols-[minmax(0,1fr)_minmax(20rem,26rem)] lg:gap-14">
        <div className="flex flex-col">
          <h1 className="display text-[3.6rem] leading-none sm:text-[4.6rem] xl:text-[5.4rem]">Strata</h1>
          <p className="serif mt-3 text-[1.55rem] leading-snug text-ink-2 italic sm:text-[1.8rem]">
            a research instrument for population genetics
          </p>
          <div className="stratum-rule stratum-draw mt-7 w-24" aria-hidden />
          <p className="measure mt-7 text-[1.3rem] leading-[1.6] text-ink-2">
            Place a genome among ancient and present-day reference populations, then test which ancestry models the
            data supports.
          </p>
          <div className="mt-8 flex flex-wrap items-center gap-3">
            <Link href="/upload/" className="btn">
              Upload a genome
            </Link>
            <Link href="/examples/" className="btn btn-quiet">
              See worked examples
            </Link>
          </div>
          <p className="mt-auto pt-10 text-caption text-ink-3">
            Your genotypes are encrypted and never reach the AI.
            {session.status === "guest" ? " Guest data is deleted after 24 hours." : ""}
          </p>
        </div>
        <div className="min-w-0">
          <LibraryCore />
        </div>
      </header>

      <section className="mb-20" aria-labelledby="flow">
        <Heading id="flow">How it works</Heading>
        <Explainer />
      </section>

      <section className="mb-20" aria-labelledby="space">
        <Heading id="space">The reference space</Heading>
        <ReferenceSpace spaces={spaces} />
      </section>

      <section className="mb-20" aria-labelledby="kinds">
        <Heading id="kinds">Two kinds of answer</Heading>
        <TwoKinds />
      </section>

      <section className="mb-20" aria-labelledby="built">
        <Heading id="built">How it is built</Heading>
        <Built spaces={spaces} />
      </section>

      <section aria-labelledby="examples">
        <div className="mb-6 flex flex-wrap items-baseline justify-between gap-4">
          <h2 id="examples" className="text-h2">
            Worked examples
          </h2>
          <Link href="/examples/" className="text-small font-semibold">
            All examples
          </Link>
        </div>
        <ExampleList />
      </section>
    </article>
  );
}
