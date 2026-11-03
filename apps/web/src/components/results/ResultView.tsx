"use client";

import { api } from "@/lib/api";
import { fixed, int, pValue, pct, weightSe } from "@/lib/format";
import { f4Residuals, qpadmNotes, qpadmVerdict, rankQpAdmModels, sortedWeights, weightsDrawable, ALPHA_REJECT } from "@/lib/results";
import { useResource } from "@/lib/useResource";
import type {
  AdmixtureFitResult,
  AnalysisResult,
  F4StatResult,
  NearestResult,
  PcaProjectionResult,
  QpAdmResult,
  QpAdmRotateResult,
  QpWaveResult,
  RotationResult,
  Sensitivity,
} from "@/lib/types";
import { PanelLimits } from "@/components/results/PanelLimits";
import { PcaPlot } from "@/components/charts/PcaPlot";
import { ResidualsChart } from "@/components/charts/ResidualsChart";
import { WeightsChart } from "@/components/charts/WeightsChart";
import {
  Caveat,
  Empty,
  ErrorNote,
  Figure,
  Footnote,
  KindMark,
  Loading,
  TableFigure,
} from "@/components/typography";

/** p-value with a typeset exponent: 3.2 × 10<sup>−5</sup>; underflow (p = 0) as < 10<sup>−300</sup>. */
function PValue({ p }: { p: number | null | undefined }) {
  if (p === null || p === undefined || !Number.isFinite(p)) return <>{"\u2014"}</>;
  if (p === 0)
    return (
      <span title="Reported as 0: below double-precision range">
        &lt; 10<sup>{"\u2212"}300</sup>
      </span>
    );
  if (p >= 0.001) return <>{pValue(p)}</>;
  const [m, e] = p.toExponential(1).split("e");
  return (
    <>
      {m} &times; 10<sup>{String(Number(e)).replace("-", "\u2212")}</sup>
    </>
  );
}
const pv = (p: number | null | undefined) => <PValue p={p} />;

const EXPLORATORY_NOTE =
  "This is a geometric fit in a PCA/G25 coordinate space. It describes which combination of reference means lies closest to the target; it is not a test of admixture and does not establish ancestry. Use qpAdm for formal testing.";

export function ResultView({ result, compact = false }: { result: AnalysisResult; compact?: boolean }) {
  switch (result.type) {
    case "pca_project":
      return <PcaView r={result} compact={compact} />;
    case "nearest":
      return <NearestView r={result} />;
    case "admixture_fit":
      return <FitView r={result} compact={compact} />;
    case "admixture_rotate":
      return <RotationView r={result} />;
    case "qpadm":
      return <QpAdmView r={result} compact={compact} />;
    case "qpadm_rotate":
      return <QpAdmRotateView r={result} />;
    case "f4":
      return <F4View r={result} />;
    case "qpwave":
      return <QpWaveView r={result} />;
    default:
      return <Empty>This result type cannot be displayed.</Empty>;
  }
}

function ExploratoryCaveat({ text }: { text?: string }) {
  return (
    <Caveat title="Exploratory result">
      {text && text.length > 0 ? text : EXPLORATORY_NOTE}
    </Caveat>
  );
}

/* ----------------------------------------------------------- PCA projection */

