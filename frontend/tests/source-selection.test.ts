// §11 Phase 2.8: the 1:1 graph↔source mapping.
//
// The complaint this answers is that navigating the graph told you nothing
// about the code: selection had to be followed by an explicit "open in
// source", and what you got was a one-line flash that faded. Selecting a
// METHOD must light its whole body, because "show me this method" is the
// question that was asked.
import { describe, expect, it } from "vitest"

import type { Icfg } from "@/lib/generated/icfg.schema"
import { sourceSelectionFor } from "@/lib/wadi/source-map"

type IcfgNode = Icfg["nodes"][number]

function node(
  id: string,
  kind: IcfgNode["kind"],
  methodId: string,
  file: string,
  start: number,
  end = start
): IcfgNode {
  return {
    id,
    kind,
    anchor: { file, start_line: start, end_line: end, variant: "original" },
    source_text: id,
    method: { id: methodId, signature: `${methodId}()`, file },
  } as IcfgNode
}

const ICFG = {
  snapshot_id: "s",
  service_id: "v",
  endpoint_id: "e",
  entry_node_id: "m1:entry",
  nodes: [
    node("m1:entry", "entry", "m1", "A.java", 10),
    node("m1:n1", "statement", "m1", "A.java", 11),
    node("m1:n2", "branch", "m1", "A.java", 12, 15),
    node("m1:exit", "exit", "m1", "A.java", 18),
    node("m2:entry", "entry", "m2", "B.java", 40),
    node("m2:n1", "statement", "m2", "B.java", 41),
    node("m2:exit", "exit", "m2", "B.java", 44),
  ],
  edges: [],
} as Icfg

describe("sourceSelectionFor", () => {
  it("selects a method's WHOLE body, declaration through closing brace", () => {
    expect(sourceSelectionFor(ICFG, "method:m1")).toEqual({
      file: "A.java",
      startLine: 10,
      endLine: 18,
      focusLine: 10,
    })
  })

  it("selects exactly a statement's own extent, not its method's", () => {
    // A branch spanning 12–15 highlights those four lines — enough to see the
    // construct, never the surrounding method.
    expect(sourceSelectionFor(ICFG, "stmt:m1:n2")).toEqual({
      file: "A.java",
      startLine: 12,
      endLine: 15,
      focusLine: 12,
    })
  })

  it("scopes a method to its own file", () => {
    expect(sourceSelectionFor(ICFG, "method:m2")?.file).toBe("B.java")
  })

  it("resolves a condensed run through its head node", () => {
    expect(sourceSelectionFor(ICFG, "run:m1:n1")).toEqual({
      file: "A.java",
      startLine: 11,
      endLine: 11,
      focusLine: 11,
    })
  })

  it("returns null for selections with no source of their own", () => {
    // A remote-target ghost is real, but it is not in this repo. The caller
    // leaves the previous highlight alone rather than blanking the panel.
    expect(sourceSelectionFor(ICFG, "ghost:svc-b")).toBeNull()
    expect(sourceSelectionFor(ICFG, "stmt:nope")).toBeNull()
    expect(sourceSelectionFor(ICFG, null)).toBeNull()
    expect(sourceSelectionFor(undefined, "method:m1")).toBeNull()
  })
})
