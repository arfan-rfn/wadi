// The responsive switch, pinned. `useMediaQuery` decides whether the endpoint
// workspace shows three panels or one, so its contract is load-bearing for
// every layout in the app — and it is the exact shape that produces hydration
// mismatches when it gets clever: reading `window.matchMedia` during render
// makes the server's markup disagree with the client's, and React silently
// discards one of them.
import { act, render } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { BREAKPOINT, useMediaQuery } from "@/lib/hooks/use-media-query"

/** A controllable `matchMedia` that records its listeners, so a test can flip
 *  the match the way a real viewport resize does. */
function stubMatchMedia(initial: boolean) {
  const listeners = new Set<() => void>()
  const list = {
    matches: initial,
    addEventListener: (_: string, fn: () => void) => listeners.add(fn),
    removeEventListener: (_: string, fn: () => void) => listeners.delete(fn),
  }
  const matchMedia = vi.fn(() => list)
  vi.stubGlobal("matchMedia", matchMedia)
  return {
    matchMedia,
    set(next: boolean) {
      list.matches = next
      for (const fn of listeners) fn()
    },
    listenerCount: () => listeners.size,
  }
}

function Probe({ query }: { query: string }) {
  return <span data-testid="v">{String(useMediaQuery(query))}</span>
}

afterEach(() => vi.unstubAllGlobals())

describe("useMediaQuery", () => {
  it("settles to the real match after mount", () => {
    stubMatchMedia(true)
    const { getByTestId } = render(<Probe query={BREAKPOINT.lg} />)
    expect(getByTestId("v").textContent).toBe("true")
  })

  it("returns false when the query does not match", () => {
    stubMatchMedia(false)
    const { getByTestId } = render(<Probe query={BREAKPOINT.lg} />)
    expect(getByTestId("v").textContent).toBe("false")
  })

  it("follows the viewport when the match changes", () => {
    const media = stubMatchMedia(false)
    const { getByTestId } = render(<Probe query={BREAKPOINT.lg} />)
    expect(getByTestId("v").textContent).toBe("false")
    act(() => media.set(true))
    expect(getByTestId("v").textContent).toBe("true")
  })

  it("unsubscribes on unmount", () => {
    // A leaked listener keeps a torn-down tree alive and fires setState on it.
    const media = stubMatchMedia(false)
    const { unmount } = render(<Probe query={BREAKPOINT.lg} />)
    expect(media.listenerCount()).toBe(1)
    unmount()
    expect(media.listenerCount()).toBe(0)
  })

  it("renders on the server without touching matchMedia", async () => {
    // The whole reason this hook exists. Reading `window.matchMedia` during
    // render throws on the server and shifts every Radix `useId` after it on
    // the client — which is how this codebase's hydration mismatches have
    // started twice. A server render with no `matchMedia` at all is the proof.
    const { renderToString } = await import("react-dom/server")
    vi.stubGlobal("matchMedia", undefined)
    expect(() => renderToString(<Probe query={BREAKPOINT.lg} />)).not.toThrow()
  })

  it("commits false first, so the pre-hydration frame matches the server", () => {
    // The server can only produce the false branch, so the client's first
    // commit has to agree with it — the layout widens after mount, never
    // narrows. `matchMedia` reports a match here and the first paint is still
    // false; only the effect moves it.
    const media = stubMatchMedia(true)
    const seen: boolean[] = []
    function Recorder({ query }: { query: string }) {
      seen.push(useMediaQuery(query))
      return null
    }
    render(<Recorder query={BREAKPOINT.lg} />)
    expect(seen[0]).toBe(false)
    expect(seen[seen.length - 1]).toBe(true)
    expect(media.matchMedia).toHaveBeenCalledWith(BREAKPOINT.lg)
  })

  it("exposes Tailwind's breakpoints so TS and CSS cannot drift", () => {
    expect(BREAKPOINT.md).toBe("(min-width: 48rem)")
    expect(BREAKPOINT.lg).toBe("(min-width: 64rem)")
    expect(BREAKPOINT.xl).toBe("(min-width: 80rem)")
  })
})
