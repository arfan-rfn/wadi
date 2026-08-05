"use client"

// The endpoint workspace shell (§11 Phase 2.8): full-viewport, graph-first.
// Owns the per-page store (fresh per endpoint — navigation resets it), the
// URL mirror, and the identity header; the interior (call tree | flow |
// source) mounts inside.
import { useEffect, useMemo, useState } from "react"
import { useSearchParams } from "next/navigation"

import { useEndpointDetail, useIcfg } from "@/lib/wadi/hooks"
import { parseWorkspaceParams, writeWorkspaceParams } from "@/lib/wadi/routes"

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

  // Mirror the shareable subset back onto the URL. Every write replaces now
  // that the lens is gone — there is no in-page mode change left that a reader
  // would expect browser Back to undo.
  useEffect(
    () =>
      store.subscribe((state) => {
        writeWorkspaceParams({
          node: state.selectedNodeId,
          focus: state.focusMethodId,
          expand: expandToParams(state.expand),
          file: state.sourceTarget?.file ?? null,
        })
      }),
    [store]
  )

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

  return (
    <WorkspaceStoreContext.Provider value={store}>
      <div className="flex min-h-0 flex-1 flex-col">
        <IdentityHeader
          snapshotId={snapshotId}
          endpointId={endpointId}
          detail={detail.data}
          icfg={icfg.data}
        />
        {detail.isError ? (
          <p className="border-b bg-destructive/5 px-4 py-2 text-sm text-destructive">
            {String(detail.error)}
          </p>
        ) : null}
        <WorkspaceInterior
          detail={detail.data}
          icfg={icfg.data}
          icfgLoading={detail.data?.icfg_available !== false && icfg.isPending}
          // A failed fetch is not an extraction result. Without this the
          // canvas falls through to "no flow graph was extracted for this
          // endpoint — the handler could not be resolved into an ICFG", which
          // blames the analysis for a network error (P10).
          icfgError={icfg.isError ? (icfg.error as Error) : null}
        />
      </div>
    </WorkspaceStoreContext.Provider>
  )
}
