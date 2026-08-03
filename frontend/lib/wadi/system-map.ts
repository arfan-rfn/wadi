// The system map model (§11 Phase 2.7 M4): pure aggregation over the
// snapshot-wide /graph view. Service nodes come straight from the payload;
// edges aggregate per (caller → target) with call counts and the strongest
// confidence; unknown targets stay first-class nodes (P10): externals by
// host, placeholders by identity, and per-caller "unresolved" sinks for
// undetermined calls — the unknown must be MORE visible, not less.

import type { SystemGraphView } from "@/lib/generated/system_graph.schema"

type GraphService = NonNullable<SystemGraphView["services"]>[number]
type GraphEdgeItem = NonNullable<SystemGraphView["edges"]>[number]

export interface MapNodeService {
  type: "service"
  id: string
  service: GraphService
}

export interface MapNodeTarget {
  type: "external" | "placeholder" | "unresolved"
  id: string
  label: string
}

export type MapNode = MapNodeService | MapNodeTarget

export interface MapEdge {
  id: string
  source: string
  target: string
  count: number
  confidence: string
  targetKind: string
  items: GraphEdgeItem[]
}

export interface SystemMap {
  nodes: MapNode[]
  edges: MapEdge[]
}

const CONFIDENCE_RANK: Record<string, number> = {
  exact: 3,
  high: 2,
  heuristic: 1,
  none: 0,
}

export function buildSystemMap(view: SystemGraphView): SystemMap {
  const nodes: MapNode[] = []
  const nodeIds = new Set<string>()
  const pushNode = (node: MapNode) => {
    if (!nodeIds.has(node.id)) {
      nodeIds.add(node.id)
      nodes.push(node)
    }
  }

  for (const service of view.services ?? []) {
    pushNode({ type: "service", id: `svc:${service.service_id}`, service })
  }

  const grouped = new Map<string, MapEdge>()
  for (const item of view.edges ?? []) {
    const source = `svc:${item.caller_service_id}`
    let target: string
    if (item.target_kind === "analyzed" && item.target_service_id) {
      target = `svc:${item.target_service_id}`
    } else if (item.target_kind === "external" && item.external_host) {
      target = `ext:${item.external_host}`
      pushNode({ type: "external", id: target, label: item.external_host })
    } else if (item.target_kind === "placeholder" && item.target_service_id) {
      target = `ph:${item.target_service_id}`
      pushNode({
        type: "placeholder",
        id: target,
        label: item.target_service_name ?? item.target_service_id,
      })
    } else {
      // Undetermined: one honest sink per caller, never dropped.
      target = `unresolved:${item.caller_service_id}`
      pushNode({ type: "unresolved", id: target, label: "unresolved" })
    }
    if (!nodeIds.has(source)) continue // caller must be a known service
    const key = `${source}->${target}`
    const existing = grouped.get(key)
    if (existing) {
      existing.count += 1
      existing.items.push(item)
      if (
        (CONFIDENCE_RANK[item.confidence] ?? 0) >
        (CONFIDENCE_RANK[existing.confidence] ?? 0)
      ) {
        existing.confidence = item.confidence
      }
    } else {
      grouped.set(key, {
        id: key,
        source,
        target,
        count: 1,
        confidence: item.confidence,
        targetKind: item.target_kind,
        items: [item],
      })
    }
  }

  return { nodes, edges: [...grouped.values()] }
}
