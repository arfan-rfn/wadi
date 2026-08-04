// The row model behind the folded source panel. Rows stopped being 1:1 with
// lines the moment folding landed, and every scroll target in the viewer goes
// through it — so the mapping is pinned here rather than trusted.
import { describe, expect, test } from "vitest"

import {
  buildSourceRows,
  foldContaining,
  foldId,
  rowIndexForLine,
  type SourceRow,
} from "@/lib/wadi/source-rows"

const lineNumbers = (model: ReturnType<typeof buildSourceRows>) =>
  model.rows.filter((r) => r.kind === "line").map((r) => r.line)

/** Row shorthand for order assertions: a line renders as its number. */
const shape = (row: SourceRow): number | string =>
  row.kind === "line" ? row.line : row.kind

const folds = (model: ReturnType<typeof buildSourceRows>) =>
  model.rows
    .filter((r) => r.kind === "fold")
    .map((r) => [r.startLine, r.endLine])

describe("buildSourceRows", () => {
  test("folds everything outside the shown regions", () => {
    // 100-line file, one method on 32-42: the reader sees the method, not the
    // 31 lines of imports above it.
    const model = buildSourceRows(100, [[32, 42]])
    expect(lineNumbers(model)).toEqual(
      Array.from({ length: 11 }, (_, i) => 32 + i)
    )
    expect(folds(model)).toEqual([
      [1, 31],
      [43, 100],
    ])
    expect(model.foldedCount).toBe(89)
  })

  test("keeps rows and lines in the right order", () => {
    const model = buildSourceRows(60, [
      [10, 12],
      [40, 41],
    ])
    expect(model.rows.map(shape)).toEqual([
      "fold",
      10,
      11,
      12,
      "fold",
      40,
      41,
      "fold",
    ])
  })

  test("maps every rendered line to its row index", () => {
    const model = buildSourceRows(60, [
      [10, 12],
      [40, 41],
    ])
    expect(model.rowByLine.get(10)).toBe(1)
    expect(model.rowByLine.get(12)).toBe(3)
    expect(model.rowByLine.get(40)).toBe(5)
    // Folded lines have no row of their own.
    expect(model.rowByLine.has(25)).toBe(false)
  })

  test("expanding a fold renders its lines in place", () => {
    const collapsed = buildSourceRows(20, [[10, 12]])
    const id = foldId(1, 9)
    const expanded = buildSourceRows(20, [[10, 12]], new Set([id]))
    expect(lineNumbers(collapsed)).toEqual([10, 11, 12])
    expect(lineNumbers(expanded).slice(0, 12)).toEqual([
      1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12,
    ])
    // The other fold is untouched.
    expect(folds(expanded)).toEqual([[13, 20]])
  })

  test("adjacent regions do not produce an empty fold between them", () => {
    const model = buildSourceRows(30, [
      [10, 12],
      [13, 15],
    ])
    expect(folds(model)).toEqual([
      [1, 9],
      [16, 30],
    ])
  })

  test("a region reaching the file's edges folds nothing there", () => {
    const model = buildSourceRows(10, [[1, 10]])
    expect(folds(model)).toEqual([])
    expect(model.foldedCount).toBe(0)
  })

  test("renders the whole file when there is nothing to fold against", () => {
    // No methods mapped (or an artifact that predates whole-method spans):
    // showing everything beats showing nothing.
    const model = buildSourceRows(5, [])
    expect(lineNumbers(model)).toEqual([1, 2, 3, 4, 5])
  })

  test("clamps a region that straddles the end of a truncated window", () => {
    // Anchors describe the whole file; the served window may stop early.
    const model = buildSourceRows(20, [[10, 400]])
    expect(lineNumbers(model)).toEqual(
      Array.from({ length: 11 }, (_, i) => 10 + i)
    )
    expect(folds(model)).toEqual([[1, 9]])
  })

  test("drops a region that starts past the window instead of clamping it", () => {
    // The orchestrator caps a source response at SOURCE_MAX_LINES and sets
    // `truncated`. A method beyond that window is not in this text at all —
    // clamping it would pin its header onto the last loaded line and label
    // unrelated code with that method's name. "Load more" brings it back.
    const model = buildSourceRows(
      2000,
      [
        [100, 120],
        [2500, 2540],
      ],
      new Set(),
      [
        { id: "m_near", signature: "A.near", startLine: 100 },
        { id: "m_far", signature: "A.far", startLine: 2500 },
      ]
    )
    expect(lineNumbers(model)).toEqual(
      Array.from({ length: 21 }, (_, i) => 100 + i)
    )
    expect(folds(model)).toEqual([
      [1, 99],
      [121, 2000],
    ])
    // …and no header claiming the far method lives at the window's edge.
    expect(
      model.rows.filter((r) => r.kind === "method").map((r) => r.id)
    ).toEqual(["m_near"])
  })

  test("merges overlapping and out-of-order regions", () => {
    const model = buildSourceRows(40, [
      [20, 25],
      [10, 22],
    ])
    expect(lineNumbers(model)).toEqual(
      Array.from({ length: 16 }, (_, i) => 10 + i)
    )
  })

  test("an empty file produces no rows", () => {
    expect(buildSourceRows(0, [[1, 5]]).rows).toEqual([])
  })
})

