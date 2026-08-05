"use client"

import { useEffect, useState } from "react"

/**
 * SSR-safe media query.
 *
 * Returns `false` on the server and on the first client render, then settles
 * after mount. That ordering matters: reading `window.matchMedia` during
 * render would either throw on the server or produce markup that disagrees
 * with the client's, and React would silently discard one of them.
 *
 * The false-first default means layouts should treat the SMALL layout as the
 * baseline and widen into the large one, so the pre-hydration frame is a
 * usable narrow layout rather than a broken wide one.
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(false)

  useEffect(() => {
    const list = window.matchMedia(query)
    const sync = () => setMatches(list.matches)
    sync()
    list.addEventListener("change", sync)
    return () => list.removeEventListener("change", sync)
  }, [query])

  return matches
}

/** Tailwind's breakpoints, so TS and CSS can never drift apart. */
export const BREAKPOINT = {
  md: "(min-width: 48rem)",
  lg: "(min-width: 64rem)",
  xl: "(min-width: 80rem)",
} as const
