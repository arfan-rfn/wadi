"use client"

// The endpoint workspace shell (§11 Phase 2.8): full-viewport, graph-first.
// Owns the per-page store (fresh per endpoint — navigation resets it), the
// URL mirror, and the identity header; the interior (rail | lens | inspector)
// mounts inside.
import { useEffect, useMemo, useState } from "react"
import { useSearchParams } from "next/navigation"

import { useEndpointDetail, useIcfg } from "@/lib/wadi/hooks"
import {
  parseWorkspaceParams,
  writeWorkspaceParams,
  type Lens,
} from "@/lib/wadi/routes"

import { IdentityHeader } from "./identity-header"
import { WorkspaceInterior } from "./workspace-interior"
import {
  createWorkspaceStore,
  expandToParams,
  WorkspaceStoreContext,
} from "./workspace-store"

export function EndpointWorkspace({
  snapshotId,
  endpointId,
}: {
  snapshotId: string
  endpointId: string
}) {
  const searchParams = useSearchParams()
  // One store per endpoint page instance, hydrated from the URL exactly once.
  const [store] = useState(() =>
    createWorkspaceStore(parseWorkspaceParams(searchParams))
  )

  // Mirror the shareable subset back onto the URL. Lens flips push a history
  // entry so browser Back leaves the Source lens before leaving the page.
  useEffect(() => {
    let lastLens: Lens = store.getState().lens
    return store.subscribe((state) => {
      const push = state.lens !== lastLens
      lastLens = state.lens
      writeWorkspaceParams(
        {
          node: state.selectedNodeId,
          focus: state.focusMethodId,
          expand: expandToParams(state.expand),
          lens: state.lens,
          tab: state.inspectorTab,
          file:
            state.lens === "source" ? (state.sourceTarget?.file ?? null) : null,
        },
        { push }
      )
    })
  }, [store])

  // Browser back/forward must move the UI, not just the address bar: the
  // store hydrates from the URL at mount, so popstate has to re-apply it.
  useEffect(() => {
    const onPopState = () => {
      store
        .getState()
        .applyUrlParams(
          parseWorkspaceParams(new URLSearchParams(window.location.search))
        )
    }
    window.addEventListener("popstate", onPopState)
    return () => window.removeEventListener("popstate", onPopState)
  }, [store])

  const detail = useEndpointDetail(snapshotId, endpointId)
  const icfg = useIcfg(
    snapshotId,
    detail.data?.icfg_available === false ? null : endpointId
  )
  const lens = useMemoLens(store)

  return (
    <WorkspaceStoreContext.Provider value={store}>
      <div className="flex min-h-0 flex-1 flex-col">
        <IdentityHeader
          snapshotId={snapshotId}
          endpointId={endpointId}
          detail={detail.data}
          icfg={icfg.data}
          lens={lens}
          onLens={(next) => store.getState().setLens(next)}
        />
        {detail.isError ? (
          <p className="border-b bg-destructive/5 px-4 py-2 text-sm text-destructive">
            {String(detail.error)}
          </p>
        ) : null}
        <WorkspaceInterior
          snapshotId={snapshotId}
          detail={detail.data}
          icfg={icfg.data}
          icfgLoading={detail.data?.icfg_available !== false && icfg.isPending}
        />
      </div>
    </WorkspaceStoreContext.Provider>
  )
}

/** Subscribe to just the lens (header toggle) without a context consumer. */
function useMemoLens(store: ReturnType<typeof createWorkspaceStore>): Lens {
  const [lens, setLens] = useState<Lens>(() => store.getState().lens)
  useEffect(() => store.subscribe((state) => setLens(state.lens)), [store])
  return lens
}
