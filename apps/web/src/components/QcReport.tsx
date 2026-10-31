import { fixed, int, pct } from "@/lib/format";
import type { Dataset } from "@/lib/types";
import { TableFigure } from "./typography";

const KNOWN: Array<[keyof Dataset["qc"], string, (v: unknown) => string]> = [
  ["vendor", "Format detected", (v) => String(v)],
  ["build", "Genome build", (v) => String(v)],
  ["n_samples", "Samples", (v) => int(v as number)],
  ["n_variants", "Variants read", (v) => int(v as number)],
  ["n_called", "Called genotypes", (v) => int(v as number)],
  ["call_rate", "Call rate", (v) => pct(v as number, 2)],
  ["n_no_calls", "No-calls", (v) => int(v as number)],
  ["n_indels_dropped", "Indels dropped", (v) => int(v as number)],
  ["het_rate", "Heterozygosity", (v) => fixed(v as number, 4)],
  ["panel_overlap", "SNPs on reference panel", (v) => int(v as number)],
  ["panel_size", "Reference panel size", (v) => int(v as number)],
];

/** QC report as a two-column table, then warnings as numbered notes. */
export function QcReport({ dataset, n = 1 }: { dataset: Dataset; n?: number | string }) {
  const qc = dataset.qc;
  const rows: Array<[string, string]> = [];
  for (const [key, label, fmt] of KNOWN) {
    const v = qc[key];
    if (v === null || v === undefined || v === "") continue;
    rows.push([label, fmt(v)]);
  }
  if (qc.panel_overlap && qc.panel_size) {
    rows.push(["Panel coverage", pct(qc.panel_overlap / qc.panel_size, 1)]);
  }
  if (qc.sex_chrom_counts) {
    rows.push([
      "Sex-chromosome calls",
      Object.entries(qc.sex_chrom_counts)
        .map(([k, v]) => `${k} ${int(v)}`)
        .join(", "),
    ]);
  }
  const known = new Set<string>([...KNOWN.map((k) => k[0] as string), "sex_chrom_counts", "warnings"]);
  for (const [k, v] of Object.entries(qc)) {
    if (known.has(k) || v === null || v === undefined || typeof v === "object") continue;
    rows.push([k.replace(/_/g, " "), typeof v === "number" ? (Number.isInteger(v) ? int(v) : fixed(v, 4)) : String(v)]);
  }

  return (
    <TableFigure
      n={n}
      caption={
        <>
          Quality control for <em>{dataset.name}</em> ({dataset.kind === "g25" ? "G25 coordinates" : dataset.kind === "vcf" ? "VCF" : "raw genotypes"}).
        </>
      }
      notes={
        qc.warnings.length ? (
          <ol className="list-[lower-alpha] space-y-1 pl-5">
            {qc.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ol>
        ) : (
          "No QC warnings."
        )
      }
    >
      <table className="booktabs max-w-[34rem]">
        <thead>
          <tr>
            <th>Measure</th>
            <th className="r">Value</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([k, v]) => (
            <tr key={k}>
              <td>{k}</td>
              <td className="r num">{v}</td>
            </tr>
          ))}
          {dataset.sample_names.length ? (
            <tr>
              <td>Sample names</td>
              <td className="r">{dataset.sample_names.slice(0, 8).join(", ")}{dataset.sample_names.length > 8 ? ` and ${dataset.sample_names.length - 8} more` : ""}</td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </TableFigure>
  );
}
