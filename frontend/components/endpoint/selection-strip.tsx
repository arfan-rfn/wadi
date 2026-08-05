"use client"

// What the selection MEANS, riding the source panel's header (§5.2.9 UI).
//
// This is where the old Selection tab's facts went when the workspace lost its
// tab strip. They did not just get deleted: the governing condition a call runs
// under and the confidence of an outbound edge appear nowhere else in the UI,
// and dropping them would have quietly cost the map two honesty guarantees.
//
// Putting them here rather than in their own panel is the point — they annotate
// the code you are already reading, one line above it.
import { Split } from "lucide-react"

import type { Icfg } from "@/lib/generated/icfg.schema"
import type { EndpointDetailView } from "@/lib/wadi/api"
import { conditionLabel, governingConditions } from "@/lib/wadi/conditions"
import { shortSignature } from "@/lib/wadi/rollup"
import { cn } from "@/lib/utils"

/** The ICFG node id a workspace selection points at, if any. */
function icfgNodeIdOf(selectedNodeId: string | null): string | null {
  if (!selectedNodeId) return null
  if (selectedNodeId.startsWith("stmt:")) return selectedNodeId.slice(5)
  if (selectedNodeId.startsWith("run:")) return selectedNodeId.slice(4)
  return null
}

export function SelectionStrip({
  icfg,
  detail,
  selectedNodeId,
  className,
}: {
  icfg: Icfg | undefined
  detail: EndpointDetailView | undefined
  selectedNodeId: string | null
  className?: string
}) {
  // Nothing selected: render NOTHING. A permanent "select a node…" line is an
  // instruction that occupies the same space as the answer it is waiting for,
  // on a panel that is already showing the code — the reader does not need to
  // be told the panel exists.
  if (!icfg || !selectedNodeId) return null

  const nodeId = icfgNodeIdOf(selectedNodeId)
  const node = nodeId ? icfg.nodes.find((n) => n.id === nodeId) : null
  const methodId = selectedNodeId.startsWith("method:")
    ? selectedNodeId.slice(7)
    : (node?.method.id ?? null)

  const methodNodes = methodId
    ? icfg.nodes.filter((n) => n.method.id === methodId)
    : []
  const branches = methodNodes.filter((n) => n.kind === "branch").length
  const loops = methodNodes.filter((n) => n.kind === "loop").length

  const signature =
    node?.method_info?.signature ??
    methodNodes[0]?.method_info?.signature ??
    null

  const conditions = nodeId
    ? (governingConditions(icfg).get(nodeId) ?? [])
    : []

  // A selected call node's stitched targets, with the confidence tier that is
  // the whole reason those tiers exist (§5.4).
  const remoteCallIds = new Set(node?.remote_call_ids ?? [])
  const edges = (detail?.outbound ?? []).filter((edge) =>
    remoteCallIds.has(edge.remote_call_id)
  )

  return (
    <div
      className={cn(
        "flex min-w-0 flex-wrap items-center gap-x-2.5 gap-y-1 font-mono text-2xs",
        className
      )}
    >
      <span className="min-w-0 truncate text-foreground" title={signature ?? undefined}>
        {signature ? shortSignature(signature) : "selection"}
      </span>
      {methodNodes.length > 0 ? (
        <span className="shrink-0 text-muted-foreground/75 tabular-nums">
          {methodNodes.length} stmt
          {branches > 0 ? ` · ${branches} br` : ""}
          {loops > 0 ? ` · ${loops} loop` : ""}
        </span>
      ) : null}

      {conditions.map((condition) => (
        <span
          key={conditionLabel(condition)}
          title="Nearest governing branch (§11 heuristic — nearest branch, not full dominance)"
          className="inline-flex max-w-full shrink-0 items-center gap-1 rounded-full border border-amber-500/40 bg-amber-500/5 px-1.5 text-[10px] text-amber-700 dark:text-amber-400"
        >
          <Split aria-hidden className="size-2.5 shrink-0" />
          <span className="truncate">{conditionLabel(condition)}</span>
        </span>
      ))}

      {edges.map((edge) => (
        <span
          key={edge.edge_id}
          className="shrink-0 rounded-full border px-1.5 text-[10px] text-muted-foreground"
          title={edge.evidence ?? undefined}
        >
          → {edge.target_service_name ?? edge.external_host ?? "undetermined"} ·{" "}
          {edge.confidence}
        </span>
      ))}
    </div>
  )
}