describe("finding a line that is folded away", () => {
  test("names the fold hiding a line", () => {
    const model = buildSourceRows(100, [[32, 42]])
    expect(foldContaining(model.rows, 5)).toMatchObject({
      startLine: 1,
      endLine: 31,
    })
    expect(foldContaining(model.rows, 35)).toBeNull()
  })

  test("scrolls to the fold when the line itself has no row", () => {
    // A selection must never be unreachable: the viewer scrolls to the fold and
    // opens it in the same pass.
    const model = buildSourceRows(100, [[32, 42]])
    expect(rowIndexForLine(model, 35)).toBe(model.rowByLine.get(35))
    expect(rowIndexForLine(model, 5)).toBe(0)
    expect(rowIndexForLine(model, 500)).toBeNull()
  })
})

describe("method header rows", () => {
  const METHODS = [
    { id: "m_1", signature: "com.acme.A.first", startLine: 32 },
    { id: "m_2", signature: "com.acme.A.second", startLine: 60 },
  ]

  test("puts a header immediately before each method's first line", () => {
    const model = buildSourceRows(
      100,
      [
        [32, 42],
        [60, 66],
      ],
      new Set(),
      METHODS
    )
    expect(model.rows.map(shape)).toEqual([
      "fold",
      "method",
      32,
      33,
      34,
      35,
      36,
      37,
      38,
      39,
      40,
      41,
      42,
      "fold",
      "method",
      60,
      61,
      62,
      63,
      64,
      65,
      66,
      "fold",
    ])
  })

  test("headers shift rowByLine, and the map stays truthful", () => {
    const model = buildSourceRows(
      100,
      [
        [32, 42],
        [60, 66],
      ],
      new Set(),
      METHODS
    )
    for (const [line, index] of model.rowByLine) {
      expect(model.rows[index]).toEqual({ kind: "line", line })
    }
    // …which is what keeps scroll-to-line landing on the line, not the header.
    expect(rowIndexForLine(model, 60)).toBe(model.rowByLine.get(60))
  })

  test("a method whose start line is folded away renders no header", () => {
    const model = buildSourceRows(100, [[60, 66]], new Set(), METHODS)
    expect(
      model.rows.filter((r) => r.kind === "method").map((r) => r.id)
    ).toEqual(["m_2"])
  })

  test("two methods declared on one line yield one header", () => {
    const model = buildSourceRows(50, [[10, 20]], new Set(), [
      { id: "m_a", signature: "A.a", startLine: 10 },
      { id: "m_b", signature: "A.b", startLine: 10 },
    ])
    expect(model.rows.filter((r) => r.kind === "method")).toHaveLength(1)
  })
})
