import "server-only";
import fs from "node:fs";
import path from "node:path";

/** Repository root, resolved from apps/web at build time. */
export const REPO_ROOT = path.resolve(process.cwd(), "..", "..");

export interface Doc {
  slug: string;
  title: string;
  body: string;
  file: string;
}

const METHOD_ORDER = [
  "pca",
  "g25-coordinates",
  "uncertainty",
  "f-statistics",
  "qpadm",
  "admixtools2",
  "consumer-data",
];

function readDoc(file: string): Doc {
  const raw = fs.readFileSync(file, "utf8");
  const m = raw.match(/^#\s+(.+)$/m);
  const title = m?.[1]?.trim() ?? path.basename(file, ".md");
  const body = m ? raw.replace(m[0], "").trim() : raw;
  return { slug: path.basename(file, ".md"), title, body, file: path.relative(REPO_ROOT, file) };
}

/** Markdown files in a repository directory, read at build time (static export). */
export function readDocs(dir: string, order: string[] = []): Doc[] {
  const abs = path.join(REPO_ROOT, dir);
  if (!fs.existsSync(abs)) return [];
  const docs = fs
    .readdirSync(abs)
    .filter((f) => f.endsWith(".md") && !f.startsWith("_") && f.toLowerCase() !== "readme.md")
    .map((f) => readDoc(path.join(abs, f)));
  const rank = (s: string) => {
    const i = order.indexOf(s);
    return i === -1 ? order.length : i;
  };
  return docs.sort((a, b) => rank(a.slug) - rank(b.slug) || a.title.localeCompare(b.title));
}

export function methodDocs(): Doc[] {
  return readDocs("docs/methods", METHOD_ORDER);
}

export function readOptional(rel: string): Doc | null {
  const abs = path.join(REPO_ROOT, rel);
  return fs.existsSync(abs) ? readDoc(abs) : null;
}

export function readJson<T>(rel: string): T | null {
  const abs = path.join(REPO_ROOT, rel);
  if (!fs.existsSync(abs)) return null;
  try {
    return JSON.parse(fs.readFileSync(abs, "utf8")) as T;
  } catch {
    return null;
  }
}
