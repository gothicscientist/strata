"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { ApiError, api, pollJob, TERMINAL } from "@/lib/api";
import { analysisLabel, dateTime } from "@/lib/format";
import { useResource } from "@/lib/useResource";
import type { Job } from "@/lib/types";
import { AnalysisDocument } from "@/components/results/AnalysisDocument";
import { Empty, ErrorNote, Loading, PageHeader } from "@/components/typography";

const STATUS_TEXT: Record<Job["status"], string> = {
  queued: "Queued. Waiting for a worker.",
  running: "Running.",
  succeeded: "Finished.",
  failed: "Failed.",
  cancelled: "Cancelled.",
};

/** Job failures: an unbuilt reference library is an expected state on a fresh server. */
function FailureNote({ message }: { message: string }) {
  const text = message.replace(/^\w+Error:\s*/, "");
  if (/reference library is not installed/i.test(text))
    return (
      <ErrorNote error={new ApiError(503, text, { detail: text, code: "reference_unavailable" })} />
    );
  return (
    <div role="alert" className="my-6 max-w-[44rem] border-l-2 border-alert py-1 pl-5 text-small">
      <p className="text-alert">The analysis failed.</p>
      <p className="mt-1 text-ink-2">{text}</p>
    </div>
  );
}

function AnalysisInner() {
  const id = useSearchParams().get("id");
  const analysis = useResource(id ? (s) => api.analysis(id, s) : null, [id]);
  const [job, setJob] = useState<Job | null>(null);
  const [pollError, setPollError] = useState<unknown>(null);

  const a = analysis.data;
  const pending = a && !TERMINAL.has(a.status);

  useEffect(() => {
    if (!a || !pending || !a.job_id) return;
    const ctrl = new AbortController();
    pollJob(a.job_id, { signal: ctrl.signal, onUpdate: setJob })
      .then(() => analysis.reload())
      .catch((e: unknown) => {
        if (!(e instanceof DOMException && e.name === "AbortError")) setPollError(e);
      });
    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [a?.id, pending, a?.job_id]);

  if (!id)
    return (
      <Empty>
        No analysis was specified. Open one from your <Link href="/workspace/">workspace</Link> or{" "}
        <Link href="/analyses/new/">compose a new analysis</Link>.
      </Empty>
    );
  if (analysis.loading && !a) return <Loading what="the analysis" />;
  if (analysis.error) return <ErrorNote error={analysis.error} retry={analysis.reload} />;
  if (!a) return null;

  if (pending) {
    const status = job?.status ?? a.status;
    return (
      <article>
        <PageHeader kicker={analysisLabel(a.kind)} title={a.title ?? analysisLabel(a.kind)} />
        <div role="status" aria-live="polite" className="measure">
          <p className="text-h3 italic">{STATUS_TEXT[status]}</p>
          <p className="mt-2 text-small text-ink-2">
            Submitted {dateTime(a.created_at)}
            {job?.started_at ? `; started ${dateTime(job.started_at)}` : ""}.
            {typeof job?.progress === "number" ? ` ${Math.round(job.progress * 100)}% complete.` : ""} This
            page updates by itself; you can leave it and return from your workspace.
          </p>
          <div className="mt-6 h-px w-full overflow-hidden bg-rule" aria-hidden>
            <div className="h-px w-1/4 animate-[strata-progress_1.8s_ease-in-out_infinite] bg-ink" />
          </div>
          {pollError ? <ErrorNote error={pollError} retry={analysis.reload} /> : null}
        </div>
      </article>
    );
  }

  if (a.status === "failed" || a.status === "cancelled") {
    return (
      <article>
        <PageHeader kicker={analysisLabel(a.kind)} title={a.title ?? analysisLabel(a.kind)} />
        <FailureNote message={a.error ?? job?.error ?? `The analysis was ${a.status}.`} />
        <p className="text-small">
          <Link href="/analyses/new/">Compose another analysis</Link>
        </p>
      </article>
    );
  }

  return <AnalysisDocument analysis={a} />;
}

export default function AnalysisPage() {
  return (
    <Suspense fallback={<Loading what="the analysis" />}>
      <AnalysisInner />
    </Suspense>
  );
}
