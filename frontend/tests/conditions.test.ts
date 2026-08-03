import { describe, expect, test } from "vitest"

import type { Icfg } from "@/lib/generated/icfg.schema"
import { conditionLabel, governingConditions } from "@/lib/wadi/conditions"

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
