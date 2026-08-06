"use client"

import { useEffect, useState } from "react"

/**
 * `false` on the server and on the client's FIRST render; `true` afterwards.
 *
 * Every list and count on the overview home comes from a client fetch, so the
 * server has nothing real to render and emits a skeleton. The client, hydrating
 * against a warm TanStack Query cache, has the data on its very first render
 * and emits the rows instead. That is a DOM-SHAPE disagreement, not merely a
 * different number, so React fails hydration outright and regenerates the tree.
 *
 * Gating on this rather than on `isPending` keeps the first client render
 * identical to the server's whether or not the cache is warm. It is not a
 * workaround: it matches where the data actually comes from.
 *
 * This was written out by hand in three places (the header's scope pickers,
 * the panel header's count, and the overview home's two lists) before it was
 * extracted, which is one place too many for a rule this easy to forget.
 */
export function useMounted(): boolean {
  const [mounted, setMounted] = useState(false)
  useEffect(() => setMounted(true), [])
  return mounted
}