function PcaView({ r, compact }: { r: PcaProjectionResult; compact: boolean }) {
  const spaces = useResource((s) => api.spaces(s), []);
  const space = spaces.data?.find((s) => s.id === r.space);
  return (
    <div>
      <p className="mb-2 text-small text-ink-2">
        <KindMark kind="exploratory" /> Projection into <em>{r.space}</em>
        {r.n_snps_used ? (
          <>
            {" "}
            using <span className="num">{int(r.n_snps_used)}</span> SNPs
          </>
        ) : null}
        .
      </p>
      {spaces.loading ? (
        <Loading what="the reference cloud" />
      ) : spaces.error ? (
        <ErrorNote error={spaces.error} retry={spaces.reload} />
      ) : space ? (
        <Figure
          n={1}
          caption={`Your sample (star) among reference populations. Low-coverage samples drift toward the centre.`}
        >
          <PcaPlot space={space} targets={r.targets} height={compact ? 380 : 540} />
        </Figure>
      ) : (
        <Empty>The reference space {r.space} is not available on this server, so only coordinates are shown.</Empty>
      )}
      <TableFigure n={1} caption="Projected coordinates on the first components.">
        <table className="booktabs max-w-[44rem]">
          <thead>
            <tr>
              <th>Sample</th>
              {Array.from({ length: Math.min(6, r.targets[0]?.coords.length ?? 0) }, (_, i) => (
                <th key={i} className="r">
                  PC{i + 1}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {r.targets.map((t) => (
              <tr key={t.name}>
                <td>{t.name}</td>
                {t.coords.slice(0, 6).map((c, i) => (
                  <td key={i} className="r num">
                    {fixed(c, 4)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </TableFigure>
      {r.note ? <Footnote mark="*">{r.note}</Footnote> : null}
      <ExploratoryCaveat text={r.caveat} />
    </div>
  );
}

/* ----------------------------------------------------------- nearest */

function NearestView({ r }: { r: NearestResult }) {
  return (
    <div>
      <TableFigure
        n={1}
        caption={
          <>
            Nearest to <em>{r.target}</em> ({r.metric} distance).
          </>
        }
        notes="Distances in different coordinate spaces are not comparable. Small differences between neighbours are not meaningful without an estimate of sampling error."
      >
        <table className="booktabs max-w-[40rem]">
          <thead>
            <tr>
              <th className="r w-12">Rank</th>
              <th>Population</th>
              <th>Region</th>
              <th className="r">Distance</th>
            </tr>
          </thead>
          <tbody>
            {r.hits.map((h, i) => (
              <tr key={h.population_id}>
                <td className="r num text-ink-3">{i + 1}</td>
                <td>{h.name}</td>
                <td>{h.region ?? "—"}</td>
                <td className="r num">{fixed(h.distance, 4)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableFigure>
      <ExploratoryCaveat text={r.caveat} />
    </div>
  );
}

/* ----------------------------------------------------------- admixture fit */

function SensitivityTables({ s, start }: { s: Sensitivity; start: number }) {
  return (
    <>
      {s.leave_one_source_out.length ? (
        <TableFigure
          n={start}
          caption="Drop one source. A big jump means it is needed."
        >
          <table className="booktabs max-w-[40rem]">
            <thead>
              <tr>
                <th>Source dropped</th>
                <th className="r">Distance</th>
                <th className="r">&Delta; distance</th>
              </tr>
            </thead>
            <tbody>
              {s.leave_one_source_out.map((row) => (
                <tr key={row.dropped}>
                  <td>{row.dropped}</td>
                  <td className="r num">{fixed(row.distance, 4)}</td>
                  <td className="r num">{fixed(row.delta_distance, 4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableFigure>
      ) : null}
      {s.leave_one_dimension_out.length ? (
        <TableFigure
          n={start + 1}
          caption="Drop one dimension. Big changes mean one component drives the fit."
        >
          <table className="booktabs max-w-[48rem]">
            <thead>
              <tr>
                <th>Dimension dropped</th>
                <th className="r">Distance</th>
                <th className="r">&Delta; distance</th>
                <th>Weights</th>
              </tr>
            </thead>
            <tbody>
              {s.leave_one_dimension_out.map((row) => (
                <tr key={row.dropped}>
                  <td>{row.dropped}</td>
                  <td className="r num">{fixed(row.distance, 4)}</td>
                  <td className="r num">{fixed(row.delta_distance, 4)}</td>
                  <td className="num text-ink-2">
                    {row.weights
                      ? Object.entries(row.weights)
                          .map(([k, v]) => `${k} ${pct(v)}`)
                          .join(", ")
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableFigure>
      ) : null}
    </>
  );
}

function FitView({ r, compact }: { r: AdmixtureFitResult; compact: boolean }) {
  const ws = sortedWeights(r);
  const hasCi = ws.some((w) => w.ci_low !== null && w.ci_low !== undefined);
  return (
    <div>
      <p className="mb-2 text-small text-ink-2">
        <KindMark kind="exploratory" /> Target <em>{r.target}</em> in {r.space}; {r.method} fit; residual
        distance <span className="num">{fixed(r.distance, 4)}</span>
        {r.n_bootstrap ? (
          <>
            ; <span className="num">{r.n_bootstrap}</span> bootstrap replicates
          </>
        ) : null}
        .
      </p>
      <Figure
        n={1}
        caption={
          hasCi
            ? `Mixture weights for ${r.target}, with 95% bootstrap intervals.`
            : `Mixture weights for ${r.target}.`
        }
      >
        <WeightsChart
          title={`Mixture weights for ${r.target}`}
          intervalLabel={hasCi ? "95% bootstrap interval" : "none"}
          rows={ws.map((w) => ({ label: w.source, weight: w.weight, lo: w.ci_low, hi: w.ci_high }))}
        />
      </Figure>
      <TableFigure n={1} caption="Estimated weights (percent).">
        <table className="booktabs max-w-[40rem]">
          <thead>
            <tr>
              <th>Source</th>
              <th className="r">Weight</th>
              <th className="r">SE</th>
              <th className="r">95% interval</th>
            </tr>
          </thead>
          <tbody>
            {ws.map((w) => (
              <tr key={w.source}>
                <td>{w.source}</td>
                <td className="r num">{pct(w.weight)}</td>
                <td className="r num">{w.se !== null ? pct(w.se) : "—"}</td>
                <td className="r num">
                  {w.ci_low !== null && w.ci_high !== null ? `${pct(w.ci_low)} to ${pct(w.ci_high)}` : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableFigure>
      {!compact && r.residuals.length ? (
        <Figure
          n={2}
          caption="Residuals per dimension. A lopsided one hints at a missing source."
        >
          <ResidualsChart
            title="Residuals by dimension"
            yLabel="Residual"
            points={r.residuals.map((v, i) => ({ label: `PC${i + 1}`, value: v }))}
          />
        </Figure>
      ) : null}
      {!compact && r.sensitivity ? <SensitivityTables s={r.sensitivity} start={2} /> : null}
      {r.quality || r.sensitivity?.stability_note || r.notes?.length ? (
        <ol className="mt-4 max-w-[44rem] list-[lower-alpha] space-y-1 pl-6 text-small text-ink-2">
          {r.quality ? (
            <li>
              Fit quality: <em>{r.quality.label}</em>. Residual distance{" "}
              <span className="num">{fixed(r.quality.distance, 4)}</span> against{" "}
              <span className="num">{fixed(r.quality.best_single_distance, 4)}</span> for the best single
              source ({r.quality.best_single_source}). {r.quality.caveat}
            </li>
          ) : null}
          {r.sensitivity?.stability_note ? (
            <li className={r.sensitivity.stable === false ? "text-alert" : ""}>{r.sensitivity.stability_note}</li>
          ) : null}
          {r.converged === false ? <li className="text-alert">The optimiser did not converge.</li> : null}
          {r.notes?.map((n, i) => (
            <li key={i}>{n}</li>
          ))}
        </ol>
      ) : null}
      <ExploratoryCaveat text={r.caveat} />
    </div>
  );
}

/* ----------------------------------------------------------- rotation */

function RotationView({ r }: { r: RotationResult }) {
  return (
    <div>
      <p className="mb-2 text-small text-ink-2">
        <KindMark kind="exploratory" /> Target <em>{r.target}</em>;{" "}
        <span className="num">{int(r.n_models_evaluated)}</span> source combinations evaluated.
      </p>
      <TableFigure
        n={1}
        caption="Models ranked by distance. Sources under 1% are pruned."
        notes={
          <>
            {r.preferred_rank ? (
              <>
                &dagger; Preferred model: the most parsimonious within the distance tolerance
                {r.tolerance !== undefined ? <> ({fixed(r.tolerance, 4)})</> : null} of the best.{" "}
              </>
            ) : null}
            Neighbouring models with similar distances are not distinguishable by this method. Carry the
            leading models into qpAdm for a formal test.
          </>
        }
      >
        <table className="booktabs">
          <thead>
            <tr>
              <th className="r w-12">Rank</th>
              <th>Sources and weights</th>
              <th className="r">Distance</th>
              <th>Pruned</th>
            </tr>
          </thead>
          <tbody>
            {r.models.map((m) => (
              <tr key={m.rank} className={m.rank === r.preferred_rank ? "font-medium" : ""}>
                <td className="r num text-ink-3">
                  {m.rank}
                  {m.rank === r.preferred_rank ? <sup>&dagger;</sup> : null}
                </td>
                <td>
                  {m.sources.map((s, i) => (
                    <span key={s} className="mr-3 inline-block whitespace-nowrap">
                      {s} <span className="num text-ink-2">{pct(m.weights[i] ?? 0)}</span>
                    </span>
                  ))}
                </td>
                <td className="r num">{fixed(m.distance, 4)}</td>
                <td className="text-ink-2">{m.pruned?.length ? m.pruned.join(", ") : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableFigure>
      <ExploratoryCaveat text={r.caveat} />
    </div>
  );
}

/* ----------------------------------------------------------- qpAdm */

function QpAdmView({ r, compact }: { r: QpAdmResult; compact: boolean }) {
  const notes = qpadmNotes(r);
  const verdict = qpadmVerdict(r);
  const drawable = weightsDrawable(r);
  return (
    <div>
      <PanelLimits kind="qpadm" />
      <p className="mb-4 text-small text-ink-2">
        <KindMark kind="formal" /> qpAdm, target <em>{r.target}</em>; {r.left.length} source
        {r.left.length === 1 ? "" : "s"} and {r.right.length} right populations
        {r.n_snps ? (
          <>
            ; <span className="num">{int(r.n_snps)}</span> SNPs
          </>
        ) : null}
        .
      </p>
      <dl className="panel mb-6 grid max-w-[44rem] grid-cols-2 overflow-hidden text-small sm:grid-cols-4">
        <div className="border-r border-b border-rule-soft px-4 py-3 sm:border-b-0">
          <dt className="text-caption text-ink-3">Tail probability</dt>
          <dd className="num mt-0.5 text-[1.7rem] leading-tight font-semibold">{pv(r.p_value)}</dd>
        </div>
        <div className="border-b border-rule-soft px-4 py-3 sm:border-r sm:border-b-0">
          <dt className="text-caption text-ink-3">
            &chi;<sup>2</sup>
          </dt>
          <dd className="num mt-0.5 text-[1.7rem] leading-tight font-semibold">{fixed(r.chisq, 2)}</dd>
        </div>
        <div className="border-r border-rule-soft px-4 py-3">
          <dt className="text-caption text-ink-3">Degrees of freedom</dt>
          <dd className="num mt-0.5 text-[1.7rem] leading-tight font-semibold">{r.dof}</dd>
        </div>
        <div
          className={`px-4 py-3 ${
            verdict === "rejected" || verdict === "infeasible" ? "bg-[#fbecea]" : verdict === "plausible" || verdict === "not rejected" ? "bg-malachite-soft" : "bg-wash"
          }`}
        >
          <dt className="text-caption text-ink-3">Verdict</dt>
          <dd
            className={`mt-0.5 text-[1.7rem] leading-tight font-semibold capitalize ${
              verdict === "rejected" || verdict === "infeasible" ? "text-alert" : verdict === "plausible" || verdict === "not rejected" ? "text-malachite" : ""
            }`}
          >
            {verdict}
          </dd>
        </div>
      </dl>

      {drawable ? (
      <Figure
          n={1}
          caption={`qpAdm weights for ${r.target}, ±1.96 SE.`}
        >
          <WeightsChart
            title={`qpAdm weights for ${r.target}`}
            intervalLabel="±1.96 SE"
            rows={r.weights.map((w) => ({
              label: w.source,
              weight: w.weight,
              lo: w.weight - 1.96 * w.se,
              hi: w.weight + 1.96 * w.se,
            }))}
          />
        </Figure>
      ) : (
        <p className="my-6 max-w-[44rem] text-small text-ink-2 italic">
          No chart: weights fall outside [0, 1]. See Table 1.
        </p>
      )}
      <TableFigure
        n={1}
        caption="Weights, block-jackknife SE."
      >
        <table className="booktabs max-w-[40rem]">
          <thead>
            <tr>
              <th>Source (left)</th>
              <th className="r">Weight &plusmn; SE</th>
              <th className="r">
                <em>z</em>
              </th>
            </tr>
          </thead>
          <tbody>
            {r.weights.map((w) => (
              <tr key={w.source}>
                <td>{w.source}</td>
                <td className="r num">{weightSe(w.weight, w.se)}</td>
                <td className="r num">{fixed(w.z, 2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableFigure>

      {r.rank_tests.length ? (
        <TableFigure
          n={2}
          caption="Rank tests (qpWave)."
        >
          <table className="booktabs max-w-[44rem]">
            <thead>
              <tr>
                <th className="r">Rank</th>
                <th className="r">dof</th>
                <th className="r">
                  &chi;<sup>2</sup>
                </th>
                <th className="r">
                  <em>p</em>
                </th>
                <th className="r">&Delta;dof</th>
                <th className="r">
                  &Delta;&chi;<sup>2</sup>
                </th>
                <th className="r">
                  <em>p</em> (nested)
                </th>
              </tr>
            </thead>
            <tbody>
              {r.rank_tests.map((t) => (
                <tr key={t.rank}>
                  <td className="r num">{t.rank}</td>
                  <td className="r num">{t.dof}</td>
                  <td className="r num">{fixed(t.chisq, 2)}</td>
                  <td className="r num whitespace-nowrap">{pv(t.p)}</td>
                  <td className="r num">{t.dofdiff ?? "—"}</td>
                  <td className="r num">{t.chisqdiff !== null && t.chisqdiff !== undefined ? fixed(t.chisqdiff, 2) : "—"}</td>
                  <td className="r num whitespace-nowrap">{pv(t.p_nested)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableFigure>
      ) : null}

      {!compact && f4Residuals(r).length ? (
        <Figure
          n={2}
          caption="Residual f4 z-scores. Beyond |z| = 3 in rose."
        >
          <ResidualsChart
            title="f4 residual z-scores"
            yLabel="Residual z"
            band={2}
            highlightAbove={3}
            points={f4Residuals(r).map((f) => ({ label: f.label, value: f.z }))}
          />
        </Figure>
      ) : null}

      <section aria-label="Interpretation" className="mt-8 max-w-[44rem]">
        <h3 className="mb-2 text-h3 italic">Interpretation</h3>
        <ol className="list-decimal space-y-2 pl-6 text-small leading-[1.55]">
          {notes.map((n, i) => (
            <li key={i} className={n.level === "reject" ? "text-alert" : ""}>
              {n.text}
            </li>
          ))}
          {r.notes?.map((n, i) => (
            <li key={`s${i}`} className="text-ink-2">
              {n}
            </li>
          ))}
        </ol>
      </section>

      <div className="mt-6 grid max-w-[44rem] gap-4 text-small sm:grid-cols-2">
        <div>
          <p className="text-caption text-ink-3">Left (sources)</p>
          <p>{r.left.join(", ")}</p>
        </div>
        <div>
          <p className="text-caption text-ink-3">Right (outgroups)</p>
          <p>{r.right.join(", ")}</p>
        </div>
      </div>
      {r.feasibility?.note ? <Caveat title="About the verdict">{r.feasibility.note}</Caveat> : null}
      {r.caveat ? <Caveat title="Formal result">{r.caveat}</Caveat> : null}
    </div>
  );
}

function verdictClass(v: string): string {
  return v === "rejected" || v === "infeasible" ? "text-alert" : "";
}

function QpAdmRotateView({ r }: { r: QpAdmRotateResult }) {
  const models = rankQpAdmModels(r);
  const engineRanked = models.every((m) => typeof m.rank === "number");
  const tested = r.n_models_tested ?? models.length;
  return (
    <div>
      <PanelLimits kind="qpadm_rotate" />
      <p className="mb-2 text-small text-ink-2">
        <KindMark kind="formal" /> qpAdm rotation for <em>{r.target}</em> against {r.right.length} fixed right
        populations; <span className="num">{tested}</span> model{tested === 1 ? "" : "s"} tested
        {r.n_models_enumerated !== undefined ? (
          <>
            {" "}
            of <span className="num">{r.n_models_enumerated}</span> enumerated
          </>
        ) : null}
        .
      </p>
      {r.rotation_caveat ? <Caveat title="Multiple testing">{r.rotation_caveat}</Caveat> : null}
      <TableFigure
        n={1}
        caption={
          engineRanked
            ? "Models as ranked by the engine."
            : "Feasible, non-rejected models first."
        }
      >
        <table className="booktabs">
          <thead>
            <tr>
              {engineRanked ? <th className="r w-12">Rank</th> : null}
              <th>Sources and weights</th>
              <th className="r">
                <em>p</em>
              </th>
              <th className="r">
                &chi;<sup>2</sup>
              </th>
              <th className="r">dof</th>
              <th>Verdict</th>
            </tr>
          </thead>
          <tbody>
            {models.map((m, i) => {
              const v = qpadmVerdict(m);
              return (
                <tr key={i}>
                  {engineRanked ? <td className="r num text-ink-3">{m.rank}</td> : null}
                  <td>
                    {m.weights.map((w) => (
                      <span key={w.source} className="mr-3 inline-block whitespace-nowrap">
                        {w.source} <span className="num text-ink-2">{weightSe(w.weight, w.se)}</span>
                      </span>
                    ))}
                    {m.feasibility?.reasons?.length ? (
                      <span className="mt-0.5 block text-caption text-ink-3">{m.feasibility.reasons.join(" ")}</span>
                    ) : null}
                  </td>
                  <td className="r num whitespace-nowrap">{pv(m.p_value)}</td>
                  <td className="r num">{fixed(m.chisq, 2)}</td>
                  <td className="r num">{m.dof}</td>
                  <td className={`italic ${verdictClass(v)}`}>{v}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </TableFigure>
      <p className="max-w-[44rem] text-caption text-ink-2">Fixed right populations: {r.right.join(", ")}.</p>
      {r.caveat ? <Caveat title="Formal result">{r.caveat}</Caveat> : null}
    </div>
  );
}

/* ----------------------------------------------------------- f4 / qpWave */

function F4View({ r }: { r: F4StatResult }) {
  const rows = r.f4.filter((f) => f.est !== null);
  return (
    <div>
      <p className="mb-2 text-small text-ink-2">
        <KindMark kind="formal" /> <span className="num">{rows.length}</span> f4-statistic{rows.length === 1 ? "" : "s"},
        f4(A, B; C, D), with block-jackknife standard errors.
      </p>
      {/* A figure only earns its place with enough statistics to compare; a few read better as a table. */}
      {rows.filter((f) => f.z !== null).length >= 6 ? (
        <Figure
          n={1}
          caption="z-scores. Dashed lines at |z| = 3."
        >
          <ResidualsChart
            title="f4 z-scores"
            yLabel="z"
            band={3}
            points={rows.filter((f) => f.z !== null).map((f) => ({ label: `${f.pop3}, ${f.pop4}`, value: f.z! }))}
          />
        </Figure>
      ) : null}
      <TableFigure n={1} caption="f4-statistics. Near zero means symmetric.">
        <table className="booktabs">
          <thead>
            <tr>
              <th>A</th>
              <th>B</th>
              <th>C</th>
              <th>D</th>
              <th className="r">Estimate</th>
              <th className="r">SE</th>
              <th className="r">
                <em>z</em>
              </th>
              <th className="r">
                <em>p</em>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((f, i) => (
              <tr key={i}>
                <td>{f.pop1}</td>
                <td>{f.pop2}</td>
                <td>{f.pop3}</td>
                <td>{f.pop4}</td>
                <td className="r num">{fixed(f.est, 5)}</td>
                <td className="r num">{fixed(f.se, 5)}</td>
                <td className="r num">{fixed(f.z, 2)}</td>
                <td className="r num whitespace-nowrap">{pv(f.p)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableFigure>
      {r.caveat ? <Caveat title="Formal result">{r.caveat}</Caveat> : null}
    </div>
  );
}

function QpWaveView({ r }: { r: QpWaveResult }) {
  const tests = [...r.rank_tests].sort((a, b) => a.rank - b.rank);
  return (
    <div>
      <p className="mb-2 text-small text-ink-2">
        <KindMark kind="formal" /> qpWave: {r.left.length} left and {r.right.length} right populations
        {r.alpha !== undefined ? (
          <>
            ; threshold <span className="num">{r.alpha}</span>
          </>
        ) : null}
        .
      </p>
      <p className="measure mb-4 text-small">
        {r.min_rank_not_rejected === null || r.min_rank_not_rejected === undefined
          ? "Every rank tested is rejected at this threshold: the left populations are not explained by fewer streams of ancestry than the full set, relative to these right populations."
          : `The lowest rank not rejected is ${r.min_rank_not_rejected}, i.e. at least ${r.min_rank_not_rejected + 1} streams of ancestry relate the left populations to the right set.`}
      </p>
      <TableFigure
        n={1}
        caption="Rank tests."
      >
        <table className="booktabs max-w-[44rem]">
          <thead>
            <tr>
              <th className="r">Rank</th>
              <th className="r">dof</th>
              <th className="r">
                &chi;<sup>2</sup>
              </th>
              <th className="r">
                <em>p</em>
              </th>
              <th className="r">
                <em>p</em> (nested)
              </th>
            </tr>
          </thead>
          <tbody>
            {tests.map((t) => (
              <tr key={t.rank}>
                <td className="r num">{t.rank}</td>
                <td className="r num">{t.dof}</td>
                <td className="r num">{fixed(t.chisq, 2)}</td>
                <td className="r num whitespace-nowrap">{pv(t.p)}</td>
                <td className="r num whitespace-nowrap">{pv(t.p_nested)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableFigure>
      <div className="mt-4 grid max-w-[44rem] gap-4 text-small sm:grid-cols-2">
        <div>
          <p className="text-caption text-ink-3">Left</p>
          <p>{r.left.join(", ")}</p>
        </div>
        <div>
          <p className="text-caption text-ink-3">Right</p>
          <p>{r.right.join(", ")}</p>
        </div>
      </div>
      {r.caveat ? <Caveat title="Formal result">{r.caveat}</Caveat> : null}
    </div>
  );
}

