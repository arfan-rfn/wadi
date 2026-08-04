import { describe, expect, test } from "vitest"

import { buildFlowGraph } from "@/lib/wadi/flow-graph"
import {
  DEFAULT_EXPAND_STATEMENT_BUDGET,
  FRAMING_MIN_ZOOM,
  framingFor,
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

describe("framingFor — the graph owes source the same guarantee", () => {
  const PANE = { width: 800, height: 600 }
  const CARD = { x: 100, y: 100, width: 240, height: 72 }
  const AT_ORIGIN = { x: 0, y: 0, zoom: 1 }

  test("leaves the viewport alone when the node is wholly in frame", () => {
    expect(framingFor(CARD, AT_ORIGIN, PANE)).toBeNull()
  })

  test("frames a node that is entirely off screen", () => {
    const framing = framingFor(
      { x: 100, y: 4000, width: 240, height: 72 },
      AT_ORIGIN,
      PANE
    )
    expect(framing).toEqual({ x: 220, y: 4036, zoom: 1 })
  })

  test("frames a node that is only PARTIALLY cut off", () => {
    // The regression: the old rule tested the node's CENTRE, so a tall lane
    // whose middle sat inside the pane counted as visible while 100px of it
    // hung past the bottom. Click a line in source, the graph does not move,
    // and the node you were sent to is cut off.
    const laneHangingBelow = { x: 100, y: 300, width: 400, height: 400 }
    const centre = laneHangingBelow.y + laneHangingBelow.height / 2
    expect(centre).toBeLessThan(PANE.height - 40) // old rule: "visible"
    expect(laneHangingBelow.y + laneHangingBelow.height).toBeGreaterThan(
      PANE.height
    ) // but 100px is off screen
    expect(framingFor(laneHangingBelow, AT_ORIGIN, PANE)).not.toBeNull()
  })

  test("frames a lane whose header has scrolled above the pane", () => {
    // Same failure at the other edge: the identity is in the header, and the
    // header is what has gone off screen.
    const headerAbove = { x: 100, y: -100, width: 400, height: 400 }
    const centre = headerAbove.y + headerAbove.height / 2
    expect(centre).toBeGreaterThan(40) // old rule: "visible"
    expect(framingFor(headerAbove, AT_ORIGIN, PANE)).not.toBeNull()
  })

  test("respects the pane's margin at every edge", () => {
    for (const node of [
      { x: 10, y: 300, width: 240, height: 72 }, // clipped left
      { x: 100, y: 10, width: 240, height: 72 }, // clipped top
      { x: 700, y: 300, width: 240, height: 72 }, // clipped right
      { x: 100, y: 580, width: 240, height: 72 }, // clipped bottom
    ]) {
      expect(framingFor(node, AT_ORIGIN, PANE)).not.toBeNull()
    }
  })

  test("accounts for pan and zoom, not just raw coordinates", () => {
    // Same node, same pane — visible only because the viewport is panned to it.
    const far = { x: 2000, y: 2000, width: 240, height: 72 }
    expect(framingFor(far, AT_ORIGIN, PANE)).not.toBeNull()
    expect(framingFor(far, { x: -1900, y: -1900, zoom: 1 }, PANE)).toBeNull()
  })

  test("never zooms further out than the readable floor", () => {
    const framing = framingFor(
      { x: 100, y: 4000, width: 240, height: 72 },
      { x: 0, y: 0, zoom: 0.2 },
      PANE
    )
    expect(framing?.zoom).toBe(FRAMING_MIN_ZOOM)
  })

  test("keeps a zoomed-in view zoomed in", () => {
    const framing = framingFor(
      { x: 100, y: 4000, width: 240, height: 72 },
      { x: 0, y: 0, zoom: 1.5 },
      PANE
    )
    expect(framing?.zoom).toBe(1.5)
  })

  test("frames the TOP of something taller than the pane", () => {
    // A long lane can never be framed whole; its header carries the identity,
    // so centring on its middle would land a hundred statements in.
    const lane = { x: 100, y: 1000, width: 400, height: 4000 }
    const framing = framingFor(lane, AT_ORIGIN, PANE)
    expect(framing).not.toBeNull()
    // Centred on the first pane-height of the lane, not on y + 2000.
    expect(framing!.y).toBeLessThan(lane.y + PANE.height)
    expect(framing!.y).toBeGreaterThan(lane.y)
  })

  test("does nothing while the pane has no size (pre-layout)", () => {
    expect(framingFor(CARD, AT_ORIGIN, { width: 0, height: 0 })).toBeNull()
  })
})
