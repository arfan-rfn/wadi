"use client"

// The workspace interior (§5.2.9 UI): call tree | flow | source, permanently.
//
// This replaced a three-panel group whose right side was a TAB STRIP holding
// Source, Selection and Endpoint — with a second Graph/Source toggle in the
// header that switched the centre between the same two things. Source was
// reachable two ways and the contract was duplicated one screen deep. Now the
// graph and the code are simply both there, and:
//
//   * the endpoint's contract moved OUT, to the overview peek — one screen
//     earlier, where you decide whether to open the flow at all;
//   * the Selection facts moved INTO the source header (`SelectionStrip`),
//     annotating the code rather than sitting beside it.
//
// The left panel reads the flow two ways (§5.2.17 UI): Calls, the call tree,
// and Data, the entities the endpoint may touch. The switch is URL state
// (`pane=data`, `entity=…`), so a link can open straight onto one entity with
// its call sites lit on the canvas.
//
// Each side panel collapses to a labelled rail and comes back on click, so a
// panel can be got out of the way without being lost. Below `lg` the three
// panels become one at a time behind a segmented switcher — three columns on a
// tablet is three unusable columns.
import { useEffect, useMemo, useState } from "react"
import {
  Group,
  Panel,
  Separator,
  useDefaultLayout,
} from "react-resizable-panels"

import type { RemoteEdgesView } from "@/lib/generated/remote_edges_view.schema"
import { BREAKPOINT, useMediaQuery } from "@/lib/hooks/use-media-query"
import { cn } from "@/lib/utils"
import type { EndpointDetailView, Icfg } from "@/lib/wadi/api"
import { deriveDataListState, entitySites } from "@/lib/wadi/entity-access"
import type { WorkspacePane } from "@/lib/wadi/routes"
import { sourceSelectionFor } from "@/lib/wadi/source-map"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Skeleton } from "@/components/ui/skeleton"
import { CallTree } from "@/components/explorer/call-tree"
import { DataList } from "@/components/explorer/data-list"
import { FlowCanvas } from "@/components/flow/flow-canvas"
import { EmptyState } from "@/components/shared/empty-state"
import { SourceViewer } from "@/components/source/source-viewer"

import { PaneRail, PaneShell } from "./pane-shell"
import { SelectionStrip } from "./selection-strip"
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

const COLLAPSE_KEY = "wadi-workspace-collapsed"
type PaneId = "tree" | "flow" | "source"

/** The left panel's name follows its mode, so the rail it collapses to never
 * names something other than what it restores. */
function leftPaneLabel(pane: WorkspacePane): string {
  return pane === "data" ? "Data" : "Call tree"
}

const LEFT_MODES: { id: WorkspacePane; label: string }[] = [
  { id: "calls", label: "Calls" },
  { id: "data", label: "Data" },
]

function LeftPaneSwitch({
  pane,
  onPane,
}: {
  pane: WorkspacePane
  onPane: (pane: WorkspacePane) => void
}) {
  return (
    <div
      role="group"
      aria-label="Left panel shows"
      className="flex shrink-0 items-center gap-1 border-b px-2 py-1.5"
    >
      {LEFT_MODES.map(({ id, label }) => (
        <button
          key={id}
          type="button"
          aria-pressed={pane === id}
          onClick={() => onPane(id)}
          className={cn(
            "cursor-pointer rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
            "focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
            pane === id
              ? "bg-muted text-foreground"
              : "text-muted-foreground hover:text-foreground"
          )}
        >
          {label}
        </button>
      ))}
    </div>
  )
}

/** A failed detail read, said as a failure. The flow canvas is drawn with the
 * endpoint's outbound calls and the source viewer is scoped to its service,
 * so both wait on it; neither may fall through to an extraction verdict. */
function DetailFailed({
  error,
  onRetry,
}: {
  error: Error | null
  onRetry: () => void
}) {
  return (
    <div className="space-y-1.5 p-6">
      <p className="text-sm text-muted-foreground">
        Could not load this endpoint
        {error ? ` — ${error.message}` : ""}. Nothing here is a result.
      </p>
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="h-6 px-2 text-2xs"
        onClick={onRetry}
      >
        Retry
      </Button>
    </div>
  )
}

function ResizeHandle() {
  return (
    <Separator className="w-px bg-border transition-colors hover:bg-ring/60 data-[resizing]:bg-ring" />
  )
}

