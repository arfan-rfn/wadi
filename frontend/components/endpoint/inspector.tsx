"use client"

// The tabbed inspector (§11 Phase 2.8): dense per-selection detail and the
// endpoint's own contract data live in TABS, not a stacked scroll (the
// Datadog span-panel pattern). Selection = what the selected node means;
// Endpoint = auth/params/shapes/outbound (the old Overview tab, kept next to
// the graph where its evidence belongs).
import type { Icfg } from "@/lib/generated/icfg.schema"
import type { RemoteEdgesView } from "@/lib/generated/remote_edges_view.schema"
import { cn } from "@/lib/utils"
import type { EndpointDetailView } from "@/lib/wadi/api"
import { INSPECTOR_TABS, type InspectorTab } from "@/lib/wadi/routes"
import { EndpointOverview } from "@/components/explorer/endpoint-overview"

import { InspectorSelection } from "./inspector-selection"
import { useWorkspaceStore, useWorkspaceStoreApi } from "./workspace-store"

const TAB_LABELS: Record<InspectorTab, string> = {
  source: "Source",
  selection: "Selection",
  endpoint: "Endpoint",
}

export function Inspector({
  detail,
  icfg,
  source,
}: {
  detail: EndpointDetailView
  icfg: Icfg | undefined
  /** The Source tab's content — rendered by the workspace, which owns the
   * graph↔source wiring, and mounted here so it shares the panel. Null when
   * the centre lens is already showing source: one viewer, one scroll
   * position, and no tab that duplicates what is on screen. */
  source: React.ReactNode | null
}) {
  const storeApi = useWorkspaceStoreApi()
  const requestedTab = useWorkspaceStore((s) => s.inspectorTab)
  const tabs = source
    ? INSPECTOR_TABS
    : INSPECTOR_TABS.filter((id) => id !== "source")
  const tab = requestedTab === "source" && !source ? "selection" : requestedTab
  const remoteEdgesView: RemoteEdgesView = {
    service_id: detail.service_id,
    outbound: detail.outbound ?? [],
    inbound: [],
  }
  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col">
      <div
        role="tablist"
        aria-label="Inspector"
        className="flex shrink-0 items-center gap-1 border-b px-2 py-1.5"
      >
        {tabs.map((id) => (
          <button
            key={id}
            role="tab"
            aria-selected={tab === id}
            onClick={() => storeApi.getState().setInspectorTab(id)}
            className={cn(
              "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
              tab === id
                ? "bg-muted text-foreground"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            {TAB_LABELS[id]}
          </button>
        ))}
      </div>
      {/* Source owns its own scroller (one shared virtualized column), so it
          is mounted OUTSIDE the tab body's overflow container. */}
      <div
        className={cn(
          "min-h-0 min-w-0 flex-1",
          tab === "source" ? "flex" : "hidden"
        )}
      >
        {source}
      </div>
      <div
        className={cn(
          "min-h-0 min-w-0 flex-1 overflow-x-hidden overflow-y-auto",
          tab === "source" && "hidden"
        )}
      >
        {tab === "selection" ? (
          <InspectorSelection icfg={icfg} detail={detail} />
        ) : tab === "endpoint" ? (
          <div className="p-3">
            <EndpointOverview
              endpoint={detail.endpoint}
              icfg={icfg}
              remoteEdges={remoteEdgesView}
              edgesLoading={false}
              snapshotId={detail.snapshot_id}
              serviceId={detail.service_id}
              unopenableCalls={detail.unopenable_calls ?? []}
            />
          </div>
        ) : null}
      </div>
    </div>
  )
}
