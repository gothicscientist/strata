import Link from "next/link";

export function SiteFooter() {
  return (
    <footer className="mx-auto mt-24 w-full max-w-[76rem] px-5 pb-10 sm:px-10">
      <div className="stratum-rule mb-5 opacity-80" aria-hidden />
      <div className="grid gap-4 text-caption leading-[1.6] text-ink-3 sm:grid-cols-2">
        <p>
          Strata is open-source software for population-genetic analysis. Exploratory fits in PCA or
          G25 space are not formal tests; see <Link href="/methods/">Methods</Link>.
        </p>
        <p>
          Reference data derive from the Allen Ancient DNA Resource, the 1000 Genomes Project and the
          publications cited in the <Link href="/library/">library</Link>. Provenance and licences
          are listed under <Link href="/data/">Data</Link>.
        </p>
      </div>
    </footer>
  );
}
