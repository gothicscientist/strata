"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { bpRange, int } from "@/lib/format";
import { useResource } from "@/lib/useResource";
import type { PopulationQuery, Publication } from "@/lib/types";
import { OriginsMap } from "@/components/charts/OriginsMap";
import { Empty, ErrorNote, Figure, Loading, PageHeader } from "@/components/typography";
import { shortCitation } from "@/lib/citation";

const PAGE_SIZE = 50;

function readQuery(sp: URLSearchParams): PopulationQuery {
  const num = (k: string) => {
    const v = sp.get(k);
    return v !== null && v !== "" && Number.isFinite(Number(v)) ? Number(v) : undefined;
  };
  return {
    q: sp.get("q") ?? undefined,
    region: sp.get("region") ?? undefined,
    period: sp.get("period") ?? undefined,
    source_dataset: sp.get("source") ?? undefined,
    min_bp: num("min_bp"),
    max_bp: num("max_bp"),
    page: num("page") ?? 1,
    page_size: PAGE_SIZE,
  };
}

function toSearch(q: PopulationQuery): string {
  const p = new URLSearchParams();
  if (q.q) p.set("q", q.q);
  if (q.region) p.set("region", q.region);
  if (q.period) p.set("period", q.period);
  if (q.source_dataset) p.set("source", q.source_dataset);
  if (q.min_bp !== undefined) p.set("min_bp", String(q.min_bp));
  if (q.max_bp !== undefined) p.set("max_bp", String(q.max_bp));
  if (q.page && q.page > 1) p.set("page", String(q.page));
  const s = p.toString();
  return s ? `?${s}` : "";
}

