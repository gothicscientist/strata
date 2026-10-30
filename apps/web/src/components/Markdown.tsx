import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeSlug from "rehype-slug";

const components: Components = {
  h1: ({ children, id }) => (
    <h3 id={id} className="mt-10 mb-3 text-h3 font-medium">
      {children}
    </h3>
  ),
  h2: ({ children, id }) => (
    <h3 id={id} className="mt-10 mb-3 scroll-mt-8 text-h3 font-medium">
      {children}
    </h3>
  ),
  h3: ({ children, id }) => (
    <h4 id={id} className="mt-7 mb-2 scroll-mt-8 text-body italic">
      {children}
    </h4>
  ),
  h4: ({ children, id }) => (
    <h5 id={id} className="mt-5 mb-1 scroll-mt-8 text-small italic">
      {children}
    </h5>
  ),
  p: ({ children }) => <p className="my-3 leading-[1.6]">{children}</p>,
  ul: ({ children }) => <ul className="my-3 list-disc space-y-1.5 pl-6 marker:text-ink-3">{children}</ul>,
  ol: ({ children }) => <ol className="my-3 list-decimal space-y-1.5 pl-6 marker:text-ink-3">{children}</ol>,
  li: ({ children }) => <li className="pl-1 leading-[1.55]">{children}</li>,
  a: ({ href, children }) => {
    const external = href?.startsWith("http");
    return (
      <a href={href} {...(external ? { target: "_blank", rel: "noreferrer noopener" } : {})}>
        {children}
      </a>
    );
  },
  blockquote: ({ children }) => (
    <blockquote className="my-4 border-l border-ink pl-5 text-ink-2 italic">{children}</blockquote>
  ),
  code: ({ children, className }) =>
    className ? (
      <code className={className}>{children}</code>
    ) : (
      <code className="bg-wash px-1 py-px">{children}</code>
    ),
  pre: ({ children }) => (
    <pre className="my-4 overflow-x-auto border-y border-rule bg-wash px-4 py-3 text-[0.78rem] leading-[1.6]">
      {children}
    </pre>
  ),
  table: ({ children }) => (
    <div className="my-5 overflow-x-auto">
      <table className="booktabs">{children}</table>
    </div>
  ),
  hr: () => <hr className="my-8" />,
};

/** Render repository Markdown with the journal styles. Raw HTML in the source is not rendered. */
export function Markdown({ children, idPrefix = "" }: { children: string; idPrefix?: string }) {
  return (
    <div className="text-body">
      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[[rehypeSlug, { prefix: idPrefix }]]} components={components}>
        {children}
      </ReactMarkdown>
    </div>
  );
}
