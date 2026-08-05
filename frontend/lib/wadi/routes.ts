// Route + URL-state helpers (§11 Phase 2.8): pages are real routes (browser
// back works, links are shareable); within-page workspace state stays in
// query params written with history.replaceState (zero re-renders — the URL
// is an output of state after the initial read). Lens flips use pushState so

export const HOME_VIEWS = ["coverage", "map", "auth", "services"] as const
export type HomeView = (typeof HOME_VIEWS)[number]

/**
 * The snapshot `/` lands on: the most recently created SUCCEEDED one.
 *
 * Falls back to the newest snapshot of any status only when nothing has
 * succeeded, so a system whose every run failed still shows its failure
 * rather than an "analyze first" dead end that hides the real story.
 */
export function newestSucceeded<
  T extends { status?: string | null; created_at?: string | null },
>(snapshots: readonly T[]): T | null {
  if (snapshots.length === 0) return null
  const byNewest = [...snapshots].sort((a, b) =>
    (b.created_at ?? "").localeCompare(a.created_at ?? "")
  )
  return byNewest.find((s) => s.status === "succeeded") ?? byNewest[0] ?? null
}

export function snapshotPath(
  snapshotId: string,
  options?: { view?: HomeView; serviceId?: string | null }
): string {
  const params = new URLSearchParams()
  if (options?.view && options.view !== "coverage")
    params.set("view", options.view)
  if (options?.serviceId) params.set("service", options.serviceId)
  const query = params.toString()
  return `/s/${snapshotId}${query ? `?${query}` : ""}`
}

export function endpointPath(
  snapshotId: string,
  endpointId: string,
  params?: Partial<WorkspaceParams>
): string {
  const query = params ? serializeWorkspaceParams(params).toString() : ""
  return `/s/${snapshotId}/e/${endpointId}${query ? `?${query}` : ""}`
}

/** Deep-linkable workspace state: the shareable subset of the store.
 * `expand` is the expanded-method set — "all" | "none" | explicit ids;
 * null = the default (entry handler only). */
export interface WorkspaceParams {
  node: string | null
  focus: string | null
  expand: "all" | "none" | string[] | null
  file: string | null
}

export const WORKSPACE_DEFAULTS: WorkspaceParams = {
  node: null,
  focus: null,
  expand: null,
  file: null,
}

export function parseWorkspaceParams(params: URLSearchParams): WorkspaceParams {
  const rawExpand = params.get("expand")
  return {
    node: params.get("node"),
    focus: params.get("focus"),
    expand:
      rawExpand === null
        ? null
        : rawExpand === "all" || rawExpand === "none"
          ? rawExpand
          : rawExpand.split(",").filter(Boolean),
    file: params.get("file"),
  }
}

export function serializeWorkspaceParams(
  state: Partial<WorkspaceParams>
): URLSearchParams {
  const params = new URLSearchParams()
  if (state.node) params.set("node", state.node)
  if (state.focus) params.set("focus", state.focus)
  if (state.expand != null) {
    // An explicitly-empty set means "I collapsed everything" — which is NOT
    // the same as an absent param (that means "default", i.e. auto-expand the
    // handler). Writing nothing here made a reload resurrect the lane the
    // user had just collapsed, so empty serializes as the explicit "none".
    const value = Array.isArray(state.expand)
      ? state.expand.join(",") || "none"
      : state.expand
    if (value) params.set("expand", value)
  }
  if (state.file) params.set("file", state.file)
  return params
}

/** Mirror workspace state onto the current URL. `push` creates a history
 * entry; everything else replaces in place. */
export function writeWorkspaceParams(
  state: WorkspaceParams,
  options?: { push?: boolean }
): void {
  if (typeof window === "undefined") return
  const query = serializeWorkspaceParams(state).toString()
  const next = query
    ? `${window.location.pathname}?${query}`
    : window.location.pathname
  const current = `${window.location.pathname}${window.location.search}`
  if (next === current) return
  if (options?.push) window.history.pushState(null, "", next)
  else window.history.replaceState(null, "", next)
}

/** Constrain a raw URL value to a known set, falling back when absent/invalid. */
export function constrain<T extends string>(
  value: string | null,
  allowed: readonly T[],
  fallback: T
): T {
  return allowed.includes(value as T) ? (value as T) : fallback
}
