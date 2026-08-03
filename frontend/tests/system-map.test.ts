import { describe, expect, test } from "vitest"

import type { SystemGraphView } from "@/lib/generated/system_graph.schema"
import { buildSystemMap } from "@/lib/wadi/system-map"

function service(id: string, name: string) {
  return {
    service_id: id,
    name,
    kind: "service",
    endpoint_count: 2,
    async_root_count: 0,
    gateway: false,
    extraction_error: null,
    cfg_anomaly_count: 0,
  }
}

function edgeItem(partial: Record<string, unknown>) {
  return {
    edge_id: `re_${Math.random().toString(16).slice(2).padEnd(16, "0").slice(0, 16)}`,
    remote_call_id: "rc_" + "1".repeat(16),
    caller_service_id: "svc_a",
    mechanism: "resttemplate",
    http_verb: "GET",
    target_kind: "analyzed",
    target_service_id: "svc_b",
    target_service_name: "billing",
    confidence: "high",
    provenance: "config-resolved",
    ...partial,
  }
}

const view = {
  snapshot_id: "snap_1",
  stitched: true,
  services: [service("svc_a", "orders"), service("svc_b", "billing")],
  edges: [
    edgeItem({}),
    edgeItem({ confidence: "exact" }),
    edgeItem({
      target_kind: "external",
      target_service_id: null,
      target_service_name: null,
      external_host: "api.stripe.com",
      confidence: "heuristic",
    }),
    edgeItem({
      target_kind: "undetermined",
      target_service_id: null,
      target_service_name: null,
      confidence: "none",
    }),
  ],
} as unknown as SystemGraphView

describe("buildSystemMap (§11 Phase 2.7 M4)", () => {
  test("aggregates parallel calls into one edge with count + best confidence", () => {
    const map = buildSystemMap(view)
    const serviceEdge = map.edges.find((edge) => edge.target === "svc:svc_b")
    expect(serviceEdge).toMatchObject({ count: 2, confidence: "exact" })
    expect(serviceEdge?.items).toHaveLength(2)
  })

  test("unknown targets are first-class nodes, never dropped (P10)", () => {
    const map = buildSystemMap(view)
    const kinds = map.nodes.map((node) => node.type)
    expect(kinds).toContain("external")
    expect(kinds).toContain("unresolved")
    const external = map.nodes.find((node) => node.type === "external")
    expect(external).toMatchObject({ label: "api.stripe.com" })
    expect(map.edges.some((edge) => edge.target === "unresolved:svc_a")).toBe(
      true
    )
  })

  test("every service renders even with no edges", () => {
    const empty = { ...view, edges: [] } as SystemGraphView
    const map = buildSystemMap(empty)
    expect(map.nodes.filter((node) => node.type === "service")).toHaveLength(2)
    expect(map.edges).toHaveLength(0)
  })
})
