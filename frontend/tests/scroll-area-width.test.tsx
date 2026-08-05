// A vertical ScrollArea must not let its content grow wider than the pane.
//
// Radix wraps a Viewport's children in `display: table; min-width: 100%`. A
// table box is shrink-to-fit, so one unbreakable string — a long URI, an
// access rule, a deep file path — widens it past the viewport. Children then
// size against the wider box, so `truncate` and `break-all` measure the wrong
// width, and Root's `overflow-hidden` clips the excess with no bar to scroll
// it back: the content is simply gone. Reported from the endpoint peek, where
// access rules and call-out badges were cut off at the right edge.
//
// jsdom computes no layout, so these assert the CONTRACT that governs it —
// which box the children live in — rather than pixel widths.
import { render } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { ScrollArea } from "@/components/ui/scroll-area"

/** The rule rides the VIEWPORT as a Tailwind child-variant — `[&>div]:!block`
 *  compiles to a rule targeting the wrapper, so the wrapper itself carries no
 *  class of its own to assert on. Radix must still render exactly one wrapper
 *  for that selector to bite, which is checked alongside it. */
function viewportOf(container: HTMLElement): HTMLElement {
  const viewport = container.querySelector<HTMLElement>(
    "[data-radix-scroll-area-viewport]"
  )
  if (!viewport) throw new Error("no Radix viewport rendered")
  return viewport
}

describe("scroll area content width", () => {
  it("keeps content in a block box when there is no horizontal bar", () => {
    const { container } = render(
      <ScrollArea>
        <p>/api/v1/executeservice/** -&gt; hasAnyRole(ROLE_ADMIN, ROLE_USER)</p>
      </ScrollArea>
    )
    const viewport = viewportOf(container)
    expect(viewport.className).toContain("[&>div]:!block")
    // The selector is only meaningful against Radix's single wrapper div; if
    // upstream ever stops rendering it, this fix is silently inert.
    expect(viewport.firstElementChild?.tagName).toBe("DIV")
  })

  it("leaves the table box alone when a horizontal bar exists", () => {
    // There the shrink-to-fit box is the point: it is what makes wide content
    // reachable instead of clipped. Forcing block would trade one class of
    // lost content for another.
    for (const orientation of ["horizontal", "both"] as const) {
      const { container } = render(
        <ScrollArea orientation={orientation}>
          <pre>a very wide line of code</pre>
        </ScrollArea>
      )
      expect(viewportOf(container).className).not.toContain("[&>div]:!block")
    }
  })

  it("still honours a caller's own viewport classes", () => {
    const { container } = render(
      <ScrollArea viewportClassName="bg-muted">
        <p>x</p>
      </ScrollArea>
    )
    const viewport = container.querySelector<HTMLElement>(
      "[data-radix-scroll-area-viewport]"
    )
    expect(viewport?.className).toContain("bg-muted")
  })
})
