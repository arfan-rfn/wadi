import { fireEvent, within } from "@testing-library/react"
import { afterEach, describe, expect, test, vi } from "vitest"

import type { Icfg } from "@/lib/generated/icfg.schema"
import { SourceSnippet, SourceViewer } from "@/components/source/source-viewer"

import { renderWithQuery } from "./utils"

const FILE = "src/main/java/com/acme/FlowController.java"

const icfg = {
  schema_version: "1.11.0",
  snapshot_id: "snap_1",
  service_id: "svc_1",
  endpoint_id: "ep_" + "0".repeat(16),
  entry_node_id: "m1:entry",
  nodes: [
    {
      id: "m1:entry",
      kind: "entry",
      source_text: "<entry>",
      method: { id: "m_1", signature: "com.acme.FlowController.go" },
      anchor: { file: FILE, start_line: 5, end_line: 5, variant: "original" },
    },
    {
      id: "m1:n1",
      kind: "branch",
      construct_kind: "if",
      condition: { expression: "n < 0", operands: [] },
      source_text: "if (n < 0)",
      method: { id: "m_1", signature: "com.acme.FlowController.go" },
      anchor: { file: FILE, start_line: 2, end_line: 2, variant: "original" },
    },
  ],
  edges: [],
} as unknown as Icfg

function stubFetch(body: unknown, ok = true, status = 200) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok,
      status,
      json: async () => body,
    }))
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("SourceViewer honesty states (§11 Phase 2.8)", () => {
  test("no icfg → skeleton, never a false empty", () => {
    stubFetch({})
    const { container } = renderWithQuery(
      <SourceViewer
        icfg={undefined}
        snapshotId="snap_1"
        serviceId="svc_1"
        active
      />
    )
    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(
      0
    )
  })

  test("renders the touched file section and fetches its source", async () => {
    stubFetch({
      file: FILE,
      start_line: 1,
      end_line: 3,
      variant: "original",
      content: "class FlowController {\n  int go;\n}\n",
      total_lines: 3,
      truncated: false,
    })
    const { findAllByText, findByText, getAllByText } = renderWithQuery(
      <SourceViewer icfg={icfg} snapshotId="snap_1" serviceId="svc_1" active />
    )
    expect(getAllByText(/FlowController\.java/).length).toBeGreaterThan(0)
    expect(await findByText(/1 file touched/)).toBeInTheDocument()
    // Shiki may split the line into token spans — match on textContent.
    const codeLines = await findAllByText(
      (_, element) =>
        element?.tagName === "CODE" &&
        (element.textContent?.includes("class FlowController {") ?? false)
    )
    expect(codeLines.length).toBeGreaterThan(0)
  })

  test("one scroller for all files — no nested scrolling", () => {
    stubFetch({
      file: FILE,
      start_line: 1,
      end_line: 3,
      variant: "original",
      content: "class FlowController {\n  int go;\n}\n",
      total_lines: 3,
      truncated: false,
    })
    const { container } = renderWithQuery(
      <SourceViewer icfg={icfg} snapshotId="snap_1" serviceId="svc_1" active />
    )
    const scrollers = container.querySelectorAll(
      '[class*="overflow-y-auto"], [class*="overflow-auto"]'
    )
    expect(scrollers.length).toBe(1)
  })

  test("a truncated window pages honestly, never silently", async () => {
    stubFetch({
      file: FILE,
      start_line: 1,
      end_line: 2,
      variant: "original",
      content: "class FlowController {\n  int go;\n",
      total_lines: 4200,
      truncated: true,
    })
    const { findByText } = renderWithQuery(
      <SourceViewer icfg={icfg} snapshotId="snap_1" serviceId="svc_1" active />
    )
    expect(await findByText(/Load lines 3–/)).toBeInTheDocument()
    expect(await findByText(/of 4200/)).toBeInTheDocument()
  })

  test("source failure is a stated state, not a blank", async () => {
    stubFetch({ detail: "file not found at pinned commit" }, false, 404)
    const { findByText } = renderWithQuery(
      <SourceViewer icfg={icfg} snapshotId="snap_1" serviceId="svc_1" active />
    )
    expect(await findByText(/Source unavailable:/)).toBeInTheDocument()
  })

  test("inactive lens fetches nothing (§5.3 on-demand)", () => {
    const spy = vi.fn()
    vi.stubGlobal("fetch", spy)
    renderWithQuery(
      <SourceViewer
        icfg={icfg}
        snapshotId="snap_1"
        serviceId="svc_1"
        active={false}
      />
    )
    expect(spy).not.toHaveBeenCalled()
  })
})

describe("SourceSnippet (drill-in peek)", () => {
  const anchor: import("@/lib/generated/icfg.schema").SourceAnchor = {
    file: FILE,
    start_line: 2,
    end_line: 2,
    variant: "original",
  }

  test("closed by default and fetches nothing until opened", () => {
    const spy = vi.fn()
    vi.stubGlobal("fetch", spy)
    const { getByText } = renderWithQuery(
      <SourceSnippet snapshotId="snap_1" serviceId="svc_1" anchor={anchor} />
    )
    expect(getByText(`${FILE}:2`).closest("button")).toHaveAttribute(
      "aria-expanded",
      "false"
    )
    expect(spy).not.toHaveBeenCalled()
  })

  test("opening fetches the anchored window and highlights the anchor line", async () => {
    stubFetch({
      file: FILE,
      start_line: 1,
      end_line: 5,
      variant: "original",
      content: "class A {\nif (n < 0)\n  x();\n}\n",
      total_lines: 5,
      truncated: false,
    })
    const { container } = renderWithQuery(
      <SourceSnippet snapshotId="snap_1" serviceId="svc_1" anchor={anchor} />
    )
    const scoped = within(container as HTMLElement)
    fireEvent.click(scoped.getByText(`${FILE}:2`))
    const highlighted = await scoped.findAllByText(
      (_, element) =>
        (element?.className?.includes?.("bg-amber-500/10") ?? false) &&
        (element?.textContent?.includes("if (n < 0)") ?? false)
    )
    expect(highlighted.length).toBeGreaterThan(0)
  })
})
