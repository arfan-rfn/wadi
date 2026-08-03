// Deep-link state (§11 Phase 2.7): the URL always mirrors the current
// selection so any view is shareable — reload restores the exact workspace.
// Written with history.replaceState, never through the Next router, so URL
// updates cause zero re-renders (the URL is an output of state, not an input
// after the initial read).

const KEYS = [
  "system",
  "snapshot",
  "service",
  "endpoint",
  "view",
  "tab",
  "node",
] as const

export type UrlStateKey = (typeof KEYS)[number]

export type ExplorerUrlState = Record<UrlStateKey, string | null>

export function parseUrlState(params: URLSearchParams): ExplorerUrlState {
  const state = {} as ExplorerUrlState
  for (const key of KEYS) state[key] = params.get(key)
  return state
}

export function writeUrlState(state: ExplorerUrlState): void {
  if (typeof window === "undefined") return
  const params = new URLSearchParams(window.location.search)
  for (const key of KEYS) {
    const value = state[key]
    if (value) params.set(key, value)
    else params.delete(key)
  }
  const query = params.toString()
  const next = query
    ? `${window.location.pathname}?${query}`
    : window.location.pathname
  const current = `${window.location.pathname}${window.location.search}`
  if (next !== current) window.history.replaceState(null, "", next)
}

/** Constrain a raw URL value to a known set, falling back when absent/invalid. */
export function constrain<T extends string>(
  value: string | null,
  allowed: readonly T[],
  fallback: T
): T {
  return allowed.includes(value as T) ? (value as T) : fallback
}
