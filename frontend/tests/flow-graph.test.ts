import { describe, expect, test } from "vitest"

import type { Icfg } from "@/lib/generated/icfg.schema"
import type { RemoteEdgesView } from "@/lib/generated/remote_edges_view.schema"
import { buildFlowGraph } from "@/lib/wadi/flow-graph"

const FILE = "src/A.java"

function n(partial: Record<string, unknown>) {
  return {
    kind: "statement",
    source_text: "stmt",
    method: { id: "m_1", signature: "com.acme.A.go" },
    anchor: { file: FILE, start_line: 1, end_line: 1, variant: "original" },
    ...partial,
  }
}

const icfg = {
  schema_version: "1.9.0",
  snapshot_id: "snap_1",
  service_id: "svc_1",
  endpoint_id: "ep_" + "0".repeat(16),
  entry_node_id: "m1:entry",
  nodes: [
    n({ id: "m1:entry", kind: "entry" }),
    // Three plain statements in a row (condensable run).
    n({
      id: "m1:s1",
      anchor: { file: FILE, start_line: 2, end_line: 2, variant: "original" },
    }),
    n({
      id: "m1:s2",
      anchor: { file: FILE, start_line: 3, end_line: 3, variant: "original" },
    }),
    n({
      id: "m1:s3",
      anchor: { file: FILE, start_line: 4, end_line: 4, variant: "original" },
    }),
    // A branch (never condensed) with true/false successors.
    n({
      id: "m1:b1",
      kind: "branch",
      construct_kind: "if",
      condition: { expression: "x > 0", operands: [] },
      anchor: { file: FILE, start_line: 5, end_line: 5, variant: "original" },
    }),
    n({
      id: "m1:s4",
      anchor: { file: FILE, start_line: 6, end_line: 6, variant: "original" },
    }),
    n({
      id: "m1:r1",
      kind: "return",
      anchor: { file: FILE, start_line: 8, end_line: 8, variant: "original" },
    }),
    // A call site carrying a remote call.
    n({
      id: "m1:c1",
      kind: "call",
      sink: "http-client",
      remote_call_ids: ["rc_" + "a".repeat(16)],
      anchor: { file: FILE, start_line: 7, end_line: 7, variant: "original" },
    }),
    n({ id: "m1:exit", kind: "exit" }),
    // Second method.
    n({
      id: "m2:entry",
      kind: "entry",
      method: { id: "m_2", signature: "com.acme.B.help" },
      anchor: {
        file: "src/B.java",
        start_line: 20,
        end_line: 20,
        variant: "original",
      },
    }),
    n({
      id: "m2:s1",
      method: { id: "m_2", signature: "com.acme.B.help" },
      anchor: {
        file: "src/B.java",
        start_line: 21,
        end_line: 21,
        variant: "original",
      },
    }),
  ],
  edges: [
    {
      source: "m1:s1",
      target: "m1:s2",
      kind: "flow",
      case_values: [],
      back: false,
    },
    {
      source: "m1:s2",
      target: "m1:s3",
      kind: "flow",
      case_values: [],
      back: false,
    },
    {
      source: "m1:s3",
      target: "m1:b1",
      kind: "flow",
      case_values: [],
      back: false,
    },
    {
      source: "m1:b1",
      target: "m1:s4",
      kind: "true",
      case_values: [],
      back: false,
    },
    {
      source: "m1:b1",
      target: "m1:r1",
      kind: "false",
      case_values: [],
      back: false,
    },
    {
      source: "m1:s4",
      target: "m1:c1",
      kind: "flow",
      case_values: [],
      back: false,
    },
    {
      source: "m1:c1",
      target: "m2:entry",
      kind: "call",
      case_values: [],
      back: false,
    },
    {
      source: "m2:exit",
      target: "m1:c1",
      kind: "return",
      case_values: [],
      back: false,
    },
  ],
} as unknown as Icfg

const remoteEdges = {
  service_id: "svc_1",
  outbound: [
    {
      edge_id: "re_" + "b".repeat(16),
      remote_call_id: "rc_" + "a".repeat(16),
      caller_service_id: "svc_1",
      mechanism: "resttemplate",
      http_verb: "GET",
      target_kind: "analyzed",
      target_service_id: "svc_2",
      target_service_name: "inventory",
      confidence: "high",
      provenance: "config-resolved",
    },
  ],
  inbound: [],
} as unknown as RemoteEdgesView

describe("buildFlowGraph (§11 Phase 2.7 M3)", () => {
  test("level 0: one node per method, call edges, lifted remote ghost", () => {
    const graph = buildFlowGraph(icfg, remoteEdges, new Set(), new Set())
    const kinds = graph.nodes.map((node) => node.type)
    expect(kinds.filter((k) => k === "method")).toHaveLength(2)
    const ghost = graph.nodes.find((node) => node.type === "ghost")
    expect(ghost).toMatchObject({
      label: "inventory",
      targetKind: "analyzed",
      confidence: "high",
    })
    expect(
      graph.edges.some(
        (edge) => edge.kind === "call" && edge.source === "method:m_1"
      )
    ).toBe(true)
    expect(
      graph.edges.some((edge) => edge.kind === "remote" && edge.label === "GET")
    ).toBe(true)
  })

  test("expansion: statement subgraph with labeled edges, condensed runs", () => {
    const graph = buildFlowGraph(icfg, remoteEdges, new Set(["m_1"]), new Set())
    const condensed = graph.nodes.filter((node) => node.type === "condensed")
    expect(condensed).toHaveLength(1)
    expect(condensed[0]).toMatchObject({ count: 3, startLine: 2, endLine: 4 })
    // The branch survives condensation with its labeled successors.
    const branch = graph.nodes.find(
      (node) => node.type === "statement" && node.icfgNode.kind === "branch"
    )
    expect(branch).toBeDefined()
    expect(
      graph.edges.some((edge) => edge.kind === "true" && edge.label === "true")
    ).toBe(true)
    expect(
      graph.edges.some(
        (edge) => edge.kind === "false" && edge.label === "false"
      )
    ).toBe(true)
    // The sink call site is never condensed; the remote stub leaves from it.
    expect(
      graph.edges.some(
        (edge) => edge.kind === "remote" && edge.source === "stmt:m1:c1"
      )
    ).toBe(true)
  })

  test("expanding a run reveals its statements", () => {
    const graph = buildFlowGraph(
      icfg,
      remoteEdges,
      new Set(["m_1"]),
      new Set(["run:m1:s1"])
    )
    expect(graph.nodes.some((node) => node.type === "condensed")).toBe(false)
    expect(graph.nodes.some((node) => node.id === "stmt:m1:s2")).toBe(true)
  })

  test("call edge lands on the callee's first statement when expanded", () => {
    const graph = buildFlowGraph(
      icfg,
      remoteEdges,
      new Set(["m_1", "m_2"]),
      new Set()
    )
    expect(
      graph.edges.some(
        (edge) => edge.kind === "call" && edge.target === "stmt:m2:s1"
      )
    ).toBe(true)
  })
})
