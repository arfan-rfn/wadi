"use client"

// Condensed runs (§11 Phase 2.8): a maximal linear run of plain statements as
// one small expandable node — condensation never hides branch/loop/call/sink
// or condition-carrying nodes (that guarantee lives in buildFlowGraph).
import { memo } from "react"
import type { Node, NodeProps } from "@xyflow/react"
import { UnfoldVertical } from "lucide-react"

import { NodeShell, useFlowActions } from "../flow-chrome"

export interface CondensedNodeDatum extends Record<string, unknown> {
  runId: string
  methodId: string
  count: number
  file: string
  startLine: number
  endLine: number
  trace?: "hot" | "dim" | null
}

export type CondensedNodeType = Node<CondensedNodeDatum, "condensed">

export const CondensedNode = memo(function CondensedNode({
  id,
  data,
}: NodeProps<CondensedNodeType>) {
  const actions = useFlowActions()
  return (
    <NodeShell
      id={id}
      trace={data.trace}
      onClick={() => actions.expandRun(data.runId)}
      className="flex h-8 w-[150px] items-center justify-center gap-1 border-dashed bg-muted/40 text-muted-foreground"
    >
      <UnfoldVertical className="size-3" aria-hidden />
      <span className="font-mono text-[10px]">
        {data.count} statements · {data.startLine}–{data.endLine}
      </span>
    </NodeShell>
  )
})
