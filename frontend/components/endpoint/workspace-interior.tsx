"use client"

// The workspace interior (§11 Phase 2.8): a resizable three-panel group —
// call-tree rail | graph canvas | tabbed inspector whose default tab IS the
// source. Selecting anything on the canvas or in the tree highlights the code
// it stands for, and clicking a line selects its node back: the mapping runs
// both ways with no "open in source" step between (the 1:1 requirement). The
// Source LENS still hands code the whole centre when the reader wants width,
// and only one SourceViewer is ever mounted either way, so there is one scroll
// position and one highlight. Panel sizes persist per user via
// react-resizable-panels' autoSaveId.
import { useMemo } from "react"
import {
  Group,
  Panel,
  Separator,
  useDefaultLayout,
} from "react-resizable-panels"

import type { RemoteEdgesView } from "@/lib/generated/remote_edges_view.schema"
import type { EndpointDetailView, Icfg } from "@/lib/wadi/api"
import { sourceSelectionFor } from "@/lib/wadi/source-map"
import { Skeleton } from "@/components/ui/skeleton"
import { CallTree } from "@/components/explorer/call-tree"
import { FlowCanvas } from "@/components/flow/flow-canvas"
import { EmptyState } from "@/components/shared/empty-state"
import { PanelHeader } from "@/components/shared/panel-header"
import { SourceViewer } from "@/components/source/source-viewer"

import { Inspector } from "./inspector"
import { useWorkspaceStore, useWorkspaceStoreApi } from "./workspace-store"

// `useDefaultLayout` reads its storage during render, so on the server —
// where there is no `localStorage` — it must degrade to a no-op rather than
// throw. Layouts simply aren't restored until hydration.
export const browserLayoutStorage: Pick<Storage, "getItem" | "setItem"> = {
  getItem: (key) =>
    typeof window === "undefined" ? null : window.localStorage.getItem(key),
  setItem: (key, value) => {
    if (typeof window !== "undefined") window.localStorage.setItem(key, value)
  },
}

function ResizeHandle() {
  return (
    <Separator className="w-px bg-border transition-colors hover:bg-ring/60 data-[resizing]:bg-ring" />
  )
}

export function WorkspaceInterior({
  detail,
  icfg,
  icfgLoading,
}: {
  snapshotId: string
  detail: EndpointDetailView | undefined
  icfg: Icfg | undefined
  icfgLoading: boolean
}) {
  const storeApi = useWorkspaceStoreApi()
  const lens = useWorkspaceStore((s) => s.lens)
  const sourceTarget = useWorkspaceStore((s) => s.sourceTarget)
  const selectedNodeId = useWorkspaceStore((s) => s.selectedNodeId)

  const remoteEdgesView = useMemo<RemoteEdgesView | null>(
    () =>
      detail
        ? {
            service_id: detail.service_id,
            outbound: detail.outbound,
            inbound: [],
          }
        : null,
    [detail]
  )

  const selectedMethodId = useMemo(() => {
    if (!selectedNodeId || !icfg) return null
    if (selectedNodeId.startsWith("method:"))
      return selectedNodeId.slice("method:".length)
    if (selectedNodeId.startsWith("stmt:"))
      return (
        icfg.nodes.find((n) => n.id === selectedNodeId.slice("stmt:".length))
          ?.method.id ?? null
      )
    if (selectedNodeId.startsWith("run:"))
      return (
        icfg.nodes.find((n) => n.id === selectedNodeId.slice("run:".length))
          ?.method.id ?? null
      )
    return null
  }, [selectedNodeId, icfg])

  const sourceFocus = useMemo(
    () =>
      sourceTarget
        ? {
            file: sourceTarget.file,
            line: sourceTarget.line,
            seq: sourceTarget.token,
          }
        : null,
    [sourceTarget]
  )

  // The 1:1 mapping: whatever is selected on the graph or in the call tree IS
  // what the source panel highlights, with no "open in source" step between.
  const sourceSelection = useMemo(
    () => sourceSelectionFor(icfg, selectedNodeId),
    [icfg, selectedNodeId]
  )

  const sourcePane = detail ? (
    <SourceViewer
      icfg={icfg}
      snapshotId={detail.snapshot_id}
      serviceId={detail.service_id}
      active
      focus={sourceFocus}
      selection={sourceSelection}
      onJumpNode={(methodId) => {
        storeApi.getState().selectNode(`method:${methodId}`)
      }}
      onSelectNode={(icfgNodeId) => {
        storeApi.getState().selectNode(`stmt:${icfgNodeId}`)
      }}
    />
  ) : null

  // Persist panel sizes per user (localStorage under this id). The hook
  // defaults to touching `localStorage` at render, which throws during SSR;
  // pass a storage shim that no-ops on the server (§13: the page must render
  // server-side without a DOM).
  const { defaultLayout, onLayoutChanged } = useDefaultLayout({
    id: "wadi-endpoint-workspace",
    onlySaveAfterUserInteractions: true,
    storage: browserLayoutStorage,
  })

  if (!detail || (icfgLoading && !icfg)) {
    return (
      <div className="space-y-3 p-6">
        <Skeleton className="h-8 w-96" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }

  return (
    <Group
      orientation="horizontal"
      defaultLayout={defaultLayout}
      onLayoutChanged={onLayoutChanged}
      className="min-h-0 flex-1"
    >
      <Panel
        defaultSize="18"
        minSize="12"
        collapsible
        collapsedSize={0}
        className="flex min-h-0 min-w-0 flex-col"
      >
        <PanelHeader label="Call tree" />
        {icfg ? (
          <div className="min-h-0 flex-1 overflow-y-auto">
            <CallTree
              icfg={icfg}
              selectedMethodId={selectedMethodId}
              onSelect={(node) =>
                storeApi.getState().selectNode(`method:${node.methodId}`)
              }
            />
          </div>
        ) : (
          <EmptyState>No flow graph — nothing to walk.</EmptyState>
        )}
      </Panel>
      <ResizeHandle />
      {/* The Source lens gives code the whole centre ("code is wide"); the
          graph lens keeps source in the right panel, live-synced. Only one
          SourceViewer is ever mounted, so there is one scroll position and one
          highlight regardless of where the reader is looking. */}
      <Panel
        defaultSize="46"
        minSize="26"
        className="flex min-h-0 min-w-0 flex-col"
      >
        {lens === "source" ? (
          sourcePane
        ) : icfg && remoteEdgesView ? (
          <FlowCanvas icfg={icfg} remoteEdges={remoteEdgesView} />
        ) : (
          <EmptyState className="p-6">
            No flow graph was extracted for this endpoint — the handler could
            not be resolved into an ICFG (see coverage for the reason). The
            Endpoint tab still shows everything known about its contract.
          </EmptyState>
        )}
      </Panel>
      <ResizeHandle />
      <Panel
        defaultSize="36"
        minSize="20"
        collapsible
        collapsedSize={0}
        className="flex min-h-0 min-w-0 flex-col"
      >
        <Inspector
          detail={detail}
          icfg={icfg}
          source={lens === "source" ? null : sourcePane}
        />
      </Panel>
    </Group>
  )
}
