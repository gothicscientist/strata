"use client";

import { api } from "@/lib/api";
import { fixed, int, pValue, pct, weightSe } from "@/lib/format";
import { f4Residuals, qpadmNotes, rankQpAdmModels, sortedWeights, ALPHA_REJECT } from "@/lib/results";
import { useResource } from "@/lib/useResource";
import type {
  AdmixtureFitResult,
  AnalysisResult,
  NearestResult,
  PcaProjectionResult,
  QpAdmResult,
  QpAdmRotateResult,
  RotationResult,
  Sensitivity,
} from "@/lib/types";
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
          caption={`Projected target${r.targets.length === 1 ? "" : "s"} (black star) against reference population means in ${space.name}, coloured and shaped by region. Projection uses only the SNPs present in the sample (least-squares, as smartpca lsqproject); low-coverage samples shrink towards the origin.`}
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
            Reference populations nearest to <em>{r.target}</em> in {r.space}, by {r.metric} distance
            between the target and population means.
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
          caption="Leave-one-source-out sensitivity. Each row refits the model without one source; a large increase in distance means that source is needed."
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
          caption="Leave-one-dimension-out sensitivity. Rows with large changes indicate a fit driven by a single component."
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
            ? `Mixture weights for ${r.target}. (a) Point estimates. (b) Estimates with 95% bootstrap intervals (2.5th to 97.5th percentile, resampling individuals within each source).`
            : `Mixture weights for ${r.target}. No bootstrap was run, so no interval is shown.`
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
          caption="Per-dimension residuals of the fitted mixture (fit minus target). Systematic residuals on one component point to ancestry not represented among the sources."
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
        caption="Source rotation, ranked by residual distance. Sources with weight below 1% are pruned and the model refitted."
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
  const rejected = r.p_value < ALPHA_REJECT;
  return (
    <div>
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
      <dl className="mb-6 grid max-w-[40rem] grid-cols-2 gap-y-1 border-y border-ink py-3 text-small sm:grid-cols-4">
        <div>
          <dt className="text-caption text-ink-3">Tail probability</dt>
          <dd className="num text-h3">{pValue(r.p_value)}</dd>
        </div>
        <div>
          <dt className="text-caption text-ink-3">
            &chi;<sup>2</sup>
          </dt>
          <dd className="num text-h3">{fixed(r.chisq, 2)}</dd>
        </div>
        <div>
          <dt className="text-caption text-ink-3">Degrees of freedom</dt>
          <dd className="num text-h3">{r.dof}</dd>
        </div>
        <div>
          <dt className="text-caption text-ink-3">Verdict</dt>
          <dd className="text-h3 italic">
            {rejected ? "rejected" : r.feasible ? "not rejected" : "infeasible"}
          </dd>
        </div>
      </dl>

      <Figure
        n={1}
        caption={`qpAdm mixture weights for ${r.target} with ±1.96 block-jackknife standard errors. Weights are unconstrained and may fall outside [0, 1].`}
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

      <TableFigure n={1} caption="Estimated weights. SE from the block jackknife; z = weight / SE.">
        <table className="booktabs max-w-[40rem]">
          <thead>
            <tr>
              <th>Source (left)</th>
              <th className="r">Weight &plusmn; SE (%)</th>
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
          caption="Rank tests (qpWave). Each row tests whether the f4 matrix between left and right populations has at most the given rank; the full model corresponds to rank = number of sources − 1."
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
                  <td className="r num">{pValue(t.p)}</td>
                  <td className="r num">{t.dofdiff ?? "—"}</td>
                  <td className="r num">{t.chisqdiff !== null && t.chisqdiff !== undefined ? fixed(t.chisqdiff, 2) : "—"}</td>
                  <td className="r num">{pValue(t.p_nested)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableFigure>
      ) : null}

      {!compact && f4Residuals(r).length ? (
        <Figure
          n={2}
          caption="Residual f4-statistics, f4(target, left; right₁, right₂) observed minus fitted, as z-scores. Dashed lines mark |z| = 2; residuals beyond |z| = 3 are drawn in rose."
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
      {r.caveat ? <Footnote mark="†">{r.caveat}</Footnote> : null}
      <Footnote mark="*">
        A non-rejected model is consistent with the data given this right set; it is not unique.
        Results depend on the choice of right populations and on the f2 blocks used.
      </Footnote>
    </div>
  );
}

function QpAdmRotateView({ r }: { r: QpAdmRotateResult }) {
  const models = rankQpAdmModels(r);
  return (
    <div>
      <p className="mb-2 text-small text-ink-2">
        <KindMark kind="formal" /> qpAdm rotation for <em>{r.target}</em> against {r.right.length} right
        populations; {models.length} models.
      </p>
      <TableFigure
        n={1}
        caption="qpAdm models ordered with feasible, non-rejected models first, then by tail probability."
        notes={`Rejection threshold p < ${ALPHA_REJECT}. Weights are percent ± SE.`}
      >
        <table className="booktabs">
          <thead>
            <tr>
              <th>Sources and weights</th>
              <th className="r">
                <em>p</em>
              </th>
              <th className="r">
                &chi;<sup>2</sup>
              </th>
              <th className="r">dof</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {models.map((m, i) => (
              <tr key={i}>
                <td>
                  {m.weights.map((w) => (
                    <span key={w.source} className="mr-3 inline-block whitespace-nowrap">
                      {w.source} <span className="num text-ink-2">{weightSe(w.weight, w.se)}</span>
                    </span>
                  ))}
                </td>
                <td className="r num">{pValue(m.p_value)}</td>
                <td className="r num">{fixed(m.chisq, 2)}</td>
                <td className="r num">{m.dof}</td>
                <td className={m.p_value < ALPHA_REJECT || !m.feasible ? "text-alert" : ""}>
                  {!m.feasible ? "infeasible" : m.p_value < ALPHA_REJECT ? "rejected" : "not rejected"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableFigure>
      <p className="max-w-[44rem] text-caption text-ink-2">
        Right populations: {r.right.join(", ")}.
        {r.n_models_tested !== undefined ? ` ${r.n_models_tested} of ${r.n_models_enumerated ?? r.n_models_tested} enumerated models tested.` : ""}
      </p>
      {r.rotation_caveat ? <Footnote mark="*">{r.rotation_caveat}</Footnote> : null}
      {r.caveat ? <Footnote mark="†">{r.caveat}</Footnote> : null}
    </div>
  );
}

