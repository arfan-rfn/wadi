import { describe, expect, test } from "vitest"

import {
  constrain,
  endpointPath,
  HOME_VIEWS,
  newestSucceeded,
  parseWorkspaceParams,
  serializeWorkspaceParams,
  snapshotPath,
  UNDETERMINED_ENTITY_KEY,
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

  test("the home Data view is a known view with its own URL (§5.2.17)", () => {
    expect(constrain("data", HOME_VIEWS, "coverage")).toBe("data")
    expect(snapshotPath("snap_1", { view: "data" })).toBe("/s/snap_1?view=data")
  })

  test("endpoint path carries workspace params", () => {
    expect(endpointPath("snap_1", "ep_a")).toBe("/s/snap_1/e/ep_a")
    expect(endpointPath("snap_1", "ep_a", { node: "n1", focus: "m_2" })).toBe(
      "/s/snap_1/e/ep_a?node=n1&focus=m_2"
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
      file: "src/A.java",
      pane: "data" as const,
      entity: "com.acme.pets.Pet",
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

  test("unknown params are ignored rather than carried", () => {
    // lens/tab were retired with the workspace tab strip (§5.2.9 UI); a stale
    // bookmark carrying them must still parse to a clean default state.
    const parsed = parseWorkspaceParams(
      new URLSearchParams("lens=hologram&tab=nope&node=stmt:n1")
    )
    expect(parsed).toEqual({ ...WORKSPACE_DEFAULTS, node: "stmt:n1" })
  })
})

describe("the Data pane in the URL (R1-26, E6)", () => {
  test("absent pane means the call tree, and writes nothing", () => {
    const parsed = parseWorkspaceParams(new URLSearchParams())
    expect(parsed.pane).toBe("calls")
    expect(parsed.entity).toBeNull()
    expect(
      serializeWorkspaceParams({ pane: "calls", entity: null }).toString()
    ).toBe("")
  })

  test("pane=data and a qualified entity name round-trip", () => {
    const query = serializeWorkspaceParams({
      pane: "data",
      entity: "com.acme.pets.Pet",
    })
    expect(query.toString()).toBe("pane=data&entity=com.acme.pets.Pet")
    expect(parseWorkspaceParams(query)).toMatchObject({
      pane: "data",
      entity: "com.acme.pets.Pet",
    })
  })

  test("the undetermined row round-trips as ~undetermined", () => {
    const query = serializeWorkspaceParams({
      pane: "data",
      entity: UNDETERMINED_ENTITY_KEY,
    })
    expect(query.get("entity")).toBe("~undetermined")
    expect(parseWorkspaceParams(query).entity).toBe(UNDETERMINED_ENTITY_KEY)
  })

  test("an entity is only meaningful in the Data pane (one form only)", () => {
    // E6: the selected entity belongs to the Data list. A URL that names one
    // while showing the call tree would be a second spelling of the same
    // state, so it neither parses nor serializes.
    expect(
      parseWorkspaceParams(new URLSearchParams("entity=com.acme.pets.Pet"))
        .entity
    ).toBeNull()
    expect(
      serializeWorkspaceParams({
        pane: "calls",
        entity: "com.acme.pets.Pet",
      }).toString()
    ).toBe("")
  })

  test("an unknown pane value falls back to the call tree", () => {
    expect(
      parseWorkspaceParams(new URLSearchParams("pane=entities")).pane
    ).toBe("calls")
  })

  test("the endpoint path deep-links straight into a selected entity", () => {
    expect(
      endpointPath("snap_1", "ep_a", {
        pane: "data",
        entity: "com.acme.pets.Pet",
      })
    ).toBe("/s/snap_1/e/ep_a?pane=data&entity=com.acme.pets.Pet")
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
