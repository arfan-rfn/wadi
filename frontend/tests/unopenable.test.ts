// §5.4.2 T5: a call with no interior must explain itself.
//
// The bug this guards is not a crash — it is a slice that looked like it had
// lost source files when in fact 92.9% of the dead-end calls were Lombok
// accessors with no source line anywhere. Silence is what made a correct
// extraction read as data loss.
import { describe, expect, it } from "vitest"

import { unopenableCopy } from "@/lib/wadi/unopenable"

const REASONS = [
  "lombok-generated",
  "inherited-external",
  "compiler-generated",
  "third-party",
  "ambiguous-overload",
  "unresolved-receiver",
] as const

describe("unopenableCopy", () => {
  it("returns null for a call that opens normally", () => {
    expect(unopenableCopy(null)).toBeNull()
    expect(unopenableCopy(undefined)).toBeNull()
    expect(unopenableCopy("")).toBeNull()
  })

  it.each(REASONS)("explains %s with a badge and a sentence", (reason) => {
    const copy = unopenableCopy(reason)
    expect(copy).not.toBeNull()
    expect(copy!.badge.length).toBeGreaterThan(0)
    // Long enough to actually say why, not just restate the code.
    expect(copy!.detail.length).toBeGreaterThan(40)
  })

  it("states an unknown reason rather than pretending the call opens", () => {
    // A newer backend reason must not silently degrade to "no badge", which
    // would render exactly the unexplained dead end this work removed.
    const copy = unopenableCopy("some-future-reason")
    expect(copy).not.toBeNull()
    expect(copy!.detail).toContain("some-future-reason")
  })

  it("never blames the analysis for generated code", () => {
    // Wording matters here: this is a fact about how the code is built, not a
    // failure report. "Lombok generates this" reads very differently from
    // "could not resolve".
    const copy = unopenableCopy("lombok-generated")!
    expect(copy.detail).toMatch(/generates/i)
    expect(copy.detail).not.toMatch(/error|failed|missing/i)
  })
})
