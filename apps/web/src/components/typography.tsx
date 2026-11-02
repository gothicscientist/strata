import type { ReactNode } from "react";
import { ApiError } from "@/lib/api";

export function PageHeader({
  kicker,
  title,
  lede,
  aside,
}: {
  /** Kept for callers; the rail already says where you are, so it is not drawn. */
  kicker?: string;
  title: ReactNode;
  lede?: ReactNode;
  aside?: ReactNode;
}) {
  void kicker;
  return (
    <header className="mb-12">
      <div className="grid gap-6 pb-7 lg:grid-cols-[minmax(0,1fr)_16rem] lg:items-end lg:gap-14">
        <div>
          <h1 className="text-[2.15rem] leading-[1.04] font-medium tracking-[-0.01em] sm:text-h1">
            {title}
          </h1>
          {lede ? (
            <div className="serif measure mt-4 text-[1.35rem] leading-[1.5] text-ink-2">{lede}</div>
          ) : null}
        </div>
        {aside ? <div className="text-small leading-[1.5] text-ink-2 lg:pb-1">{aside}</div> : null}
      </div>
      <div className="stratum-rule stratum-draw" aria-hidden />
    </header>
  );
}

/** A section of a page. Numbers are for real sequences (steps of a form, parts of a report). */
export function Section({
  n,
  title,
  id,
  children,
  aside,
}: {
  n?: number | string;
  title: ReactNode;
  id?: string;
  children: ReactNode;
  aside?: ReactNode;
}) {
  return (
    <section id={id} className="mb-16 scroll-mt-20" aria-labelledby={id ? `${id}-h` : undefined}>
      <h2 id={id ? `${id}-h` : undefined} className="mb-5 flex items-center gap-3 text-h2">
        {n !== undefined ? (
          <span
            className="num inline-flex size-7 shrink-0 items-center justify-center rounded-full border border-ink text-[0.9rem] font-semibold"
            aria-hidden
          >
            {n}
          </span>
        ) : null}
        <span>{title}</span>
      </h2>
      {aside ? (
        <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_16rem] lg:gap-14">
          <div className="min-w-0">{children}</div>
          <aside className="text-caption leading-relaxed text-ink-2">{aside}</aside>
        </div>
      ) : (
        children
      )}
    </section>
  );
}

export function Figure({
  n,
  caption,
  children,
  label = "Figure",
}: {
  n: number | string;
  caption: ReactNode;
  children: ReactNode;
  label?: string;
}) {
  return (
    <figure className="my-8">
      <div className="panel overflow-hidden p-3 sm:p-5">{children}</div>
      <figcaption className="mt-3 max-w-[46rem] text-caption leading-[1.55] text-ink-2">
        <span className="font-semibold text-ink">
          {label} {n}.
        </span>{" "}
        {caption}
      </figcaption>
    </figure>
  );
}

/** Table with its caption above it ("Table 2. ..."). */
export function TableFigure({
  n,
  caption,
  children,
  notes,
}: {
  n: number | string;
  caption: ReactNode;
  children: ReactNode;
  notes?: ReactNode;
}) {
  return (
    <figure className="my-8">
      <figcaption className="mb-2.5 max-w-[46rem] text-caption leading-[1.55] text-ink-2">
        <span className="font-semibold text-ink">Table {n}.</span> {caption}
      </figcaption>
      <div className="panel overflow-x-auto px-4 py-2">{children}</div>
      {notes ? <div className="mt-2 max-w-[46rem] text-caption leading-[1.55] text-ink-3">{notes}</div> : null}
    </figure>
  );
}

/** Footnote-style caveat with a marker. */
export function Footnote({ mark = "*", children }: { mark?: string; children: ReactNode }) {
  return (
    <p className="mt-3 max-w-[46rem] text-caption leading-[1.55] text-ink-3">
      <sup className="mr-1">{mark}</sup>
      {children}
    </p>
  );
}

/** A caveat that must be read: an ochre band with its title. */
export function Caveat({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="my-6 max-w-[46rem] rounded-r-[6px] border-l-[3px] border-[#c08419] bg-loess-soft py-3 pr-4 pl-4 text-small leading-[1.55]">
      <p className="mb-1 font-semibold text-ink">{title}</p>
      <div className="text-ink-2">{children}</div>
    </div>
  );
}

