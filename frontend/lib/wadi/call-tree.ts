// The call tree (§11 Phase 2.7 M2): who calls whom, from the ICFG's
// interprocedural call edges. Pure derivation — the handler is the root,
// callees nest at their call sites (ordered by line), recursion into an
// ancestor renders as a cycle leaf instead of descending forever. A method
// reached from several call sites appears under each caller (the closure is
// context-insensitive; the tree shows every path).

import type { Icfg } from "@/lib/generated/icfg.schema"

import { rollupMethods, type MethodRollup } from "./rollup"

export interface CallTreeNode {
  methodId: string
  signature: string
  file: string | null
  line: number | null
  /** Line in the PARENT method's file where this call happens (null = root). */
  callSiteLine: number | null
  callSiteFile: string | null
  children: CallTreeNode[]
  /** True when this call re-enters a method already on the path (recursion). */
  cycle: boolean
  rollup: MethodRollup | null
}

interface CallSite {
  line: number
  file: string
  calleeMethodId: string
}

export function buildCallTree(icfg: Icfg): CallTreeNode | null {
  const nodeById = new Map(icfg.nodes.map((n) => [n.id, n]))
  const rollups = new Map(rollupMethods(icfg).map((r) => [r.id, r]))

  const entryByMethod = new Map<string, (typeof icfg.nodes)[number]>()
  for (const node of icfg.nodes) {
    if (node.kind === "entry") entryByMethod.set(node.method.id, node)
  }

  const callsByMethod = new Map<string, CallSite[]>()
  for (const edge of icfg.edges ?? []) {
    if (edge.kind !== "call") continue
    const source = nodeById.get(edge.source)
    const target = nodeById.get(edge.target)
    if (!source || !target || target.kind !== "entry") continue
    const sites = callsByMethod.get(source.method.id) ?? []
    sites.push({
      line: source.anchor.start_line,
      file: source.anchor.file,
      calleeMethodId: target.method.id,
    })
    callsByMethod.set(source.method.id, sites)
  }
  for (const sites of callsByMethod.values()) {
    sites.sort((a, b) => a.line - b.line)
  }

  const rootEntry = nodeById.get(icfg.entry_node_id)
  if (!rootEntry) return null

  const build = (
    methodId: string,
    callSite: CallSite | null,
    path: Set<string>
  ): CallTreeNode => {
    const entry = entryByMethod.get(methodId)
    const cycle = path.has(methodId)
    const node: CallTreeNode = {
      methodId,
      signature:
        entry?.method.signature ?? rollups.get(methodId)?.signature ?? methodId,
      file: entry?.anchor.file ?? null,
      line: entry?.anchor.start_line ?? null,
      callSiteLine: callSite?.line ?? null,
      callSiteFile: callSite?.file ?? null,
      children: [],
      cycle,
      rollup: rollups.get(methodId) ?? null,
    }
    if (cycle) return node
    const nextPath = new Set(path).add(methodId)
    for (const site of callsByMethod.get(methodId) ?? []) {
      node.children.push(build(site.calleeMethodId, site, nextPath))
    }
    return node
  }

  return build(rootEntry.method.id, null, new Set())
}

/** Total node count (for collapse heuristics and tests). */
export function treeSize(node: CallTreeNode): number {
  return 1 + node.children.reduce((sum, child) => sum + treeSize(child), 0)
}
