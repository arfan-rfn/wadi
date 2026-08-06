"use client"

// Statement cards (§11 Phase 2.8): real code as the label (line number +
// source text), construct accent on tokens, sink icon, governing-condition
// chips on remote-call sites. No branch diamonds — a branch is a card whose
// OUT-edges carry the true/false labels; the condition text lives here.
import { memo } from "react"
import type { Node, NodeProps } from "@xyflow/react"
import {
  CircleAlert,
  Database,
  Globe,
  MailWarning,
  Repeat2,
  Split,
} from "lucide-react"

import { cn } from "@/lib/utils"
import type { GoverningCondition } from "@/lib/wadi/conditions"
import { conditionLabel } from "@/lib/wadi/conditions"
import { NODE_BOX } from "@/lib/wadi/flow-lanes"
import { unopenableCopy } from "@/lib/wadi/unopenable"

import { NodeShell, useFlowActions } from "../flow-chrome"

const SINK_ICON: Record<string, typeof Database> = {
  db: Database,
  "http-client": Globe,
  "http-client-suspected": Globe,
  mq: MailWarning,
}

/** Construct accent (left border) via flow tokens. */
function accentFor(kind: string, constructKind: string | null): string | null {
  if (
    kind === "branch" ||
    constructKind === "switch" ||
    constructKind === "switch-arrow"
  )
    return "var(--flow-case)"
  if (kind === "loop") return "var(--flow-loop)"
  if (
    constructKind &&
    ["try", "catch", "finally", "throw"].includes(constructKind)
  )
    return "var(--flow-exception)"
  return null
}

export interface StatementNodeDatum extends Record<string, unknown> {
  icfgNodeId: string
  methodId: string
  sourceText: string
  file: string
  line: number
  kind: string
  constructKind: string | null
  conditionExpression: string | null
  sink: string | null
  /** Why this call has no interior to open (§5.4.2 T5), or null when it opens. */
  unopenableReason: string | null
  /** Arms on which control leaves the method entirely (§5.2.8 T3). */
  exitArms: string[]
  hasRemote: boolean
  conditions: GoverningCondition[]
  trace?: "hot" | "dim" | null
}

export type StatementNodeType = Node<StatementNodeDatum, "statement">

export const StatementNode = memo(function StatementNode({
  id,
  data,
}: NodeProps<StatementNodeType>) {
  const actions = useFlowActions()
  const accent = accentFor(data.kind, data.constructKind)
  const SinkIcon = data.sink ? SINK_ICON[data.sink] : null
  const isBranch = data.kind === "branch" || data.conditionExpression !== null
  const unopenable = unopenableCopy(data.unopenableReason)
  return (
    <NodeShell
      id={id}
      trace={data.trace}
      onClick={() => actions.selectNode(id)}
      style={{ width: NODE_BOX.statement.width }}
      className="flex min-h-[44px] flex-col justify-center gap-0.5 px-2.5 py-1.5"
    >
      {accent ? (
        <span
          aria-hidden
          className="absolute inset-y-0 left-0 w-[3px] rounded-l-md"
          style={{ background: accent }}
        />
      ) : null}
      <div className="flex items-center gap-1.5">
        <button
          className="shrink-0 font-mono text-2xs text-subtle-foreground hover:text-foreground"
          title={`Open ${data.file}:${data.line} in source`}
          onClick={(event) => {
            event.stopPropagation()
            actions.revealSource(data.file, data.line)
          }}
        >
          {data.line}
        </button>
        {isBranch ? (
          <Split
            className="size-3 shrink-0 text-muted-foreground"
            aria-label="branch"
          />
        ) : null}
        {data.kind === "loop" ? (
          <Repeat2
            className="size-3 shrink-0 text-muted-foreground"
            aria-label="loop"
          />
        ) : null}
        {data.constructKind === "throw" ? (
          <CircleAlert
            className="size-3 shrink-0 text-muted-foreground"
            aria-label="throw"
          />
        ) : null}
        <code className="min-w-0 flex-1 truncate font-mono text-2xs">
          {data.sourceText.trim()}
        </code>
        {unopenable ? (
          // The call runs, but there is no body to open. Saying so on the node
          // is the difference between "generated code" and what reads as a
          // hole in the map (§5.4.2 T5).
          <span
            className="shrink-0 rounded-sm border border-dashed border-muted-foreground/40 px-1 text-2xs uppercase tracking-wide text-muted-foreground [.zoom-simplified_&]:hidden"
            title={unopenable.detail}
          >
            {unopenable.badge}
          </span>
        ) : null}
        {SinkIcon ? (
          <SinkIcon
            className={cn(
              "size-3 shrink-0",
              data.hasRemote ? "text-flow-remote" : "text-muted-foreground"
            )}
            aria-label={data.sink ?? undefined}
          />
        ) : null}
      </div>
      {data.exitArms.length > 0 ? (
        // §5.2.8 T3: the arm the reader would otherwise have to infer from an
        // absence. The canvas draws lanes, not exit nodes, so the labeled edge
        // into the method's exit is stated here instead of vanishing.
        <div className="flex flex-wrap gap-1 pl-4 [.zoom-simplified_&]:hidden">
          {data.exitArms.map((arm) => (
            <span
              key={arm}
              title={`On ${arm}, control leaves this method`}
              className="inline-flex items-center gap-0.5 rounded-full border px-1.5 text-2xs leading-3.5 text-muted-foreground"
            >
              {arm} → returns
            </span>
          ))}
        </div>
      ) : null}
      {data.conditions.length > 0 ? (
        <div className="flex flex-wrap gap-1 pl-4 [.zoom-simplified_&]:hidden">
          {data.conditions.map((condition) => (
            <span
              key={conditionLabel(condition)}
              title={`Nearest governing branch (heuristic): ${conditionLabel(condition)}`}
              className="inline-flex max-w-full items-center gap-0.5 truncate rounded-full border border-warn/40 bg-warn/5 px-1.5 text-2xs leading-3.5 text-warn"
            >
              {conditionLabel(condition)}
            </span>
          ))}
        </div>
      ) : null}
    </NodeShell>
  )
})
