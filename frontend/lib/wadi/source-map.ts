// The endpoint source map (§11 Phase 2.7 M1): pure derivation from the ICFG.
// Every fact here comes from node anchors and edges — no extra API calls.
// Files are ordered by first touch in the closure's flow order (the assembler
// appends method subgraphs in BFS order from the handler).

import type { Icfg } from "@/lib/generated/icfg.schema"

type IcfgNode = Icfg["nodes"][number]

export interface LineMark {
  nodeId: string
  kind: string
  construct: string | null
  sink: string | null
  hasCondition: boolean
  startLine: number
  endLine: number
}

export interface CallLink {
  /** Call-site line in this file. */
  line: number
  nodeId: string
  targetFile: string
  targetLine: number
  targetSignature: string
  targetMethodId: string
}

export interface MethodSpan {
  id: string
  signature: string
  startLine: number
  endLine: number
}

export interface SourceFileSection {
  file: string
  /** First-touch position in flow order (0 = the handler's file). */
  order: number
  methods: MethodSpan[]
  /** Merged, sorted [start, end] line intervals the endpoint executes. */
  touched: Array<[number, number]>
  /**
   * Merged line intervals the panel renders by default: every method in the
   * closure, WHOLE — annotations through closing brace — not just the lines
   * that execute. A method cut off at its last executed statement loses its
   * signature's closing brace and reads as broken code; the endpoint's story
   * is told in methods, so methods are the unit of disclosure. Everything
   * outside these intervals collapses into an expandable strip.
   */
  shown: Array<[number, number]>
  /** Marks keyed by anchor start line. */
  marks: Map<number, LineMark[]>
  callLinks: CallLink[]
}

function mergeIntervals(
  spans: Array<[number, number]>
): Array<[number, number]> {
  const sorted = [...spans].sort((a, b) => a[0] - b[0] || a[1] - b[1])
  const merged: Array<[number, number]> = []
  for (const [start, end] of sorted) {
    const last = merged[merged.length - 1]
    if (last && start <= last[1] + 1) {
      last[1] = Math.max(last[1], end)
    } else {
      merged.push([start, end])
    }
  }
  return merged
}

export function isTouched(section: SourceFileSection, line: number): boolean {
  return section.touched.some(([start, end]) => line >= start && line <= end)
}

export function buildSourceMap(icfg: Icfg): SourceFileSection[] {
  const byFile = new Map<string, SourceFileSection>()
  const nodeById = new Map<string, IcfgNode>()
  const spansByFile = new Map<string, Array<[number, number]>>()
  const methodEnd = new Map<string, number>()
  // A method's real last line. The assembler anchors the EXIT node at the
  // method's `line_end` (Joern's `method.lineNumberEnd`) while the ENTRY node
  // gets the declaration line alone — so the closing brace is already in every
  // artifact, one node away from where anyone thought to look.
  const methodClose = new Map<string, number>()

  const sectionFor = (file: string): SourceFileSection => {
    let section = byFile.get(file)
    if (!section) {
      section = {
        file,
        order: byFile.size,
        methods: [],
        touched: [],
        shown: [],
        marks: new Map(),
        callLinks: [],
      }
      byFile.set(file, section)
    }
    return section
  }

  for (const node of icfg.nodes) {
    nodeById.set(node.id, node)
    if (node.kind === "exit") {
      methodClose.set(
        node.method.id,
        Math.max(
          methodClose.get(node.method.id) ?? 0,
          node.anchor.end_line,
          node.anchor.start_line
        )
      )
      continue
    }
    const file = node.anchor.file
    const section = sectionFor(file)
    const start = node.anchor.start_line
    const end = Math.max(node.anchor.end_line, start)

    if (node.kind === "entry") {
      section.methods.push({
        id: node.method.id,
        signature: node.method.signature,
        startLine: start,
        endLine: end,
      })
      continue
    }

    const spans = spansByFile.get(file) ?? []
    spans.push([start, end])
    spansByFile.set(file, spans)
    methodEnd.set(
      node.method.id,
      Math.max(methodEnd.get(node.method.id) ?? 0, end)
    )

    const mark: LineMark = {
      nodeId: node.id,
      kind: node.kind,
      construct: node.construct_kind ?? null,
      sink: node.sink ?? null,
      hasCondition: node.condition != null,
      startLine: start,
      endLine: end,
    }
    const marks = section.marks.get(start) ?? []
    marks.push(mark)
    section.marks.set(start, marks)
  }

  // Call connections: a `call` edge runs call-site node → callee entry node.
  for (const edge of icfg.edges ?? []) {
    if (edge.kind !== "call") continue
    const source = nodeById.get(edge.source)
    const target = nodeById.get(edge.target)
    if (!source || !target || target.kind !== "entry") continue
    if (source.kind === "entry" || source.kind === "exit") continue
    const section = byFile.get(source.anchor.file)
    if (!section) continue
    section.callLinks.push({
      line: source.anchor.start_line,
      nodeId: source.id,
      targetFile: target.anchor.file,
      targetLine: target.anchor.start_line,
      targetSignature: target.method.signature,
      targetMethodId: target.method.id,
    })
  }

  for (const section of byFile.values()) {
    section.touched = mergeIntervals(spansByFile.get(section.file) ?? [])
    section.methods = section.methods
      .map((m) => ({
        ...m,
        // The exit anchor when there is one; otherwise the furthest statement,
        // which is all an abstract or interface method (no body, no exit node)
        // ever has. Never guess past what the artifact states (P10).
        endLine: Math.max(
          m.endLine,
          methodEnd.get(m.id) ?? m.endLine,
          methodClose.get(m.id) ?? m.endLine
        ),
      }))
      .sort((a, b) => a.startLine - b.startLine)
    section.shown = mergeIntervals(
      section.methods.map((m) => [m.startLine, m.endLine])
    )
    section.callLinks.sort((a, b) => a.line - b.line)
  }

  return [...byFile.values()].sort((a, b) => a.order - b.order)
}

