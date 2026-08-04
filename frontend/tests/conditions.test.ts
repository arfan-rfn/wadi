import { describe, expect, test } from "vitest"

import type { Icfg } from "@/lib/generated/icfg.schema"
import {
  conditionLabel,
  ghostConditions,
  governingConditions,
} from "@/lib/wadi/conditions"
import type { FlowGraph } from "@/lib/wadi/flow-graph"

function n(partial: Record<string, unknown>) {
  return {
    kind: "statement",
    source_text: "stmt",
    method: { id: "m_1", signature: "com.acme.A.go" },
    anchor: {
      file: "src/A.java",
      start_line: 1,
      end_line: 1,
      variant: "original",
    },
    ...partial,
  }
}

const icfg = {
  schema_version: "1.10.0",
  snapshot_id: "snap_1",
  service_id: "svc_1",
  endpoint_id: "ep_" + "0".repeat(16),
  entry_node_id: "m1:entry",
  nodes: [
    n({ id: "m1:entry", kind: "entry" }),
    n({
      id: "m1:b1",
      kind: "branch",
      construct_kind: "if",
      condition: { expression: "order.getStatus() == NOTPAID", operands: [] },
    }),
    n({ id: "m1:s1" }),
    n({
      id: "m1:c1",
      kind: "call",
      sink: "http-client",
      remote_call_ids: ["rc_" + "a".repeat(16)],
    }),
    n({
      id: "m1:c2",
      kind: "call",
      sink: "http-client",
      remote_call_ids: ["rc_" + "b".repeat(16)],
    }),
  ],
  edges: [
    // true arm: s1 → c1 (governed "when"); false arm: c2 directly ("unless").
    {
      source: "m1:b1",
      target: "m1:s1",
      kind: "true",
      case_values: [],
      back: false,
    },
    {
      source: "m1:s1",
      target: "m1:c1",
      kind: "flow",
      case_values: [],
      back: false,
    },
    {
      source: "m1:b1",
      target: "m1:c2",
      kind: "false",
      case_values: [],
      back: false,
    },
  ],
} as unknown as Icfg

describe("governingConditions (§11 Phase 2.7 M5)", () => {
  test("a call in the true arm reads 'when <condition>'", () => {
    const conditions = governingConditions(icfg)
    const forC1 = conditions.get("m1:c1")
    expect(forC1).toHaveLength(1)
    expect(conditionLabel(forC1![0])).toBe("when order.getStatus() == NOTPAID")
  })

  test("a call on the false edge reads 'unless <condition>'", () => {
    const conditions = governingConditions(icfg)
    expect(conditionLabel(conditions.get("m1:c2")![0])).toBe(
      "unless order.getStatus() == NOTPAID"
    )
  })

  test("unmarked nodes are not computed", () => {
    const conditions = governingConditions(icfg)
    expect(conditions.has("m1:s1")).toBe(false)
  })

  test("the walk crosses call edges: a helper's call is governed by its call site", () => {
    const inter = {
      ...icfg,
      nodes: [
        ...(icfg.nodes as unknown[]),
        n({
          id: "m2:entry",
          kind: "entry",
          method: { id: "m_2", signature: "com.acme.Helper.send" },
        }),
        n({
          id: "m2:c1",
          kind: "call",
          sink: "http-client",
          method: { id: "m_2", signature: "com.acme.Helper.send" },
          remote_call_ids: ["rc_" + "c".repeat(16)],
        }),
      ],
      edges: [
        ...(icfg.edges as unknown[]),
        // c1 (in the true arm of m1) calls the helper.
        {
          source: "m1:c1",
          target: "m2:entry",
          kind: "call",
          case_values: [],
          back: false,
        },
        {
          source: "m2:entry",
          target: "m2:c1",
          kind: "flow",
          case_values: [],
          back: false,
        },
      ],
    } as unknown as Icfg
    const conditions = governingConditions(inter)
    expect(conditionLabel(conditions.get("m2:c1")![0])).toBe(
      "when order.getStatus() == NOTPAID"
    )
  })
})

describe("ghostConditions — one chip per distinct condition", () => {
  const COND = { expression: "order.paid()", operands: [] }
  const graph: FlowGraph = {
    nodes: [
      {
        type: "statement",
        id: "stmt:a",
        methodId: "m_1",
        icfgNode: { id: "a" } as never,
      },
      {
        type: "statement",
        id: "stmt:b",
        methodId: "m_1",
        icfgNode: { id: "b" } as never,
      },
      {
        type: "ghost",
        id: "ghost:svc_x",
        label: "orders",
        targetKind: "analyzed",
        confidence: "high",
        edgeId: null,
      },
    ],
    edges: [
      {
        id: "remote:a",
        source: "stmt:a",
        target: "ghost:svc_x",
        kind: "remote",
        label: "GET",
        back: false,
      },
      {
        id: "remote:b",
        source: "stmt:b",
        target: "ghost:svc_x",
        kind: "remote",
        label: "GET",
        back: false,
      },
    ],
  }
  const when = { ...COND, polarity: "when" as const, caseValues: [] }
  const unless = { ...COND, polarity: "unless" as const, caseValues: [] }

  test("two call sites under the SAME branch yield one chip", () => {
    // The reported crash: React saw two children with the same key, because a
    // ghost unions conditions across every call site reaching it.
    const byNode = new Map([
      ["a", [when]],
      ["b", [when]],
    ])
    const result = ghostConditions(graph, byNode, "ghost:svc_x")
    expect(result).toHaveLength(1)
    expect(result.map(conditionLabel)).toEqual(["when order.paid()"])
  })

  test("keeps genuinely different conditions, including opposite arms", () => {
    const byNode = new Map([
      ["a", [when]],
      ["b", [unless]],
    ])
    const result = ghostConditions(graph, byNode, "ghost:svc_x")
    expect(result.map(conditionLabel)).toEqual([
      "when order.paid()",
      "unless order.paid()",
    ])
  })

  test("dedupes before any display cap, so a budget shows distinct chips", () => {
    // Dedupe after slicing would leave the two-chip budget showing one
    // condition twice — the bug this ordering exists to prevent.
    const byNode = new Map([
      ["a", [when, when]],
      ["b", [when, unless]],
    ])
    expect(
      ghostConditions(graph, byNode, "ghost:svc_x")
        .slice(0, 2)
        .map(conditionLabel)
    ).toEqual(["when order.paid()", "unless order.paid()"])
  })

  test("ignores edges that are not remote, and other ghosts", () => {
    const byNode = new Map([["a", [when]]])
    expect(ghostConditions(graph, byNode, "ghost:other")).toEqual([])
    const noRemote: FlowGraph = {
      nodes: graph.nodes,
      edges: graph.edges.map((edge) => ({ ...edge, kind: "call" })),
    }
    expect(ghostConditions(noRemote, byNode, "ghost:svc_x")).toEqual([])
  })
})
