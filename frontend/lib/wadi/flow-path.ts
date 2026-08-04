// Trace highlight (§11 Phase 2.8): "why does this run" as a path — reverse
// BFS from a node to the endpoint's entry over non-back edges. Returns ICFG
// node + edge ids; the canvas maps them onto whatever is currently drawn
// (a path through a collapsed method highlights its method card).

import type { Icfg } from "@/lib/generated/icfg.schema"

export interface FlowPath {
  nodeIds: Set<string>
  /** Edge keys as `${source}->${target}` over ICFG ids. */
  edgeKeys: Set<string>
}

export function pathToEntry(icfg: Icfg, fromNodeId: string): FlowPath {
  const incoming = new Map<string, Array<{ source: string }>>()
  for (const edge of icfg.edges ?? []) {
    if (edge.back) continue
    const list = incoming.get(edge.target) ?? []
    list.push({ source: edge.source })
    incoming.set(edge.target, list)
  }

  // Reverse BFS recording one predecessor per node (a single witness path,
  // not the full ancestor cone — the point is a readable trace).
  const previous = new Map<string, string>()
  const queue = [fromNodeId]
  const seen = new Set([fromNodeId])
  // Cursor rather than `shift()`: dequeuing off the front of a growing array
  // is O(n), which would make the trace quadratic in closure size.
  for (let head = 0; head < queue.length; head++) {
    const current = queue[head]
    if (current === icfg.entry_node_id) break
    for (const { source } of incoming.get(current) ?? []) {
      if (seen.has(source)) continue
      seen.add(source)
      previous.set(source, current)
      queue.push(source)
    }
  }

  const nodeIds = new Set<string>()
  const edgeKeys = new Set<string>()
  if (!seen.has(icfg.entry_node_id)) {
    // No path (P10: state it, don't fake one) — highlight just the node.
    nodeIds.add(fromNodeId)
    return { nodeIds, edgeKeys }
  }
  let cursor: string | undefined = icfg.entry_node_id
  while (cursor !== undefined) {
    nodeIds.add(cursor)
    const next: string | undefined = previous.get(cursor)
    if (next !== undefined) edgeKeys.add(`${cursor}->${next}`)
    cursor = next
  }
  return { nodeIds, edgeKeys }
}
