import { describe, expect, test } from "vitest"

import type { Icfg } from "@/lib/generated/icfg.schema"
import { buildCallTree, treeSize } from "@/lib/wadi/call-tree"

const FILE_A = "src/A.java"
const FILE_B = "src/B.java"

function entry(methodId: string, file: string, line: number) {
  return {
    id: `${methodId}:entry`,
    kind: "entry",
    source_text: "<entry>",
    method: { id: methodId, signature: `com.acme.${methodId}.run` },
    anchor: { file, start_line: line, end_line: line, variant: "original" },
  }
}

function site(methodId: string, n: number, line: number) {
  return {
    id: `${methodId}:n${n}`,
    kind: "call",
    source_text: "call()",
    method: { id: methodId, signature: `com.acme.${methodId}.run` },
    anchor: {
      file: methodId === "m_a" ? FILE_A : FILE_B,
      start_line: line,
      end_line: line,
      variant: "original",
    },
  }
}

function callEdge(from: string, toMethod: string) {
  return {
    source: from,
    target: `${toMethod}:entry`,
    kind: "call",
    case_values: [],
    back: false,
  }
}

const icfg = {
  schema_version: "1.9.0",
  snapshot_id: "snap_1",
  service_id: "svc_1",
  endpoint_id: "ep_" + "0".repeat(16),
  entry_node_id: "m_a:entry",
  nodes: [
    entry("m_a", FILE_A, 10),
    site("m_a", 1, 14),
    site("m_a", 2, 12),
    entry("m_b", FILE_B, 30),
    site("m_b", 1, 33),
  ],
  edges: [
    callEdge("m_a:n1", "m_b"),
    callEdge("m_a:n2", "m_b"),
    // Recursion: B calls A again.
    callEdge("m_b:n1", "m_a"),
  ],
} as unknown as Icfg

describe("buildCallTree (§11 Phase 2.7 M2)", () => {
  test("handler is the root, callees nest at call sites ordered by line", () => {
    const root = buildCallTree(icfg)
    expect(root?.methodId).toBe("m_a")
    expect(root?.children.map((c) => [c.methodId, c.callSiteLine])).toEqual([
      ["m_b", 12],
      ["m_b", 14],
    ])
  })

  test("recursion into an ancestor is a cycle leaf, never infinite descent", () => {
    const root = buildCallTree(icfg)
    const b = root?.children[0]
    expect(b?.children).toHaveLength(1)
    const backToA = b?.children[0]
    expect(backToA?.methodId).toBe("m_a")
    expect(backToA?.cycle).toBe(true)
    expect(backToA?.children).toHaveLength(0)
  })

  test("a method called from two sites appears under each (context shown)", () => {
    const root = buildCallTree(icfg)
    // root + two m_b occurrences + one cycle leaf under each.
    expect(root ? treeSize(root) : 0).toBe(5)
  })

  test("nodes carry their rollup for badges", () => {
    const root = buildCallTree(icfg)
    expect(root?.rollup?.id).toBe("m_a")
    expect(root?.children[0]?.rollup?.id).toBe("m_b")
  })
})
