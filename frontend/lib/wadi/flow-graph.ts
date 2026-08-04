// The flow-canvas graph model (§11 Phase 2.7 M3): semantic zoom over the
// ICFG, derived purely — no API calls.
//
// Level 0: one node per method, edges per call, with the important facts
// LIFTED UP — each method's remote/DB/MQ sinks render as ghost-target stubs
// so the collapsed view alone answers "what does it do, who does it talk to".
// Level 1: an expanded method swaps its card for its statement subgraph
// (labeled true/false/case/fallthrough/exception edges, back flags).
// Condensation: maximal runs of plain linear statements inside an expanded
// method collapse into one "n statements" node — condensation never hides
// branch/loop/call/sink/condition-carrying nodes.

import type { Icfg } from "@/lib/generated/icfg.schema"
import type { RemoteEdgesView } from "@/lib/generated/remote_edges_view.schema"

import { rollupMethods, type MethodRollup } from "./rollup"

type IcfgNode = Icfg["nodes"][number]
type IcfgEdge = NonNullable<Icfg["edges"]>[number]
type RemoteEdgeItem = NonNullable<RemoteEdgesView["outbound"]>[number]

export interface FlowNodeMethod {
  type: "method"
  id: string
  methodId: string
  rollup: MethodRollup
  isRoot: boolean
}

export interface FlowNodeStatement {
  type: "statement"
  id: string
  methodId: string
  icfgNode: IcfgNode
}

export interface FlowNodeCondensed {
  type: "condensed"
  id: string
  methodId: string
  count: number
  file: string
  startLine: number
  endLine: number
  memberIds: string[]
}

export interface FlowNodeGhost {
  type: "ghost"
  id: string
  label: string
  targetKind: string
  confidence: string | null
  edgeId: string | null
}

export type FlowGraphNode =
  FlowNodeMethod | FlowNodeStatement | FlowNodeCondensed | FlowNodeGhost

export interface FlowGraphEdge {
  id: string
  source: string
  target: string
  kind: string
  label: string | null
  back: boolean
}

export interface FlowGraph {
  nodes: FlowGraphNode[]
  edges: FlowGraphEdge[]
}

function edgeLabel(edge: IcfgEdge): string | null {
  switch (edge.kind) {
    case "true":
      return "true"
    case "false":
      return "false"
    case "case":
      return edge.case_values?.length ? edge.case_values.join(", ") : "case"
    case "default":
      return "default"
    case "fallthrough":
      return "fallthrough"
    case "exception":
      return "exception"
    default:
      return null
  }
}

/** A statement is condensable when it carries no signal of its own. */
function condensable(node: IcfgNode): boolean {
  return (
    (node.kind === "statement" ||
      node.kind === "call" ||
      node.kind === "return") &&
    !node.construct_kind &&
    !node.sink &&
    !node.condition &&
    !(node.remote_call_ids ?? []).length &&
    !node.mq_interaction_id
  )
}

