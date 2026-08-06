import { cleanup, fireEvent, within } from "@testing-library/react"
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
      anchor: { file: FILE, start_line: 1, end_line: 1, variant: "original" },
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
    {
      // The exit node carries the method's real last line — which is what lets
      // the panel show a WHOLE method instead of stopping at the last executed
      // statement.
      id: "m1:exit",
      kind: "exit",
      source_text: "<exit>",
      method: { id: "m_1", signature: "com.acme.FlowController.go" },
      anchor: { file: FILE, start_line: 3, end_line: 3, variant: "original" },
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
  // vitest runs without `globals`, so testing-library's auto-cleanup is off:
  // without this every case searches the DOM of every case before it.
  cleanup()
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
    // The chips filter now; "all N files" is the unfiltered state.
    expect(await findByText(/^All 1$/)).toBeInTheDocument()
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
    // Counts the ScrollArea viewport (the real scrolling element) as well as
    // any hand-rolled vertical scroller — the invariant is ONE of them, never
    // a scroller nested inside a scroller, whichever mechanism provides it.
    const scrollers = container.querySelectorAll(
      '[data-radix-scroll-area-viewport], [class*="overflow-y-auto"], [class*="overflow-auto"]'
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
        (element?.className?.includes?.("bg-warn/10") ?? false) &&
        (element?.textContent?.includes("if (n < 0)") ?? false)
    )
    expect(highlighted.length).toBeGreaterThan(0)
  })
})

// --- multiple files: one card each, opened on purpose ------------------------

const CALLEE_FILE = "src/main/java/com/acme/FlowService.java"

const twoFileIcfg = {
  ...icfg,
  nodes: [
    ...icfg.nodes,
    {
      id: "m2:entry",
      kind: "entry",
      source_text: "<entry>",
      method: { id: "m_2", signature: "com.acme.FlowService.run" },
      anchor: {
        file: CALLEE_FILE,
        start_line: 1,
        end_line: 1,
        variant: "original",
      },
    },
    {
      id: "m2:n1",
      kind: "call",
      source_text: "repo.save(x)",
      method: { id: "m_2", signature: "com.acme.FlowService.run" },
      anchor: {
        file: CALLEE_FILE,
        start_line: 2,
        end_line: 2,
        variant: "original",
      },
    },
    {
      id: "m2:exit",
      kind: "exit",
      source_text: "<exit>",
      method: { id: "m_2", signature: "com.acme.FlowService.run" },
      anchor: {
        file: CALLEE_FILE,
        start_line: 3,
        end_line: 3,
        variant: "original",
      },
    },
  ],
} as unknown as Icfg

/** Answers per file, so a test can tell WHICH file was fetched. */
function stubFetchByFile(bodies: Record<string, unknown>) {
  const spy = vi.fn(async (url: string) => {
    const file = new URL(url, "http://localhost").searchParams.get("file") ?? ""
    return { ok: true, status: 200, json: async () => bodies[file] ?? {} }
  })
  vi.stubGlobal("fetch", spy)
  return spy
}

const window3 = (file: string, content: string) => ({
  file,
  start_line: 1,
  end_line: 3,
  variant: "original",
  content,
  total_lines: 3,
  truncated: false,
})

const fetchedFiles = (spy: ReturnType<typeof stubFetchByFile>) =>
  spy.mock.calls.map(
    ([url]) => new URL(url, "http://localhost").searchParams.get("file") ?? ""
  )

describe("a flow's files are cards, not one continuous column", () => {
  const bodies = {
    [FILE]: window3(FILE, "class FlowController {\n  int go;\n}\n"),
    [CALLEE_FILE]: window3(CALLEE_FILE, "class FlowService {\n  int run;\n}\n"),
  }

  /** The card's disclosure control — `data-source-card` is what separates a
   *  file's own header from the tab that filters to it. */
  const cardToggle = (container: HTMLElement, file: string) =>
    container.querySelector<HTMLButtonElement>(
      `[data-source-card="${file}"] button[aria-expanded]`
    )

  const renderTwo = (selection?: {
    file: string
    startLine: number
    endLine: number
    focusLine: number
  }) =>
    renderWithQuery(
      <SourceViewer
        icfg={twoFileIcfg}
        snapshotId="snap_1"
        serviceId="svc_1"
        active
        selection={selection}
      />
    )

  test("every touched file gets its own card", () => {
    stubFetchByFile(bodies)
    const { container } = renderTwo()
    // A closed card is still on screen and still says what it holds — that is
    // the point of boxing them rather than concatenating their code.
    expect(container.querySelectorAll("[data-source-card]").length).toBe(2)
  })

  test("the handler's file opens; the rest wait, and fetch nothing until asked", async () => {
    const spy = stubFetchByFile(bodies)
    const { container, findAllByText } = renderTwo()
    await findAllByText(
      (_, element) =>
        element?.tagName === "CODE" &&
        (element.textContent?.includes("class FlowController {") ?? false)
    )
    expect(cardToggle(container, FILE)).toHaveAttribute("aria-expanded", "true")
    expect(cardToggle(container, CALLEE_FILE)).toHaveAttribute(
      "aria-expanded",
      "false"
    )
    expect(fetchedFiles(spy)).not.toContain(CALLEE_FILE)
  })

  test("clicking a file's header opens it in place and loads its code", async () => {
    const spy = stubFetchByFile(bodies)
    const { container, findAllByText } = renderTwo()
    fireEvent.click(cardToggle(container, CALLEE_FILE)!)
    const opened = await findAllByText(
      (_, element) =>
        element?.tagName === "CODE" &&
        (element.textContent?.includes("class FlowService {") ?? false)
    )
    expect(opened.length).toBeGreaterThan(0)
    expect(fetchedFiles(spy)).toContain(CALLEE_FILE)
  })

  test("a selection in a closed file opens it — never a dead end", () => {
    stubFetchByFile(bodies)
    const { container } = renderTwo({
      file: CALLEE_FILE,
      startLine: 2,
      endLine: 2,
      focusLine: 2,
    })
    expect(cardToggle(container, CALLEE_FILE)).toHaveAttribute(
      "aria-expanded",
      "true"
    )
  })
})

