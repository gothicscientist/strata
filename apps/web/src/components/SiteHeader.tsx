"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { useSession } from "./SessionProvider";
import { StrataMark } from "./StrataMark";
import { relativeExpiry } from "@/lib/format";

interface NavItem {
  href: string;
  label: string;
  hint: string;
  step?: number;
}

/**
 * Navigation follows the work. Upload, compose and review are a real sequence and are numbered;
 * the other groups are places you visit in any order.
 */
const GROUPS: Array<{ title: string; items: NavItem[] }> = [
  {
    title: "Explore",
    items: [
      { href: "/library/", label: "Library", hint: "Reference populations" },
      { href: "/examples/", label: "Examples", hint: "Worked qpAdm and f4 tests" },
    ],
  },
  {
    title: "Analyse",
    items: [
      { href: "/upload/", label: "Upload", hint: "Raw file, VCF or G25", step: 1 },
      { href: "/analyses/new/", label: "Compose", hint: "Choose a method", step: 2 },
      { href: "/workspace/", label: "Workspace", hint: "Datasets and results", step: 3 },
    ],
  },
  {
    title: "Ask",
    items: [{ href: "/assistant/", label: "Assistant", hint: "Questions answered with analyses" }],
  },
  {
    title: "Reference",
    items: [
      { href: "/methods/", label: "Methods", hint: "Statistics and assumptions" },
      { href: "/data/", label: "Data", hint: "Sources and licences" },
    ],
  },
];

function isActive(path: string, href: string): boolean {
  const p = path.endsWith("/") ? path : `${path}/`;
  if (href === "/analyses/new/") return p.startsWith("/analyses/");
  if (href === "/workspace/") return p.startsWith("/workspace/") || p.startsWith("/analysis/");
  return p.startsWith(href);
}

export function SessionLine() {
  const { session, retry } = useSession();
  switch (session.status) {
    case "connecting":
      return <span>Connecting to the API&hellip;</span>;
    case "guest":
      return (
        <span>
          Guest workspace, {relativeExpiry(session.expiresAt)}. <Link href="/account/">Account</Link>
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
          <span className="text-[#f0a79c]">API offline.</span>{" "}
          <button type="button" className="linkish" onClick={retry}>
            Retry
          </button>
        </span>
      );
  }
}

function Readout({ label, value, state }: { label: string; value: string; state: "ok" | "off" | "wait" }) {
  const dot = state === "ok" ? "bg-[#62c39a]" : state === "off" ? "bg-[#d39a3a]" : "bg-[#6b7682]";
  return (
    <div className="grid grid-cols-[0.5rem_4.75rem_1fr] items-baseline gap-x-2">
      <span className={`inline-block size-1.5 -translate-y-px rounded-full ${dot}`} aria-hidden />
      <dt className="text-[#8d98a3]">{label}</dt>
      <dd className="num truncate text-[#d5dbe0]" title={value}>
        {value}
      </dd>
    </div>
  );
}

function Status() {
  const { health } = useSession();
  const caps = health?.capabilities;
  const wait = !health;
  return (
    <dl className="space-y-1 text-[0.75rem] leading-[1.5]" aria-label="Server status">
      <Readout label="API" value={health ? `${health.status}, v${health.version}` : "not connected"} state={wait ? "wait" : health.status === "ok" ? "ok" : "off"} />
      <Readout label="Reference" value={caps?.reference_version ?? "not built"} state={wait ? "wait" : caps?.reference_loaded ? "ok" : "off"} />
      <Readout label="qpAdm" value={caps ? (caps.qpadm ? "available" : "not installed") : "—"} state={wait ? "wait" : caps?.qpadm ? "ok" : "off"} />
      <Readout
        label="Assistant"
        value={caps ? (caps.llm_providers.length ? caps.llm_providers.join(", ") : "not configured") : "—"}
        state={wait ? "wait" : caps?.llm_providers.length ? "ok" : "off"}
      />
    </dl>
  );
}