export function Loading({ what }: { what: string }) {
  return (
    <p className="flex items-center gap-3 py-6 text-small text-ink-3" role="status" aria-live="polite">
      <span className="flex h-5 w-5 flex-col-reverse justify-start gap-px" aria-hidden>
        {["#34404f", "#5f7f6e", "#a46a3a", "#cdae66"].map((c, i) => (
          <span
            key={c}
            className="block h-[4px] w-full rounded-[1px]"
            style={{ background: c, animation: `strata-stack 1.6s ease-out ${i * 0.18}s infinite both` }}
          />
        ))}
      </span>
      <span className="italic">Loading {what}&hellip;</span>
    </p>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="my-4 rounded-[var(--radius-panel)] border border-dashed border-rule bg-panel/60 px-5 py-5 text-small leading-[1.6] text-ink-2">
      {children}
    </div>
  );
}

export function describeError(error: unknown): { title: string; detail: string; expected?: boolean } {
  if (error instanceof ApiError) {
    if (error.unreachable)
      return {
        title: "The Strata API could not be reached.",
        detail:
          "Check that the API is running and that NEXT_PUBLIC_API_URL points at it. See docs/DEPLOYMENT.md.",
      };
    const code =
      error.detail && typeof error.detail === "object" && "code" in error.detail
        ? String((error.detail as { code: unknown }).code)
        : null;
    if (code === "reference_unavailable")
      return {
        expected: true,
        title: "The reference library has not been built on this server yet.",
        detail:
          "Reference populations come from the data pipeline (data/pipeline), which builds data/derived from the Allen Ancient DNA Resource. See the Data page and docs/DEPLOYMENT.md.",
      };
    if (code === "llm_unavailable")
      return { expected: true, title: "The research assistant is not configured on this server.", detail: error.message };
    if (code === "qpadm_unavailable")
      return {
        expected: true,
        title: "qpAdm is not available on this server.",
        detail: "Formal tests need R and ADMIXTOOLS 2, provided by the worker image (services/worker).",
      };
    if (error.status === 404) return { title: "Not found.", detail: error.message };
    if (error.status === 503)
      return { title: "This part of Strata is not available on this server.", detail: error.message };
    return { title: `The request failed (${error.status}).`, detail: error.message };
  }
  return { title: "Something went wrong.", detail: error instanceof Error ? error.message : String(error) };
}

export function ErrorNote({ error, retry }: { error: unknown; retry?: () => void }) {
  const { title, detail, expected } = describeError(error);
  return (
    <div
      role={expected ? "status" : "alert"}
      className={`my-6 max-w-[46rem] rounded-r-[6px] border-l-[3px] py-3 pr-4 pl-4 text-small ${
        expected ? "border-ink-3 bg-wash" : "border-alert bg-[#fbecea]"
      }`}
    >
      <p className={`font-semibold ${expected ? "text-ink" : "text-alert"}`}>{title}</p>
      <p className="mt-1 text-ink-2">{detail}</p>
      {retry && !expected ? (
        <button type="button" className="linkish mt-2 text-small" onClick={retry}>
          Try again
        </button>
      ) : null}
    </div>
  );
}

/**
 * Marks a result as exploratory (G25/PCA distance fitting) or formal (qpAdm f-statistics).
 * Formal is solid malachite; exploratory is a dashed ochre outline, so the two differ in shape
 * as well as colour.
 */
export function KindMark({ kind }: { kind: "exploratory" | "formal" }) {
  return (
    <span
      className={`inline-block rounded-[var(--radius-tag)] px-1.5 py-px align-[0.14em] text-[0.8rem] leading-[1.35] font-semibold tracking-[0.01em] whitespace-nowrap ${
        kind === "formal"
          ? "border border-malachite bg-malachite text-white"
          : "border border-dashed border-[#c08419] bg-loess-soft text-loess"
      }`}
      title={
        kind === "formal"
          ? "Formal test: qpAdm on f-statistics with a stated right-population set."
          : "Exploratory: geometric fit in a PCA/G25 space. Not a test of admixture."
      }
    >
      {kind === "formal" ? "Formal" : "Exploratory"}
    </span>
  );
}
