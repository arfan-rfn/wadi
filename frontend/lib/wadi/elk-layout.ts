// ELK layered layout for the flow canvas (§11 Phase 2.7 M3). Deterministic,
// top-down — the right idiom for CFG/call-graph shapes. The bundled build
// runs on the main thread: the canvas is bounded (collapse-all default above
// the node budget, condensation on by default), so layout stays in the
// low-millisecond range; a worker is the recorded escalation if profiling
// ever disagrees.

import type { FlowGraph, FlowGraphNode } from "./flow-graph"

export interface LayoutedNode {
  id: string
  x: number
  y: number
  width: number
  height: number
}

export function nodeSize(node: FlowGraphNode): {
  width: number
  height: number
} {
  switch (node.type) {
    case "method":
      return { width: 240, height: 72 }
    case "statement":
      return { width: 220, height: 44 }
    case "condensed":
      return { width: 150, height: 32 }
    case "ghost":
      return { width: 180, height: 44 }
  }
}

export async function layoutFlowGraph(
  graph: FlowGraph
): Promise<Map<string, LayoutedNode>> {
  const { default: ELK } = await import("elkjs/lib/elk.bundled.js")
  const elk = new ELK()
  const result = await elk.layout({
    id: "root",
    layoutOptions: {
      "elk.algorithm": "layered",
      "elk.direction": "DOWN",
      "elk.layered.spacing.nodeNodeBetweenLayers": "40",
      "elk.spacing.nodeNode": "28",
      "elk.layered.considerModelOrder.strategy": "NODES_AND_EDGES",
    },
    children: graph.nodes.map((node) => ({ id: node.id, ...nodeSize(node) })),
    edges: graph.edges
      // Back edges would fight the layering; route them after layout instead.
      .filter((edge) => !edge.back)
      .map((edge) => ({
        id: edge.id,
        sources: [edge.source],
        targets: [edge.target],
      })),
  })
  const positions = new Map<string, LayoutedNode>()
  for (const child of result.children ?? []) {
    positions.set(child.id, {
      id: child.id,
      x: child.x ?? 0,
      y: child.y ?? 0,
      width: child.width ?? 0,
      height: child.height ?? 0,
    })
  }
  return positions
}
