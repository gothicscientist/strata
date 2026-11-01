"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSession } from "./SessionProvider";
import { relativeExpiry } from "@/lib/format";

const NAV: Array<{ href: string; label: string }> = [
  { href: "/library/", label: "Library" },
  { href: "/examples/", label: "Examples" },
  { href: "/upload/", label: "Upload" },
  { href: "/analyses/new/", label: "Compose" },
  { href: "/workspace/", label: "Workspace" },
  { href: "/assistant/", label: "Assistant" },
  { href: "/methods/", label: "Methods" },
  { href: "/data/", label: "Data" },
];

function isActive(path: string, href: string): boolean {
  const p = path.endsWith("/") ? path : `${path}/`;
  if (href === "/analyses/new/") return p.startsWith("/analyses/") || p.startsWith("/analysis/");
  return p.startsWith(href);
}

export function SessionLine() {
  const { session, retry } = useSession();
  switch (session.status) {
    case "connecting":
      return <span className="italic">Connecting to the API&hellip;</span>;
    case "guest":
      return (
        <span>
          Guest workspace, {relativeExpiry(session.expiresAt)}.{" "}
          <Link href="/account/">Account</Link>
        </span>
      );
    case "signed-in":
      return (
        <span>
          Signed in{session.email ? ` as ${session.email}` : ""}. <Link href="/account/">Account</Link>
        </span>
      );
    case "offline":
      return (
        <span>
          <span className="text-alert">API offline.</span>{" "}
          <button type="button" className="linkish" onClick={retry}>
            Retry
          </button>
        </span>
      );
  }
}

export function SiteHeader() {
  const path = usePathname() ?? "/";
  return (
    <header className="mx-auto w-full max-w-[72rem] px-5 pt-7 sm:px-8">
      <a
        href="#main"
        className="absolute left-2 top-2 -translate-y-20 bg-paper px-3 py-2 text-small focus:translate-y-0"
      >
        Skip to content
      </a>
      <div className="flex flex-wrap items-baseline justify-between gap-x-8 gap-y-2 border-b border-ink pb-3">
        <Link href="/" className="no-underline" aria-label="Strata, home">
          <span className="text-[2rem] leading-none font-medium tracking-[0.01em]">Strata</span>
        </Link>
        <p className="text-caption text-ink-2">
          <SessionLine />
        </p>
      </div>
      <nav aria-label="Primary" className="-mx-5 overflow-x-auto border-b border-rule px-5 sm:mx-0 sm:px-0">
        <ul className="-mx-2 flex gap-x-1 py-1.5 whitespace-nowrap sm:flex-wrap">
          {NAV.map((n) => {
            const active = isActive(path, n.href);
            return (
              <li key={n.href}>
                <Link
                  href={n.href}
                  aria-current={active ? "page" : undefined}
                  className={`smallcaps inline-block px-2 py-1 ${
                    active ? "text-ink underline decoration-ink" : "text-ink-2 no-underline hover:text-ink"
                  }`}
                >
                  {n.label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
    </header>
  );
}
