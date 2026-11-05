import Link from "next/link";
import { StrataMark } from "@/components/StrataMark";
import { Caveman } from "@/components/Caveman";

export default function NotFound() {
  return (
    <article className="flex flex-col items-start gap-6 py-10 sm:flex-row sm:items-center sm:gap-12">
      <div className="flex shrink-0 items-end gap-2">
        <div className="relative h-56 w-20 shrink-0 overflow-hidden rounded-b-[40%_12px] border border-dashed border-ink-3/60">
          <div className="absolute inset-x-0 bottom-0 h-1/4 bg-[#34404f]/15" />
          <div className="absolute inset-x-0 top-3 flex justify-center opacity-60">
            <StrataMark size={18} />
          </div>
        </div>
        <Caveman pose="puzzled" size={104} className="-mb-1" />
      </div>
      <div>
        <h1 className="display text-[2.6rem] sm:text-h1">Nothing at this depth.</h1>
        <p className="measure mt-4 text-[1.3rem] leading-[1.5] text-ink-2">
          The page you dug for is not in this core. It may have moved, or the link may be wrong.
        </p>
        <div className="mt-7 flex flex-wrap gap-3">
          <Link href="/" className="btn">
            Back to the surface
          </Link>
          <Link href="/library/" className="btn btn-quiet">
            Browse the library
          </Link>
        </div>
      </div>
    </article>
  );
}