/** Which panes are collapsed, persisted so the choice survives navigation. */
function useCollapsedPanes() {
  const [collapsed, setCollapsed] = useState<ReadonlySet<PaneId>>(new Set())
  // Read after mount: localStorage during render breaks SSR, and a wrong first
  // paint is worse than a one-frame-late restore.
  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(COLLAPSE_KEY)
      if (raw) setCollapsed(new Set(JSON.parse(raw) as PaneId[]))
    } catch {
      /* a corrupt or unavailable store just means "nothing collapsed" */
    }
  }, [])
  const toggle = (id: PaneId, next: boolean) =>
    setCollapsed((current) => {
      const updated = new Set(current)
      if (next) updated.add(id)
      else updated.delete(id)
      try {
        window.localStorage.setItem(COLLAPSE_KEY, JSON.stringify([...updated]))
      } catch {
        /* non-fatal: the panel still collapses, it just won't be remembered */
      }
      return updated
    })
  return { collapsed, toggle }
}

export function WorkspaceInterior({
  detail,
  detailError,
  onRetryDetail,
  icfg,
  icfgLoading,
  icfgError,
}: {
  detail: EndpointDetailView | undefined
  detailError: Error | null
  onRetryDetail: () => void
  icfg: Icfg | undefined
  icfgLoading: boolean
  icfgError: Error | null
}) {
  const storeApi = useWorkspaceStoreApi()
  const sourceTarget = useWorkspaceStore((s) => s.sourceTarget)
  const selectedNodeId = useWorkspaceStore((s) => s.selectedNodeId)
  const pane = useWorkspaceStore((s) => s.pane)
  const selectedEntity = useWorkspaceStore((s) => s.selectedEntity)
  const { collapsed, toggle } = useCollapsedPanes()
  const wide = useMediaQuery(BREAKPOINT.lg)
  const [narrowPane, setNarrowPane] = useState<PaneId>("flow")

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

  // The 1:1 mapping: whatever is selected on the graph or in the tree IS what
  // the source panel highlights, with no "open in source" step between.
  const sourceSelection = useMemo(
    () => sourceSelectionFor(icfg, selectedNodeId),
    [icfg, selectedNodeId]
  )

  const dataState = useMemo(
    () => deriveDataListState({ detail, error: detailError }),
    [detail, detailError]
  )

  const { defaultLayout, onLayoutChanged } = useDefaultLayout({
    id: "wadi-endpoint-workspace-v2",
    onlySaveAfterUserInteractions: true,
    storage: browserLayoutStorage,
  })

  // A failed detail read renders (below) rather than holding the skeleton up
  // forever: the Data list owes the reader its fetch-failed state.
  if ((!detail && !detailError) || (icfgLoading && !icfg)) {
    return (
      <div className="space-y-3 p-6">
        <Skeleton className="h-8 w-96" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }

  const treeBody = (
    <>
      <LeftPaneSwitch
        pane={pane}
        onPane={(next) => storeApi.getState().setPane(next)}
      />
      {pane === "data" ? (
        <ScrollArea className="min-h-0 flex-1">
          <DataList
            state={dataState}
            selectedEntity={selectedEntity}
            sitesOf={(key) => (icfg ? entitySites(icfg, key) : [])}
            flowAvailable={icfg !== undefined}
            onSelectEntity={(key) => storeApi.getState().selectEntity(key)}
            // Selecting the statement is what reveals it: the canvas opens a
            // collapsed method and frames it, and the source panel scrolls.
            onSelectSite={(site) =>
              storeApi.getState().selectNode(`stmt:${site.nodeId}`)
            }
            onRetry={onRetryDetail}
          />
        </ScrollArea>
      ) : icfg ? (
        <ScrollArea className="min-h-0 flex-1">
          <CallTree
            icfg={icfg}
            selectedMethodId={selectedMethodId}
            onSelect={(node) =>
              storeApi.getState().selectNode(`method:${node.methodId}`)
            }
          />
        </ScrollArea>
      ) : (
        <EmptyState>No flow graph — nothing to walk.</EmptyState>
      )}
    </>
  )

  const flowBody = !detail ? (
    <DetailFailed error={detailError} onRetry={onRetryDetail} />
  ) : icfg && remoteEdgesView ? (
    <FlowCanvas icfg={icfg} remoteEdges={remoteEdgesView} />
  ) : icfgError ? (
    // "Not fetched" and "not extracted" are different facts, and only one of
    // them is about the code (P10).
    <EmptyState className="p-6">
      Could not load the flow graph — {icfgError.message}. This says nothing
      about whether one was extracted; retry to find out.
    </EmptyState>
  ) : (
    <EmptyState className="p-6">
      No flow graph was extracted for this endpoint — the handler could not be
      resolved into an ICFG. The coverage report says why.
    </EmptyState>
  )

  const sourceBody = !detail ? (
    <DetailFailed error={detailError} onRetry={onRetryDetail} />
  ) : (
    <>
      {selectedNodeId ? (
        <div className="shrink-0 border-b px-2.5 py-1.5">
          <SelectionStrip
            icfg={icfg}
            detail={detail}
            selectedNodeId={selectedNodeId}
          />
        </div>
      ) : null}
      <SourceViewer
        icfg={icfg}
        snapshotId={detail.snapshot_id}
        serviceId={detail.service_id}
        active
        focus={sourceFocus}
        selection={sourceSelection}
        onJumpNode={(methodId) =>
          storeApi.getState().selectNode(`method:${methodId}`)
        }
        onSelectNode={(icfgNodeId) =>
          storeApi.getState().selectNode(`stmt:${icfgNodeId}`)
        }
      />
    </>
  )

  const body: Record<PaneId, React.ReactNode> = {
    tree: treeBody,
    flow: flowBody,
    source: sourceBody,
  }

  // --- narrow: one pane at a time -------------------------------------------
  if (!wide) {
    return (
      <div className="flex min-h-0 flex-1 flex-col">
        <div
          role="tablist"
          aria-label="Workspace panel"
          className="flex shrink-0 items-center gap-1 border-b px-2 py-1.5"
        >
          {(
            [
              { id: "tree", label: leftPaneLabel(pane) },
              { id: "flow", label: "Flow" },
              { id: "source", label: "Source" },
            ] as const
          ).map(({ id, label }) => (
            <button
              key={id}
              role="tab"
              type="button"
              aria-selected={narrowPane === id}
              onClick={() => setNarrowPane(id)}
              className={cn(
                "cursor-pointer rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
                "focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
                narrowPane === id
                  ? "bg-muted text-foreground"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          {body[narrowPane]}
        </div>
      </div>
    )
  }

  // --- wide: three panels, each collapsible to a rail -----------------------
  return (
    <Group
      orientation="horizontal"
      defaultLayout={defaultLayout}
      onLayoutChanged={onLayoutChanged}
      className="min-h-0 flex-1"
    >
      {collapsed.has("tree") ? (
        <PaneRail
          label={leftPaneLabel(pane)}
          side="left"
          onExpand={() => toggle("tree", false)}
        />
      ) : (
        <>
          <Panel
            defaultSize="18"
            minSize="12"
            className="flex min-h-0 min-w-0 flex-col"
          >
            <PaneShell
              label={leftPaneLabel(pane)}
              side="left"
              onCollapse={() => toggle("tree", true)}
            >
              {treeBody}
            </PaneShell>
          </Panel>
          <ResizeHandle />
        </>
      )}

      {collapsed.has("flow") ? (
        <PaneRail
          label="Flow"
          side="left"
          onExpand={() => toggle("flow", false)}
        />
      ) : (
        <>
          <Panel
            defaultSize="46"
            minSize="24"
            className="flex min-h-0 min-w-0 flex-col"
          >
            <PaneShell
              label="Flow"
              side="left"
              onCollapse={() => toggle("flow", true)}
            >
              {flowBody}
            </PaneShell>
          </Panel>
          <ResizeHandle />
        </>
      )}

      {collapsed.has("source") ? (
        <PaneRail
          label="Source"
          side="right"
          onExpand={() => toggle("source", false)}
        />
      ) : (
        <Panel
          defaultSize="36"
          minSize="20"
          className="flex min-h-0 min-w-0 flex-col"
        >
          <PaneShell
            label="Source"
            side="right"
            onCollapse={() => toggle("source", true)}
          >
            {sourceBody}
          </PaneShell>
        </Panel>
      )}
    </Group>
  )
}
