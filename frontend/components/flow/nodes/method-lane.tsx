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
import { shortSignature } from "@/lib/wadi/rollup"

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
      className={cn(
        "flex h-[72px] w-[240px] flex-col justify-center gap-1 px-3",
        data.isRoot && "border-primary/50"
      )}
    >
      <div className="flex items-center gap-1.5">
        <button
          className="shrink-0 rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
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
          <span className="shrink-0 rounded-full bg-primary/10 px-1.5 text-[9px] font-semibold uppercase tracking-wider text-primary">
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
 * it as independent nodes. */
export const LaneNode = memo(function LaneNode({
  data,
}: NodeProps<LaneNodeType>) {
  const actions = useFlowActions()
  return (
    <div
      className={cn(
        "pointer-events-none rounded-lg border border-dashed bg-muted/20",
        data.isRoot && "border-primary/40"
      )}
      style={{ width: data.width, height: data.height }}
    >
      <div className="pointer-events-auto flex h-9 items-center gap-1.5 border-b border-dashed px-2.5">
        <button
          className="shrink-0 rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
          title="Collapse to a method card"
          onClick={() => actions.toggleMethod(data.methodId)}
        >
          <ChevronDown className="size-3.5" aria-hidden />
        </button>
        <span className="truncate font-mono text-xs font-medium">
          {shortSignature(data.signature)}
        </span>
        {data.isRoot ? (
          <span className="shrink-0 rounded-full bg-primary/10 px-1.5 text-[9px] font-semibold uppercase tracking-wider text-primary">
            handler
          </span>
        ) : null}
        <button
          className="ml-auto shrink-0 rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
          title="Focus on this method and its callees"
          onClick={() => actions.focusMethod(data.methodId)}
        >
          <Crosshair className="size-3.5" aria-hidden />
        </button>
      </div>
    </div>
  )
})
