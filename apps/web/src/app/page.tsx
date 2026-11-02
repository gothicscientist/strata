"use client";

import Link from "next/link";
import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useResource } from "@/lib/useResource";
import { analysisLabel, int } from "@/lib/format";
import { sortPeriods } from "@/lib/periods";
import type { PopulationSummary } from "@/lib/types";
import { PcaPlot } from "@/components/charts/PcaPlot";
import { CoreSample, type Layer } from "@/components/charts/CoreSample";
import { useSession } from "@/components/SessionProvider";
import { Empty, ErrorNote, Footnote, KindMark, Loading } from "@/components/typography";

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
      <figcaption className="mt-4 text-caption leading-[1.55] text-ink-3">
        The reference library as a core sample: <span className="num text-ink-2">{int(total)}</span>{" "}
        populations and <span className="num text-ink-2">{int(individuals)}</span> individuals, one layer
        per period, youngest at the surface. Thicker layers hold more populations. Select a layer to
        browse it.
      </figcaption>
    </figure>
  );
}

const STEPS: Array<{ title: string; body: string; href: string; action: string }> = [
  {
    title: "Upload",
    body: "A raw file from 23andMe, AncestryDNA, FamilyTreeDNA or MyHeritage, a single-sample VCF, or Global25-style coordinates.",
    href: "/upload/",
    action: "Upload a file",
  },
  {
    title: "Place",
    body: "Project the sample into the reference PCA using only the SNPs it carries, and rank the populations nearest to it.",
    href: "/analyses/new/?method=pca_project",
    action: "Project a sample",
  },
  {
    title: "Fit",
    body: "Find the mixture of candidate sources that lies closest to the sample, with bootstrap intervals and leave-one-out checks.",
    href: "/analyses/new/?method=admixture_fit",
    action: "Fit sources",
  },
  {
    title: "Test",
    body: "Test the models that survive formally with qpAdm on f-statistics, against a stated set of outgroups.",
    href: "/analyses/new/?method=qpadm",
    action: "Set up qpAdm",
  },
];

/** True once the element has scrolled into view (and stays true). */
function useSeen<T extends HTMLElement>(): [React.RefObject<T | null>, boolean] {
  const ref = useRef<T | null>(null);
  const [seen, setSeen] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof IntersectionObserver === "undefined") {
      setSeen(true);
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setSeen(true);
          io.disconnect();
        }
      },
      { threshold: 0.35 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return [ref, seen];
}

function Workflow() {
  const [ref, seen] = useSeen<HTMLOListElement>();
  return (
    <ol ref={ref} className="relative grid gap-8 sm:grid-cols-2 lg:grid-cols-4 lg:gap-6">
      <span
        aria-hidden
        className="absolute top-[0.9rem] right-[calc(25%-0.6rem)] left-[0.9rem] hidden h-px origin-left bg-ink/25 transition-transform duration-[1400ms] ease-[cubic-bezier(.65,0,.35,1)] lg:block"
        style={{ transform: seen ? "scaleX(1)" : "scaleX(0)" }}
      />
      {STEPS.map((s, i) => (
        <li key={s.title} className="group relative">
          <span
            className={`num relative z-10 mb-4 flex size-7 items-center justify-center rounded-full bg-ink text-[0.9rem] font-semibold text-white transition-[background-color,transform] duration-200 group-hover:-translate-y-0.5 group-hover:rotate-[-8deg] group-hover:bg-malachite ${
              seen ? "pop" : "opacity-0"
            }`}
            style={{ animationDelay: `${i * 300}ms` }}
          >
            {i + 1}
          </span>
          <h3 className="text-h3">{s.title}</h3>
          <p className="mt-1.5 text-small leading-[1.55] text-ink-2">{s.body}</p>
          <Link href={s.href} className="mt-3 inline-block text-small font-semibold">
            {s.action}
          </Link>
        </li>
      ))}
    </ol>
  );
}

