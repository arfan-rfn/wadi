import { describe, expect, test } from "vitest"

import { buildFlowGraph } from "@/lib/wadi/flow-graph"
import {
  DEFAULT_EXPAND_STATEMENT_BUDGET,
  GUTTER_WIDTH,
  laneOrder,
  layoutLanes,
  resolveExpandedMethods,
} from "@/lib/wadi/flow-lanes"

import { flowIcfg, flowRemoteEdges } from "./fixtures/flow-fixture"

describe("laneOrder (§11 Phase 2.8)", () => {
  test("callee lanes follow their caller (DFS preorder)", () => {
    expect(laneOrder(flowIcfg)).toEqual(["m_1", "m_2"])
  })
})

describe("resolveExpandedMethods", () => {
  test("default expands only the entry handler", () => {
    expect(resolveExpandedMethods("default", flowIcfg)).toEqual(
      new Set(["m_1"])
    )
  })

  test("default falls back to collapsed above the statement budget", () => {
    const big = {
      ...flowIcfg,
      nodes: [
        ...flowIcfg.nodes,
        ...Array.from(
          { length: DEFAULT_EXPAND_STATEMENT_BUDGET + 1 },
          (_, i) => ({
            ...flowIcfg.nodes[1],
            id: `m1:pad${i}`,
          })
        ),
      ],
    } as unknown as typeof flowIcfg
    expect(resolveExpandedMethods("default", big)).toEqual(new Set())
  })

  test("all / none / explicit resolve literally", () => {
    expect(resolveExpandedMethods("all", flowIcfg)).toEqual(
      new Set(["m_1", "m_2"])
    )
    expect(resolveExpandedMethods("none", flowIcfg)).toEqual(new Set())
    expect(resolveExpandedMethods(new Set(["m_2"]), flowIcfg)).toEqual(
      new Set(["m_2"])
    )
  })
})

describe("layoutLanes", () => {
  test("happens-before: the callee lane sits strictly below the caller", async () => {
    const graph = buildFlowGraph(
      flowIcfg,
      flowRemoteEdges,
      new Set(["m_1"]),
      new Set()
    )
    const layout = await layoutLanes(graph, flowIcfg)
    const caller = layout.lanes.find((l) => l.methodId === "m_1")
    const callee = layout.lanes.find((l) => l.methodId === "m_2")
    expect(caller).toBeDefined()
    expect(callee).toBeDefined()
    expect(callee!.y).toBeGreaterThan(caller!.y + caller!.height)
  })

  test("statements stack in source order inside a lane", async () => {
    const graph = buildFlowGraph(
      flowIcfg,
      flowRemoteEdges,
      new Set(["m_1"]),
      new Set()
    )
    const layout = await layoutLanes(graph, flowIcfg)
    const branchY = layout.positions.get("stmt:m1:b1")?.y
    const callY = layout.positions.get("stmt:m1:c1")?.y
    const returnY = layout.positions.get("stmt:m1:r1")?.y
    expect(branchY).toBeDefined()
    expect(callY).toBeDefined()
    expect(returnY).toBeDefined()
    expect(callY!).toBeGreaterThan(branchY!)
    expect(returnY!).toBeGreaterThan(branchY!)
  })

  test("every lane node clears the call gutter column", async () => {
    const graph = buildFlowGraph(
      flowIcfg,
      flowRemoteEdges,
      new Set(["m_1"]),
      new Set()
    )
    const layout = await layoutLanes(graph, flowIcfg)
    for (const lane of layout.lanes) {
      expect(lane.x).toBeGreaterThanOrEqual(GUTTER_WIDTH)
    }
  })

  test("the ghost rail pins targets at their call-site height, right of every lane", async () => {
    const graph = buildFlowGraph(
      flowIcfg,
      flowRemoteEdges,
      new Set(["m_1"]),
      new Set()
    )
    const layout = await layoutLanes(graph, flowIcfg)
    const ghost = [...layout.positions.values()].find((p) =>
      p.id.startsWith("ghost:")
    )
    const callSite = layout.positions.get("stmt:m1:c1")
    expect(ghost).toBeDefined()
    expect(callSite).toBeDefined()
    expect(ghost!.x).toBe(layout.railX)
    for (const lane of layout.lanes) {
      expect(layout.railX).toBeGreaterThan(lane.x + lane.width)
    }
    expect(ghost!.y).toBe(callSite!.y)
  })

  test("layout is deterministic", async () => {
    const graph = buildFlowGraph(
      flowIcfg,
      flowRemoteEdges,
      new Set(["m_1"]),
      new Set()
    )
    const a = await layoutLanes(graph, flowIcfg)
    const b = await layoutLanes(graph, flowIcfg)
    expect([...a.positions.entries()]).toEqual([...b.positions.entries()])
  })

  test("collapsed view still shows every method and the ghost rail", async () => {
    const graph = buildFlowGraph(
      flowIcfg,
      flowRemoteEdges,
      new Set(),
      new Set()
    )
    const layout = await layoutLanes(graph, flowIcfg)
    expect(layout.lanes).toHaveLength(2)
    expect(layout.lanes.every((l) => l.collapsed)).toBe(true)
    expect(
      [...layout.positions.keys()].some((id) => id.startsWith("ghost:"))
    ).toBe(true)
  })
})
