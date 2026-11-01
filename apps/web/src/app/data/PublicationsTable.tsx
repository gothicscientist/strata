"use client";

import { api } from "@/lib/api";
import { doiUrl } from "@/lib/citation";
import { useResource } from "@/lib/useResource";
import { Empty, ErrorNote, Loading, TableFigure } from "@/components/typography";

export function PublicationsTable() {
  const pubs = useResource((s) => api.publications(s), []);
  if (pubs.loading) return <Loading what="publications" />;
  if (pubs.error) return <ErrorNote error={pubs.error} retry={pubs.reload} />;
  if (!pubs.data?.length)
    return <Empty>The reference library has not been built on this server, so no publications are listed.</Empty>;
  const sorted = [...pubs.data].sort((a, b) => (a.year ?? 0) - (b.year ?? 0) || a.citation.localeCompare(b.citation));
  return (
    <TableFigure n={2} caption={`Source publications (${sorted.length}), by year.`}>
      <table className="booktabs">
        <thead>
          <tr>
            <th className="r w-16">Year</th>
            <th>Citation</th>
            <th>DOI</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((p) => {
            const href = doiUrl(p.doi) ?? p.url ?? null;
            return (
              <tr key={p.id}>
                <td className="r num">{p.year ?? "—"}</td>
                <td>{p.citation}</td>
                <td className="whitespace-nowrap">
                  {href ? (
                    <a href={href} target="_blank" rel="noreferrer noopener">
                      {p.doi ?? "link"}
                    </a>
                  ) : (
                    "—"
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </TableFigure>
  );
}
