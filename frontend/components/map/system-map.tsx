"use client"

// The system map (§11 Phase 2.7 M4): the whole snapshot's service graph,
// drawn. Service nodes styled by kind (gateway/library/extraction-error
// distinct), edges styled by confidence, and the unknown states — external
// hosts, placeholders, undetermined calls — are first-class nodes, MORE
// visible than the resolved ones, never less (P10). Clicking an edge opens
// its call sites with evidence; clicking a service scopes the Explorer.
import { useEffect, useMemo, useState } from "react"
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
  AlertTriangle,
  ArrowRight,
  Globe,
  HelpCircle,
  Router,
  X,
} from "lucide-react"
import { useTheme } from "next-themes"

import "@xyflow/react/dist/style.css"

import { cn } from "@/lib/utils"
import { layoutGeneric } from "@/lib/wadi/elk-layout"
import { useSystemGraph } from "@/lib/wadi/hooks"
import {
  buildSystemMap,
  type MapEdge,
  type MapNode,
  type MapNodeService,
  type MapNodeTarget,
} from "@/lib/wadi/system-map"
import { Skeleton } from "@/components/ui/skeleton"

interface ServiceData {
  node: MapNodeService
  onOpen: () => void
  [key: string]: unknown
}

interface TargetData {
  node: MapNodeTarget
  [key: string]: unknown
}

function ServiceNode({ data }: NodeProps<Node<ServiceData>>) {
  const { node, onOpen } = data
  const service = node.service
  const broken = service.extraction_error != null
  return (
    <div
      className={cn(
        "w-[200px] rounded-md border bg-card px-2.5 py-1.5 text-card-foreground shadow-sm",
        broken && "border-destructive/60 border-dashed"
      )}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="!bg-muted-foreground/40"
      />
      <button
        onClick={onOpen}
        className="w-full text-left"
        title={service.name}
      >
        <div className="flex items-center gap-1.5">
          {service.gateway ? (
            <Router className="size-3 shrink-0 text-muted-foreground" />
          ) : null}
          <span className="min-w-0 flex-1 truncate font-mono text-[11px] font-medium">
            {service.name}
          </span>
          {broken ? (
            <AlertTriangle className="size-3 shrink-0 text-destructive" />
          ) : null}
        </div>
        <div className="mt-0.5 flex items-center gap-2 font-mono text-[9px] text-muted-foreground">
          <span>{service.endpoint_count} endpoints</span>
          {service.async_root_count > 0 ? (
            <span>{service.async_root_count} roots</span>
          ) : null}
          {service.cfg_anomaly_count != null &&
          service.cfg_anomaly_count > 0 ? (
            <span className="text-amber-600 dark:text-amber-400">
              {service.cfg_anomaly_count} anomalies
            </span>
          ) : null}
          {broken ? (
            <span className="text-destructive">extraction failed</span>
          ) : null}
        </div>
      </button>
      <Handle
        type="source"
        position={Position.Bottom}
        className="!bg-muted-foreground/40"
      />
    </div>
  )
}

const TARGET_STYLE: Record<string, string> = {
  external: "border-muted-foreground/50 text-muted-foreground",
  placeholder: "border-dashed border-muted-foreground/70 text-muted-foreground",
  unresolved: "border-dashed border-destructive/60 text-destructive",
}

function TargetNode({ data }: NodeProps<Node<TargetData>>) {
  const { node } = data
  return (
    <div
      className={cn(
        "w-[170px] rounded-md border bg-background/70 px-2 py-1.5",
        TARGET_STYLE[node.type]
      )}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="!bg-muted-foreground/40"
      />
      <div className="flex items-center gap-1.5">
        {node.type === "unresolved" ? (
          <HelpCircle className="size-3 shrink-0" />
        ) : (
          <Globe className="size-3 shrink-0" />
        )}
        <span className="min-w-0 flex-1 truncate font-mono text-[10px]">
          {node.label}
        </span>
        <span className="shrink-0 font-mono text-[8px] uppercase opacity-70">
          {node.type}
        </span>
      </div>
    </div>
  )
}

const NODE_TYPES = { service: ServiceNode, target: TargetNode }

const CONFIDENCE_STYLE: Record<string, { dash?: string; width: number }> = {
  exact: { width: 2 },
  high: { width: 1.6 },
  heuristic: { dash: "6 4", width: 1.3 },
  none: { dash: "2 4", width: 1.2 },
}