function Library() {
  const router = useRouter();
  const sp = useSearchParams();
  const query = useMemo(() => readQuery(new URLSearchParams(sp.toString())), [sp]);
  const [text, setText] = useState(query.q ?? "");
  const [minBp, setMinBp] = useState(query.min_bp?.toString() ?? "");
  const [maxBp, setMaxBp] = useState(query.max_bp?.toString() ?? "");

  const pops = useResource((s) => api.populations(query, s), [JSON.stringify(query)]);
  const pubs = useResource((s) => api.publications(s), []);
  const pubIndex = useMemo(() => {
    const m = new Map<string, Publication>();
    for (const p of pubs.data ?? []) m.set(p.id, p);
    return m;
  }, [pubs.data]);

  // Facets come from the API; until it reports them, offer the values visible on this page.
  const [facets, setFacets] = useState<{ region: string[]; period: string[]; source_dataset: string[] }>({
    region: [],
    period: [],
    source_dataset: [],
  });
  useEffect(() => {
    const d = pops.data;
    if (!d) return;
    if (d.facets) {
      setFacets(d.facets);
      return;
    }
    setFacets((f) => {
      const merge = (a: string[], b: Array<string | null>) =>
        [...new Set([...a, ...b.filter((x): x is string => !!x)])].sort();
      return {
        region: merge(f.region, d.items.map((i) => i.region)),
        period: merge(f.period, d.items.map((i) => i.period)),
        source_dataset: merge(f.source_dataset, d.items.map((i) => i.source_dataset)),
      };
    });
  }, [pops.data]);

  // Debounce free-text search and BP bounds into the URL.
  useEffect(() => {
    const t = setTimeout(() => {
      const next: PopulationQuery = {
        ...query,
        q: text || undefined,
        min_bp: minBp !== "" && Number.isFinite(Number(minBp)) ? Number(minBp) : undefined,
        max_bp: maxBp !== "" && Number.isFinite(Number(maxBp)) ? Number(maxBp) : undefined,
      };
      if (next.q !== query.q || next.min_bp !== query.min_bp || next.max_bp !== query.max_bp) {
        router.replace(`/library/${toSearch({ ...next, page: 1 })}`, { scroll: false });
      }
    }, 300);
    return () => clearTimeout(t);
  }, [text, minBp, maxBp, query, router]);

  const set = (patch: Partial<PopulationQuery>) =>
    router.replace(`/library/${toSearch({ ...query, ...patch, page: patch.page ?? 1 })}`, { scroll: false });

  const data = pops.data;
  const first = data ? (data.page - 1) * data.page_size + 1 : 0;
  const last = data ? Math.min(data.total, data.page * data.page_size) : 0;
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  const selects: Array<[string, keyof typeof facets, string | undefined, (v: string) => void]> = [
    ["Region", "region", query.region, (v) => set({ region: v || undefined })],
    ["Period", "period", query.period, (v) => set({ period: v || undefined })],
    ["Source dataset", "source_dataset", query.source_dataset, (v) => set({ source_dataset: v || undefined })],
  ];

  return (
    <>
      <PageHeader
        kicker="Reference library"
        title="Reference populations"
        lede="Ancient and present-day groups available as sources, outgroups and points of comparison. Dates are calibrated years before present (BP, present = 1950)."
        aside={
          data ? (
            <p className="num">
              {int(data.total)} population{data.total === 1 ? "" : "s"} match
              {data.total === 1 ? "es" : ""} the current filters.
            </p>
          ) : null
        }
      />

      <form
        role="search"
        aria-label="Filter reference populations"
        className="mb-10 grid grid-cols-2 gap-x-6 gap-y-5 md:grid-cols-4 lg:grid-cols-[2fr_1fr_1fr_1fr_0.7fr_0.7fr]"
        onSubmit={(e) => e.preventDefault()}
      >
        <label className="col-span-2 md:col-span-4 lg:col-span-1">
          <span className="label">Search names, sites and publications</span>
          <input
            className="field"
            type="search"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="e.g. Yamnaya, Anatolia_N, Botai"
          />
        </label>
        {selects.map(([label, key, value, onChange]) => (
          <label key={key}>
            <span className="label">{label}</span>
            <select className="field" value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
              <option value="">All</option>
              {facets[key].map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </select>
          </label>
        ))}
        <label>
          <span className="label">Older than (BP)</span>
          <input
            className="field num"
            inputMode="numeric"
            value={minBp}
            onChange={(e) => setMinBp(e.target.value.replace(/[^\d]/g, ""))}
            placeholder="0"
          />
        </label>
        <label>
          <span className="label">Younger than (BP)</span>
          <input
            className="field num"
            inputMode="numeric"
            value={maxBp}
            onChange={(e) => setMaxBp(e.target.value.replace(/[^\d]/g, ""))}
            placeholder="50 000"
          />
        </label>
      </form>

      {pops.loading && !data ? <Loading what="the reference library" /> : null}
      {pops.error ? (
        <ErrorNote error={pops.error} retry={pops.reload} />
      ) : data && data.total === 0 ? (
        <Empty>
          {query.q || query.region || query.period || query.source_dataset || query.min_bp || query.max_bp ? (
            <>No population matches these filters. Widen the date range or clear a filter.</>
          ) : (
            <>
              The reference library has not been built on this server yet. It is produced by the
              data pipeline from the Allen Ancient DNA Resource; see <Link href="/data/">Data</Link>{" "}
              and <code>data/pipeline/README.md</code>.
            </>
          )}
        </Empty>
      ) : data ? (
        <>
          <Figure
            n={1}
            caption={`Sampling locations of the ${last - first + 1} populations listed in Table 1. Marker area is proportional to the number of individuals. Select a marker to open the population.`}
          >
            <OriginsMap
              title="Map of population sampling locations"
              points={data.items
                .filter((p) => p.lat !== null && p.lon !== null)
                .map((p) => ({
                  id: p.id,
                  lat: p.lat!,
                  lon: p.lon!,
                  label: p.name,
                  detail: `${p.region ?? "Unassigned"}; ${bpRange(p.date_min_bp, p.date_max_bp, p.date_mean_bp)}; n = ${p.n_samples}`,
                  n: p.n_samples,
                }))}
              onSelect={(id) => router.push(`/library/population/?id=${encodeURIComponent(id)}`)}
            />
          </Figure>

          <figure className="my-8">
            <figcaption className="mb-2 text-caption text-ink-2">
              <span className="font-semibold text-ink">Table 1.</span> Reference populations{" "}
              <span className="num">
                {first}&ndash;{last}
              </span>{" "}
              of <span className="num">{int(data.total)}</span>. Dates give the range of sample
              dates within the group; <em>n</em> is the number of individuals.
            </figcaption>
            <div className="overflow-x-auto">
              <table className="booktabs">
                <thead>
                  <tr>
                    <th>Population</th>
                    <th>Region</th>
                    <th>Period</th>
                    <th className="r">Date</th>
                    <th className="r">
                      <em>n</em>
                    </th>
                    <th>Source</th>
                    <th>Publications</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((p) => (
                    <tr key={p.id} data-interactive="">
                      <td>
                        <Link href={`/library/population/?id=${encodeURIComponent(p.id)}`}>{p.name}</Link>
                      </td>
                      <td>{p.region ?? "—"}</td>
                      <td>{p.period ?? "—"}</td>
                      <td className="r num whitespace-nowrap">
                        {bpRange(p.date_min_bp, p.date_max_bp, p.date_mean_bp)}
                      </td>
                      <td className="r num">{p.n_samples}</td>
                      <td>{p.source_dataset ?? "—"}</td>
                      <td className="text-ink-2">
                        {p.publication_ids.length
                          ? p.publication_ids
                              .map((id) => {
                                const pub = pubIndex.get(id);
                                return pub ? shortCitation(pub) : id;
                              })
                              .join("; ")
                          : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </figure>

          {pages > 1 ? (
            <nav aria-label="Pages" className="flex items-baseline justify-between text-small">
              <button
                type="button"
                className="linkish disabled:no-underline disabled:opacity-40"
                disabled={data.page <= 1}
                onClick={() => set({ page: data.page - 1 })}
              >
                Previous page
              </button>
              <span className="num text-ink-3">
                Page {data.page} of {pages}
              </span>
              <button
                type="button"
                className="linkish disabled:no-underline disabled:opacity-40"
                disabled={data.page >= pages}
                onClick={() => set({ page: data.page + 1 })}
              >
                Next page
              </button>
            </nav>
          ) : null}
        </>
      ) : null}
    </>
  );
}

export default function LibraryPage() {
  return (
    <Suspense fallback={<Loading what="the reference library" />}>
      <Library />
    </Suspense>
  );
}