// A 40-line file with one 5-line method: the panel exists to show the method,
// not the 35 lines of imports and unrelated code around it.
const LONG_FILE = "src/main/java/com/acme/Big.java"

function longNode(id: string, kind: string, line: number) {
  return {
    id,
    kind,
    source_text: id,
    method: { id: "m_1", signature: "com.acme.Big.handle" },
    anchor: {
      file: LONG_FILE,
      start_line: line,
      end_line: line,
      variant: "original",
    },
  }
}

const longIcfg = {
  schema_version: "1.11.0",
  snapshot_id: "snap_1",
  service_id: "svc_1",
  endpoint_id: "ep_" + "0".repeat(16),
  entry_node_id: "m1:entry",
  nodes: [
    longNode("m1:entry", "entry", 20),
    longNode("m1:n1", "call", 22),
    longNode("m1:exit", "exit", 24),
  ],
  edges: [],
} as unknown as Icfg

const longContent =
  Array.from({ length: 40 }, (_, i) => `line ${i + 1}`).join("\n") + "\n"

/** Shiki tokenizes asynchronously and splits a line into token spans, so a
 * plain string matcher races the highlighter. Match the CODE element itself —
 * the same workaround the file's earlier cases use. */
const codeLine = (text: string) => (_: string, element: Element | null) =>
  element?.tagName === "CODE" && element.textContent === text

describe("the source panel shows methods, not whole files", () => {
  const stubLong = () =>
    stubFetch({
      file: LONG_FILE,
      start_line: 1,
      end_line: 40,
      variant: "original",
      content: longContent,
      total_lines: 40,
      truncated: false,
    })

  const renderLong = (selection?: {
    file: string
    startLine: number
    endLine: number
    focusLine: number
  }) => {
    stubLong()
    return renderWithQuery(
      <SourceViewer
        icfg={longIcfg}
        snapshotId="snap_1"
        serviceId="svc_1"
        active
        selection={selection}
      />
    )
  }

  test("renders the whole method and folds everything else", async () => {
    const { findByText, queryByText } = renderLong()
    // The method, complete: declaration (20) through closing brace (24) — the
    // exit anchor, not the last executed statement (22).
    expect(await findByText(codeLine("line 20"))).toBeInTheDocument()
    expect(await findByText(codeLine("line 24"))).toBeInTheDocument()
    // …and nothing outside it.
    expect(queryByText(codeLine("line 19"))).toBeNull()
    expect(queryByText(codeLine("line 25"))).toBeNull()
  })

  test("the folds say exactly what they are hiding", async () => {
    const { findByText } = renderLong()
    expect(await findByText(/19 lines · 1–19/)).toBeInTheDocument()
    expect(await findByText(/16 lines · 25–40/)).toBeInTheDocument()
  })

  test("clicking a fold shows the code it was hiding", async () => {
    const { findByText, queryByText } = renderLong()
    expect(queryByText(codeLine("line 5"))).toBeNull()
    fireEvent.click(await findByText(/19 lines · 1–19/))
    expect(await findByText(codeLine("line 5"))).toBeInTheDocument()
    // The other fold stays shut — expanding is per-fold, not all-or-nothing.
    expect(queryByText(codeLine("line 40"))).toBeNull()
  })

  test("a selection inside a fold opens it — never an unreachable line", async () => {
    const { findByText } = renderLong({
      file: LONG_FILE,
      startLine: 33,
      endLine: 33,
      focusLine: 33,
    })
    expect(await findByText(codeLine("line 33"))).toBeInTheDocument()
  })

  test("names the enclosing method above its code", async () => {
    const { findAllByText } = renderLong()
    expect((await findAllByText(/Big\.handle/)).length).toBeGreaterThan(0)
  })
})
