"use client"

// The workspace's one selection truth (§11 Phase 2.8): tree, canvas, source,
// and inspector all subscribe here — no prop-drilled sync channels, no seq
// counters. A fresh store per endpoint page (factory + context) so navigation
// resets state; the shareable subset mirrors to the URL via routes.ts.
import { createContext, useContext } from "react"
import { createStore, useStore, type StoreApi } from "zustand"

import type { WorkspacePane, WorkspaceParams } from "@/lib/wadi/routes"

/** Expanded-method state. `default` = the entry handler only (resolved
 * against the ICFG by the canvas); explicit sets round-trip the URL. */
export type ExpandState =
  | { mode: "default" }
  | { mode: "all" }
  | { mode: "none" }
  | { mode: "explicit"; ids: ReadonlySet<string> }

export interface SourceTarget {
  file: string
  line: number
  /** Monotonic token: repeating the same reveal still retriggers the scroll. */
  token: number
}

export interface WorkspaceState {
  selectedNodeId: string | null
  hoveredNodeId: string | null
  expand: ExpandState
  expandedRuns: ReadonlySet<string>
  focusMethodId: string | null
  sourceTarget: SourceTarget | null
  search: string
  traceEnabled: boolean
  /** The left pane: the call tree, or the Data list (§5.2.17 UI). */
  pane: WorkspacePane
  /** The selected Data-list row: a qualified type name, or
   * `UNDETERMINED_ENTITY_KEY` for "entity not determined". Its call sites
   * take the canvas's trace highlight while the Data pane is showing. */
  selectedEntity: string | null

  selectNode: (id: string | null) => void
  hoverNode: (id: string | null) => void
  /** Toggle one method; `resolvedExpanded` is the currently-drawn expanded
   * set (the component resolves `default`/`all` against its ICFG). */
  toggleMethod: (id: string, resolvedExpanded: ReadonlySet<string>) => void
  expandAll: () => void
  collapseAll: () => void
  setExplicitExpand: (ids: Iterable<string>) => void
  toggleRun: (id: string) => void
  setFocus: (methodId: string | null) => void
  revealSource: (file: string, line: number) => void
  setSearch: (query: string) => void
  setTraceEnabled: (enabled: boolean) => void
  /** Switch the left pane. Leaving the Data pane drops the selected entity:
   * the highlight it drives would otherwise outlive the row explaining it. */
  setPane: (pane: WorkspacePane) => void
  /** Select (or, with null, clear) a Data-list row; opens the Data pane. */
  selectEntity: (entity: string | null) => void
  /** Re-hydrate the URL-backed fields (browser back/forward). */
  applyUrlParams: (params: WorkspaceParams) => void
}

function expandFromParams(expand: WorkspaceParams["expand"]): ExpandState {
  if (expand === null) return { mode: "default" }
  if (expand === "all") return { mode: "all" }
  if (expand === "none") return { mode: "none" }
  return { mode: "explicit", ids: new Set(expand) }
}

export function expandToParams(state: ExpandState): WorkspaceParams["expand"] {
  switch (state.mode) {
    case "default":
      return null
    case "all":
      return "all"
    case "none":
      return "none"
    case "explicit":
      return [...state.ids]
  }
}

/** The URL-backed subset of the store, as `writeWorkspaceParams` takes it. */
export function workspaceParamsOf(state: WorkspaceState): WorkspaceParams {
  return {
    node: state.selectedNodeId,
    focus: state.focusMethodId,
    expand: expandToParams(state.expand),
    file: state.sourceTarget?.file ?? null,
    pane: state.pane,
    entity: state.pane === "data" ? state.selectedEntity : null,
  }
}

export type WorkspaceStore = StoreApi<WorkspaceState>

export function createWorkspaceStore(initial: WorkspaceParams): WorkspaceStore {
  return createStore<WorkspaceState>()((set) => ({
    selectedNodeId: initial.node,
    hoveredNodeId: null,
    expand: expandFromParams(initial.expand),
    expandedRuns: new Set<string>(),
    focusMethodId: initial.focus,
    sourceTarget: initial.file
      ? { file: initial.file, line: 1, token: 0 }
      : null,
    search: "",
    traceEnabled: false,
    pane: initial.pane,
    selectedEntity: initial.pane === "data" ? initial.entity : null,

    // Selecting anything lands on the CODE. The source viewer already
    // highlights and scrolls to whatever is selected (workspace-interior's
    // `sourceSelection`), so a click on the graph IS the graph→source link —
    // no facts panel in between, no "open in source" step. Ghosts are the one
    // exception: they stand for a call leaving the system and have no source
    // of their own. Their target resolution, confidence and provenance are
    // stated in the source header's selection strip, which is now the single
    // place a selection explains itself (P10).
    selectNode: (id) => set({ selectedNodeId: id }),
    hoverNode: (id) => set({ hoveredNodeId: id }),
    toggleMethod: (id, resolvedExpanded) =>
      set(() => {
        const ids = new Set(resolvedExpanded)
        if (ids.has(id)) ids.delete(id)
        else ids.add(id)
        return { expand: { mode: "explicit", ids } }
      }),
    expandAll: () => set({ expand: { mode: "all" } }),
    collapseAll: () =>
      set({ expand: { mode: "none" }, expandedRuns: new Set() }),
    setExplicitExpand: (ids) =>
      set({ expand: { mode: "explicit", ids: new Set(ids) } }),
    toggleRun: (id) =>
      set((state) => {
        const runs = new Set(state.expandedRuns)
        if (runs.has(id)) runs.delete(id)
        else runs.add(id)
        return { expandedRuns: runs }
      }),
    setFocus: (methodId) => set({ focusMethodId: methodId }),
    revealSource: (file, line) =>
      set((state) => ({
        // Source is always on screen, so "open in source" means "point it at
        // this" — never swapping the centre out from under the reader.
        sourceTarget: {
          file,
          line,
          token: (state.sourceTarget?.token ?? 0) + 1,
        },
      })),
    setSearch: (query) => set({ search: query }),
    setTraceEnabled: (enabled) => set({ traceEnabled: enabled }),
    setPane: (pane) =>
      set((state) => ({
        pane,
        selectedEntity: pane === "data" ? state.selectedEntity : null,
      })),
    selectEntity: (entity) => set({ pane: "data", selectedEntity: entity }),
    applyUrlParams: (params) =>
      set((state) => ({
        pane: params.pane,
        selectedEntity: params.pane === "data" ? params.entity : null,
        selectedNodeId: params.node,
        focusMethodId: params.focus,
        expand: expandFromParams(params.expand),
        // Re-scroll only when the URL names a different file than the one
        // already shown; otherwise keep the current line.
        sourceTarget:
          params.file && params.file !== state.sourceTarget?.file
            ? {
                file: params.file,
                line: 1,
                token: (state.sourceTarget?.token ?? 0) + 1,
              }
            : state.sourceTarget,
      })),
  }))
}

export const WorkspaceStoreContext = createContext<WorkspaceStore | null>(null)

export function useWorkspaceStore<T>(
  selector: (state: WorkspaceState) => T
): T {
  const store = useContext(WorkspaceStoreContext)
  if (!store)
    throw new Error("useWorkspaceStore requires a WorkspaceStoreContext")
  return useStore(store, selector)
}

export function useWorkspaceStoreApi(): WorkspaceStore {
  const store = useContext(WorkspaceStoreContext)
  if (!store)
    throw new Error("useWorkspaceStoreApi requires a WorkspaceStoreContext")
  return store
}
