import { describe, expect, test } from "vitest"

import { buildCallTree } from "@/lib/wadi/call-tree"
import {
  breadcrumbPath,
  focusMethodIds,
  hiddenNodeIds,
} from "@/lib/wadi/flow-focus"
import { buildFlowGraph } from "@/lib/wadi/flow-graph"

import { flowIcfg, flowRemoteEdges } from "./fixtures/flow-fixture"

describe("focus / re-root (§11 Phase 2.8)", () => {
  const tree = buildCallTree(flowIcfg)

  test("focus collects the method and its call-tree descendants", () => {
    expect(focusMethodIds(tree, "m_1")).toEqual(new Set(["m_1", "m_2"]))
    expect(focusMethodIds(tree, "m_2")).toEqual(new Set(["m_2"]))
  })

  test("breadcrumb is the call path from the root", () => {
    expect(breadcrumbPath(tree, null).map((n) => n.methodId)).toEqual(["m_1"])
    expect(breadcrumbPath(tree, "m_2").map((n) => n.methodId)).toEqual([
      "m_1",
      "m_2",
    ])
  })

  test("focusing m_2 hides m_1's nodes and its now-unreachable ghost", () => {
    const graph = buildFlowGraph(
      flowIcfg,
      flowRemoteEdges,
      new Set(),
      new Set()
    )
    const hidden = hiddenNodeIds(graph, focusMethodIds(tree, "m_2"))
    expect(hidden.has("method:m_1")).toBe(true)
    expect(hidden.has("method:m_2")).toBe(false)
    // The ghost's only caller (m_1's call site) is hidden → the ghost hides
    // with it; it is NOT dropped when any visible node still reaches it.
    const ghostId = [...hidden].find((id) => id.startsWith("ghost:"))
    expect(ghostId).toBeDefined()
  })

  test("no focus hides nothing", () => {
    const graph = buildFlowGraph(
      flowIcfg,
      flowRemoteEdges,
      new Set(),
      new Set()
    )
    expect(hiddenNodeIds(graph, null).size).toBe(0)
  })

  test("ghost stays visible while any caller is visible (P10)", () => {
    const graph = buildFlowGraph(
      flowIcfg,
      flowRemoteEdges,
      new Set(),
      new Set()
    )
    const hidden = hiddenNodeIds(graph, focusMethodIds(tree, "m_1"))
    expect([...hidden].some((id) => id.startsWith("ghost:"))).toBe(false)
  })
})
