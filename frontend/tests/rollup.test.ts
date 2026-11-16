import { describe, expect, test } from "vitest"

import type { Icfg } from "@/lib/generated/icfg.schema"
import { rollupMethods } from "@/lib/wadi/rollup"

const METHOD = { id: "m_a", signature: "com.acme.MixedSinkController.wrap" }
const ANCHOR = {
  file: "src/A.java",
  start_line: 10,
  end_line: 10,
  variant: "original",
}

function node(id: string, extra: Record<string, unknown>) {
  return {
    id,
    kind: "call",
    source_text: "call()",
    method: METHOD,
    anchor: ANCHOR,
    ...extra,
  }
}

function icfgWith(nodes: Record<string, unknown>[]): Icfg {
  return {
    schema_version: "1.27.0",
    snapshot_id: "snap_1",
    service_id: "svc_1",
    endpoint_id: "ep_" + "0".repeat(16),
    entry_node_id: "m_a:entry",
    nodes: [
      {
        id: "m_a:entry",
        kind: "entry",
        source_text: "<entry>",
        method: METHOD,
        anchor: ANCHOR,
      },
      ...nodes,
    ],
    edges: [],
  } as unknown as Icfg
}

describe("method sink chips", () => {
  // Value: protects=a method's chips name every sink kind its statements make, not only each node's primary call; fails_when=chips read node.sink alone again; why_new=no rollup test covered a statement making two kinds of sink call (pre-landing review, golden 53); seam=none; no_claim=chip order
  test("a repository call wrapping an HTTP call shows both chips", () => {
    const [rollup] = rollupMethods(
      icfgWith([
        node("m_a:n1", {
          sink: "db",
          remote_call_ids: ["rc_0000000000000001"],
          entity_access_sites: [{ repository: "com.acme.OrderRepository" }],
        }),
      ])
    )
    expect(rollup?.sinks).toEqual(["db", "http-client"])
  })

  test("an HTTP call wrapping a repository call shows both chips", () => {
    const [rollup] = rollupMethods(
      icfgWith([
        node("m_a:n1", {
          sink: "http-client",
          remote_call_ids: ["rc_0000000000000001"],
          entity_access_sites: [{ repository: "com.acme.OrderRepository" }],
        }),
      ])
    )
    expect(rollup?.sinks).toEqual(["http-client", "db"])
  })

  test("a node with one sink kind shows one chip", () => {
    const [rollup] = rollupMethods(icfgWith([node("m_a:n1", { sink: "db" })]))
    expect(rollup?.sinks).toEqual(["db"])
  })
})
