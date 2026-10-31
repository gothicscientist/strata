"use client";

import Link from "next/link";
import { api } from "@/lib/api";
import { useResource } from "@/lib/useResource";
import { analysisLabel } from "@/lib/format";
import { PcaPlot } from "@/components/charts/PcaPlot";
import { useSession } from "@/components/SessionProvider";
import { Empty, ErrorNote, Figure, KindMark, Loading, Section } from "@/components/typography";

function LibraryFigure() {
  const spaces = useResource((s) => api.spaces(s), []);
  if (spaces.loading) return <Loading what="the reference space" />;
  if (spaces.error) return <ErrorNote error={spaces.error} retry={spaces.reload} />;
  const space = spaces.data?.find((s) => s.populations.length > 0);
  if (!space)
    return (
      <Empty>
        The reference library has not been built on this server yet, so there is nothing to plot.
        The data pipeline in <code>data/pipeline</code> builds it; see <Link href="/data/">Data</Link>.
      </Empty>
    );
  return (
    <Figure
      n={1}
      caption={
        <>
          The reference library in the <em>{space.name}</em> coordinate space, first two components.
          Each mark is a population mean ({space.populations.length} populations), coloured and shaped
          by region. Hover a mark for its name and sample count; the full interactive view is in the{" "}
          <Link href="/library/">library</Link>.
        </>
      }
    >
      <PcaPlot space={space} compact height={420} />
    </Figure>
  );
}

function ExampleList() {
  const ex = useResource((s) => api.examples(s), []);
  if (ex.loading) return <Loading what="examples" />;
  if (ex.error) return <ErrorNote error={ex.error} retry={ex.reload} />;
  if (!ex.data?.length)
    return (
      <Empty>
        No precomputed examples are published on this server yet. They are produced by{" "}
        <code>data/pipeline</code> from public reference data.
      </Empty>
    );
  return (
    <ol className="divide-y divide-rule-soft border-y border-rule">
      {ex.data.slice(0, 5).map((e, i) => (
        <li key={e.slug} className="grid grid-cols-[2rem_1fr] gap-2 py-3">
          <span className="num pt-0.5 text-small text-ink-3">{i + 1}.</span>
          <div>
            <Link href={`/examples/view/?slug=${encodeURIComponent(e.slug)}`} className="text-h3 leading-tight">
              {e.title}
            </Link>{" "}
            <KindMark kind={e.result_kind} />
            <p className="mt-1 text-small text-ink-2">
              {analysisLabel(e.kind)}. {e.summary}
            </p>
          </div>
        </li>
      ))}
    </ol>
  );
}