export function SystemMapPane({
  snapshotId,
  active,
  onOpenService,
}: {
  snapshotId: string | null
  active: boolean
  onOpenService: (serviceId: string) => void
}) {
  const { resolvedTheme } = useTheme()
  const graphQuery = useSystemGraph(active, snapshotId)
  const [rfNodes, setRfNodes] = useState<Node[]>([])
  const [rfEdges, setRfEdges] = useState<Edge[]>([])
  const [selectedEdge, setSelectedEdge] = useState<MapEdge | null>(null)

  const map = useMemo(
    () => (graphQuery.data ? buildSystemMap(graphQuery.data) : null),
    [graphQuery.data]
  )

  useEffect(() => {
    if (!map) return
    let cancelled = false
    const sizeOf = (node: MapNode) =>
      node.type === "service"
        ? { width: 200, height: 52 }
        : { width: 170, height: 40 }
    void layoutGeneric(
      map.nodes.map((node) => ({ id: node.id, ...sizeOf(node) })),
      map.edges.map((edge) => ({
        id: edge.id,
        source: edge.source,
        target: edge.target,
      }))
    ).then((positions) => {
      if (cancelled) return
      setRfNodes(
        map.nodes.map((node) => {
          const position = positions.get(node.id)
          const size = sizeOf(node)
          if (node.type === "service") {
            return {
              id: node.id,
              type: "service",
              position: { x: position?.x ?? 0, y: position?.y ?? 0 },
              ...size,
              data: {
                node,
                onOpen: () => onOpenService(node.service.service_id),
              } satisfies ServiceData,
            }
          }
          return {
            id: node.id,
            type: "target",
            position: { x: position?.x ?? 0, y: position?.y ?? 0 },
            ...size,
            data: { node } satisfies TargetData,
          }
        })
      )
      setRfEdges(
        map.edges.map((edge) => {
          const style =
            CONFIDENCE_STYLE[edge.confidence] ?? CONFIDENCE_STYLE.none
          const undetermined = edge.targetKind === "undetermined"
          return {
            id: edge.id,
            source: edge.source,
            target: edge.target,
            label: edge.count > 1 ? `×${edge.count}` : undefined,
            labelStyle: { fontSize: 9 },
            style: {
              strokeWidth: style.width,
              strokeDasharray: style.dash,
              stroke: undetermined ? "#ef4444" : undefined,
              opacity: 0.75,
            },
          } satisfies Edge
        })
      )
    })
    return () => {
      cancelled = true
    }
  }, [map, onOpenService])

  if (!snapshotId) {
    return (
      <p className="p-6 text-sm text-muted-foreground">
        Pick a snapshot to see its service map.
      </p>
    )
  }
  if (graphQuery.isPending) {
    return (
      <div className="space-y-3 p-6">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }
  if (graphQuery.isError) {
    return (
      <p className="p-6 text-sm text-muted-foreground">
        Map unavailable: {(graphQuery.error as Error).message}
      </p>
    )
  }

  return (
    <div className="relative h-full min-h-0 w-full">
      {graphQuery.data && !graphQuery.data.stitched ? (
        <p className="absolute left-3 top-3 z-10 rounded-md border bg-background/90 px-2.5 py-1.5 text-xs text-muted-foreground">
          Not stitched yet — services are shown; edges appear once stitching
          completes.
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
        onEdgeClick={(_, edge) => {
          const found = map?.edges.find((candidate) => candidate.id === edge.id)
          setSelectedEdge(found ?? null)
        }}
      >
        <Background gap={18} />
        <Controls showInteractive={false} />
        <MiniMap pannable zoomable className="!h-24 !w-36" />
      </ReactFlow>

      {selectedEdge ? (
        <aside className="absolute bottom-0 right-0 top-0 z-10 w-96 overflow-y-auto border-l bg-background/95 p-4 backdrop-blur">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              {selectedEdge.count} call site
              {selectedEdge.count === 1 ? "" : "s"}
            </h3>
            <button
              onClick={() => setSelectedEdge(null)}
              aria-label="Close"
              className="text-muted-foreground hover:text-foreground"
            >
              <X className="size-4" />
            </button>
          </div>
          <ul className="space-y-3">
            {selectedEdge.items.map((item) => (
              <li
                key={item.edge_id}
                className="rounded-md border p-2.5 text-xs"
              >
                <div className="flex items-center gap-1.5 font-mono">
                  <span className="font-semibold">{item.http_verb ?? "?"}</span>
                  <span
                    className="min-w-0 flex-1 truncate"
                    title={item.url ?? ""}
                  >
                    {item.url ?? "(no url)"}
                  </span>
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[10px] text-muted-foreground">
                  <span>{item.mechanism}</span>
                  <span>confidence: {item.confidence}</span>
                  <span>{item.provenance}</span>
                  {item.target_simplified_uri ? (
                    <span className="inline-flex items-center gap-0.5 font-mono">
                      <ArrowRight className="size-2.5" />
                      {item.target_http_method} {item.target_simplified_uri}
                    </span>
                  ) : null}
                </div>
                {item.evidence ? (
                  <p className="mt-1 text-[10px] text-muted-foreground">
                    {item.evidence}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        </aside>
      ) : null}
    </div>
  )
}
