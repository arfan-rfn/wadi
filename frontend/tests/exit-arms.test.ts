// §5.2.8 T3: an arm that ends the method must survive the trip to the canvas.
//
// The assembler materializes "on false, the method returns" as a labeled edge
// into the method's synthetic exit. The canvas draws lanes rather than
// entry/exit nodes and drops every edge into exit — so without this the fix
// would be correct in the contract and invisible in the product.
import { describe, expect, it } from "vitest"

import type { Icfg } from "@/lib/generated/icfg.schema"
import { exitArms } from "@/lib/wadi/flow-graph"

type IcfgNode = Icfg["nodes"][number]
type IcfgEdge = NonNullable<Icfg["edges"]>[number]

const METHOD = { id: "m1", signature: "handle()", file: "A.java" }

function node(id: string, kind: IcfgNode["kind"]): IcfgNode {
  return {
    id,
    kind,
    anchor: { file: "A.java", start_line: 1, end_line: 1, variant: "original" },
    source_text: id,
    method: METHOD,
  } as IcfgNode
}

function icfg(nodes: IcfgNode[], edges: IcfgEdge[]): Icfg {
  return {
    snapshot_id: "s",
    service_id: "v",
    endpoint_id: "e",
    entry_node_id: "entry",
    nodes,
    edges,
  } as Icfg
}

describe("exitArms", () => {
  it("surfaces a branch arm that leaves the method", () => {
    const graph = icfg(
      [
        node("entry", "entry"),
        node("b", "branch"),
        node("t", "statement"),
        node("exit", "exit"),
      ],
      [
        { source: "b", target: "t", kind: "true" },
        { source: "b", target: "exit", kind: "false" },
      ] as IcfgEdge[]
    )
    expect(exitArms(graph).get("b")).toEqual(["false"])
  })

  it("ignores plain flow into exit — the lane already says that", () => {
    // Every terminal statement edges to exit; chipping all of them would bury
    // the one arm that carries new information.
    const graph = icfg(
      [node("entry", "entry"), node("r", "return"), node("exit", "exit")],
      [{ source: "r", target: "exit", kind: "flow" }] as IcfgEdge[]
    )
    expect(exitArms(graph).size).toBe(0)
  })

  it("reports a default-less switch's no-match path", () => {
    const graph = icfg(
      [
        node("entry", "entry"),
        node("s", "branch"),
        node("a", "statement"),
        node("exit", "exit"),
      ],
      [
        { source: "s", target: "a", kind: "case" },
        { source: "s", target: "exit", kind: "default" },
      ] as IcfgEdge[]
    )
    expect(exitArms(graph).get("s")).toEqual(["default"])
  })

  it("never attributes another method's exit", () => {
    const other = node("exit2", "exit")
    other.method = { ...METHOD, id: "m2" }
    const graph = icfg([node("entry", "entry"), node("b", "branch"), other], [
      { source: "b", target: "exit2", kind: "false" },
    ] as IcfgEdge[])
    expect(exitArms(graph).size).toBe(0)
  })
})
