// Shared two-method ICFG fixture for the Phase 2.8 canvas suites: handler
// m_1 (linear run → branch → remote call site) calling m_2.

import type { Icfg } from "@/lib/generated/icfg.schema"
import type { RemoteEdgesView } from "@/lib/generated/remote_edges_view.schema"

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

function e(
  source: string,
  target: string,
  kind = "flow",
  back = false
): Record<string, unknown> {
  return { source, target, kind, case_values: [], back }
}

export const flowIcfg = {
  schema_version: "1.11.0",
  snapshot_id: "snap_1",
  service_id: "svc_1",
  endpoint_id: "ep_" + "0".repeat(16),
  entry_node_id: "m1:entry",
  nodes: [
    n({ id: "m1:entry", kind: "entry" }),
    n({
      id: "m1:s1",
      source_text: "int a = 1;",
      anchor: { file: FILE, start_line: 2, end_line: 2, variant: "original" },
    }),
    n({
      id: "m1:s2",
      source_text: "int b = 2;",
      anchor: { file: FILE, start_line: 3, end_line: 3, variant: "original" },
    }),
    n({
      id: "m1:b1",
      kind: "branch",
      construct_kind: "if",
      source_text: "if (x > 0)",
      condition: { expression: "x > 0", operands: [] },
      anchor: { file: FILE, start_line: 4, end_line: 4, variant: "original" },
    }),
    n({
      id: "m1:c1",
      kind: "call",
      sink: "http-client",
      source_text: "inventory.get(id);",
      remote_call_ids: ["rc_" + "a".repeat(16)],
      anchor: { file: FILE, start_line: 5, end_line: 5, variant: "original" },
    }),
    n({
      id: "m1:r1",
      kind: "return",
      source_text: "return done;",
      anchor: { file: FILE, start_line: 7, end_line: 7, variant: "original" },
    }),
    n({ id: "m1:exit", kind: "exit" }),
    n({
      id: "m2:entry",
      kind: "entry",
      source_text: "void help() {",
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
      source_text: "log.info(...);",
      method: { id: "m_2", signature: "com.acme.B.help" },
      anchor: {
        file: "src/B.java",
        start_line: 21,
        end_line: 21,
        variant: "original",
      },
    }),
    n({
      id: "m2:exit",
      kind: "exit",
      method: { id: "m_2", signature: "com.acme.B.help" },
      anchor: {
        file: "src/B.java",
        start_line: 22,
        end_line: 22,
        variant: "original",
      },
    }),
  ],
  edges: [
    e("m1:entry", "m1:s1"),
    e("m1:s1", "m1:s2"),
    e("m1:s2", "m1:b1"),
    e("m1:b1", "m1:c1", "true"),
    e("m1:b1", "m1:r1", "false"),
    e("m1:c1", "m1:r1"),
    e("m1:c1", "m2:entry", "call"),
    e("m2:entry", "m2:s1"),
    e("m2:s1", "m2:exit"),
    e("m2:exit", "m1:c1", "return"),
    e("m1:r1", "m1:exit"),
  ],
} as unknown as Icfg

export const flowRemoteEdges = {
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
