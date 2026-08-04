import { describe, expect, test } from "vitest"

import { pathToEntry } from "@/lib/wadi/flow-path"

import { flowIcfg } from "./fixtures/flow-fixture"

describe("pathToEntry (§11 Phase 2.8)", () => {
  test("traces a witness path from a node back to the entry", () => {
    const path = pathToEntry(flowIcfg, "m1:c1")
    expect(path.nodeIds.has("m1:entry")).toBe(true)
    expect(path.nodeIds.has("m1:c1")).toBe(true)
    expect(path.nodeIds.has("m1:b1")).toBe(true)
    // The false-arm return is NOT on the witness path.
    expect(path.nodeIds.has("m1:r1")).toBe(false)
    expect(path.edgeKeys.has("m1:b1->m1:c1")).toBe(true)
  })

  test("crosses call edges into callees", () => {
    const path = pathToEntry(flowIcfg, "m2:s1")
    expect(path.nodeIds.has("m1:entry")).toBe(true)
    expect(path.nodeIds.has("m1:c1")).toBe(true)
    expect(path.edgeKeys.has("m1:c1->m2:entry")).toBe(true)
  })

  test("entry itself is a one-node path", () => {
    const path = pathToEntry(flowIcfg, "m1:entry")
    expect(path.nodeIds).toEqual(new Set(["m1:entry"]))
    expect(path.edgeKeys.size).toBe(0)
  })

  test("an unreachable node states so: just itself, no fabricated path", () => {
    const path = pathToEntry(flowIcfg, "no-such-node")
    expect(path.nodeIds).toEqual(new Set(["no-such-node"]))
    expect(path.edgeKeys.size).toBe(0)
  })
})
