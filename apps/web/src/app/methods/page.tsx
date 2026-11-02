import type { Metadata } from "next";
import { Markdown } from "@/components/Markdown";
import { Empty, PageHeader } from "@/components/typography";
import { methodDocs } from "@/lib/server/docs";

export const metadata: Metadata = { title: "Methods" };

export default function MethodsPage() {
  const docs = methodDocs();
  return (
    <>
      <PageHeader
        kicker="Documentation"
        title="Methods"
        lede="What each statistic assumes."
      />
      {docs.length === 0 ? (
        <Empty>
          The methods documentation has not been written for this build. It is read from{" "}
          <code>docs/methods/*.md</code> when the site is built.
        </Empty>
      ) : (
        <div className="grid gap-12 lg:grid-cols-[13rem_minmax(0,1fr)] lg:gap-14">
          <nav aria-label="Contents" className="text-small lg:sticky lg:top-8 lg:self-start">
            <p className="smallcaps mb-3 text-ink-3">Contents</p>
            <ol className="space-y-1.5">
              {docs.map((d, i) => (
                <li key={d.slug} className="grid grid-cols-[1.6rem_1fr]">
                  <span className="num text-ink-3">{i + 1}.</span>
                  <a href={`#${d.slug}`} className="no-underline hover:underline">
                    {d.title}
                  </a>
                </li>
              ))}
            </ol>
          </nav>
          <div className="min-w-0 max-w-[40rem]">
            {docs.map((d, i) => (
              <section key={d.slug} id={d.slug} aria-labelledby={`${d.slug}-h`} className="mb-16 scroll-mt-8">
                <h2 id={`${d.slug}-h`} className="mb-2 flex items-baseline gap-3 border-b border-ink pb-2 text-h2">
                  <span className="num text-ink-3">{i + 1}.</span>
                  <span>{d.title}</span>
                </h2>
                <Markdown idPrefix={`${d.slug}--`}>{d.body}</Markdown>
                <p className="mt-6 text-caption text-ink-3">
                  Source: <code>{d.file}</code>
                </p>
              </section>
            ))}
          </div>
        </div>
      )}
    </>
  );
}
