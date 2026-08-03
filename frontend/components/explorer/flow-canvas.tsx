"use client"

// The flow canvas (§11 Phase 2.7 M3): semantic zoom over the ICFG.
// Level 0 — method cards + call edges, with remote/DB/MQ targets lifted up
// as ghost stubs. Level 1 — a method expands in place into its statement
// subgraph (labeled true/false/case/fallthrough/exception edges, back
// flags); linear runs condense into "n statements" nodes. n8n/Tines canvas
// pattern from the recorded research; nodes are shadcn-styled cards.
import { useCallback, useEffect, useMemo, useState } from "react"
import {
  Background,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react"
import {
  ChevronsUpDown,
  CircleDot,
  Database,
  Globe,
  HelpCircle,
  MailWarning,
  Minimize2,
  Repeat,
  Split,
} from "lucide-react"
import { useTheme } from "next-themes"

import "@xyflow/react/dist/style.css"

import { cn } from "@/lib/utils"
import type { Icfg, RemoteEdgesView } from "@/lib/wadi/api"
import { layoutFlowGraph, nodeSize } from "@/lib/wadi/elk-layout"
import {
  buildFlowGraph,
  type FlowGraphNode,
  type FlowNodeCondensed,
  type FlowNodeGhost,
  type FlowNodeMethod,
  type FlowNodeStatement,
} from "@/lib/wadi/flow-graph"
import { shortSignature } from "@/lib/wadi/rollup"

const SINK_ICON: Record<string, typeof Database> = {
  db: Database,
  "http-client": Globe,
  "http-client-suspected": Globe,
  mq: MailWarning,
}

/** Above this many methods the canvas stays collapsed-only by default. */
const NODE_BUDGET = 150

interface MethodData {
  node: FlowNodeMethod
  selected: boolean
  onSelect: () => void
  onToggle: () => void
  [key: string]: unknown
}

interface StatementData {
  node: FlowNodeStatement
  onSelect: () => void
  [key: string]: unknown
}

interface CondensedData {
  node: FlowNodeCondensed
  onExpand: () => void
  [key: string]: unknown
}

interface GhostData {
  node: FlowNodeGhost
  [key: string]: unknown
}

function NodeShell({
  className,
  children,
}: {
  className?: string
  children: React.ReactNode
}) {
  return (
    <div
      className={cn(
        "rounded-md border bg-card text-card-foreground",
        className
      )}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="!bg-muted-foreground/40"
      />
      {children}
      <Handle
        type="source"
        position={Position.Bottom}
        className="!bg-muted-foreground/40"
      />
    </div>
  )
}

function MethodNode({ data }: NodeProps<Node<MethodData>>) {
  const { node, selected, onSelect, onToggle } = data
  const rollup = node.rollup
  const constructs = Object.entries(rollup.constructCounts).slice(0, 4)
  return (
    <NodeShell
      className={cn(
        "w-[240px] px-2.5 py-1.5 shadow-sm",
        node.isRoot && "border-primary/60",
        selected && "ring-2 ring-primary/50"
      )}
    >
      <div className="flex items-center gap-1.5">
        <button
          onClick={onSelect}
          className="min-w-0 flex-1 truncate text-left font-mono text-[11px] font-medium"
          title={rollup.signature}
        >
          {node.isRoot ? (
            <span className="mr-1 text-[9px] font-semibold uppercase text-primary">
              handler
            </span>
          ) : null}
          {shortSignature(rollup.signature)}
        </button>
        {rollup.sinks.map((sink) => {
          const Icon = SINK_ICON[sink]
          return Icon ? (
            <Icon key={sink} className="size-3 shrink-0 text-red-500/80" />
          ) : null
        })}
        <button
          onClick={onToggle}
          title="Expand into statements"
          className="shrink-0 text-muted-foreground/60 hover:text-foreground"
        >
          <ChevronsUpDown className="size-3" />
        </button>
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-1 font-mono text-[9px] text-muted-foreground">
        <span>
          {rollup.statementCount}s · {rollup.branchCount}b · {rollup.loopCount}l
          · {rollup.callCount}c
        </span>
        {constructs.map(([construct, count]) => (
          <span key={construct} className="rounded border px-1">
            {construct}
            {count > 1 ? `×${count}` : ""}
          </span>
        ))}
      </div>
    </NodeShell>
  )
}

const CONSTRUCT_STYLE: Record<string, string> = {
  if: "border-l-amber-500",
  switch: "border-l-amber-500",
  "switch-arrow": "border-l-amber-500",
  for: "border-l-sky-500",
  foreach: "border-l-sky-500",
  while: "border-l-sky-500",
  "do-while": "border-l-sky-500",
  try: "border-l-violet-500",
  catch: "border-l-violet-500",
  finally: "border-l-violet-500",
  throw: "border-l-rose-500",
  break: "border-l-rose-400",
  continue: "border-l-rose-400",
}

function StatementNode({ data }: NodeProps<Node<StatementData>>) {
  const { node, onSelect } = data
  const icfgNode = node.icfgNode
  const construct = icfgNode.construct_kind
  const isBranch = icfgNode.kind === "branch"
  const isLoop = icfgNode.kind === "loop"
  const sink = icfgNode.sink
  const SinkIcon = sink ? SINK_ICON[sink] : null
  return (
    <NodeShell
      className={cn(
        "w-[220px] border-l-4 px-2 py-1",
        CONSTRUCT_STYLE[construct ?? ""] ?? "border-l-transparent"
      )}
    >
      <button
        onClick={onSelect}
        className="flex w-full min-w-0 items-center gap-1.5 text-left"
        title={
          icfgNode.condition?.expression
            ? `${construct ?? icfgNode.kind}: ${icfgNode.condition.expression}`
            : icfgNode.source_text
        }
      >
        {isBranch ? (
          <Split className="size-3 shrink-0 text-amber-500" />
        ) : isLoop ? (
          <Repeat className="size-3 shrink-0 text-sky-500" />
        ) : (
          <CircleDot className="size-2.5 shrink-0 text-muted-foreground/50" />
        )}
        <span className="min-w-0 flex-1 truncate font-mono text-[10px]">
          {icfgNode.condition?.expression ?? icfgNode.source_text}
        </span>
        {construct ? (
          <span className="shrink-0 rounded border px-1 font-mono text-[8px] uppercase text-muted-foreground">
            {construct}
          </span>
        ) : null}
        {SinkIcon ? (
          <SinkIcon className="size-3 shrink-0 text-red-500/80" />
        ) : null}
      </button>
    </NodeShell>
  )
}

function CondensedNode({ data }: NodeProps<Node<CondensedData>>) {
  const { node, onExpand } = data
  return (
    <NodeShell className="w-[150px] border-dashed px-2 py-1">
      <button
        onClick={onExpand}
        className="flex w-full items-center justify-center gap-1 font-mono text-[10px] text-muted-foreground hover:text-foreground"
        title={`Lines ${node.startLine}–${node.endLine} — click to expand`}
      >
        <Minimize2 className="size-2.5" />
        {node.count} statements
      </button>
    </NodeShell>
  )
}

const GHOST_STYLE: Record<string, string> = {
  analyzed: "border-primary/50 text-foreground",
  external: "border-muted-foreground/50 text-muted-foreground",
  placeholder: "border-dashed border-muted-foreground/60 text-muted-foreground",
  undetermined: "border-dashed border-destructive/50 text-destructive",
}

function GhostNode({ data }: NodeProps<Node<GhostData>>) {
  const { node } = data
  return (
    <div
      className={cn(
        "w-[180px] rounded-md border bg-background/60 px-2 py-1.5",
        GHOST_STYLE[node.targetKind] ?? GHOST_STYLE.undetermined
      )}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="!bg-muted-foreground/40"
      />
      <div className="flex items-center gap-1.5">
        {node.targetKind === "undetermined" ? (
          <HelpCircle className="size-3 shrink-0" />
        ) : (
          <Globe className="size-3 shrink-0" />
        )}
        <span className="min-w-0 flex-1 truncate font-mono text-[10px]">
          {node.label}
        </span>
        {node.confidence ? (
          <span className="shrink-0 font-mono text-[8px] uppercase opacity-70">
            {node.confidence}
          </span>
        ) : null}
      </div>
    </div>
  )
}

const NODE_TYPES = {
  method: MethodNode,
  statement: StatementNode,
  condensed: CondensedNode,
  ghost: GhostNode,
}

const EDGE_STYLE: Record<string, { stroke?: string; dash?: string }> = {
  true: { stroke: "#10b981" },
  false: { stroke: "#f43f5e" },
  case: { stroke: "#f59e0b" },
  default: { stroke: "#f59e0b", dash: "4 3" },
  fallthrough: { stroke: "#f59e0b", dash: "2 3" },
  exception: { stroke: "#8b5cf6", dash: "5 3" },
  call: { stroke: "#64748b" },
  remote: { stroke: "#ef4444", dash: "6 3" },
}

export function FlowCanvas({
  icfg,
  remoteEdges,
  selectedMethodId,
  onSelectMethod,
  onFocusSource,
}: {
  icfg: Icfg
  remoteEdges: RemoteEdgesView | undefined
  selectedMethodId: string | null
  onSelectMethod: (methodId: string | null) => void
  onFocusSource: (file: string, line: number) => void
}) {
  const { resolvedTheme } = useTheme()
  const [expandedMethods, setExpandedMethods] = useState<ReadonlySet<string>>(
    new Set()
  )
  const [expandedRuns, setExpandedRuns] = useState<ReadonlySet<string>>(
    new Set()
  )
  const [rfNodes, setRfNodes] = useState<Node[]>([])
  const [rfEdges, setRfEdges] = useState<Edge[]>([])

  const graph = useMemo(
    () => buildFlowGraph(icfg, remoteEdges, expandedMethods, expandedRuns),
    [icfg, remoteEdges, expandedMethods, expandedRuns]
  )
  const overBudget = graph.nodes.length > NODE_BUDGET

  const toggleMethod = useCallback((methodId: string) => {
    setExpandedMethods((prev) => {
      const next = new Set(prev)
      if (next.has(methodId)) next.delete(methodId)
      else next.add(methodId)
      return next
    })
  }, [])

  const expandRun = useCallback((runId: string) => {
    setExpandedRuns((prev) => new Set(prev).add(runId))
  }, [])

  useEffect(() => {
    let cancelled = false
    void layoutFlowGraph(graph).then((positions) => {
      if (cancelled) return
      const toRfNode = (node: FlowGraphNode): Node => {
        const position = positions.get(node.id)
        const size = nodeSize(node)
        const base = {
          id: node.id,
          position: { x: position?.x ?? 0, y: position?.y ?? 0 },
          width: size.width,
          height: size.height,
          draggable: true,
        }
        switch (node.type) {
          case "method":
            return {
              ...base,
              type: "method",
              data: {
                node,
                selected: node.methodId === selectedMethodId,
                onSelect: () => {
                  onSelectMethod(node.methodId)
                  const rollup = node.rollup
                  if (rollup.file && rollup.line)
                    onFocusSource(rollup.file, rollup.line)
                },
                onToggle: () => toggleMethod(node.methodId),
              } satisfies MethodData,
            }
          case "statement":
            return {
              ...base,
              type: "statement",
              data: {
                node,
                onSelect: () => {
                  onSelectMethod(node.methodId)
                  onFocusSource(
                    node.icfgNode.anchor.file,
                    node.icfgNode.anchor.start_line
                  )
                },
              } satisfies StatementData,
            }
          case "condensed":
            return {
              ...base,
              type: "condensed",
              data: {
                node,
                onExpand: () => expandRun(node.id),
              } satisfies CondensedData,
            }
          case "ghost":
            return {
              ...base,
              type: "ghost",
              data: { node } satisfies GhostData,
            }
        }
      }
      setRfNodes(graph.nodes.map(toRfNode))
      setRfEdges(
        graph.edges.map((edge) => {
          const style = EDGE_STYLE[edge.kind] ?? {}
          return {
            id: edge.id,
            source: edge.source,
            target: edge.target,
            label: edge.label ?? undefined,
            animated: edge.back,
            labelStyle: { fontSize: 9, fill: style.stroke },
            style: {
              stroke: style.stroke,
              strokeDasharray: edge.back ? "3 4" : style.dash,
              opacity: 0.8,
            },
          } satisfies Edge
        })
      )
    })
    return () => {
      cancelled = true
    }
  }, [
    graph,
    selectedMethodId,
    onSelectMethod,
    onFocusSource,
    toggleMethod,
    expandRun,
  ])

  return (
    <div className="relative h-full min-h-0 w-full">
      {overBudget ? (
        <p className="absolute left-2 top-2 z-10 rounded border bg-background/90 px-2 py-1 text-[10px] text-muted-foreground">
          Large flow — {graph.nodes.length} nodes; collapse methods to keep the
          map readable.
        </p>
      ) : null}
      <ReactFlow
        nodes={rfNodes}
        edges={rfEdges}
        nodeTypes={NODE_TYPES}
        colorMode={resolvedTheme === "dark" ? "dark" : "light"}
        fitView
        minZoom={0.1}
        proOptions={{ hideAttribution: true }}
        nodesConnectable={false}
      >
        <Background gap={18} />
        <Controls showInteractive={false} />
        <MiniMap pannable zoomable className="!h-24 !w-36" />
      </ReactFlow>
    </div>
  )
}
