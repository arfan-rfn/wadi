// The lanes layout (§11 Phase 2.8): the flow canvas is a vertical STACK of
// per-method lanes, not one global graph — callee lanes sit below their first
// call site (call-tree DFS preorder), so the whole canvas reads top-to-bottom
// in execution order, "like a document, not a map". Each expanded method's
// statement subgraph is laid out by ELK independently (tiny graphs, cached
// per lane); collapsing/expanding one method re-lays out ONLY that lane —
// the rest restack arithmetically. Three fixed columns: a left gutter for
// interprocedural call edges, the center execution document, and a right rail
// where remote/DB/MQ ghost targets pin at the height of their call site — the
// collapsed view literally reads "what it does" down the middle and "who it
// talks to" down the right.

import type { Icfg } from "@/lib/generated/icfg.schema"

import { buildCallTree, type CallTreeNode } from "./call-tree"
import { layoutGeneric, type LayoutedNode } from "./elk-layout"
import type { FlowGraph, FlowGraphNode } from "./flow-graph"
import { rollupMethods } from "./rollup"

// Column geometry (canvas coordinates).
export const GUTTER_WIDTH = 64
export const LANE_X = GUTTER_WIDTH + 16
export const LANE_PADDING = 16
export const LANE_HEADER_HEIGHT = 36
export const LANE_GAP = 48
export const LANE_MIN_WIDTH = 280
export const RAIL_GAP = 96
export const GHOST_HEIGHT = 44
export const GHOST_GAP = 16

/** Above this many drawn statements the default state falls back to
 * fully-collapsed (budget honesty over dogma). */
export const DEFAULT_EXPAND_STATEMENT_BUDGET = 60

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
      return { width: 180, height: GHOST_HEIGHT }
  }
}

// Execution-order-faithful ELK options (VEIL): model order IS document order
// — children are fed sorted by source line and crossing minimization must not
// reorder them.
const LANE_ELK_OPTIONS: Record<string, string> = {
  "elk.layered.considerModelOrder.strategy": "NODES_AND_EDGES",
  "elk.layered.crossingMinimization.forceNodeModelOrder": "true",
  "elk.layered.nodePlacement.strategy": "NETWORK_SIMPLEX",
  "elk.layered.spacing.nodeNodeBetweenLayers": "28",
  "elk.spacing.nodeNode": "16",
}

/** Lane order: call-tree DFS preorder, deduped at first encounter — a callee
 * lane always sits below its first call site (happens-before by
 * construction). Methods unreachable from the entry (P10: they exist in the
 * closure) append at the end in rollup order. */
export function laneOrder(icfg: Icfg): string[] {
  const order: string[] = []
  const seen = new Set<string>()
  const visit = (node: CallTreeNode) => {
    if (!seen.has(node.methodId)) {
      seen.add(node.methodId)
      order.push(node.methodId)
    }
    if (!node.cycle) node.children.forEach(visit)
  }
  const root = buildCallTree(icfg)
  if (root) visit(root)
  for (const rollup of rollupMethods(icfg)) {
    if (!seen.has(rollup.id)) {
      seen.add(rollup.id)
      order.push(rollup.id)
    }
  }
  return order
}

/** Resolve the store's expand intent against this ICFG. `default` = the
 * entry handler only — unless its drawn subgraph would blow the budget. */
export function resolveExpandedMethods(
  expand: "default" | "all" | "none" | ReadonlySet<string>,
  icfg: Icfg
): Set<string> {
  if (expand === "all") return new Set(rollupMethods(icfg).map((r) => r.id))
  if (expand === "none") return new Set()
  if (expand !== "default") return new Set(expand)
  const entryMethod = icfg.nodes.find((n) => n.id === icfg.entry_node_id)
    ?.method.id
  if (!entryMethod) return new Set()
  const handlerStatements = icfg.nodes.filter(
    (n) =>
      n.method.id === entryMethod && n.kind !== "entry" && n.kind !== "exit"
  ).length
  if (handlerStatements > DEFAULT_EXPAND_STATEMENT_BUDGET) return new Set()
  return new Set([entryMethod])
}

export interface LaneBox {
  methodId: string
  signature: string
  x: number
  y: number
  width: number
  height: number
  collapsed: boolean
}

export interface FlowLayout {
  /** Absolute canvas positions for every FlowGraph node. */
  positions: Map<string, LayoutedNode>
  lanes: LaneBox[]
  /** X of the ghost rail column. */
  railX: number
  width: number
  height: number
}

interface CachedLane {
  /** Positions relative to the lane's content origin. */
  relative: LayoutedNode[]
  width: number
  height: number
}

// Per-ICFG lane cache: expanding method N lays out only N; every other lane
// hits this and just restacks. Keyed by the drawn member set (captures both
// method identity and expanded-run state).
const laneCaches = new WeakMap<Icfg, Map<string, CachedLane>>()

function laneCacheFor(icfg: Icfg): Map<string, CachedLane> {
  let cache = laneCaches.get(icfg)
  if (!cache) {
    cache = new Map()
    laneCaches.set(icfg, cache)
  }
  return cache
}

function anchorLine(node: FlowGraphNode): number {
  switch (node.type) {
    case "statement":
      return node.icfgNode.anchor.start_line
    case "condensed":
      return node.startLine
    default:
      return 0
  }
}

