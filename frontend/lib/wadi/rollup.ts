// Client-side method-level roll-up of an ICFG (mirrors the MCP server's §8
// progressive-disclosure view): which methods run, what each touches.

import type { Icfg } from "@/lib/generated/icfg.schema"

export interface MethodRollup {
  id: string
  signature: string
  isRoot: boolean
  badges: string[]
  statementCount: number
  branchCount: number
  loopCount: number
  callCount: number
  /** §5.2.8 construct tallies, e.g. { for: 2, switch: 1, "try": 1 } */
  constructCounts: Record<string, number>
  sinks: string[]
  file: string | null
  line: number | null
}

export function rollupMethods(icfg: Icfg): MethodRollup[] {
  const byId = new Map<string, MethodRollup>()
  const rootMethodId = icfg.nodes.find((n) => n.id === icfg.entry_node_id)
    ?.method.id

  for (const node of icfg.nodes) {
    let entry = byId.get(node.method.id)
    if (!entry) {
      entry = {
        id: node.method.id,
        signature: node.method.signature,
        isRoot: node.method.id === rootMethodId,
        badges: [],
        statementCount: 0,
        branchCount: 0,
        loopCount: 0,
        callCount: 0,
        constructCounts: {},
        sinks: [],
        file: null,
        line: null,
      }
      byId.set(node.method.id, entry)
    }
    if (node.kind === "entry") {
      entry.file = node.anchor.file
      entry.line = node.anchor.start_line
      // NOTE: method_info.signature is Joern's bare type signature
      // (return + params, no name) — keep method.signature (fully qualified)
      // for display and only take the badges from method_info.
      if (node.method_info) {
        entry.badges = node.method_info.badges ?? []
      }
    } else if (node.kind === "branch") {
      entry.branchCount += 1
    } else if (node.kind === "loop") {
      entry.loopCount += 1
    } else if (node.kind === "call") {
      entry.callCount += 1
    } else if (node.kind === "statement" || node.kind === "return") {
      entry.statementCount += 1
    }
    if (node.construct_kind) {
      entry.constructCounts[node.construct_kind] =
        (entry.constructCounts[node.construct_kind] ?? 0) + 1
    }
    if (node.sink && !entry.sinks.includes(node.sink)) {
      entry.sinks.push(node.sink)
    }
  }

  return [...byId.values()].sort((a, b) =>
    a.isRoot ? -1 : b.isRoot ? 1 : a.signature.localeCompare(b.signature)
  )
}

/** Short human form: `Class.method` from a fully-qualified signature. */
export function shortSignature(signature: string): string {
  const beforeParams = signature.split(":")[0] ?? signature
  const parts = beforeParams.split(".")
  return parts.slice(-2).join(".")
}
