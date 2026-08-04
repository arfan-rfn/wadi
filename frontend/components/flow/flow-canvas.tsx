"use client"

// The rebuilt flow canvas (§11 Phase 2.8). Architecture rules:
//  - Layout depends ONLY on the graph (never selection): clicking a node
//    re-renders subscribing nodes, not the canvas, and never re-runs ELK.
//  - Disclosure is React Flow's `hidden` prop (focus) + lane-cached layouts
//    (expand/collapse re-lays out one lane; the rest restack).
//  - All actions flow through the stable FlowActionsContext — no closures in
//    node `data`.
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Edge,
  type Node,
} from "@xyflow/react"
import { useTheme } from "next-themes"

import "@xyflow/react/dist/style.css"

import type { Icfg } from "@/lib/generated/icfg.schema"
import type { RemoteEdgesView } from "@/lib/generated/remote_edges_view.schema"
import { cn } from "@/lib/utils"
import { buildCallTree } from "@/lib/wadi/call-tree"
import { governingConditions } from "@/lib/wadi/conditions"
import {
  breadcrumbPath,
  focusMethodIds,
  hiddenNodeIds,
} from "@/lib/wadi/flow-focus"
import { buildFlowGraph, exitArms, type FlowGraph } from "@/lib/wadi/flow-graph"
import {
  layoutLanes,
  resolveExpandedMethods,
  type FlowLayout,
} from "@/lib/wadi/flow-lanes"
import { pathToEntry } from "@/lib/wadi/flow-path"
import { searchFlow } from "@/lib/wadi/flow-search"
import {
  useWorkspaceStore,
  useWorkspaceStoreApi,
  type ExpandState,
} from "@/components/endpoint/workspace-store"

import { CanvasToolbar } from "./canvas-toolbar"
import { FlowEdge } from "./edges/flow-edge"
import { FlowActionsContext, type FlowActions } from "./flow-chrome"
import { FocusBreadcrumb } from "./focus-breadcrumb"
import { CondensedNode } from "./nodes/condensed-node"
import { GhostNode } from "./nodes/ghost-node"
import { LaneNode, MethodNode } from "./nodes/method-lane"
import { StatementNode } from "./nodes/statement-node"

const nodeTypes = {
  method: MethodNode,
  lane: LaneNode,
  statement: StatementNode,
  condensed: CondensedNode,
  ghost: GhostNode,
}
const edgeTypes = { flow: FlowEdge }

function expandIntent(
  expand: ExpandState
): "default" | "all" | "none" | ReadonlySet<string> {
  return expand.mode === "explicit" ? expand.ids : expand.mode
}

/** ICFG node id → drawn canvas node id (statement, run, or method card). */
function buildCanvasIdMap(graph: FlowGraph, icfg: Icfg): Map<string, string> {
  const map = new Map<string, string>()
  const methodCard = new Map<string, string>()
  for (const node of graph.nodes) {
    if (node.type === "statement") map.set(node.icfgNode.id, node.id)
    else if (node.type === "condensed")
      for (const member of node.memberIds) map.set(member, node.id)
    else if (node.type === "method") methodCard.set(node.methodId, node.id)
  }
  for (const icfgNode of icfg.nodes) {
    if (!map.has(icfgNode.id)) {
      const card = methodCard.get(icfgNode.method.id)
      if (card) map.set(icfgNode.id, card)
    }
  }
  return map
}

export function FlowCanvas(props: {
  icfg: Icfg
  remoteEdges: RemoteEdgesView
}) {
  return (
    <ReactFlowProvider>
      <FlowCanvasInner {...props} />
    </ReactFlowProvider>
  )
}

