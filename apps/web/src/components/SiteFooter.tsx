"use client";

import Link from "next/link";
import { useSession } from "./SessionProvider";

export function SiteFooter() {
  const { health } = useSession();
  const caps = health?.capabilities;
  return (
    <footer className="mx-auto mt-24 w-full max-w-[72rem] px-5 pb-12 sm:px-8">
      <div className="grid gap-6 border-t border-ink pt-5 text-caption leading-[1.6] text-ink-2 sm:grid-cols-3">
        <p>
          Strata is open-source software for population-genetic analysis. Exploratory fits in PCA
          or G25 space are not formal tests; see <Link href="/methods/">Methods</Link>.
        </p>
        <p>
          Reference data derive from the Allen Ancient DNA Resource and the publications cited in
          the <Link href="/library/">library</Link>. Provenance and licences are listed under{" "}
          <Link href="/data/">Data</Link>.
        </p>
        <dl className="grid grid-cols-[auto_1fr] gap-x-4">
          <dt>API</dt>
          <dd className="num">{health ? `${health.status}, v${health.version}` : "not connected"}</dd>
          <dt>Reference</dt>
          <dd className="num">{caps?.reference_version ?? "not built"}</dd>
          <dt>qpAdm</dt>
          <dd>{caps ? (caps.qpadm ? "available" : "unavailable on this server") : "—"}</dd>
          <dt>Assistant</dt>
          <dd>
            {caps ? (caps.llm_providers.length ? caps.llm_providers.join(", ") : "bring your own API key") : "—"}
          </dd>
        </dl>
      </div>
    </footer>
  );
}
