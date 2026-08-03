import { describe, expect, test } from "vitest"

import type { Icfg } from "@/lib/generated/icfg.schema"
import { buildSourceMap, isTouched } from "@/lib/wadi/source-map"

const CONTROLLER = "src/main/java/com/acme/CancelController.java"
const IMPL = "src/main/java/com/acme/CancelServiceImpl.java"

function node(partial: Record<string, unknown>) {
  return {
    kind: "statement",
    source_text: "stmt",
    method: { id: "m_1", signature: "com.acme.CancelController.cancel" },
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
    node({
      id: "m1:entry",
      kind: "entry",
      anchor: {
        file: CONTROLLER,
        start_line: 30,
        end_line: 30,
        variant: "original",
      },
    }),
    node({
      id: "m1:n1",
      kind: "branch",
      construct_kind: "if",
      condition: { expression: "n < 0", operands: [] },
      anchor: {
        file: CONTROLLER,
        start_line: 33,
        end_line: 35,
        variant: "original",
      },
    }),
    node({
      id: "m1:n2",
      kind: "call",
      anchor: {
        file: CONTROLLER,
        start_line: 36,
        end_line: 36,
        variant: "original",
      },
    }),
    node({
      id: "m1:exit",
      kind: "exit",
      anchor: {
        file: CONTROLLER,
        start_line: 40,
        end_line: 40,
        variant: "original",
      },
    }),
    node({
      id: "m2:entry",
      kind: "entry",
      method: { id: "m_2", signature: "com.acme.CancelServiceImpl.cancel" },
      anchor: { file: IMPL, start_line: 45, end_line: 45, variant: "original" },
    }),
    node({
      id: "m2:n1",
      kind: "call",
      sink: "http-client",
      method: { id: "m_2", signature: "com.acme.CancelServiceImpl.cancel" },
      anchor: { file: IMPL, start_line: 50, end_line: 52, variant: "original" },
    }),
  ],
  edges: [
    {
      source: "m1:n2",
      target: "m2:entry",
      kind: "call",
      case_values: [],
      back: false,
    },
  ],
} as unknown as Icfg

describe("buildSourceMap (§11 Phase 2.7 M1)", () => {
  test("files come out in flow order, handler file first", () => {
    const sections = buildSourceMap(icfg)
    expect(sections.map((s) => s.file)).toEqual([CONTROLLER, IMPL])
  })

  test("touched intervals merge adjacent node extents", () => {
    const [controller] = buildSourceMap(icfg)
    // 33-35 (branch) and 36 (call) are adjacent → one region.
    expect(controller.touched).toEqual([[33, 36]])
    expect(isTouched(controller, 34)).toBe(true)
    expect(isTouched(controller, 32)).toBe(false)
  })

  test("marks carry construct and sink facts", () => {
    const [controller, impl] = buildSourceMap(icfg)
    expect(controller.marks.get(33)?.[0]).toMatchObject({
      kind: "branch",
      construct: "if",
      hasCondition: true,
    })
    expect(impl.marks.get(50)?.[0]).toMatchObject({ sink: "http-client" })
  })

  test("call edges become cross-file jump links", () => {
    const [controller] = buildSourceMap(icfg)
    expect(controller.callLinks).toEqual([
      {
        line: 36,
        nodeId: "m1:n2",
        targetFile: IMPL,
        targetLine: 45,
        targetSignature: "com.acme.CancelServiceImpl.cancel",
        targetMethodId: "m_2",
      },
    ])
  })

  test("method spans grow to cover their statements", () => {
    const [, impl] = buildSourceMap(icfg)
    expect(impl.methods).toEqual([
      {
        id: "m_2",
        signature: "com.acme.CancelServiceImpl.cancel",
        startLine: 45,
        endLine: 52,
      },
    ])
  })

  test("entry/exit nodes never count as touched code", () => {
    const [controller] = buildSourceMap(icfg)
    expect(isTouched(controller, 30)).toBe(false)
    expect(isTouched(controller, 40)).toBe(false)
  })
})
