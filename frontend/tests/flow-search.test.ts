import { describe, expect, test } from "vitest"

import { buildFlowGraph } from "@/lib/wadi/flow-graph"
import { searchFlow } from "@/lib/wadi/flow-search"

import { flowIcfg, flowRemoteEdges } from "./fixtures/flow-fixture"

const graph = buildFlowGraph(flowIcfg, flowRemoteEdges, new Set(), new Set())

describe("searchFlow (§11 Phase 2.8)", () => {
  test("matches statement text with its owning method (auto-expand target)", () => {
    const matches = searchFlow(flowIcfg, graph, "inventory.get")
    expect(matches).toHaveLength(1)
    expect(matches[0]).toMatchObject({
      id: "m1:c1",
      kind: "statement",
      methodId: "m_1",
    })
  })

  test("matches condition expressions", () => {
    const matches = searchFlow(flowIcfg, graph, "x > 0")
    expect(matches.some((m) => m.id === "m1:b1")).toBe(true)
  })

  test("matches method signatures and ghost labels", () => {
    expect(
      searchFlow(flowIcfg, graph, "B.help").some((m) => m.kind === "method")
    ).toBe(true)
    const ghosts = searchFlow(flowIcfg, graph, "inventory").filter(
      (m) => m.kind === "ghost"
    )
    expect(ghosts).toHaveLength(1)
    expect(ghosts[0].methodId).toBeNull()
  })

  test("searches the FULL closure, not just drawn nodes", () => {
    // m_2 is collapsed in `graph`, but its statement is still findable.
    const matches = searchFlow(flowIcfg, graph, "log.info")
    expect(matches).toHaveLength(1)
    expect(matches[0].methodId).toBe("m_2")
  })

  test("short queries return nothing", () => {
    expect(searchFlow(flowIcfg, graph, "a")).toEqual([])
  })
})
