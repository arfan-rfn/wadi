// The source panel's row model (§11 Phase 2.8): what a file actually renders.
//
// The panel used to render every line of every touched file — 389 lines to
// show the 27 an endpoint runs. It now renders whole METHODS and folds the
// rest (imports, fields, untouched methods) into strips the reader can open.
// Rows are therefore no longer 1:1 with lines, which is why this lives in one
// pure function: every scroll target in the viewer goes through `rowByLine`,
// and a selection that lands inside a fold has to be able to find its way out.

export type SourceRow =
  | { kind: "line"; line: number }
  | { kind: "fold"; id: string; startLine: number; endLine: number }
  | { kind: "method"; id: string; signature: string; startLine: number }

export interface RowMethod {
  id: string
  signature: string
  startLine: number
}

export interface SourceRowModel {
  rows: SourceRow[]
  /** Line number → row index, for lines currently rendered. */
  rowByLine: Map<number, number>
  /** Lines hidden inside collapsed folds. */
  foldedCount: number
}

/** Stable across expansions, so React keys and the expanded set survive a
 * re-render that changes neighbouring folds. */
export function foldId(startLine: number, endLine: number): string {
  return `${startLine}-${endLine}`
}

/**
 * Build the rendered rows for a file.
 *
 * `shown` is the merged set of intervals to render (whole methods). Anything
 * between them becomes one fold row, unless its id is in `expanded`. An empty
 * `shown` means "nothing to fold against" — the whole file renders, because
 * showing nothing would be worse than showing too much.
 */
export function buildSourceRows(
  totalLines: number,
  shown: ReadonlyArray<readonly [number, number]>,
  expanded: ReadonlySet<string> = new Set(),
  methods: readonly RowMethod[] = []
): SourceRowModel {
  const rows: SourceRow[] = []
  const rowByLine = new Map<number, number>()
  let foldedCount = 0

  // A header row precedes each method's first line, so scrolling into the
  // middle of a file never leaves the reader asking which method they are in.
  // It is a ROW rather than decoration on the line: rows carry the scroll
  // math, and a header smuggled inside a line row would make that row a
  // different height than every other one.
  const headerByLine = new Map<number, RowMethod>()
  for (const method of methods) {
    if (!headerByLine.has(method.startLine))
      headerByLine.set(method.startLine, method)
  }

  const pushLines = (from: number, to: number) => {
    for (let line = from; line <= to; line += 1) {
      const method = headerByLine.get(line)
      if (method)
        rows.push({
          kind: "method",
          id: method.id,
          signature: method.signature,
          startLine: method.startLine,
        })
      rowByLine.set(line, rows.length)
      rows.push({ kind: "line", line })
    }
  }

  if (totalLines <= 0) return { rows, rowByLine, foldedCount }
  if (shown.length === 0) {
    pushLines(1, totalLines)
    return { rows, rowByLine, foldedCount }
  }

  // Clamp and re-merge: `shown` comes from anchors, which describe the whole
  // file, while the served window stops at the orchestrator's cap
  // (SOURCE_MAX_LINES). A region that STARTS past the window is not here at
  // all — clamping it would pin a method's header onto the last loaded line
  // and label unrelated code with that method's name. Drop it; "load more"
  // brings it back for real.
  const regions: Array<[number, number]> = []
  for (const [rawStart, rawEnd] of [...shown].sort((a, b) => a[0] - b[0])) {
    if (rawStart > totalLines) continue
    const start = Math.max(1, rawStart)
    const end = Math.max(start, Math.min(rawEnd, totalLines))
    const last = regions[regions.length - 1]
    if (last && start <= last[1] + 1) last[1] = Math.max(last[1], end)
    else regions.push([start, end])
  }

  let cursor = 1
  const pushGap = (from: number, to: number) => {
    if (to < from) return
    const id = foldId(from, to)
    if (expanded.has(id)) {
      pushLines(from, to)
      return
    }
    foldedCount += to - from + 1
    rows.push({ kind: "fold", id, startLine: from, endLine: to })
  }

  for (const [start, end] of regions) {
    pushGap(cursor, start - 1)
    pushLines(start, end)
    cursor = end + 1
  }
  pushGap(cursor, totalLines)

  return { rows, rowByLine, foldedCount }
}

/** The fold hiding `line`, or null when the line is rendered (or absent). */
export function foldContaining(
  rows: readonly SourceRow[],
  line: number
): (SourceRow & { kind: "fold" }) | null {
  for (const row of rows) {
    if (row.kind !== "fold") continue
    if (line >= row.startLine && line <= row.endLine) return row
  }
  return null
}

/**
 * Row index to scroll to for `line`. A line inside a collapsed fold has no row
 * of its own; scrolling to the fold at least puts the reader where the line
 * lives, and the viewer opens the fold in the same pass.
 */
export function rowIndexForLine(
  model: SourceRowModel,
  line: number
): number | null {
  const exact = model.rowByLine.get(line)
  if (exact !== undefined) return exact
  const index = model.rows.findIndex(
    (row) => row.kind === "fold" && line >= row.startLine && line <= row.endLine
  )
  return index === -1 ? null : index
}

const WRAP_STORAGE_KEY = "wadi.source.wrap"

/** Wrap is a reading preference, not shared state: it lives in localStorage,
 * never in the URL. Reads defensively — SSR has no storage, and a corrupt
 * value must not take the panel down with it. */
export function readWrapPreference(): boolean {
  if (typeof window === "undefined") return false
  try {
    return window.localStorage.getItem(WRAP_STORAGE_KEY) === "1"
  } catch {
    return false
  }
}

export function writeWrapPreference(wrap: boolean): void {
  if (typeof window === "undefined") return
  try {
    window.localStorage.setItem(WRAP_STORAGE_KEY, wrap ? "1" : "0")
  } catch {
    // A blocked or full storage is not a reason to break the viewer.
  }
}
