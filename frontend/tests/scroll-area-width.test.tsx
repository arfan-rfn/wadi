// A vertical ScrollArea must not let its content grow wider than the pane.
//
// History: Radix wrapped a Viewport's children in `display: table;
// min-width: 100%`. A table box is shrink-to-fit, so one unbreakable string —
// a long URI, an access rule, a deep file path — widened it past the viewport.
// Children then sized against the wider box, `truncate` and `break-all`
// measured the wrong width, and Root's `overflow-hidden` clipped the excess
// with no bar to scroll it back: the content was simply gone. Reported from
// the endpoint peek, where access rules and call-out badges were cut off at
// the right edge. The fix was a `[&>div]:!block` child-variant on the viewport.
//
// Base UI (2026-08-06) renders children DIRECTLY into the viewport — there is
// no intermediate box to fight. The override is gone, and what these tests
// pin is the structural property that made it unnecessary, so that a future
// upstream change reintroducing a wrapper fails here rather than silently in
// the endpoint peek.
//
// jsdom computes no layout, so these assert the CONTRACT that governs it —
// which box the children live in — rather than pixel widths.
import { render } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { ScrollArea } from "@/components/ui/scroll-area"

function viewportOf(container: HTMLElement): HTMLElement {
  const viewport = container.querySelector<HTMLElement>('[data-id$="-viewport"]')
  if (!viewport) throw new Error("no scroll-area viewport rendered")
  return viewport
}

describe("scroll area content width", () => {
  it("renders content directly into the viewport, with no intervening box", () => {
    const { container } = render(
      <ScrollArea>
        <p>/api/v1/executeservice/** -&gt; hasAnyRole(ROLE_ADMIN, ROLE_USER)</p>
      </ScrollArea>
    )
    const viewport = viewportOf(container)
    // The whole point: the caller's own element is the first child. Any
    // wrapper here is a shrink-to-fit box waiting to clip a long URI again.
    expect(viewport.firstElementChild?.tagName).toBe("P")
    expect(viewport.children).toHaveLength(1)
  })

  it("does the same when a horizontal bar exists", () => {
    // Wide content stays reachable through the horizontal scrollbar rather
    // than through a shrink-to-fit content box, so the structure is identical
    // in every orientation — one rule to reason about instead of two.
    for (const orientation of ["horizontal", "both"] as const) {
      const { container } = render(
        <ScrollArea orientation={orientation}>
          <pre>a very wide line of code</pre>
        </ScrollArea>
      )
      expect(viewportOf(container).firstElementChild?.tagName).toBe("PRE")
    }
  })

  it("still honours a caller's own viewport classes", () => {
    const { container } = render(
      <ScrollArea viewportClassName="bg-muted">
        <p>x</p>
      </ScrollArea>
    )
    expect(viewportOf(container).className).toContain("bg-muted")
  })
})
