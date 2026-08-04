// Shared ELK layered layout (system map + the per-lane flow layout in
// flow-lanes.ts). Deterministic, top-down. The bundled build runs on the main
// thread: inputs are bounded (per-method lanes; the system map's service
// count), so layout stays in the low-millisecond range; a worker is the
// recorded escalation if profiling ever disagrees.

export interface LayoutedNode {
  id: string
  x: number
  y: number
  width: number
  height: number
}

export async function layoutGeneric(
  children: Array<{ id: string; width: number; height: number }>,
  edges: Array<{ id: string; source: string; target: string }>,
  options?: Record<string, string>
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
      ...options,
    },
    children,
    edges: edges.map((edge) => ({
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