function FlowCanvasInner({
  icfg,
  remoteEdges,
}: {
  icfg: Icfg
  remoteEdges: RemoteEdgesView
}) {
  const storeApi = useWorkspaceStoreApi()
  const expand = useWorkspaceStore((s) => s.expand)
  const expandedRuns = useWorkspaceStore((s) => s.expandedRuns)
  const focusMethodId = useWorkspaceStore((s) => s.focusMethodId)
  const traceEnabled = useWorkspaceStore((s) => s.traceEnabled)
  const search = useWorkspaceStore((s) => s.search)
  // Subscribed ONLY because trace + zoom-to-selection need it; with trace off
  // this changes nothing in the node/edge arrays below.
  const selectedNodeId = useWorkspaceStore((s) => s.selectedNodeId)
  const { resolvedTheme } = useTheme()
  const reactFlow = useReactFlow()
  const wrapperRef = useRef<HTMLDivElement>(null)

  const resolvedExpanded = useMemo(
    () => resolveExpandedMethods(expandIntent(expand), icfg),
    [expand, icfg]
  )
  const graph = useMemo(
    () => buildFlowGraph(icfg, remoteEdges, resolvedExpanded, expandedRuns),
    [icfg, remoteEdges, resolvedExpanded, expandedRuns]
  )
  const conditions = useMemo(() => governingConditions(icfg), [icfg])
  const armsToExit = useMemo(() => exitArms(icfg), [icfg])
  const tree = useMemo(() => buildCallTree(icfg), [icfg])
  const canvasIdByIcfgId = useMemo(
    () => buildCanvasIdMap(graph, icfg),
    [graph, icfg]
  )

  // --- layout: keyed on the graph alone -------------------------------------------
  const [layoutState, setLayoutState] = useState<{
    graph: FlowGraph
    layout: FlowLayout
  } | null>(null)
  useEffect(() => {
    let cancelled = false
    void layoutLanes(graph, icfg).then((layout) => {
      if (!cancelled) setLayoutState({ graph, layout })
    })
    return () => {
      cancelled = true
    }
  }, [graph, icfg])

  // --- focus / trace overlays ------------------------------------------------------
  const visibleMethods = useMemo(
    () => (focusMethodId ? focusMethodIds(tree, focusMethodId) : null),
    [tree, focusMethodId]
  )
  const hidden = useMemo(
    () => hiddenNodeIds(graph, visibleMethods),
    [graph, visibleMethods]
  )
  const traceNodes = useMemo(() => {
    if (!traceEnabled || !selectedNodeId) return null
    let icfgId: string | null = null
    if (selectedNodeId.startsWith("stmt:"))
      icfgId = selectedNodeId.slice("stmt:".length)
    else if (selectedNodeId.startsWith("run:"))
      icfgId = selectedNodeId.slice("run:".length)
    else if (selectedNodeId.startsWith("method:")) {
      const methodId = selectedNodeId.slice("method:".length)
      icfgId =
        icfg.nodes.find((n) => n.kind === "entry" && n.method.id === methodId)
          ?.id ?? null
    }
    if (!icfgId) return null
    const path = pathToEntry(icfg, icfgId)
    const hot = new Set<string>()
    for (const nodeId of path.nodeIds) {
      const canvasId = canvasIdByIcfgId.get(nodeId)
      if (canvasId) hot.add(canvasId)
    }
    return hot
  }, [traceEnabled, selectedNodeId, icfg, canvasIdByIcfgId])

  const traceStateOf = useCallback(
    (canvasId: string): "hot" | "dim" | null =>
      traceNodes ? (traceNodes.has(canvasId) ? "hot" : "dim") : null,
    [traceNodes]
  )

  // --- React Flow arrays -----------------------------------------------------------
  const rfNodes = useMemo<Node[]>(() => {
    if (!layoutState || layoutState.graph !== graph) return []
    const { layout } = layoutState
    const nodes: Node[] = []
    for (const lane of layout.lanes) {
      if (lane.collapsed) continue
      const laneHidden =
        visibleMethods !== null && !visibleMethods.has(lane.methodId)
      nodes.push({
        id: `lane:${lane.methodId}`,
        type: "lane",
        position: { x: lane.x, y: lane.y },
        data: {
          methodId: lane.methodId,
          signature: lane.signature,
          isRoot: tree?.methodId === lane.methodId,
          width: lane.width,
          height: lane.height,
        },
        hidden: laneHidden,
        selectable: false,
        draggable: false,
        // Lane containers sit behind their statements but still above the
        // canvas background (never a negative index).
        zIndex: 0,
      })
    }
    for (const node of graph.nodes) {
      const position = layoutState.layout.positions.get(node.id)
      if (!position) continue
      const base = {
        id: node.id,
        position: { x: position.x, y: position.y },
        hidden: hidden.has(node.id),
        draggable: false,
        selectable: false,
        zIndex: 1,
      }
      if (node.type === "method") {
        nodes.push({
          ...base,
          type: "method",
          data: {
            methodId: node.methodId,
            signature: node.rollup.signature,
            isRoot: node.isRoot,
            statementCount: node.rollup.statementCount,
            branchCount: node.rollup.branchCount,
            loopCount: node.rollup.loopCount,
            sinks: node.rollup.sinks,
            badges: node.rollup.badges,
            trace: traceStateOf(node.id),
          },
        })
      } else if (node.type === "statement") {
        nodes.push({
          ...base,
          type: "statement",
          data: {
            icfgNodeId: node.icfgNode.id,
            methodId: node.methodId,
            sourceText: node.icfgNode.source_text,
            file: node.icfgNode.anchor.file,
            line: node.icfgNode.anchor.start_line,
            kind: node.icfgNode.kind,
            constructKind: node.icfgNode.construct_kind ?? null,
            conditionExpression: node.icfgNode.condition?.expression ?? null,
            sink: node.icfgNode.sink ?? null,
            unopenableReason: node.icfgNode.callee_unbound_reason ?? null,
            exitArms: armsToExit.get(node.icfgNode.id) ?? [],
            hasRemote: (node.icfgNode.remote_call_ids ?? []).length > 0,
            conditions: conditions.get(node.icfgNode.id) ?? [],
            trace: traceStateOf(node.id),
          },
        })
      } else if (node.type === "condensed") {
        nodes.push({
          ...base,
          type: "condensed",
          data: {
            runId: node.id,
            methodId: node.methodId,
            count: node.count,
            file: node.file,
            startLine: node.startLine,
            endLine: node.endLine,
            trace: traceStateOf(node.id),
          },
        })
      } else {
        const verbs = [
          ...new Set(
            graph.edges
              .filter((e) => e.kind === "remote" && e.target === node.id)
              .map((e) => e.label)
              .filter((v): v is string => v !== null)
          ),
        ]
        const ghostConditions = graph.edges
          .filter((e) => e.kind === "remote" && e.target === node.id)
          .flatMap((e) => {
            const source = graph.nodes.find((n) => n.id === e.source)
            if (source?.type !== "statement") return []
            return conditions.get(source.icfgNode.id) ?? []
          })
        nodes.push({
          ...base,
          type: "ghost",
          data: {
            label: node.label,
            targetKind: node.targetKind,
            confidence: node.confidence,
            verbs,
            conditions: ghostConditions.slice(0, 2),
            trace: traceStateOf(node.id),
          },
        })
      }
    }
    return nodes
  }, [
    layoutState,
    graph,
    hidden,
    visibleMethods,
    conditions,
    tree,
    traceStateOf,
  ])

  const rfEdges = useMemo<Edge[]>(() => {
    if (!layoutState || layoutState.graph !== graph) return []
    return graph.edges.map((edge) => {
      const handles = edge.back
        ? { sourceHandle: "s-right", targetHandle: "t-right" }
        : edge.kind === "call"
          ? { sourceHandle: "s-left", targetHandle: "t-left" }
          : edge.kind === "remote"
            ? { sourceHandle: "s-right", targetHandle: "t-left" }
            : { sourceHandle: "s-bottom", targetHandle: "t-top" }
      const bothHot =
        traceNodes !== null &&
        traceNodes !== undefined &&
        traceNodes.has(edge.source) &&
        traceNodes.has(edge.target)
      return {
        id: edge.id,
        source: edge.source,
        target: edge.target,
        type: "flow" as const,
        ...handles,
        hidden: hidden.has(edge.source) || hidden.has(edge.target),
        data: {
          kind: edge.kind,
          label: edge.label,
          back: edge.back,
          trace: traceNodes
            ? bothHot
              ? ("hot" as const)
              : ("dim" as const)
            : null,
        },
      }
    })
  }, [layoutState, graph, hidden, traceNodes])

  // --- stable actions --------------------------------------------------------------
  const resolvedExpandedRef = useRef(resolvedExpanded)
  useEffect(() => {
    resolvedExpandedRef.current = resolvedExpanded
  }, [resolvedExpanded])
  const actions = useMemo<FlowActions>(
    () => ({
      selectNode: (id) => {
        const state = storeApi.getState()
        state.selectNode(id)
        state.setInspectorTab("selection")
      },
      toggleMethod: (methodId) =>
        storeApi.getState().toggleMethod(methodId, resolvedExpandedRef.current),
      expandRun: (runId) => storeApi.getState().toggleRun(runId),
      focusMethod: (methodId) => storeApi.getState().setFocus(methodId),
      revealSource: (file, line) =>
        storeApi.getState().revealSource(file, line),
    }),
    [storeApi]
  )

  // --- search ----------------------------------------------------------------------
  const matches = useMemo(
    () => searchFlow(icfg, graph, search),
    [icfg, graph, search]
  )
  const [activeMatch, setActiveMatch] = useState(0)
  const [resolveTick, setResolveTick] = useState(0)
  useEffect(() => setActiveMatch(0), [search])
  const pendingSelectRef = useRef<string | null>(null)

  const goToMatch = useCallback(
    (index: number) => {
      const match = matches[index]
      if (!match) return
      setActiveMatch(index)
      if (match.kind === "ghost" || match.kind === "method") {
        const canvasId =
          match.kind === "ghost" ? match.id : `method:${match.methodId}`
        // Method cards disappear when expanded — fall back to the lane's first node.
        pendingSelectRef.current =
          match.kind === "method" ? `m:${match.methodId}` : canvasId
      } else {
        pendingSelectRef.current = `i:${match.id}`
        if (
          match.methodId &&
          !resolvedExpandedRef.current.has(match.methodId)
        ) {
          storeApi
            .getState()
            .setExplicitExpand([...resolvedExpandedRef.current, match.methodId])
        }
      }
      // Resolution happens in the effect below once the graph reflects the
      // expansion (or immediately if it already does).
      setResolveTick((t) => t + 1)
    },
    [matches, storeApi]
  )

  useEffect(() => {
    const pending = pendingSelectRef.current
    if (!pending) return
    let canvasId: string | null = null
    if (pending.startsWith("i:"))
      canvasId = canvasIdByIcfgId.get(pending.slice(2)) ?? null
    else if (pending.startsWith("m:")) {
      const methodId = pending.slice(2)
      canvasId =
        graph.nodes.find((n) => n.type === "method" && n.methodId === methodId)
          ?.id ??
        graph.nodes.find((n) => n.type !== "ghost" && n.methodId === methodId)
          ?.id ??
        null
    } else canvasId = pending
    if (!canvasId) return
    pendingSelectRef.current = null
    actions.selectNode(canvasId)
  }, [canvasIdByIcfgId, graph, actions, resolveTick])

  const stepMatch = useCallback(
    (direction: 1 | -1) => {
      if (matches.length === 0) return
      goToMatch((activeMatch + direction + matches.length) % matches.length)
    },
    [matches.length, activeMatch, goToMatch]
  )

  // --- initial viewport: top of the document, 1:1 ----------------------------------
  // NOT fitView. The lanes stack tall by design; fitting the whole height would
  // zoom a 17-method flow down to unreadable. Open at the top at 1:1 (only
  // zooming OUT if the columns are wider than the pane) and let the user scroll
  // it like a document — the whole point of the lanes layout.
  const didInitialViewport = useRef(false)
  useEffect(() => {
    if (didInitialViewport.current || !layoutState) return
    const wrapper = wrapperRef.current
    if (!wrapper || wrapper.clientWidth === 0) return
    didInitialViewport.current = true
    const margin = 24
    const zoom = Math.min(
      1,
      (wrapper.clientWidth - margin * 2) / Math.max(layoutState.layout.width, 1)
    )
    void reactFlow.setViewport({ x: margin, y: margin, zoom })
  }, [layoutState, reactFlow])

  // --- zoom to selection when offscreen -------------------------------------------
  useEffect(() => {
    if (!selectedNodeId || !layoutState) return
    let position = layoutState.layout.positions.get(selectedNodeId)
    if (!position && selectedNodeId.startsWith("method:")) {
      // The method is expanded (no card drawn) — center on its lane instead.
      const lane = layoutState.layout.lanes.find(
        (l) => l.methodId === selectedNodeId.slice("method:".length)
      )
      if (lane)
        position = {
          id: selectedNodeId,
          x: lane.x,
          y: lane.y,
          width: lane.width,
          height: Math.min(lane.height, 400),
        }
    }
    const wrapper = wrapperRef.current
    if (!position || !wrapper) return
    const viewport = reactFlow.getViewport()
    const cx = (position.x + position.width / 2) * viewport.zoom + viewport.x
    const cy = (position.y + position.height / 2) * viewport.zoom + viewport.y
    const margin = 40
    const outside =
      cx < margin ||
      cy < margin ||
      cx > wrapper.clientWidth - margin ||
      cy > wrapper.clientHeight - margin
    if (outside) {
      void reactFlow.setCenter(
        position.x + position.width / 2,
        position.y + position.height / 2,
        { zoom: Math.max(viewport.zoom, 0.85), duration: 300 }
      )
    }
  }, [selectedNodeId, layoutState, reactFlow])

  // --- keyboard --------------------------------------------------------------------
  const executionOrder = useMemo(() => {
    if (!layoutState || layoutState.graph !== graph) return []
    return graph.nodes
      .filter((n) => n.type !== "ghost" && !hidden.has(n.id))
      .map((n) => ({
        id: n.id,
        y: layoutState.layout.positions.get(n.id)?.y ?? 0,
      }))
      .sort((a, b) => a.y - b.y)
      .map((n) => n.id)
  }, [layoutState, graph, hidden])

  const onKeyDown = useCallback(
    (event: React.KeyboardEvent) => {
      const state = storeApi.getState()
      if (
        event.key === "/" &&
        !(event.target as HTMLElement).closest("input")
      ) {
        event.preventDefault()
        wrapperRef.current
          ?.querySelector<HTMLInputElement>("input[data-flow-search]")
          ?.focus()
        return
      }
      if ((event.target as HTMLElement).closest("input")) return
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault()
        if (executionOrder.length === 0) return
        const index = state.selectedNodeId
          ? executionOrder.indexOf(state.selectedNodeId)
          : -1
        const next =
          event.key === "ArrowDown"
            ? Math.min(index + 1, executionOrder.length - 1)
            : Math.max(index - 1, 0)
        actions.selectNode(executionOrder[next])
      } else if (event.key === "Enter" && state.selectedNodeId) {
        event.preventDefault()
        if (state.selectedNodeId.startsWith("method:"))
          actions.toggleMethod(state.selectedNodeId.slice("method:".length))
        else if (state.selectedNodeId.startsWith("run:"))
          actions.expandRun(state.selectedNodeId)
      } else if (event.key === "f" && state.selectedNodeId) {
        const node = graph.nodes.find((n) => n.id === state.selectedNodeId)
        if (node && node.type !== "ghost") actions.focusMethod(node.methodId)
      } else if (event.key === "Escape") {
        if (state.search) state.setSearch("")
        else if (state.focusMethodId) state.setFocus(null)
        else state.selectNode(null)
      }
    },
    [storeApi, executionOrder, actions, graph]
  )

  // --- zoom-simplified bucket ------------------------------------------------------
  const [simplified, setSimplified] = useState(false)
  const onMove = useCallback(() => {
    const zoom = reactFlow.getViewport().zoom
    setSimplified((prev) => (zoom < 0.5 ? true : zoom > 0.55 ? false : prev))
  }, [reactFlow])

  const crumbs = useMemo(
    () => (focusMethodId ? breadcrumbPath(tree, focusMethodId) : []),
    [tree, focusMethodId]
  )

  return (
    <FlowActionsContext.Provider value={actions}>
      <div
        className={cn(
          "flex h-full w-full flex-col",
          simplified && "zoom-simplified"
        )}
      >
        {/* Canvas chrome lives in its own bar — a floating overlay would
            occlude the top of a surface the user scrolls like a document. */}
        <div className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1.5 border-b px-3 py-1.5">
          <CanvasToolbar
            search={search}
            onSearch={(q) => storeApi.getState().setSearch(q)}
            matches={matches}
            activeMatch={activeMatch}
            onStep={stepMatch}
            traceEnabled={traceEnabled}
            onTrace={(enabled) => storeApi.getState().setTraceEnabled(enabled)}
            projectedFullCount={icfg.nodes.length}
            onExpandAll={() => storeApi.getState().expandAll()}
            onCollapseAll={() => storeApi.getState().collapseAll()}
            onExpandDepth1={() =>
              storeApi
                .getState()
                .setExplicitExpand(
                  tree
                    ? [tree.methodId, ...tree.children.map((c) => c.methodId)]
                    : []
                )
            }
          />
          {crumbs.length > 0 ? (
            <FocusBreadcrumb
              path={crumbs}
              onFocus={(methodId) => storeApi.getState().setFocus(methodId)}
              onClear={() => storeApi.getState().setFocus(null)}
            />
          ) : null}
        </div>
        <div
          ref={wrapperRef}
          tabIndex={0}
          onKeyDown={onKeyDown}
          className="relative min-h-0 flex-1 outline-none"
        >
          <ReactFlow
            nodes={rfNodes}
            edges={rfEdges}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            colorMode={resolvedTheme === "dark" ? "dark" : "light"}
            minZoom={0.1}
            maxZoom={1.75}
            nodesDraggable={false}
            nodesConnectable={false}
            elementsSelectable={false}
            onlyRenderVisibleElements={rfNodes.length > 300}
            onPaneClick={() => storeApi.getState().selectNode(null)}
            onMove={onMove}
            proOptions={{ hideAttribution: true }}
          >
            <Background gap={18} />
            <Controls showInteractive={false} />
            <MiniMap
              pannable
              zoomable
              className="!h-40 !w-56"
              nodeColor={(node) =>
                node.type === "ghost"
                  ? "var(--flow-remote)"
                  : node.type === "method" || node.type === "lane"
                    ? "var(--muted-foreground)"
                    : "var(--border)"
              }
              maskColor="color-mix(in oklch, var(--background) 70%, transparent)"
            />
          </ReactFlow>
        </div>
      </div>
    </FlowActionsContext.Provider>
  )
}
