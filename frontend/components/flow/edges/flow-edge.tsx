"use client"

// The one edge component (§11 Phase 2.8): kind decides route and style, all
// colors come from the flow tokens (no raw hexes), and edge kind is
// triple-encoded — hue + dash pattern + label chip — so color is never
// load-bearing. Routing: intra-method edges step top→bottom inside the lane;
// call edges bow LEFT through the gutter column; remote edges run straight to
// the ghost rail; back edges loop on the lane's RIGHT margin (grouped to one
// side, per the CFG-readability research). Nothing animates.
import { memo } from "react"
import {
  BaseEdge,
  EdgeLabelRenderer,
  getSmoothStepPath,
  type Edge,
  type EdgeProps,
} from "@xyflow/react"

import { cn } from "@/lib/utils"

export interface FlowEdgeDatum extends Record<string, unknown> {
  kind: string
  label: string | null
  back: boolean
  /** Trace overlay: "hot" = on the highlighted path, "dim" = the rest. */
  trace?: "hot" | "dim" | null
}

export type FlowEdgeType = Edge<FlowEdgeDatum, "flow">

function strokeFor(kind: string, back: boolean): string {
  if (back) return "var(--flow-loop)"
  switch (kind) {
    case "true":
      return "var(--flow-true)"
    case "false":
      return "var(--flow-false)"
    case "case":
    case "default":
    case "fallthrough":
      return "var(--flow-case)"
    case "exception":
      return "var(--flow-exception)"
    case "call":
      return "var(--flow-call)"
    case "remote":
      return "var(--flow-remote)"
    default:
      return "color-mix(in oklch, var(--muted-foreground) 45%, transparent)"
  }
}

function dashFor(kind: string, back: boolean): string | undefined {
  if (back) return "3 4"
  if (kind === "remote") return "4 4"
  if (kind === "exception") return "5 3"
  return undefined
}

export const FlowEdge = memo(function FlowEdge({
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
}: EdgeProps<FlowEdgeType>) {
  const kind = data?.kind ?? "flow"
  const back = data?.back ?? false
  const trace = data?.trace ?? null

  let path: string
  let labelX: number
  let labelY: number
  if (kind === "call") {
    // Bow left through the gutter column.
    const bendX = Math.min(sourceX, targetX) - 48
    path = `M ${sourceX},${sourceY} C ${bendX},${sourceY} ${bendX},${targetY} ${targetX},${targetY}`
    labelX = bendX + 12
    labelY = (sourceY + targetY) / 2
  } else if (back) {
    // Loop on the lane's right margin.
    const bendX = Math.max(sourceX, targetX) + 44
    path = `M ${sourceX},${sourceY} C ${bendX},${sourceY} ${bendX},${targetY} ${targetX},${targetY}`
    labelX = bendX - 8
    labelY = (sourceY + targetY) / 2
  } else if (kind === "remote") {
    path = `M ${sourceX},${sourceY} L ${targetX},${targetY}`
    labelX = (sourceX + targetX) / 2
    labelY = (sourceY + targetY) / 2 - 8
  } else {
    const [stepPath, stepLabelX, stepLabelY] = getSmoothStepPath({
      sourceX,
      sourceY,
      targetX,
      targetY,
      sourcePosition,
      targetPosition,
      borderRadius: 6,
    })
    path = stepPath
    labelX = stepLabelX
    labelY = stepLabelY
  }

  const label = data?.label ?? (back ? "↺" : null)

  return (
    <>
      <BaseEdge
        path={path}
        style={{
          stroke: strokeFor(kind, back),
          strokeWidth: trace === "hot" ? 2.25 : 1.25,
          strokeDasharray: dashFor(kind, back),
          opacity: trace === "dim" ? 0.15 : 1,
        }}
      />
      {label ? (
        <EdgeLabelRenderer>
          <span
            className={cn(
              "pointer-events-none absolute rounded-sm border bg-background px-1 font-mono text-2xs leading-3.5 text-muted-foreground",
              trace === "dim" && "opacity-15"
            )}
            style={{
              transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
            }}
          >
            {label}
          </span>
        </EdgeLabelRenderer>
      ) : null}
    </>
  )
})