function ReferenceSpace() {
  const spaces = useResource((s) => api.spaces(s), []);
  if (spaces.loading) return <Loading what="the reference space" />;
  if (spaces.error) return <ErrorNote error={spaces.error} retry={spaces.reload} />;
  const space = spaces.data?.find((s) => s.populations.length > 0);
  if (!space)
    return <Empty>The reference space has not been built on this server yet, so there is nothing to plot.</Empty>;
  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_16rem] lg:gap-12">
      <figure className="panel min-w-0 p-3 sm:p-5">
        <PcaPlot space={space} compact height={430} />
      </figure>
      <div className="text-small leading-[1.6] text-ink-2 lg:pt-2">
        <p>
          Every population mean in <em>{space.name}</em>, the space your sample is projected into.
          Distance here is the first thing Strata measures, and the last thing it should be trusted
          for on its own.
        </p>
        <p className="mt-3">
          <span className="num font-semibold text-ink">{space.populations.length}</span> populations,
          coloured and shaped by region. Hover a mark for its name and sample count.
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
    ["Method", "Non-negative least squares on PCA or G25 coordinates", "qpAdm on f4-statistics (ADMIXTOOLS 2)"],
    [
      "Question",
      "Which mixture of sources lies closest to the target in this space?",
      "Is the target consistent with descending from these sources, given outgroups?",
    ],
    [
      "Uncertainty",
      "Bootstrap over source individuals; sensitivity to dropped sources and dimensions",
      "Block-jackknife standard errors; tail probability of the rank test",
    ],
    ["How to read it", "A description of geometry. A good fit is not evidence of admixture.", "A model can be rejected. A model that is not rejected may still be wrong."],
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
          <span className="text-small text-ink-2">PCA projection, nearest populations, mixture fits</span>
        </p>
        {col(1)}
      </div>
      <div className="rounded-[var(--radius-panel)] border border-malachite bg-malachite-soft/70 p-5 sm:p-6">
        <p className="mb-4 flex items-center gap-2">
          <KindMark kind="formal" />
          <span className="text-small text-ink-2">qpAdm, qpAdm rotation, qpWave, f4</span>
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
                <span className="mt-1 block text-small text-ink-2">{e.summary}</span>
              </span>
              <span className="flex items-start gap-2 sm:justify-end sm:pt-0.5">
                <span className="text-caption text-ink-3">{analysisLabel(e.kind)}</span>
                <KindMark kind={e.result_kind} />
              </span>
            </Link>
          </li>
        ))}
      </ul>
      {notes.map((n) => (
        <Footnote key={n} mark="*">
          {n}
        </Footnote>
      ))}
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

export default function Home() {
  const { session } = useSession();
  return (
    <article>
      <header className="mb-20 grid gap-12 lg:grid-cols-[minmax(0,1fr)_minmax(20rem,26rem)] lg:gap-14">
        <div className="flex flex-col">
          <h1 className="display text-[2.9rem] sm:text-[3.6rem] xl:text-display">
            {["Ancient", "DNA,", "read", "layer", "by", "layer."].map((w, i) => (
              <Fragment key={i}>
                <span className="settle" style={{ animationDelay: `${120 + i * 90}ms` }}>
                  {w}
                </span>{" "}
              </Fragment>
            ))}
          </h1>
          <p className="serif measure mt-7 text-[1.4rem] leading-[1.55] text-ink-2">
            Strata places a genome among ancient and present-day reference populations, fits mixture
            models with their uncertainty, and tests them formally with qpAdm. Every result states its
            method and the reference data it rests on.
          </p>
          <div className="mt-8 flex flex-wrap items-center gap-3">
            <Link href="/upload/" className="btn">
              Upload a genome
            </Link>
            <Link href="/examples/" className="btn btn-quiet">
              See worked examples
            </Link>
          </div>
          <div className="mt-auto pt-12">
            <div className="max-w-[30rem] border-l-[3px] border-malachite pl-4 text-caption leading-[1.6] text-ink-2">
              <p className="font-semibold text-ink">Your data</p>
              <p className="mt-0.5">
                Raw genotype files are parsed in memory. Only SNPs on the reference panel are kept,
                encrypted, and never sent to a language model.{" "}
                {session.status === "guest"
                  ? "As a guest, uploads and analyses are deleted after 24 hours."
                  : session.status === "signed-in"
                    ? "Your workspace persists until you delete it."
                    : ""}
              </p>
            </div>
          </div>
        </div>
        <div className="min-w-0">
          <LibraryCore />
        </div>
      </header>

      <section className="mb-20" aria-labelledby="flow">
        <Heading id="flow">From raw file to formal test</Heading>
        <Workflow />
      </section>

      <section className="mb-20" aria-labelledby="space">
        <Heading id="space">The reference space</Heading>
        <ReferenceSpace />
      </section>

      <section className="mb-20" aria-labelledby="kinds">
        <Heading id="kinds">Two kinds of answer, never mixed</Heading>
        <p className="measure -mt-2 mb-6 text-ink-2">
          An exploratory fit describes where a sample sits. A formal test asks whether a model of its
          ancestry survives the data. Every result in Strata carries one of these two marks.
        </p>
        <TwoKinds />
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
