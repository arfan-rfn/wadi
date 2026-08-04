import { describe, expect, test } from "vitest"

import {
  constrain,
  endpointPath,
  newestSucceeded,
  parseWorkspaceParams,
  serializeWorkspaceParams,
  snapshotPath,
  WORKSPACE_DEFAULTS,
} from "@/lib/wadi/routes"

describe("newestSucceeded — what `/` lands on", () => {
  const snap = (id: string, created_at: string, status = "succeeded") => ({
    id,
    created_at,
    status,
  })

  test("picks the most recently created succeeded snapshot", () => {
    const picked = newestSucceeded([
      snap("old", "2026-08-01T00:00:00+00:00"),
      snap("newest", "2026-08-03T00:00:00+00:00"),
      snap("mid", "2026-08-02T00:00:00+00:00"),
    ])
    expect(picked?.id).toBe("newest")
  })

  test("skips newer non-succeeded runs in favour of a succeeded one", () => {
    const picked = newestSucceeded([
      snap("running", "2026-08-09T00:00:00+00:00", "running"),
      snap("failed", "2026-08-08T00:00:00+00:00", "failed"),
      snap("good", "2026-08-01T00:00:00+00:00"),
    ])
    expect(picked?.id).toBe("good")
  })

  test("falls back to the newest run when none succeeded", () => {
    const picked = newestSucceeded([
      snap("older-fail", "2026-08-01T00:00:00+00:00", "failed"),
      snap("newer-fail", "2026-08-05T00:00:00+00:00", "failed"),
    ])
    expect(picked?.id).toBe("newer-fail")
  })

  // The regression: the resolver used to read systems[0] only. With
  // spring-petstore-mini sorting first and holding zero snapshots, the UI
  // announced "no snapshots yet" while 39 succeeded snapshots existed in six
  // other systems. Pooling every system's snapshots is what fixes it.
  test("a system with no snapshots does not mask other systems", () => {
    const petstore: { id: string; created_at: string; status: string }[] = []
    const trainTicket = [snap("snap_tt", "2026-08-03T08:13:58+00:00")]
    expect(newestSucceeded([...petstore, ...trainTicket])?.id).toBe("snap_tt")
  })

  test("empty everywhere yields null", () => {
    expect(newestSucceeded([])).toBeNull()
  })
})

describe("route builders (§11 Phase 2.8)", () => {
  test("snapshot path omits defaults", () => {
    expect(snapshotPath("snap_1")).toBe("/s/snap_1")
    expect(snapshotPath("snap_1", { view: "coverage" })).toBe("/s/snap_1")
    expect(
      snapshotPath("snap_1", { view: "services", serviceId: "svc_9" })
    ).toBe("/s/snap_1?view=services&service=svc_9")
  })

  test("endpoint path carries workspace params", () => {
    expect(endpointPath("snap_1", "ep_a")).toBe("/s/snap_1/e/ep_a")
    expect(endpointPath("snap_1", "ep_a", { node: "n1", lens: "source" })).toBe(
      "/s/snap_1/e/ep_a?node=n1&lens=source"
    )
  })
})

describe("workspace params round-trip", () => {
  test("defaults parse from an empty query", () => {
    expect(parseWorkspaceParams(new URLSearchParams())).toEqual(
      WORKSPACE_DEFAULTS
    )
  })

  test("full state round-trips", () => {
    const state = {
      node: "n42",
      focus: "m_7",
      expand: ["m_1", "m_2"],
      lens: "source" as const,
      tab: "endpoint" as const,
      file: "src/A.java",
    }
    const query = serializeWorkspaceParams(state)
    expect(parseWorkspaceParams(query)).toEqual({
      ...state,
      expand: ["m_1", "m_2"],
    })
  })

  test("expand sentinels survive", () => {
    for (const sentinel of ["all", "none"] as const) {
      const query = serializeWorkspaceParams({ expand: sentinel })
      expect(parseWorkspaceParams(query).expand).toBe(sentinel)
    }
  })

  // Regression: collapsing the one lane the default view auto-expands used to
  // serialize to an EMPTY query — indistinguishable from "never touched it".
  // Reloading then resurrected the lane the user had just collapsed.
  test("an explicitly-empty expand set is not mistaken for the default", () => {
    const query = serializeWorkspaceParams({ expand: [] })
    expect(query.get("expand")).toBe("none")
    expect(parseWorkspaceParams(query).expand).toBe("none")
  })

  test("defaults are omitted from the query", () => {
    expect(serializeWorkspaceParams(WORKSPACE_DEFAULTS).toString()).toBe("")
  })

  test("invalid enum values clamp to defaults", () => {
    const params = new URLSearchParams("lens=hologram&tab=nope")
    const parsed = parseWorkspaceParams(params)
    expect(parsed.lens).toBe("graph")
    expect(parsed.tab).toBe("source")
  })
})

describe("constrain", () => {
  test("keeps known values, clamps unknown", () => {
    expect(constrain("map", ["coverage", "map"] as const, "coverage")).toBe(
      "map"
    )
    expect(constrain("bogus", ["coverage", "map"] as const, "coverage")).toBe(
      "coverage"
    )
    expect(constrain(null, ["coverage", "map"] as const, "coverage")).toBe(
      "coverage"
    )
  })
})