export async function layoutLanes(
  graph: FlowGraph,
  icfg: Icfg
): Promise<FlowLayout> {
  const cache = laneCacheFor(icfg)
  const byLane = new Map<string, FlowGraphNode[]>()
  const ghosts: FlowGraphNode[] = []
  for (const node of graph.nodes) {
    if (node.type === "ghost") {
      ghosts.push(node)
      continue
    }
    const list = byLane.get(node.methodId) ?? []
    list.push(node)
    byLane.set(node.methodId, list)
  }

  const order = laneOrder(icfg).filter((methodId) => byLane.has(methodId))

  // --- per-lane content layout (cached) -------------------------------------------
  const laneContents = new Map<string, CachedLane>()
  for (const methodId of order) {
    const members = byLane.get(methodId) ?? []
    const collapsed = members.length === 1 && members[0].type === "method"
    if (collapsed) {
      const size = nodeSize(members[0])
      laneContents.set(methodId, {
        relative: [{ id: members[0].id, x: 0, y: 0, ...size }],
        width: size.width,
        height: size.height,
      })
      continue
    }
    const key = `${methodId}|${members
      .map((m) => m.id)
      .sort()
      .join(",")}`
    const cached = cache.get(key)
    if (cached) {
      laneContents.set(methodId, cached)
      continue
    }
    const sorted = [...members].sort((a, b) => anchorLine(a) - anchorLine(b))
    const memberIds = new Set(sorted.map((m) => m.id))
    const intraEdges = graph.edges.filter(
      (edge) =>
        !edge.back &&
        edge.kind !== "call" &&
        edge.kind !== "remote" &&
        memberIds.has(edge.source) &&
        memberIds.has(edge.target)
    )
    const positions = await layoutGeneric(
      sorted.map((node) => ({ id: node.id, ...nodeSize(node) })),
      intraEdges,
      LANE_ELK_OPTIONS
    )
    let width = 0
    let height = 0
    const relative: LayoutedNode[] = []
    for (const node of sorted) {
      const p = positions.get(node.id)
      if (!p) continue
      relative.push(p)
      width = Math.max(width, p.x + p.width)
      height = Math.max(height, p.y + p.height)
    }
    const content: CachedLane = { relative, width, height }
    cache.set(key, content)
    laneContents.set(methodId, content)
  }

  // --- vertical stacking (pure arithmetic) ----------------------------------------
  const positions = new Map<string, LayoutedNode>()
  const lanes: LaneBox[] = []
  const signatureOf = new Map(
    rollupMethods(icfg).map((r) => [r.id, r.signature])
  )
  let y = 0
  let maxLaneRight = LANE_X + LANE_MIN_WIDTH
  for (const methodId of order) {
    const content = laneContents.get(methodId)
    if (!content) continue
    const members = byLane.get(methodId) ?? []
    const collapsed = members.length === 1 && members[0].type === "method"
    const laneWidth = Math.max(content.width + LANE_PADDING * 2, LANE_MIN_WIDTH)
    const laneHeight = collapsed
      ? content.height
      : content.height + LANE_HEADER_HEIGHT + LANE_PADDING * 2
    const contentTop = collapsed ? y : y + LANE_HEADER_HEIGHT + LANE_PADDING
    for (const p of content.relative) {
      positions.set(p.id, {
        ...p,
        x: LANE_X + (collapsed ? 0 : LANE_PADDING) + p.x,
        y: contentTop + p.y,
      })
    }
    lanes.push({
      methodId,
      signature: signatureOf.get(methodId) ?? methodId,
      x: LANE_X,
      y,
      width: laneWidth,
      height: laneHeight,
      collapsed,
    })
    maxLaneRight = Math.max(maxLaneRight, LANE_X + laneWidth)
    y += laneHeight + LANE_GAP
  }
  const totalHeight = Math.max(y - LANE_GAP, 0)

  // --- ghost rail: pin each target at the height of its first call site ------------
  const railX = maxLaneRight + RAIL_GAP
  const ghostAnchor = new Map<string, number>()
  for (const edge of graph.edges) {
    if (edge.kind !== "remote") continue
    const sourceY = positions.get(edge.source)?.y
    if (sourceY === undefined) continue
    const current = ghostAnchor.get(edge.target)
    ghostAnchor.set(
      edge.target,
      current === undefined ? sourceY : Math.min(current, sourceY)
    )
  }
  const sortedGhosts = [...ghosts].sort(
    (a, b) => (ghostAnchor.get(a.id) ?? 0) - (ghostAnchor.get(b.id) ?? 0)
  )
  let lastBottom = -Infinity
  for (const ghost of sortedGhosts) {
    const size = nodeSize(ghost)
    let ghostY = ghostAnchor.get(ghost.id) ?? 0
    if (ghostY < lastBottom + GHOST_GAP) ghostY = lastBottom + GHOST_GAP
    positions.set(ghost.id, { id: ghost.id, x: railX, y: ghostY, ...size })
    lastBottom = ghostY + size.height
  }

  return {
    positions,
    lanes,
    railX,
    width: railX + 180,
    height: Math.max(totalHeight, lastBottom),
  }
}
