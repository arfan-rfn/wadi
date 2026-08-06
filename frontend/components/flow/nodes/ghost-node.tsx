"use client"

// Ghost rail cards (§11 Phase 2.8): the lifted "who does it talk to" —
// analyzed services, external hosts, and the honest unknowns. Placeholder /
// undetermined targets are the ONLY destructive-toned element on the canvas
// and are never hidden by collapse or condensation (P10). Verb chips reuse
// the method-chip visual (the one saturated element).
import { memo } from "react"
import type { Node, NodeProps } from "@xyflow/react"
import { Globe, HelpCircle, Server } from "lucide-react"

import { cn } from "@/lib/utils"
import type { GoverningCondition } from "@/lib/wadi/conditions"
import { conditionLabel } from "@/lib/wadi/conditions"

import { NODE_BOX } from "@/lib/wadi/flow-lanes"

import { NodeShell, useFlowActions } from "../flow-chrome"

export interface GhostNodeDatum extends Record<string, unknown> {
  label: string
  targetKind: string
  confidence: string | null
  verbs: string[]
  conditions: GoverningCondition[]
  trace?: "hot" | "dim" | null
}

export type GhostNodeType = Node<GhostNodeDatum, "ghost">

export const GhostNode = memo(function GhostNode({
  id,
  data,
}: NodeProps<GhostNodeType>) {
  const actions = useFlowActions()
  const unknown =
    data.targetKind === "undetermined" || data.targetKind === "placeholder"
  const Icon = unknown
    ? HelpCircle
    : data.targetKind === "external"
      ? Globe
      : Server
  return (
    <NodeShell
      id={id}
      trace={data.trace}
      onClick={() => actions.selectNode(id)}
      style={{ width: NODE_BOX.ghost.width }}
      className={cn(
        "flex min-h-[44px] flex-col justify-center gap-0.5 px-2.5 py-1",
        unknown && "border-dashed border-destructive/60"
      )}
    >
      <div className="flex items-center gap-1.5">
        <Icon
          className={cn(
            "size-3.5 shrink-0",
            unknown ? "text-destructive" : "text-muted-foreground"
          )}
          aria-hidden
        />
        <span
          className={cn(
            "truncate font-mono text-2xs font-medium",
            unknown && "text-destructive"
          )}
        >
          {data.label}
        </span>
        {data.verbs.map((verb) => (
          <span
            key={verb}
            className="shrink-0 rounded-sm bg-muted px-1 font-mono text-2xs font-semibold text-muted-foreground"
          >
            {verb}
          </span>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-1 pl-5 text-2xs text-muted-foreground [.zoom-simplified_&]:hidden">
        <span>
          {data.targetKind}
          {data.confidence ? ` · ${data.confidence}` : ""}
        </span>
        {data.conditions.map((condition) => (
          <span
            key={conditionLabel(condition)}
            title={`Nearest governing branch (heuristic): ${conditionLabel(condition)}`}
            className="inline-flex max-w-full items-center truncate rounded-full border border-warn/40 bg-warn/5 px-1.5 leading-3.5 text-warn"
          >
            {conditionLabel(condition)}
          </span>
        ))}
      </div>
    </NodeShell>
  )
})
