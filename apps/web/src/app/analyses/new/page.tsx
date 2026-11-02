"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useId, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { buildAnalysisRequest, METHODS, type ComposerState, type MethodKey } from "@/lib/composer";
import { useResource } from "@/lib/useResource";
import { PopulationPicker, type Picked } from "@/components/PopulationPicker";
import { useSession } from "@/components/SessionProvider";
import { Empty, ErrorNote, KindMark, Loading, PageHeader, Section } from "@/components/typography";

function NumberField({
  label,
  value,
  onChange,
  min,
  max,
  hint,
}: {
  label: string;
  value: number;
  onChange: (n: number) => void;
  min?: number;
  max?: number;
  hint?: string;
}) {
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="label">
        {label}
      </label>
      <input
        id={id}
        className="field num"
        type="number"
        value={Number.isFinite(value) ? value : ""}
        min={min}
        max={max}
        onChange={(e) => onChange(Number(e.target.value))}
      />
      {hint ? <p className="mt-1 text-caption text-ink-3">{hint}</p> : null}
    </div>
  );
}

function Composer() {
  const router = useRouter();
  const sp = useSearchParams();
  const { health } = useSession();
  const datasets = useResource((s) => api.datasets(s), []);
  const spaces = useResource((s) => api.spaces(s), []);
  const qpadmOk = health?.capabilities.qpadm ?? false;

  const methodParam = sp.get("method");
  const [state, setState] = useState<ComposerState>({
    method: METHODS.some((m) => m.key === methodParam) ? (methodParam as MethodKey) : "admixture_fit",
    datasetId: sp.get("dataset") ?? "",
    sample: "",
    targetPopulation: [],
    space: "",
    k: 20,
    sources: [],
    bootstrap: 500,
    seed: 1,
    sensitivity: true,
    minSources: 1,
    maxSources: 3,
    maxModels: 200,
    left: [],
    right: [],
    allsnps: false,
    title: "",
  });
  const set = (patch: Partial<ComposerState>) => setState((s) => ({ ...s, ...patch }));

  // Preselect a source passed from a population page.
  const sourceParam = sp.get("source");
  useEffect(() => {
    if (!sourceParam) return;
    api
      .population(sourceParam)
      .then((p) => setState((s) => ({ ...s, sources: [{ id: p.id, name: p.name }], left: [{ id: p.id, name: p.name }] })))
      .catch(() => undefined);
  }, [sourceParam]);

  const ds = datasets.data?.find((d) => d.id === state.datasetId) ?? null;
  useEffect(() => {
    if (!state.datasetId && datasets.data?.length) set({ datasetId: datasets.data[0]!.id });
  }, [datasets.data, state.datasetId]);
  useEffect(() => {
    if (ds && !ds.sample_names.includes(state.sample)) set({ sample: ds.sample_names[0] ?? "" });
  }, [ds, state.sample]);
  // A dataset whose coordinates live in a known space (G25 rows) can only be analysed there,
  // so choosing it also chooses its space.
  useEffect(() => {
    if (ds?.space) set({ space: ds.space });
  }, [ds?.id, ds?.space]);
  useEffect(() => {
    if (!state.space && spaces.data?.length) set({ space: spaces.data[0]!.id });
  }, [spaces.data, state.space]);

  const method = METHODS.find((m) => m.key === state.method)!;
  const built = useMemo(() => buildAnalysisRequest(state, ds), [state, ds]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function submit() {
    if (!built.ok) return;
    setBusy(true);
    setError(null);
    try {
      const created = await api.createAnalysis(built.request);
      router.push(`/analysis/?id=${encodeURIComponent(created.analysis.id)}`);
    } catch (e) {
      setError(e);
      setBusy(false);
    }
  }

  const formalTarget = method.formal;

  return (
    <>
      <PageHeader
        kicker="Compose"
        title="New analysis"
        lede="Pick a method, a target and its sources."
      />

      <div className="grid gap-12 lg:grid-cols-[minmax(0,1fr)_19rem] lg:gap-12">
        <div className="min-w-0">
          <Section n={1} title="Method">
            <fieldset>
              <legend className="sr-only">Method</legend>
              {(["exploratory", "formal"] as const).map((kind) => (
                <div key={kind} className="mb-5">
                  <p className="mb-2">
                    <KindMark kind={kind} />
                  </p>
                  <div className="grid gap-2 sm:grid-cols-2">
                    {METHODS.filter((m) => m.formal === (kind === "formal")).map((m) => {
                      const disabled = m.formal && !qpadmOk;
                      const checked = state.method === m.key;
                      return (
                        <label
                          key={m.key}
                          className={`relative grid grid-cols-[1.1rem_1fr] gap-x-3 rounded-[var(--radius-panel)] border p-4 transition-colors ${
                            disabled
                              ? "cursor-not-allowed border-dashed border-rule bg-transparent opacity-60"
                              : checked
                                ? `cursor-pointer bg-panel ${m.formal ? "border-malachite" : "border-[#c08419]"} shadow-[0_0_0_1px_currentColor] ${m.formal ? "text-malachite" : "text-[#c08419]"}`
                                : "cursor-pointer border-rule bg-panel hover:border-ink-3"
                          }`}
                        >
                          <input
                            type="radio"
                            name="method"
                            value={m.key}
                            checked={checked}
                            disabled={disabled}
                            onChange={() => set({ method: m.key as MethodKey })}
                            className="mt-1 self-start"
                          />
                          <span className="text-ink">
                            <span className="block text-[1.2rem] leading-snug font-semibold">{m.label}</span>
                            <span className="mt-1 block text-small leading-[1.5] text-ink-2">{m.description}</span>
                            {disabled ? (
                              <span className="mt-1.5 block text-caption text-ink-3">
                                Not installed on this server.
                              </span>
                            ) : null}
                          </span>
                        </label>
                      );
                    })}
                  </div>
                </div>
              ))}
            </fieldset>
          </Section>

          <Section n={2} title="Target">
            {formalTarget ? (
              <div className="mb-6 max-w-[28rem]">
                <PopulationPicker
                  label="Target population from the library"
                  hint="Or use an uploaded sample below."
                  value={state.targetPopulation}
                  onChange={(v: Picked[]) => set({ targetPopulation: v })}
                  max={1}
                />
              </div>
            ) : null}
            {datasets.loading ? (
              <Loading what="your datasets" />
            ) : datasets.error ? (
              <ErrorNote error={datasets.error} retry={datasets.reload} />
            ) : !datasets.data?.length ? (
              <Empty>
                You have no datasets yet. <Link href="/upload/">Upload one</Link>
                {formalTarget ? ", or choose a library population as the target above" : ""}.
              </Empty>
            ) : (
              <div className="grid max-w-[40rem] gap-6 sm:grid-cols-2">
                <label>
                  <span className="label">Dataset</span>
                  <select className="field" value={state.datasetId} onChange={(e) => set({ datasetId: e.target.value, sample: "" })}>
                    {datasets.data.map((d) => (
                      <option key={d.id} value={d.id}>
                        {d.name} ({d.kind === "g25" ? "G25" : d.kind === "vcf" ? "VCF" : "raw"})
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  <span className="label">Sample</span>
                  <select className="field" value={state.sample} onChange={(e) => set({ sample: e.target.value })}>
                    {(ds?.sample_names ?? []).map((n) => (
                      <option key={n} value={n}>
                        {n}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            )}
          </Section>

          <Section n={3} title="Parameters">
            {spaces.error ? <ErrorNote error={spaces.error} /> : null}
            <div className="grid max-w-[44rem] gap-x-8 gap-y-6 sm:grid-cols-2">
              {!method.formal ? (
                <label className="sm:col-span-2 sm:max-w-[20rem]">
                  <span className="label">Coordinate space</span>
                  <select className="field" value={state.space} onChange={(e) => set({ space: e.target.value })}>
                    {(spaces.data ?? []).map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.name} ({s.n_dims} dimensions)
                      </option>
                    ))}
                    {ds?.space && !spaces.data?.some((s) => s.id === ds.space) ? (
                      <option value={ds.space}>{ds.space} (from the dataset)</option>
                    ) : null}
                    {!spaces.data?.length && !ds?.space ? <option value="">No coordinate space available</option> : null}
                  </select>
                </label>
              ) : null}

              {state.method === "nearest" ? (
                <NumberField label="Number of populations" value={state.k} min={1} max={200} onChange={(k) => set({ k })} />
              ) : null}

              {state.method === "admixture_fit" ? (
                <>
                  <div className="sm:col-span-2">
                    <PopulationPicker
                      label="Sources"
                      hint="2 to 8 sources."
                      value={state.sources}
                      onChange={(sources) => set({ sources })}
                      max={8}
                      space={state.space || undefined}
                    />
                  </div>
                  <NumberField
                    label="Bootstrap replicates"
                    value={state.bootstrap}
                    min={0}
                    max={5000}
                    hint="0 turns intervals off."
                    onChange={(bootstrap) => set({ bootstrap })}
                  />
                  <NumberField label="Random seed" value={state.seed} min={0} onChange={(seed) => set({ seed })} />
                  <label className="flex items-baseline gap-2 text-small sm:col-span-2">
                    <input
                      type="checkbox"
                      className=""
                      checked={state.sensitivity}
                      onChange={(e) => set({ sensitivity: e.target.checked })}
                    />
                    Leave-one-out checks
                  </label>
                </>
              ) : null}

              {state.method === "admixture_rotate" ? (
                <>
                  <div className="sm:col-span-2">
                    <PopulationPicker
                      label="Candidate sources"
                      hint="Every combination is fitted."
                      value={state.sources}
                      onChange={(sources) => set({ sources })}
                      max={24}
                      space={state.space || undefined}
                    />
                  </div>
                  <NumberField label="Fewest sources" value={state.minSources} min={1} max={6} onChange={(minSources) => set({ minSources })} />
                  <NumberField label="Most sources" value={state.maxSources} min={1} max={6} onChange={(maxSources) => set({ maxSources })} />
                  <NumberField label="Models to report" value={state.maxModels} min={1} max={2000} onChange={(maxModels) => set({ maxModels })} />
                  <NumberField label="Random seed" value={state.seed} min={0} onChange={(seed) => set({ seed })} />
                </>
              ) : null}

              {method.formal ? (
                <>
                  <div>
                    <PopulationPicker
                      label={state.method === "qpadm" ? "Left (sources)" : "Candidate left populations"}
                      value={state.left}
                      onChange={(left) => set({ left })}
                      max={state.method === "qpadm" ? 6 : 16}
                      exclude={[...state.right.map((r) => r.id), ...state.targetPopulation.map((t) => t.id)]}
                    />
                  </div>
                  <div>
                    <PopulationPicker
                      label="Right (outgroups)"
                      hint="Use more right than left."
                      value={state.right}
                      onChange={(right) => set({ right })}
                      max={30}
                      exclude={[...state.left.map((r) => r.id), ...state.targetPopulation.map((t) => t.id)]}
                    />
                  </div>
                  {state.method === "qpadm_rotate" ? (
                    <NumberField label="Most sources per model" value={state.maxSources} min={1} max={5} onChange={(maxSources) => set({ maxSources })} />
                  ) : null}
                  <label className="flex items-baseline gap-2 text-small sm:col-span-2">
                    <input type="checkbox" className="" checked={state.allsnps} onChange={(e) => set({ allsnps: e.target.checked })} />
                    Use all SNPs per f4-statistic (allsnps)
                  </label>
                </>
              ) : null}

              <label className="sm:col-span-2 sm:max-w-[28rem]">
                <span className="label">Title (optional)</span>
                <input className="field" value={state.title} maxLength={160} onChange={(e) => set({ title: e.target.value })} />
              </label>
            </div>
          </Section>

        </div>

        <aside className="lg:sticky lg:top-8 lg:self-start">
          <div className="panel p-5">
                        <p className="mt-1 flex flex-wrap items-center gap-2 text-[1.2rem] font-semibold">
              {method.label}{" "}
              <span key={method.key} className="pop inline-block">
                <KindMark kind={method.formal ? "formal" : "exploratory"} />
              </span>
            </p>
            <ul className="mt-4 space-y-1.5 text-small">
              {[
                ["Target", formalTarget && state.targetPopulation[0] ? state.targetPopulation[0].name : ds ? `${state.sample || "—"} (${ds.name})` : null],
                ...(method.formal
                  ? ([
                      ["Left", state.left.length ? `${state.left.length} chosen` : null],
                      ["Right", state.right.length ? `${state.right.length} chosen` : null],
                    ] as Array<[string, string | null]>)
                  : state.method === "admixture_fit" || state.method === "admixture_rotate"
                    ? ([["Sources", state.sources.length ? `${state.sources.length} chosen` : null]] as Array<[string, string | null]>)
                    : []),
              ].map(([k, v]) => (
                <li key={k as string} className="grid grid-cols-[1rem_4rem_1fr] items-baseline gap-x-2">
                  <span key={v ? "y" : "n"} className={`inline-block ${v ? "pop text-malachite" : "text-ink-3"}`} aria-hidden>
                    {v ? "\u2713" : "\u25CB"}
                  </span>
                  <span className="text-ink-3">{k}</span>
                  <span className={`truncate ${v ? "text-ink" : "text-ink-3"}`}>{v ?? "not chosen"}</span>
                </li>
              ))}
            </ul>
            {!built.ok ? (
              <ul className="mt-4 space-y-1 border-t border-rule-soft pt-3 text-caption leading-[1.5] text-ink-2">
                {built.problems.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
            ) : null}
            <button type="button" className="btn mt-5 w-full" disabled={!built.ok || busy} onClick={submit}>
              {busy ? "Submitting\u2026" : `Run ${method.label.toLowerCase()}`}
            </button>
            {error ? <ErrorNote error={error} /> : null}
          </div>
          <details className="group mt-4 px-1 text-caption leading-[1.6] text-ink-2">
            <summary className="cursor-pointer list-none font-semibold text-ink marker:hidden hover:text-malachite [&::-webkit-details-marker]:hidden">
              <span className="mr-1.5 inline-block text-[0.8em] text-ink-3 transition-transform group-open:rotate-90" aria-hidden>
                &#9656;
              </span>
              When to use this
            </summary>
            <p className="mt-2">{method.guidance}</p>
            <p className="mt-2">
              <Link href="/methods/">Methods</Link>
            </p>
          </details>
        </aside>
      </div>
    </>
  );
}

export default function ComposerPage() {
  return (
    <Suspense fallback={<Loading what="the composer" />}>
      <Composer />
    </Suspense>
  );
}
