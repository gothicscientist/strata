"use client";

import { api } from "@/lib/api";
import { useResource } from "@/lib/useResource";
import { Caveat } from "@/components/typography";

/**
 * What the installed reference panel cannot answer, shown above a formal result.
 *
 * A limit is not visible in the numbers: an under-identified weight looks like
 * any other weight, and a model rejected for want of an informative outgroup
 * looks like a model the data rejected. So it is stated next to the result
 * rather than left in the documentation.
 *
 * It renders nothing when the panel reports no limit, when none applies to this
 * analysis, or when the request fails — a caveat that cannot be loaded must not
 * become an empty box implying there is none, and must not hide the result.
 */
export function PanelLimits({ kind }: { kind: string }) {
  const panel = useResource((signal) => api.panel(signal), []);
  const limits = (panel.data?.limits ?? []).filter(
    (limit) => !limit.affects || limit.affects.includes(kind),
  );
  if (limits.length === 0) return null;
  return (
    <>
      {limits.map((limit) => (
        <Caveat key={limit.id} title="This panel cannot answer this fully">
          {limit.summary}
        </Caveat>
      ))}
    </>
  );
}
