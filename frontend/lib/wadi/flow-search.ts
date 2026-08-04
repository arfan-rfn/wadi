// Canvas search (§11 Phase 2.8): matches over the FULL ICFG — method
// signatures, statement text, branch conditions, ghost-target labels — not
// just the currently drawn nodes, so a hit inside a collapsed method can
// auto-expand it. Pure index; the canvas resolves matches to drawn nodes.

import type { Icfg } from "@/lib/generated/icfg.schema"

import type { FlowGraph } from "./flow-graph"
import { rollupMethods, shortSignature } from "./rollup"

export interface FlowSearchMatch {
  /** ICFG node id for statements, method id for methods, canvas id for ghosts. */
  id: string
  kind: "method" | "statement" | "ghost"
  /** Owning method (auto-expand target); null for ghosts. */
  methodId: string | null
  label: string
}

export function searchFlow(
  icfg: Icfg,
  graph: FlowGraph,
  query: string
): FlowSearchMatch[] {
  const q = query.trim().toLowerCase()
  if (q.length < 2) return []
  const matches: FlowSearchMatch[] = []

  for (const rollup of rollupMethods(icfg)) {
    if (rollup.signature.toLowerCase().includes(q)) {
      matches.push({
        id: rollup.id,
        kind: "method",
        methodId: rollup.id,
        label: shortSignature(rollup.signature),
      })
    }
  }

  for (const node of icfg.nodes) {
    if (node.kind === "entry" || node.kind === "exit") continue
    const haystacks = [node.source_text, node.condition?.expression ?? ""]
    if (haystacks.some((text) => text.toLowerCase().includes(q))) {
      matches.push({
        id: node.id,
        kind: "statement",
        methodId: node.method.id,
        label: node.source_text.trim().slice(0, 80),
      })
    }
  }

  for (const node of graph.nodes) {
    if (node.type !== "ghost") continue
    if (node.label.toLowerCase().includes(q)) {
      matches.push({
        id: node.id,
        kind: "ghost",
        methodId: null,
        label: node.label,
      })
    }
  }

  return matches
}
