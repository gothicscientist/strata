"use client";

import { useEffect, useRef, useState } from "react";

/** True once the element has scrolled into view (and, unless `live`, stays true). */
export function useSeen<T extends HTMLElement>(threshold = 0.35, live = false): [React.RefObject<T | null>, boolean] {
  const ref = useRef<T | null>(null);
  const [seen, setSeen] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof IntersectionObserver === "undefined") {
      setSeen(true);
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        const on = entries.some((e) => e.isIntersecting);
        if (live) setSeen(on);
        else if (on) {
          setSeen(true);
          io.disconnect();
        }
      },
      { threshold },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [threshold, live]);
  return [ref, seen];
}
