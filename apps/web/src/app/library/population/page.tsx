"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { api } from "@/lib/api";
import { bp, bpRange, fixed, int } from "@/lib/format";
import { doiUrl } from "@/lib/citation";
import { useResource } from "@/lib/useResource";
import { OriginsMap } from "@/components/charts/OriginsMap";
import { Empty, ErrorNote, Figure, Loading, PageHeader, Section, TableFigure } from "@/components/typography";

function Population() {
  const id = useSearchParams().get("id");
  const pop = useResource(id ? (s) => api.population(id, s) : null, [id]);

  if (!id)
    return (
      <Empty>
        No population was specified. Choose one from the <Link href="/library/">library</Link>.
      </Empty>
    );
  if (pop.loading) return <Loading what="the population" />;
  if (pop.error) return <ErrorNote error={pop.error} retry={pop.reload} />;
  const p = pop.data;
  if (!p) return null;

  const located = p.samples.filter((s) => s.lat !== null && s.lon !== null);
  const mapPoints = located.length
    ? located.map((s) => ({
        id: s.id,
        lat: s.lat!,
        lon: s.lon!,
        label: s.name,
        detail: `${bp(s.date_mean_bp)}${s.sex ? `; ${s.sex}` : ""}`,
        emphasis: true,
      }))
    : p.lat !== null && p.lon !== null
      ? [{ id: p.id, lat: p.lat, lon: p.lon, label: p.name, emphasis: true }]
      : [];

  return (
    <article>
      <p className="mb-6 text-small">
        <Link href="/library/">Reference library</Link>
      </p>
      <PageHeader
        kicker={[p.region, p.country].filter(Boolean).join(", ") || "Reference population"}
        title={p.name}
        lede={p.description ?? undefined}
        aside={
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
            <dt className="text-ink-3">Date</dt>
            <dd className="num">{bpRange(p.date_min_bp, p.date_max_bp, p.date_mean_bp)}</dd>
            <dt className="text-ink-3">Period</dt>
            <dd>{p.period ?? "—"}</dd>
            <dt className="text-ink-3">Individuals</dt>
            <dd className="num">{p.n_samples}</dd>
            <dt className="text-ink-3">Source</dt>
            <dd>{p.source_dataset ?? "—"}</dd>
            {p.spaces?.length ? (
              <>
                <dt className="text-ink-3">Spaces</dt>
                <dd>{p.spaces.join(", ")}</dd>
              </>
            ) : null}
          </dl>
        }
      />

      <Section n={1} title="Location">
        {mapPoints.length ? (
          <Figure
            n={1}
            caption={
              located.length
                ? `Sampling sites of the ${located.length} individual${located.length === 1 ? "" : "s"} with recorded coordinates.`
                : "Representative location of the population; individual coordinates were not recorded."
            }
          >
            <OriginsMap points={mapPoints} title={`Map of sampling sites for ${p.name}`} height={340} />
          </Figure>
        ) : (
          <Empty>No coordinates are recorded for this population.</Empty>
        )}
        {p.lat !== null && p.lon !== null ? (
          <p className="num text-caption text-ink-3">
            Centroid {fixed(p.lat, 2)}&deg;, {fixed(p.lon, 2)}&deg;
          </p>
        ) : null}
      </Section>

      <Section n={2} title="Individuals">
        {p.samples.length === 0 ? (
          <Empty>Individual records are not available for this population.</Empty>
        ) : (
          <TableFigure
            n={1}
            caption={`Individuals assigned to ${p.name}. Dates are means of calibrated ranges where available.`}
            notes={
              p.samples.some((s) => s.qc_flags?.length)
                ? "QC flags are carried through from the source annotation; flagged individuals may be excluded from some analyses."
                : undefined
            }
          >
            <table className="booktabs">
              <thead>
                <tr>
                  <th>Individual</th>
                  <th className="r">Date</th>
                  <th>Sex</th>
                  <th className="r">Coverage</th>
                  <th className="r">SNPs</th>
                  <th>QC</th>
                </tr>
              </thead>
              <tbody>
                {p.samples.map((s) => (
                  <tr key={s.id}>
                    <td>{s.name}</td>
                    <td className="r num whitespace-nowrap">
                      {bp(s.date_mean_bp)}
                      {s.date_sd_bp ? <span className="text-ink-3"> &plusmn; {int(s.date_sd_bp)}</span> : null}
                    </td>
                    <td>{s.sex ?? "—"}</td>
                    <td className="r num">{s.coverage !== null && s.coverage !== undefined ? `${fixed(s.coverage, 2)}×` : "—"}</td>
                    <td className="r num">{int(s.n_snps)}</td>
                    <td className="text-ink-2">{s.qc_flags?.length ? s.qc_flags.join(", ") : "pass"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableFigure>
        )}
      </Section>

      <Section n={3} title="Publications">
        {p.publications.length === 0 ? (
          <Empty>No publication is linked to this population.</Empty>
        ) : (
          <ol className="measure list-decimal space-y-2 pl-6 text-small">
            {p.publications.map((pub) => {
              const href = doiUrl(pub.doi) ?? pub.url ?? null;
              return (
                <li key={pub.id}>
                  {pub.citation}
                  {href ? (
                    <>
                      {" "}
                      <a href={href} rel="noreferrer noopener" target="_blank">
                        {pub.doi ? `doi:${pub.doi.replace(/^https?:\/\/(dx\.)?doi\.org\//, "")}` : "link"}
                      </a>
                    </>
                  ) : null}
                </li>
              );
            })}
          </ol>
        )}
      </Section>

      <p className="text-small">
        <Link href={`/analyses/new/?source=${encodeURIComponent(p.id)}`}>
          Use {p.name} as a source in a new analysis
        </Link>
      </p>
    </article>
  );
}

export default function PopulationPage() {
  return (
    <Suspense fallback={<Loading what="the population" />}>
      <Population />
    </Suspense>
  );
}
