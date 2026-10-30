import type { Publication } from "./types";

/** "Haak, W., Lazaridis, I. ... (2015) Massive migration ..." -> "Haak et al. 2015". */
export function shortCitation(pub: Pick<Publication, "citation" | "year" | "id">): string {
  const c = (pub.citation ?? "").trim();
  if (!c) return pub.year ? `${pub.id} ${pub.year}` : pub.id;
  const surname = c.split(/[,\s(]/).find((t) => t.length > 1) ?? c;
  const authorsPart = c.split(/\(\d{4}\)|\.\s/)[0] ?? "";
  const many = /et al|,.*,|&| and /i.test(authorsPart);
  const m = c.match(/\b(19|20)\d{2}\b/);
  const year = pub.year ?? (m ? Number(m[0]) : null);
  return `${surname}${many ? " et al." : ""}${year ? ` ${year}` : ""}`;
}

export function doiUrl(doi: string | null | undefined): string | null {
  if (!doi) return null;
  const d = doi.replace(/^https?:\/\/(dx\.)?doi\.org\//i, "").trim();
  return d ? `https://doi.org/${d}` : null;
}
