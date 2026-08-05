// A count that only the client knows must not change the DOM SHAPE (§13 SSR).
//
// `PanelHeader`'s count comes from a client fetch in every caller, so the
// server omits the span and a client hydrating against a warm query cache
// renders it. React treats a present-vs-absent element as a hard mismatch and
// regenerates the tree, which is louder than a wrong number and was reported
// from a real page load.
//
// These assert against the SERVER renderer rather than a mocked hook, because
// the bug lives in the difference between the two renderers — a client-only
// test cannot see it at all.
import { render } from "@testing-library/react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { PanelHeader } from "@/components/shared/panel-header"

describe("panel header hydration", () => {
  it("omits a client-known count from the server markup", () => {
    const html = renderToStaticMarkup(<PanelHeader label="Services" count={22} />)
    expect(html).toContain("Services")
    expect(html).not.toContain("22")
  })

  it("renders the same shape on the server whether or not a count is known", () => {
    // The actual invariant. Server output must not depend on cache warmth,
    // because the client's first render never does either.
    const withCount = renderToStaticMarkup(
      <PanelHeader label="Services" count={22} />
    )
    const withoutCount = renderToStaticMarkup(<PanelHeader label="Services" />)
    expect(withCount).toBe(withoutCount)
  })

  it("shows the count once mounted", () => {
    const { container } = render(<PanelHeader label="Services" count={22} />)
    expect(container.textContent).toContain("22")
  })

  it("still renders nothing when there is genuinely no count", () => {
    const { container } = render(<PanelHeader label="Services" />)
    expect(container.querySelector("span.font-mono")).toBeNull()
  })
})
