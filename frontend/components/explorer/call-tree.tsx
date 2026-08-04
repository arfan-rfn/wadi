"use client"

// The call-tree rail (§11 Phase 2.7 M2): the handler at the root, callees
// nested at their call sites, recursion as a cycle chip. Clicking a method
// selects it across the Flow workspace (source pane scrolls to it; the
// canvas focuses it in M3). LangSmith-trace-tree pattern from the recorded
// research: indentation + chevrons + per-row badges, calm palette.
import { useMemo, useState } from "react"
import {
  ChevronDown,
  ChevronRight,
  CornerDownRight,
  Database,
  Globe,
  MailWarning,
  RefreshCw,
} from "lucide-react"

import { cn } from "@/lib/utils"
import type { Icfg } from "@/lib/wadi/api"
import { buildCallTree, type CallTreeNode } from "@/lib/wadi/call-tree"
import { shortSignature } from "@/lib/wadi/rollup"

const SINK_ICON: Record<string, typeof Database> = {
  db: Database,
  "http-client": Globe,
  "http-client-suspected": Globe,
  mq: MailWarning,
}

const DEFAULT_EXPAND_DEPTH = 3

export function CallTree({
  icfg,
  selectedMethodId,
  onSelect,
}: {
  icfg: Icfg
  selectedMethodId: string | null
  onSelect: (node: CallTreeNode) => void
}) {
  const root = useMemo(() => buildCallTree(icfg), [icfg])
  if (!root) {
    return (
      <p className="p-3 text-xs text-muted-foreground">
        No call tree — the flow has no resolvable entry.
      </p>
    )
  }
  return (
    // No scroller here — the rail that mounts this owns the one scroll
    // container; a second one nested inside it traps the wheel.
    <div className="py-1">
      <TreeRow
        node={root}
        depth={0}
        selectedMethodId={selectedMethodId}
        onSelect={onSelect}
      />
    </div>
  )
}

function TreeRow({
  node,
  depth,
  selectedMethodId,
  onSelect,
}: {
  node: CallTreeNode
  depth: number
  selectedMethodId: string | null
  onSelect: (node: CallTreeNode) => void
}) {
  const [open, setOpen] = useState(depth < DEFAULT_EXPAND_DEPTH)
  const hasChildren = node.children.length > 0
  const sinks = node.rollup?.sinks ?? []
  const constructs = node.rollup?.constructCounts ?? {}
  const constructSummary = Object.entries(constructs)
    .slice(0, 3)
    .map(([construct, count]) =>
      count > 1 ? `${construct}×${count}` : construct
    )

  return (
    <div>
      <div
        className={cn(
          "group flex items-center gap-1 py-0.5 pr-2 transition-colors hover:bg-muted/50",
          selectedMethodId === node.methodId && "bg-muted/70"
        )}
        style={{ paddingLeft: 8 + depth * 14 }}
      >
        {hasChildren ? (
          <button
            onClick={() => setOpen((prev) => !prev)}
            aria-label={open ? "Collapse" : "Expand"}
            className="shrink-0 text-muted-foreground/60 hover:text-foreground"
          >
            {open ? (
              <ChevronDown className="size-3" />
            ) : (
              <ChevronRight className="size-3" />
            )}
          </button>
        ) : (
          <span className="w-3 shrink-0" />
        )}
        <button
          onClick={() => onSelect(node)}
          className="flex min-w-0 flex-1 items-center gap-1.5 text-left"
          title={node.signature}
        >
          {depth > 0 ? (
            <CornerDownRight className="size-2.5 shrink-0 text-muted-foreground/50" />
          ) : null}
          <span
            className={cn(
              "truncate font-mono text-[11px]",
              depth === 0
                ? "font-semibold"
                : "text-muted-foreground group-hover:text-foreground"
            )}
          >
            {shortSignature(node.signature)}
          </span>
          {node.cycle ? (
            <span
              className="inline-flex shrink-0 items-center gap-0.5 rounded border px-1 text-[9px] uppercase text-muted-foreground"
              title="Recursion: re-enters a method already on this path"
            >
              <RefreshCw className="size-2" /> cycle
            </span>
          ) : null}
          {sinks.map((sink) => {
            const Icon = SINK_ICON[sink]
            return Icon ? (
              <Icon key={sink} className="size-2.5 shrink-0 text-red-500/70" />
            ) : null
          })}
          {constructSummary.length > 0 ? (
            <span className="hidden shrink-0 font-mono text-[9px] text-muted-foreground/60 xl:inline">
              {constructSummary.join(" ")}
            </span>
          ) : null}
        </button>
      </div>
      {open && hasChildren ? (
        <div>
          {node.children.map((child, index) => (
            <TreeRow
              key={`${child.methodId}-${child.callSiteLine}-${index}`}
              node={child}
              depth={depth + 1}
              selectedMethodId={selectedMethodId}
              onSelect={onSelect}
            />
          ))}
        </div>
      ) : null}
    </div>
  )
}
