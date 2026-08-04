// Focus / re-root (§11 Phase 2.8): focusing a method shows that method plus
// its call-tree descendants and HIDES everything else (Datadog's
// focus-on-span — hide, don't dim: hidden lanes pay no render or layout tax
// and the survivors rescale). Reversible via the breadcrumb, which is the
// call path from the entry handler to the focus. Ghost targets stay visible
// whenever any VISIBLE node calls them (P10: unknowns never disappear as a
// side effect of focus).

import type { CallTreeNode } from "./call-tree"
import type { FlowGraph } from "./flow-graph"

/** The focused method plus every call-tree descendant (cycle leaves stop). */
export function focusMethodIds(
  tree: CallTreeNode | null,
  focusMethodId: string
): Set<string> {
  const result = new Set<string>()
  const collect = (node: CallTreeNode) => {
    result.add(node.methodId)
    if (!node.cycle) node.children.forEach(collect)
  }
  const findAndCollect = (node: CallTreeNode): boolean => {
    if (node.methodId === focusMethodId) {
      collect(node)
      return true
    }
    if (node.cycle) return false
    return node.children.some(findAndCollect)
  }
  if (tree) findAndCollect(tree)
  return result
}

/** Breadcrumb: the first call path from the root to the focused method,
 * root-first. Empty focus (or an unreachable id) → just the root. */
export function breadcrumbPath(
  tree: CallTreeNode | null,
  focusMethodId: string | null
): CallTreeNode[] {
  if (!tree) return []
  if (!focusMethodId) return [tree]
  const path: CallTreeNode[] = []
  const walk = (node: CallTreeNode): boolean => {
    path.push(node)
    if (node.methodId === focusMethodId) return true
    if (!node.cycle && node.children.some(walk)) return true
    path.pop()
    return false
  }
  return walk(tree) ? path : [tree]
}

/** Canvas node ids hidden under the current focus. Ghosts hide only when
 * every remote edge into them comes from a hidden node. */
export function hiddenNodeIds(
  graph: FlowGraph,
  visibleMethods: ReadonlySet<string> | null
): Set<string> {
  const hidden = new Set<string>()
  if (visibleMethods === null) return hidden
  for (const node of graph.nodes) {
    if (node.type === "ghost") continue
    if (!visibleMethods.has(node.methodId)) hidden.add(node.id)
  }
  for (const node of graph.nodes) {
    if (node.type !== "ghost") continue
    const callers = graph.edges.filter(
      (edge) => edge.kind === "remote" && edge.target === node.id
    )
    if (callers.length > 0 && callers.every((edge) => hidden.has(edge.source)))
      hidden.add(node.id)
  }
  return hidden
}
