import type { ReactNode } from "react";
import { ApiError } from "@/lib/api";

export function PageHeader({
  kicker,
  title,
  lede,
  aside,
}: {
  kicker?: string;
  title: ReactNode;
  lede?: ReactNode;
  aside?: ReactNode;
}) {
  return (
    <header className="mb-12 grid gap-6 border-b border-ink pb-8 lg:grid-cols-[minmax(0,1fr)_15rem] lg:gap-14">
      <div>
        {kicker ? <p className="smallcaps mb-3 text-ink-3">{kicker}</p> : null}
        <h1 className="text-[2.1rem] leading-[1.12] sm:text-h1">{title}</h1>
        {lede ? (
          <div className="measure mt-4 text-[1.25rem] leading-[1.45] text-ink-2 italic">{lede}</div>
        ) : null}
      </div>
      {aside ? <div className="self-end text-small text-ink-2 lg:pb-1">{aside}</div> : null}
    </header>
  );
}

/** A numbered section in the manner of a paper: "2. Methods". */
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
    <section id={id} className="mb-14 scroll-mt-8" aria-labelledby={id ? `${id}-h` : undefined}>
      <h2 id={id ? `${id}-h` : undefined} className="mb-5 flex items-baseline gap-3 text-h2">
        {n !== undefined ? <span className="num text-ink-3 tabular-nums">{n}.</span> : null}
        <span>{title}</span>
      </h2>
      {aside ? (
        <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_15rem] lg:gap-14">
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
      <div className="border-y border-rule py-4">{children}</div>
      <figcaption className="mt-3 max-w-[44rem] text-caption leading-[1.5] text-ink-2">
        <span className="font-semibold text-ink">
          {label} {n}.
        </span>{" "}
        {caption}
      </figcaption>
    </figure>
  );
}

/** Table with a journal caption above it ("Table 2. ..."). */
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
      <figcaption className="mb-2 max-w-[44rem] text-caption leading-[1.5] text-ink-2">
        <span className="font-semibold text-ink">Table {n}.</span> {caption}
      </figcaption>
      <div className="overflow-x-auto">{children}</div>
      {notes ? <div className="mt-2 max-w-[44rem] text-caption leading-[1.5] text-ink-3">{notes}</div> : null}
    </figure>
  );
}

/** Footnote-style caveat with a marker. */
export function Footnote({ mark = "*", children }: { mark?: string; children: ReactNode }) {
  return (
    <p className="mt-3 max-w-[44rem] text-caption leading-[1.5] text-ink-2">
      <sup className="mr-1">{mark}</sup>
      {children}
    </p>
  );
}

/** A ruled note in the margin of the text block, used for caveats that must be read. */
export function Caveat({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="my-6 max-w-[44rem] border-l border-ink py-1 pl-5 text-small leading-[1.55]">
      <p className="mb-1 italic">{title}</p>
      <div className="text-ink-2">{children}</div>
    </div>
  );
}

export function Loading({ what }: { what: string }) {
  return (
    <p className="py-6 text-small text-ink-3 italic" role="status" aria-live="polite">
      Loading {what}&hellip;
    </p>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="py-6 text-small text-ink-2 italic">{children}</div>;
}

export function describeError(error: unknown): { title: string; detail: string } {
  if (error instanceof ApiError) {
    if (error.unreachable)
      return {
        title: "The Strata API could not be reached.",
        detail:
          "Check that the API is running and that NEXT_PUBLIC_API_URL points at it. See docs/DEPLOYMENT.md.",
      };
    if (error.status === 404) return { title: "Not found.", detail: error.message };
    if (error.status === 503)
      return { title: "This part of Strata is not available on this server.", detail: error.message };
    return { title: `The request failed (${error.status}).`, detail: error.message };
  }
  return { title: "Something went wrong.", detail: error instanceof Error ? error.message : String(error) };
}

export function ErrorNote({ error, retry }: { error: unknown; retry?: () => void }) {
  const { title, detail } = describeError(error);
  return (
    <div role="alert" className="my-6 max-w-[44rem] border-l-2 border-alert py-1 pl-5 text-small">
      <p className="text-alert">{title}</p>
      <p className="mt-1 text-ink-2">{detail}</p>
      {retry ? (
        <button type="button" className="linkish mt-2 text-small" onClick={retry}>
          Try again
        </button>
      ) : null}
    </div>
  );
}

/** Marks a result as exploratory (G25/PCA distance fitting) or formal (qpAdm f-statistics). */
export function KindMark({ kind }: { kind: "exploratory" | "formal" }) {
  return (
    <span
      className={`smallcaps inline-block border px-1.5 py-px align-[0.1em] ${
        kind === "formal" ? "border-ink text-ink" : "border-ink-3 text-ink-2"
      }`}
      title={
        kind === "formal"
          ? "Formal test: qpAdm on f-statistics with a stated right-population set."
          : "Exploratory: geometric fit in a PCA/G25 space. Not a test of admixture."
      }
    >
      {kind}
    </span>
  );
}
