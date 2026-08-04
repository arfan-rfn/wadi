// Regression: the workspace's panel-size persistence must not touch
// `localStorage` during server render. `useDefaultLayout` reads its storage
// at render time, so a bare `localStorage` reference threw
// "ReferenceError: localStorage is not defined" on every SSR pass of
// /s/[snapshotId]/e/[endpointId]. React recovered by client-rendering the
// subtree, which is exactly why it stayed invisible in the browser.
import { afterEach, describe, expect, it, vi } from "vitest"

import { browserLayoutStorage } from "@/components/endpoint/workspace-interior"

describe("browserLayoutStorage", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    window.localStorage.clear()
  })

  it("round-trips through localStorage in the browser", () => {
    browserLayoutStorage.setItem("wadi-test-layout", "[30,50,20]")
    expect(browserLayoutStorage.getItem("wadi-test-layout")).toBe("[30,50,20]")
  })

  it("returns null instead of throwing when there is no window (SSR)", () => {
    vi.stubGlobal("window", undefined)
    expect(() =>
      browserLayoutStorage.getItem("wadi-endpoint-workspace")
    ).not.toThrow()
    expect(browserLayoutStorage.getItem("wadi-endpoint-workspace")).toBeNull()
  })

  it("swallows writes instead of throwing when there is no window (SSR)", () => {
    vi.stubGlobal("window", undefined)
    expect(() =>
      browserLayoutStorage.setItem("wadi-endpoint-workspace", "[30,50,20]")
    ).not.toThrow()
  })
})
