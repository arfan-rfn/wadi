// Governing conditions (§11 Phase 2.7 M5): under which branches does a
// statement execute? A nearest-branch-ancestry walk — deliberately a
// heuristic (recorded in §11): the NEAREST branch on each backward path, not
// full dominance analysis. The walk crosses interprocedural call edges as
// pass-throughs (a helper's call is governed by branches at its CALL SITES —
// on real code the remote call usually sits in a small helper and the
// business branch in the caller); a multi-caller helper honestly reports the
// conditions of every path.

import type { Icfg } from "@/lib/generated/icfg.schema"

import type { FlowGraph } from "./flow-graph"

export interface GoverningCondition {
  /** The condition expression text. */
  expression: string
  /** How the path reaches the statement: taken/not-taken/case value. */
  polarity: "when" | "unless" | "case"
  caseValues: string[]
}

const MAX_CONDITIONS = 2
const MAX_STEPS = 400

/** Per-node governing conditions, keyed by node id. Only nodes that carry
 * remote-call or MQ markers are computed (the story consumers). */
export function governingConditions(
  icfg: Icfg
): Map<string, GoverningCondition[]> {
  const nodeById = new Map(icfg.nodes.map((n) => [n.id, n]))
  const incoming = new Map<
    string,
    Array<{ source: string; kind: string; caseValues: string[] }>
  >()
  for (const edge of icfg.edges ?? []) {
    if (edge.kind === "return") continue
    const source = nodeById.get(edge.source)
    const target = nodeById.get(edge.target)
    if (!source || !target) continue
    // Intra-method flow, plus `call` edges (call site → callee entry) as
    // cross-method pass-throughs.
    if (edge.kind !== "call" && source.method.id !== target.method.id) continue
    const list = incoming.get(edge.target) ?? []
    list.push({
      source: edge.source,
      kind: edge.kind,
      caseValues: edge.case_values ?? [],
    })
    incoming.set(edge.target, list)
  }

  const result = new Map<string, GoverningCondition[]>()
  for (const node of icfg.nodes) {
    const marked =
      (node.remote_call_ids ?? []).length > 0 || node.mq_interaction_id != null
    if (!marked) continue

    const conditions: GoverningCondition[] = []
    const seenExpressions = new Set<string>()
    const visited = new Set<string>([node.id])
    let frontier = [node.id]
    let steps = 0
    while (
      frontier.length > 0 &&
      conditions.length < MAX_CONDITIONS &&
      steps < MAX_STEPS
    ) {
      const next: string[] = []
      for (const id of frontier) {
        for (const edge of incoming.get(id) ?? []) {
          steps += 1
          const source = nodeById.get(edge.source)
          if (!source || visited.has(edge.source)) continue
          visited.add(edge.source)
          const isDecision =
            (edge.kind === "true" ||
              edge.kind === "false" ||
              edge.kind === "case" ||
              edge.kind === "default") &&
            source.condition?.expression
          if (isDecision && source.condition) {
            const expression = source.condition.expression
            if (!seenExpressions.has(expression)) {
              seenExpressions.add(expression)
              conditions.push({
                expression,
                polarity:
                  edge.kind === "false"
                    ? "unless"
                    : edge.kind === "case" || edge.kind === "default"
                      ? "case"
                      : "when",
                caseValues: edge.caseValues,
              })
            }
            // A decision edge governs; stop walking past it on this path.
            continue
          }
          next.push(edge.source)
        }
      }
      frontier = next
    }
    if (conditions.length > 0) result.set(node.id, conditions)
  }
  return result
}

export function conditionLabel(condition: GoverningCondition): string {
  if (condition.polarity === "case") {
    return condition.caseValues.length
      ? `case ${condition.caseValues.join(", ")} of ${condition.expression}`
      : `default of ${condition.expression}`
  }
  return `${condition.polarity} ${condition.expression}`
}

/**
 * Governing conditions for a ghost target: the union over every call site that
 * reaches it, deduped by label.
 *
 * A ghost stands for one remote target, and several call sites commonly sit
 * under the SAME governing branch. Undeduped, the display budget spends every
 * slot on one repeated condition — and React sees two children with the same
 * key. Dedupe must happen BEFORE any cap for the budget to show distinct
 * conditions, which is why the union lives here and not at the call site.
 */
export function ghostConditions(
  graph: FlowGraph,
  conditionsByNode: ReadonlyMap<string, GoverningCondition[]>,
  ghostNodeId: string
): GoverningCondition[] {
  const byLabel = new Map<string, GoverningCondition>()
  for (const edge of graph.edges) {
    if (edge.kind !== "remote" || edge.target !== ghostNodeId) continue
    const source = graph.nodes.find((node) => node.id === edge.source)
    if (source?.type !== "statement") continue
    for (const condition of conditionsByNode.get(source.icfgNode.id) ?? []) {
      const label = conditionLabel(condition)
      if (!byLabel.has(label)) byLabel.set(label, condition)
    }
  }
  return [...byLabel.values()]
}