function Nav({ path, onNavigate }: { path: string; onNavigate?: () => void }) {
  return (
    <nav aria-label="Primary" className="space-y-6">
      {GROUPS.map((g) => (
        <div key={g.title}>
          <p className="mb-1.5 px-3 text-[0.72rem] font-semibold tracking-[0.02em] text-[#7f8a95]">{g.title}</p>
          <ul className="space-y-px">
            {g.items.map((n) => {
              const active = isActive(path, n.href);
              return (
                <li key={n.href}>
                  <Link
                    href={n.href}
                    onClick={onNavigate}
                    aria-current={active ? "page" : undefined}
                    className={`group relative grid grid-cols-[1.25rem_1fr] items-baseline gap-x-2 rounded-[6px] px-3 py-1.5 no-underline transition-colors ${
                      active ? "bg-white/[0.07] text-white" : "text-[#c3cbd2] hover:bg-white/[0.04] hover:text-white"
                    }`}
                  >
                    {active ? (
                      <span className="absolute top-1.5 bottom-1.5 left-0 w-[3px] rounded-r bg-[#62c39a]" aria-hidden />
                    ) : null}
                    <span className={`num text-[0.72rem] ${active ? "text-[#62c39a]" : "text-[#6f7a86]"}`}>
                      {n.step ?? ""}
                    </span>
                    <span>
                      <span className="block text-[0.9375rem] font-medium leading-tight">{n.label}</span>
                      <span className="block text-[0.72rem] leading-snug text-[#8d98a3] group-hover:text-[#a9b3bc]">
                        {n.hint}
                      </span>
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );
}

export function SiteHeader() {
  const path = usePathname() ?? "/";
  const [open, setOpen] = useState(false);
  useEffect(() => setOpen(false), [path]);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const brand = (
    <Link href="/" className="flex items-center gap-2.5 text-white no-underline hover:text-white" aria-label="Strata, home">
      <StrataMark size={24} />
      <span className="text-[1.3rem] leading-none font-semibold tracking-[-0.01em] [font-stretch:125%]">Strata</span>
    </Link>
  );

  return (
    <>
      <a
        href="#main"
        className="absolute top-2 left-2 z-50 -translate-y-20 rounded-[6px] bg-panel px-3 py-2 text-small focus:translate-y-0"
      >
        Skip to content
      </a>

      {/* Small screens: a bar with a menu that opens the same rail as a sheet. */}
      <header className="sticky top-0 z-40 flex items-center justify-between bg-basalt px-5 py-3 lg:hidden">
        {brand}
        <button
          type="button"
          className="rounded-[6px] border border-white/15 px-3 py-1.5 text-small font-medium text-white"
          aria-expanded={open}
          aria-controls="rail"
          onClick={() => setOpen((o) => !o)}
        >
          {open ? "Close" : "Menu"}
        </button>
      </header>
      {open ? (
        <button
          type="button"
          aria-label="Close menu"
          className="fixed inset-0 z-40 bg-basalt/40 lg:hidden"
          onClick={() => setOpen(false)}
        />
      ) : null}

      <aside
        id="rail"
        className={`fixed inset-y-0 left-0 z-50 flex w-[16rem] flex-col overflow-y-auto bg-basalt px-3 pt-6 pb-5 text-[#c3cbd2] transition-transform lg:sticky lg:top-0 lg:z-auto lg:h-screen lg:translate-x-0 ${
          open ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="mb-8 px-3">{brand}</div>
        <Nav path={path} onNavigate={() => setOpen(false)} />
        <div className="mt-auto space-y-4 px-3 pt-10">
          <Status />
          <p className="border-t border-white/10 pt-3 text-[0.75rem] leading-[1.5] text-[#a9b3bc] [&_a]:text-[#d5dbe0]">
            <SessionLine />
          </p>
        </div>
      </aside>
    </>
  );
}
