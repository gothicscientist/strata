/**
 * Client-side pre-check of pasted Global25-style coordinates, mirroring strata.io.parse_g25.
 * It only gives immediate feedback; the server re-validates everything.
 */

export const G25_DIMS = 25;

export interface G25Row {
  name: string;
  coords: number[];
  line: number;
}

export interface G25Issue {
  line: number;
  message: string;
}

export interface G25Preview {
  rows: G25Row[];
  errors: G25Issue[];
  warnings: G25Issue[];
  hadHeader: boolean;
}

function splitLine(line: string): string[] {
  const sep = line.includes("\t") ? "\t" : ",";
  return line.split(sep).map((c) => c.trim());
}

export function parseG25(text: string): G25Preview {
  const rows: G25Row[] = [];
  const errors: G25Issue[] = [];
  const warnings: G25Issue[] = [];
  const seen = new Set<string>();
  let hadHeader = false;

  const lines = text.split(/\r\n|\n|\r/);
  lines.forEach((raw, i) => {
    const lineNo = i + 1;
    const line = raw.trim();
    if (!line || line.startsWith("#")) return;
    const cells = splitLine(line);
    const [name = "", ...rest] = cells;

    // A header row: first data-like line whose numeric cells are labels such as PC1.
    if (rows.length === 0 && !hadHeader && rest.length > 0 && rest.every((c) => !isNumeric(c))) {
      hadHeader = true;
      return;
    }
    if (!name) {
      errors.push({ line: lineNo, message: "missing sample name in the first column" });
      return;
    }
    if (rest.length !== G25_DIMS) {
      errors.push({
        line: lineNo,
        message: `expected ${G25_DIMS} coordinates after the name, found ${rest.length}`,
      });
      return;
    }
    const coords = rest.map(Number);
    const bad = coords.findIndex((v, j) => !isNumeric(rest[j] ?? "") || !Number.isFinite(v));
    if (bad !== -1) {
      errors.push({ line: lineNo, message: `PC${bad + 1} is not a finite number` });
      return;
    }
    if (seen.has(name)) {
      errors.push({ line: lineNo, message: `duplicate sample name “${name}”` });
      return;
    }
    seen.add(name);
    if (coords.some((v) => Math.abs(v) > 1)) {
      warnings.push({
        line: lineNo,
        message: "values outside ±1 suggest unscaled coordinates; G25 expects scaled values",
      });
    }
    rows.push({ name, coords, line: lineNo });
  });

  return { rows, errors, warnings, hadHeader };
}

function isNumeric(s: string): boolean {
  return /^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$/.test(s);
}