export default function Home() {
  const { session } = useSession();
  return (
    <article>
      <header className="mb-14 grid gap-10 lg:grid-cols-[minmax(0,1fr)_15rem] lg:gap-14">
        <div>
          <h1 className="text-[2.6rem] leading-[1.06] font-normal sm:text-display">
            Strata
            <span className="mt-2 block text-[1.6rem] leading-[1.2] text-ink-2 italic sm:text-[2.1rem]">
              a research instrument for population genetics
            </span>
          </h1>
          <div className="measure mt-10">
            <p className="smallcaps mb-2 text-ink-3">Abstract</p>
            <p className="text-[1.25rem] leading-[1.55]">
              Strata places a genome, or a set of Global25-style coordinates, among a curated library
              of ancient and present-day reference populations. It projects samples into a shared
              principal-component space, ranks nearby populations, fits exploratory mixture models
              with bootstrap intervals, and runs formal qpAdm tests on f-statistics through
              ADMIXTOOLS&nbsp;2. Every result states its method, its uncertainty and the reference
              data it rests on.
            </p>
          </div>
          <div className="mt-8 flex flex-wrap items-center gap-x-6 gap-y-3">
            <Link href="/upload/" className="btn no-underline">
              Upload a dataset
            </Link>
            <Link href="/examples/" className="text-small">
              Read the worked examples
            </Link>
          </div>
        </div>
        <aside className="self-end border-t border-ink pt-3 text-caption leading-[1.6] text-ink-2">
          <p>
            {session.status === "guest"
              ? "You are working as a guest. Uploads and analyses are kept for 24 hours, then deleted."
              : session.status === "signed-in"
                ? "You are signed in. Your workspace persists until you delete it."
                : session.status === "offline"
                  ? "The API is not reachable, so a guest workspace could not be opened."
                  : "Opening a guest workspace…"}
          </p>
          <p className="mt-2">
            Raw genotype files are parsed in memory. Only the SNPs on the reference panel are kept,
            encrypted, and they are never sent to a language model.
          </p>
        </aside>
      </header>

      <Section n={1} title="What it does" id="what">
        <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_15rem] lg:gap-14">
          <div className="min-w-0">
            <LibraryFigure />
          </div>
          <ol className="space-y-4 text-small leading-[1.55] text-ink-2 lg:pt-8">
            <li>
              <span className="text-ink">Project.</span> Place a sample in the reference PCA using
              only the SNPs it carries.
            </li>
            <li>
              <span className="text-ink">Compare.</span> Rank reference populations by distance in
              the same space.
            </li>
            <li>
              <span className="text-ink">Model.</span> Fit and rotate candidate sources, then test
              the surviving models formally with qpAdm.
            </li>
            <li>
              <span className="text-ink">Ask.</span> Pose questions to a research assistant that
              runs these analyses and cites what it ran.
            </li>
          </ol>
        </div>
      </Section>

      <Section n={2} title="Exploratory fits and formal tests" id="kinds">
        <p className="measure mb-6">
          Strata keeps two families of results apart, because they answer different questions. The
          distinction is marked on every result.
        </p>
        <div className="overflow-x-auto">
          <table className="booktabs max-w-[52rem]">
            <thead>
              <tr>
                <th className="w-[11rem]" />
                <th>
                  <KindMark kind="exploratory" />
                </th>
                <th>
                  <KindMark kind="formal" />
                </th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td className="italic">Method</td>
                <td>Non-negative least squares on PCA or G25 coordinates</td>
                <td>qpAdm on f4-statistics (ADMIXTOOLS&nbsp;2)</td>
              </tr>
              <tr>
                <td className="italic">Question</td>
                <td>Which mixture of sources lies closest to the target in this space?</td>
                <td>Is the target consistent with descending from these sources, given outgroups?</td>
              </tr>
              <tr>
                <td className="italic">Uncertainty</td>
                <td>Bootstrap over source individuals; sensitivity to dropped sources and dimensions</td>
                <td>Block-jackknife standard errors; tail probability of the rank test</td>
              </tr>
              <tr>
                <td className="italic">Reading</td>
                <td>A description of geometry. A good fit is not evidence of admixture.</td>
                <td>A model can be rejected. A model that is not rejected may still be wrong.</td>
              </tr>
            </tbody>
          </table>
        </div>
      </Section>

      <Section n={3} title="Worked examples" id="examples">
        <p className="measure mb-6">
          Each example is computed from public reference data with the same code you run here, and
          carries its inputs and provenance.
        </p>
        <ExampleList />
      </Section>

      <Section n={4} title="Where to begin" id="begin">
        <div className="measure space-y-3">
          <p>
            Browse the <Link href="/library/">reference library</Link> to see which populations and
            periods are covered. Then <Link href="/upload/">upload</Link> a raw file from 23andMe,
            AncestryDNA, FamilyTreeDNA or MyHeritage, a single-sample VCF, or paste G25 coordinates,
            and <Link href="/analyses/new/">compose an analysis</Link>.
          </p>
          <p>
            The <Link href="/methods/">methods</Link> describe each statistic and its assumptions.
          </p>
        </div>
      </Section>
    </article>
  );
}
