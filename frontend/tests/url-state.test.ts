import { describe, expect, test } from "vitest"

import { constrain, parseUrlState, writeUrlState } from "@/lib/wadi/url-state"

describe("deep-link url state (§11 Phase 2.7)", () => {
  test("parses only known keys, absent keys are null", () => {
    const state = parseUrlState(
      new URLSearchParams("snapshot=snap_1&service=svc_2&bogus=x")
    )
    expect(state.snapshot).toBe("snap_1")
    expect(state.service).toBe("svc_2")
    expect(state.system).toBeNull()
    expect(state.endpoint).toBeNull()
    expect("bogus" in state).toBe(false)
  })

  test("writeUrlState mirrors state into the URL and drops nulls", () => {
    window.history.replaceState(null, "", "/?service=stale&tab=json")
    writeUrlState({
      system: "sys_1",
      snapshot: "snap_1",
      service: null,
      endpoint: "ep_9",
      view: null,
      tab: null,
      node: null,
    })
    const params = new URLSearchParams(window.location.search)
    expect(params.get("system")).toBe("sys_1")
    expect(params.get("snapshot")).toBe("snap_1")
    expect(params.get("endpoint")).toBe("ep_9")
    expect(params.get("service")).toBeNull()
    expect(params.get("tab")).toBeNull()
  })

  test("preserves unknown query params it does not own", () => {
    window.history.replaceState(null, "", "/?utm=abc")
    writeUrlState({
      system: "sys_1",
      snapshot: null,
      service: null,
      endpoint: null,
      view: null,
      tab: null,
      node: null,
    })
    expect(new URLSearchParams(window.location.search).get("utm")).toBe("abc")
  })

  test("constrain falls back on absent or invalid values", () => {
    expect(constrain(null, ["a", "b"] as const, "a")).toBe("a")
    expect(constrain("z", ["a", "b"] as const, "a")).toBe("a")
    expect(constrain("b", ["a", "b"] as const, "a")).toBe("b")
  })
})