/** Short display name for a repo-relative path. */
export function fileBasename(file: string): string {
  return file.split("/").pop() ?? file
}

/** Everything before the basename — "" for a path with no directory part. */
export function fileDirname(file: string): string {
  const cut = file.lastIndexOf("/")
  return cut === -1 ? "" : file.slice(0, cut)
}

/**
 * A directory elided in the MIDDLE, keeping the root and the last two
 * segments: `wadi-libs/…/common/entity`. Plain truncation cuts the tail, which
 * is the half that says which package this is — the head is boilerplate
 * (`src/main/java`) shared by every file in the repo.
 */
export function shortDirectory(directory: string): string {
  const parts = directory.split("/").filter(Boolean)
  if (parts.length <= 3) return directory
  return `${parts[0]}/…/${parts.slice(-2).join("/")}`
}

/** A region of source that a canvas/tree selection maps onto. */
export interface SourceSelection {
  file: string
  startLine: number
  endLine: number
  /** The line to scroll to — an anchor, not necessarily the region's start. */
  focusLine: number
}

/** Where a canvas or call-tree selection lives in source (§11 Phase 2.8).
 *
 * The mapping is 1:1 and automatic: selecting anything on the graph selects
 * the code it stands for, with no "open in source" step in between. A METHOD
 * selects its whole body — asking to see a method and getting one highlighted
 * line on its signature answers a question nobody asked — while a statement or
 * branch selects exactly its own extent.
 *
 * Returns null for selections with no source of their own (remote-target
 * ghosts, unknown ids): the caller leaves the previous highlight alone rather
 * than clearing the panel to nothing.
 */
export function sourceSelectionFor(
  icfg: Icfg | undefined,
  selectedNodeId: string | null | undefined
): SourceSelection | null {
  if (!icfg || !selectedNodeId) return null

  if (selectedNodeId.startsWith("method:")) {
    const methodId = selectedNodeId.slice("method:".length)
    let file: string | null = null
    let start = Number.POSITIVE_INFINITY
    let end = 0
    for (const node of icfg.nodes) {
      if (node.method.id !== methodId) continue
      // The first file wins: a method lives in one file, and a stray anchor
      // elsewhere must not stretch the highlight across the whole panel.
      file ??= node.anchor.file
      if (node.anchor.file !== file) continue
      start = Math.min(start, node.anchor.start_line)
      end = Math.max(end, node.anchor.end_line, node.anchor.start_line)
    }
    if (file === null || start === Number.POSITIVE_INFINITY) return null
    return { file, startLine: start, endLine: end, focusLine: start }
  }

  const prefix = ["stmt:", "run:"].find((p) => selectedNodeId.startsWith(p))
  if (!prefix) return null
  const node = icfg.nodes.find(
    (n) => n.id === selectedNodeId.slice(prefix.length)
  )
  if (!node) return null
  const startLine = node.anchor.start_line
  return {
    file: node.anchor.file,
    startLine,
    endLine: Math.max(node.anchor.end_line, startLine),
    focusLine: startLine,
  }
}