export function buildFlowGraph(
  icfg: Icfg,
  remoteEdges: RemoteEdgesView | undefined,
  expandedMethods: ReadonlySet<string>,
  expandedRuns: ReadonlySet<string>
): FlowGraph {
  const nodeById = new Map(icfg.nodes.map((n) => [n.id, n]))
  const rollups = rollupMethods(icfg)
  const rootMethodId = nodeById.get(icfg.entry_node_id)?.method.id ?? null
  const edgesByRemoteCallId = new Map<string, RemoteEdgeItem>()
  for (const item of remoteEdges?.outbound ?? []) {
    edgesByRemoteCallId.set(item.remote_call_id, item)
  }

  const nodes: FlowGraphNode[] = []
  const edges: FlowGraphEdge[] = []
  const seenEdgeIds = new Set<string>()
  const pushEdge = (edge: FlowGraphEdge) => {
    if (!seenEdgeIds.has(edge.id)) {
      seenEdgeIds.add(edge.id)
      edges.push(edge)
    }
  }

  // ---- per-method statement partition + condensation ------------------------------
  const intraByMethod = new Map<string, IcfgEdge[]>()
  const statementsByMethod = new Map<string, IcfgNode[]>()
  for (const node of icfg.nodes) {
    if (node.kind === "entry" || node.kind === "exit") continue
    const list = statementsByMethod.get(node.method.id) ?? []
    list.push(node)
    statementsByMethod.set(node.method.id, list)
  }
  for (const edge of icfg.edges ?? []) {
    if (edge.kind === "call" || edge.kind === "return") continue
    const source = nodeById.get(edge.source)
    const target = nodeById.get(edge.target)
    if (!source || !target) continue
    if (source.method.id !== target.method.id) continue
    if (source.kind === "entry" || target.kind === "exit") continue
    if (source.kind === "exit" || target.kind === "entry") continue
    const list = intraByMethod.get(source.method.id) ?? []
    list.push(edge)
    intraByMethod.set(source.method.id, list)
  }

  /** Node-id → canvas-node-id, accounting for condensation. */
  const canvasIdOf = new Map<string, string>()

  for (const rollup of rollups) {
    const methodId = rollup.id
    if (!expandedMethods.has(methodId)) {
      const id = `method:${methodId}`
      nodes.push({
        type: "method",
        id,
        methodId,
        rollup,
        isRoot: methodId === rootMethodId,
      })
      for (const statement of statementsByMethod.get(methodId) ?? []) {
        canvasIdOf.set(statement.id, id)
      }
      continue
    }

    const statements = statementsByMethod.get(methodId) ?? []
    const intra = intraByMethod.get(methodId) ?? []
    const inDegree = new Map<string, number>()
    const outDegree = new Map<string, number>()
    for (const edge of intra) {
      outDegree.set(edge.source, (outDegree.get(edge.source) ?? 0) + 1)
      inDegree.set(edge.target, (inDegree.get(edge.target) ?? 0) + 1)
    }
    const nextOf = new Map<string, string>()
    for (const edge of intra) {
      if (edge.kind === "flow" && !edge.back)
        nextOf.set(edge.source, edge.target)
    }

    // Maximal linear runs of condensable statements (in/out degree ≤ 1).
    const runnable = (node: IcfgNode) =>
      condensable(node) &&
      (inDegree.get(node.id) ?? 0) <= 1 &&
      (outDegree.get(node.id) ?? 0) <= 1
    const inRun = new Set<string>()
    const runs: IcfgNode[][] = []
    for (const statement of statements) {
      if (!runnable(statement) || inRun.has(statement.id)) continue
      // Only start at a run head: predecessor is not part of a run.
      const isHead = !statements.some(
        (p) => runnable(p) && nextOf.get(p.id) === statement.id
      )
      if (!isHead) continue
      const run: IcfgNode[] = []
      let current: IcfgNode | undefined = statement
      while (current && runnable(current) && !inRun.has(current.id)) {
        run.push(current)
        inRun.add(current.id)
        const nextId = nextOf.get(current.id)
        current = nextId ? nodeById.get(nextId) : undefined
      }
      if (run.length >= 2) {
        runs.push(run)
      } else {
        for (const member of run) inRun.delete(member.id)
      }
    }

    const runOf = new Map<string, IcfgNode[]>()
    for (const run of runs) {
      const runId = `run:${run[0].id}`
      if (expandedRuns.has(runId)) continue
      for (const member of run) runOf.set(member.id, run)
    }

    const emittedRuns = new Set<string>()
    for (const statement of statements) {
      const run = runOf.get(statement.id)
      if (run) {
        const runId = `run:${run[0].id}`
        canvasIdOf.set(statement.id, runId)
        if (!emittedRuns.has(runId)) {
          emittedRuns.add(runId)
          nodes.push({
            type: "condensed",
            id: runId,
            methodId,
            count: run.length,
            file: run[0].anchor.file,
            startLine: run[0].anchor.start_line,
            endLine: run[run.length - 1].anchor.end_line,
            memberIds: run.map((m) => m.id),
          })
        }
      } else {
        canvasIdOf.set(statement.id, `stmt:${statement.id}`)
        nodes.push({
          type: "statement",
          id: `stmt:${statement.id}`,
          methodId,
          icfgNode: statement,
        })
      }
    }

    for (const edge of intra) {
      const source = canvasIdOf.get(edge.source)
      const target = canvasIdOf.get(edge.target)
      if (!source || !target || source === target) continue
      pushEdge({
        id: `e:${edge.source}->${edge.target}`,
        source,
        target,
        kind: edge.kind,
        label: edgeLabel(edge),
        back: edge.back ?? false,
      })
    }
  }

  // ---- interprocedural call edges -------------------------------------------------
  for (const edge of icfg.edges ?? []) {
    if (edge.kind !== "call") continue
    const source = nodeById.get(edge.source)
    const target = nodeById.get(edge.target)
    if (!source || !target || target.kind !== "entry") continue
    const from = canvasIdOf.get(source.id) ?? `method:${source.method.id}`
    // Into the callee's first statement when expanded (entry isn't drawn).
    const calleeFirst = statementsByMethod.get(target.method.id)?.[0]
    const to =
      expandedMethods.has(target.method.id) && calleeFirst
        ? (canvasIdOf.get(calleeFirst.id) ?? `method:${target.method.id}`)
        : `method:${target.method.id}`
    if (from === to) continue
    pushEdge({
      id: `call:${from}->${to}`,
      source: from,
      target: to,
      kind: "call",
      label: null,
      back: false,
    })
  }

  // ---- lifted remote targets (ghost stubs) ---------------------------------------
  const ghostSeen = new Set<string>()
  for (const node of icfg.nodes) {
    const remoteIds = node.remote_call_ids ?? []
    if (remoteIds.length === 0) continue
    const from = canvasIdOf.get(node.id) ?? `method:${node.method.id}`
    for (const remoteCallId of remoteIds) {
      const item = edgesByRemoteCallId.get(remoteCallId)
      const label = item
        ? (item.target_service_name ??
          item.external_host ??
          (item.target_kind === "undetermined"
            ? "undetermined"
            : item.target_kind))
        : "unresolved call"
      const targetKind = item?.target_kind ?? "undetermined"
      const ghostId = `ghost:${item?.target_service_id ?? item?.external_host ?? remoteCallId}`
      if (!ghostSeen.has(ghostId)) {
        ghostSeen.add(ghostId)
        nodes.push({
          type: "ghost",
          id: ghostId,
          label,
          targetKind,
          confidence: item?.confidence ?? null,
          edgeId: item?.edge_id ?? null,
        })
      }
      pushEdge({
        id: `remote:${from}->${ghostId}`,
        source: from,
        target: ghostId,
        kind: "remote",
        label: item?.http_verb ?? null,
        back: false,
      })
    }
  }

  return { nodes, edges }
}

