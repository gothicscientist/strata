import Link from "next/link";
import { Caveman } from "./Caveman";

export function SiteFooter() {
  return (
    <footer className="mx-auto mt-24 w-full max-w-[76rem] px-5 pb-10 sm:px-10">
      <div className="relative mb-5">
        <span className="cm-walker" aria-hidden>
          <Caveman pose="walk" size={38} />
        </span>
        <div className="stratum-rule opacity-80 transition-[height,opacity] duration-300 hover:h-4 hover:opacity-100" aria-hidden />
      </div>
      <p className="flex flex-wrap gap-x-5 gap-y-1 text-caption text-ink-3">
        <span className="italic">Dug up by hand, one layer at a time.</span>
        <Link href="/methods/">Methods</Link>
        <Link href="/data/">Data and licences</Link>
        <a href="https://github.com/gothicscientist/strata">Source</a>
      </p>
    </footer>
  );
}
