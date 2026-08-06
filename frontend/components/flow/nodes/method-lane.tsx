"use client"

// Method nodes (§11 Phase 2.8): a collapsed method is a summary card — the
// collapsed view alone answers "what does it run, what does it touch". An
// expanded method renders as a LANE: a background container with a header
// carrying the same identity plus collapse/focus controls; its statements
// live inside as separate nodes.
import { memo } from "react"
import type { Node, NodeProps } from "@xyflow/react"
import {
  ChevronDown,
  ChevronRight,
  Crosshair,
  Database,
  Globe,
  MailWarning,
} from "lucide-react"

import { cn } from "@/lib/utils"
import { NODE_BOX } from "@/lib/wadi/flow-lanes"
import { shortSignature } from "@/lib/wadi/rollup"
import { useWorkspaceStore } from "@/components/endpoint/workspace-store"

import { NodeShell, useFlowActions } from "../flow-chrome"

const SINK_ICON: Record<string, typeof Database> = {
  db: Database,
  "http-client": Globe,
  "http-client-suspected": Globe,
  mq: MailWarning,
}

export interface MethodNodeDatum extends Record<string, unknown> {
  methodId: string
  signature: string
  isRoot: boolean
  statementCount: number
  branchCount: number
  loopCount: number
  sinks: string[]
  badges: string[]
  trace?: "hot" | "dim" | null
}

export type MethodNodeType = Node<MethodNodeDatum, "method">

export const MethodNode = memo(function MethodNode({
  id,
  data,
}: NodeProps<MethodNodeType>) {
  const actions = useFlowActions()
  return (
    <NodeShell
      id={id}
      trace={data.trace}
      onClick={() => actions.selectNode(id)}
      style={{ width: NODE_BOX.method.width }}
      className={cn(
        "flex h-[72px] flex-col justify-center gap-1 px-3",
        data.isRoot && "border-primary/50"
      )}
    >
      <div className="flex items-center gap-1.5">
        <button
          className="shrink-0 rounded-sm p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
          title="Expand into statements"
          onClick={(event) => {
            event.stopPropagation()
            actions.toggleMethod(data.methodId)
          }}
        >
          <ChevronRight className="size-3.5" aria-hidden />
        </button>
        <span className="truncate font-mono text-xs font-medium">
          {shortSignature(data.signature)}
        </span>
        {data.isRoot ? (
          <span className="shrink-0 rounded-full bg-primary/10 px-1.5 text-2xs font-semibold uppercase tracking-wider text-primary">
            handler
          </span>
        ) : null}
      </div>
      <div className="flex items-center gap-2 pl-6 text-2xs text-muted-foreground [.zoom-simplified_&]:hidden">
        <span>
          {data.statementCount} stmt · {data.branchCount} br · {data.loopCount}{" "}
          loop
        </span>
        {data.sinks.map((sink) => {
          const Icon = SINK_ICON[sink]
          return Icon ? (
            <Icon
              key={sink}
              className="size-3 text-muted-foreground"
              aria-label={sink}
            />
          ) : null
        })}
      </div>
    </NodeShell>
  )
})

export interface LaneNodeDatum extends Record<string, unknown> {
  methodId: string
  signature: string
  isRoot: boolean
  width: number
  height: number
}

export type LaneNodeType = Node<LaneNodeDatum, "lane">

/** The expanded-method container: header + bounds; statements render above
 * it as independent nodes.
 *
 * A lane carries its own SELECTED state. The ring in NodeShell keys on a
 * canvas node id, and an expanded method draws no card to hold one — so
 * selecting a method from the call tree or a call link inside source used to
 * change the URL and highlight the source region while the canvas showed
 * nothing. Same rule as everywhere else on this surface: a selection must be
 * visible. */
export const LaneNode = memo(function LaneNode({
  data,
}: NodeProps<LaneNodeType>) {
  const actions = useFlowActions()
  // A boolean selector, so a selection change elsewhere re-renders only the
  // lane whose selectedness actually flipped.
  const selected = useWorkspaceStore(
    (s) => s.selectedNodeId === `method:${data.methodId}`
  )
  return (
    <div
      className={cn(
        "pointer-events-none rounded-lg border border-dashed bg-muted/20",
        data.isRoot && "border-primary/40",
        // `ring` is the canvas's selection colour (NodeShell uses it for
        // cards); `primary` stays the handler's, so the two never blur.
        selected && "border-solid border-ring bg-ring/[0.04]"
      )}
      style={{ width: data.width, height: data.height }}
    >
      {/* The header is the lane's clickable body: clicking it selects the
          method, mirroring a click on the collapsed card it replaces. */}
      <div
        role="button"
        tabIndex={-1}
        aria-current={selected ? "true" : undefined}
        onClick={() => actions.selectNode(`method:${data.methodId}`)}
        className={cn(
          "pointer-events-auto flex h-9 cursor-pointer items-center gap-1.5 border-b border-dashed px-2.5",
          selected && "border-solid border-ring/50 bg-ring/10"
        )}
      >
        <button
          className="shrink-0 rounded-sm p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
          title="Collapse to a method card"
          onClick={(event) => {
            // The header selects; the buttons do their own thing. Both firing
            // would select a method and immediately collapse it away.
            event.stopPropagation()
            actions.toggleMethod(data.methodId)
          }}
        >
          <ChevronDown className="size-3.5" aria-hidden />
        </button>
        <span className="truncate font-mono text-xs font-medium">
          {shortSignature(data.signature)}
        </span>
        {data.isRoot ? (
          <span className="shrink-0 rounded-full bg-primary/10 px-1.5 text-2xs font-semibold uppercase tracking-wider text-primary">
            handler
          </span>
        ) : null}
        <button
          className="ml-auto shrink-0 rounded-sm p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
          title="Focus on this method and its callees"
          onClick={(event) => {
            event.stopPropagation()
            actions.focusMethod(data.methodId)
          }}
        >
          <Crosshair className="size-3.5" aria-hidden />
        </button>
      </div>
    </div>
  )
})