/** Arm labels on which a statement's control leaves its method (§5.2.8 T3).
 *
 * The assembler materializes the arm a construct takes when it ends its
 * method — "on false, the method returns" — as a labeled edge into the
 * method's synthetic exit. The canvas draws lanes rather than entry/exit
 * nodes, so that edge has nowhere to land and would silently disappear,
 * hiding the very thing the fix made visible. Surfaced on the node instead.
 *
 * Plain `flow` into exit is excluded: "this statement ends the method" is what
 * a lane's bottom edge already says. Only a NAMED arm carries new information.
 */
export function exitArms(icfg: Icfg): Map<string, IcfgEdge["kind"][]> {
  const nodeById = new Map(icfg.nodes.map((n) => [n.id, n]))
  const arms = new Map<string, IcfgEdge["kind"][]>()
  for (const edge of icfg.edges ?? []) {
    if (edge.kind === "flow" || edge.kind === "call" || edge.kind === "return")
      continue
    const source = nodeById.get(edge.source)
    const target = nodeById.get(edge.target)
    if (!source || !target) continue
    if (target.kind !== "exit" || source.method.id !== target.method.id)
      continue
    arms.set(source.id, [...(arms.get(source.id) ?? []), edge.kind])
  }
  return arms
}

/** What must be opened for a selection to become visible on the canvas. */
export type Reveal =
  { kind: "method"; id: string } | { kind: "run"; id: string }

/**
 * What must be drawn OPEN for `selectedNodeId` to appear on the canvas — or
 * null when the selection is already drawn under its own id.
 *
 * A selection can arrive from outside the canvas: a click on a line in the
 * source panel, a deep link, browser Back. Two things can hide it, and both
 * read to the user as a dead click — the URL says `stmt:…`, source highlights
 * the line, and nothing on the graph is ringed:
 *
 *  - the owning METHOD is collapsed to a summary card, so no statement of it
 *    is drawn at all;
 *  - the statement is inside a condensed RUN, which is drawn under the run's
 *    id. The selection ring keys on node id, so a member's id matches nothing.
 *
 * Resolution is one step at a time and converges: opening the method rebuilds
 * the graph, which may then reveal a run to open, which draws the statement.
 */
export function revealFor(
  graph: FlowGraph,
  icfg: Icfg,
  selectedNodeId: string | null | undefined
): Reveal | null {
  if (!selectedNodeId) return null
  const prefix = ["stmt:", "run:"].find((p) => selectedNodeId.startsWith(p))
  if (!prefix) return null
  const icfgId = selectedNodeId.slice(prefix.length)
  for (const node of graph.nodes) {
    if (node.type === "statement" && node.icfgNode.id === icfgId) return null
    if (node.type === "condensed" && node.memberIds.includes(icfgId)) {
      // Selecting the run node itself is a real selection of a drawn node;
      // only a member hiding inside it needs the run opened.
      return node.id === selectedNodeId ? null : { kind: "run", id: node.id }
    }
  }
  const methodId = icfg.nodes.find((n) => n.id === icfgId)?.method.id
  return methodId ? { kind: "method", id: methodId } : null
}
