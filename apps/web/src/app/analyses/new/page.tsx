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

  const [state, setState] = useState<ComposerState>({
    method: "admixture_fit",
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
    // Exploratory methods need a dataset whose coordinates live in a known space.
    if (ds?.space && !state.space) set({ space: ds.space });
  }, [ds, state.sample, state.space]);
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
        lede="Choose a target, a method and its parameters. Exploratory methods work in a PCA or G25 space; qpAdm tests a model formally on f-statistics."
      />

      <div className="grid gap-12 lg:grid-cols-[minmax(0,1fr)_17rem] lg:gap-14">
        <div className="min-w-0">
          <Section n={1} title="Method">
            <fieldset>
              <legend className="sr-only">Method</legend>
              <div className="border-t border-ink">
                {METHODS.map((m) => {
                  const disabled = m.formal && !qpadmOk;
                  return (
                    <label
                      key={m.key}
                      className={`grid cursor-pointer grid-cols-[1.5rem_1fr] gap-2 border-b border-rule py-3 ${
                        disabled ? "cursor-not-allowed opacity-50" : ""
                      }`}
                    >
                      <input
                        type="radio"
                        name="method"
                        value={m.key}
                        checked={state.method === m.key}
                        disabled={disabled}
                        onChange={() => set({ method: m.key as MethodKey })}
                        className="mt-1.5 accent-black"
                      />
                      <span>
                        <span className="text-h3">{m.label}</span> <KindMark kind={m.formal ? "formal" : "exploratory"} />
                        <span className="mt-0.5 block text-small text-ink-2">{m.description}</span>
                        {disabled ? (
                          <span className="mt-0.5 block text-caption text-ink-3 italic">
                            ADMIXTOOLS&nbsp;2 is not installed on this server; see the worker documentation.
                          </span>
                        ) : null}
                      </span>
                    </label>
                  );
                })}
              </div>
            </fieldset>
          </Section>

          <Section n={2} title="Target">
            {formalTarget ? (
              <div className="mb-6 max-w-[28rem]">
                <PopulationPicker
                  label="Target population from the library"
                  hint="Or leave empty and choose a sample from an uploaded raw-genotype dataset below."
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
                    {!spaces.data?.length ? <option value="">No coordinate space available</option> : null}
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
                      hint="Two to eight candidate source populations."
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
                    hint="Resamples individuals within each source; 0 disables intervals."
                    onChange={(bootstrap) => set({ bootstrap })}
                  />
                  <NumberField label="Random seed" value={state.seed} min={0} onChange={(seed) => set({ seed })} />
                  <label className="flex items-baseline gap-2 text-small sm:col-span-2">
                    <input
                      type="checkbox"
                      className="accent-black"
                      checked={state.sensitivity}
                      onChange={(e) => set({ sensitivity: e.target.checked })}
                    />
                    Run leave-one-out sensitivity diagnostics
                  </label>
                </>
              ) : null}

              {state.method === "admixture_rotate" ? (
                <>
                  <div className="sm:col-span-2">
                    <PopulationPicker
                      label="Candidate sources"
                      hint="Every combination within the size range is fitted and ranked."
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
                      hint="Populations differentially related to the sources. Use more right than left populations."
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
                    <input type="checkbox" className="accent-black" checked={state.allsnps} onChange={(e) => set({ allsnps: e.target.checked })} />
                    Use all SNPs per f4-statistic (allsnps), rather than only SNPs present in every population
                  </label>
                </>
              ) : null}

              <label className="sm:col-span-2 sm:max-w-[28rem]">
                <span className="label">Title (optional)</span>
                <input className="field" value={state.title} maxLength={160} onChange={(e) => set({ title: e.target.value })} />
              </label>
            </div>
          </Section>

          <div className="border-t border-ink pt-6">
            {!built.ok ? (
              <ul className="mb-4 list-disc space-y-0.5 pl-5 text-small text-ink-2">
                {built.problems.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
            ) : null}
            <button type="button" className="btn" disabled={!built.ok || busy} onClick={submit}>
              {busy ? "Submitting…" : `Run ${method.label.toLowerCase()}`}
            </button>
            {error ? <ErrorNote error={error} /> : null}
          </div>
        </div>

        <aside className="text-caption leading-[1.6] text-ink-2 lg:pt-14">
          <p className="mb-2 italic text-ink">On choosing a method</p>
          <p>{method.guidance}</p>
          <p className="mt-3">
            See <Link href="/methods/">Methods</Link> for the statistics and their assumptions.
          </p>
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
