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

  const sectionFor = (file: string): SourceFileSection => {
    let section = byFile.get(file)
    if (!section) {
      section = {
        file,
        order: byFile.size,
        methods: [],
        touched: [],
        marks: new Map(),
        callLinks: [],
      }
      byFile.set(file, section)
    }
    return section
  }

  for (const node of icfg.nodes) {
    nodeById.set(node.id, node)
    if (node.kind === "exit") continue
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
        endLine: Math.max(m.endLine, methodEnd.get(m.id) ?? m.endLine),
      }))
      .sort((a, b) => a.startLine - b.startLine)
    section.callLinks.sort((a, b) => a.line - b.line)
  }

  return [...byFile.values()].sort((a, b) => a.order - b.order)
}

/** Short display name for a repo-relative path. */
export function fileBasename(file: string): string {
  return file.split("/").pop() ?? file
}
