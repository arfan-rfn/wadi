// The role palette's one promise: a role's colour comes from its NAME.
import { describe, expect, test } from "vitest"

import {
  buildRolePalette,
  preferredHue,
  ROLE_HUE_COUNT,
} from "@/lib/wadi/role-colors"

describe("role colours", () => {
  test("the same role set always yields the same colours", () => {
    // The whole point of the legend is that a swatch can be LEARNED, so the
    // assignment must not depend on the order roles happened to arrive in.
    const a = buildRolePalette(["USER", "ADMIN", "SERVICE"])
    const b = buildRolePalette(["SERVICE", "ADMIN", "USER"])
    expect([...a.entries()].sort()).toEqual([...b.entries()].sort())
  })

  test("case does not change a role's colour", () => {
    // Services spell the same role both ways; two swatches for one role would
    // read as two roles.
    const palette = buildRolePalette(["admin", "ADMIN", "Admin"])
    expect(palette.size).toBe(1)
  })

  test("colliding roles are separated, not merged", () => {
    // ADMIN and SERVICE both PREFER hue 4 — the exact collision that makes a
    // pure hash unusable here. The probe must give them different hues.
    expect(preferredHue("ADMIN")).toBe(preferredHue("SERVICE"))
    const palette = buildRolePalette(["ADMIN", "SERVICE"])
    expect(palette.get("ADMIN")).not.toBe(palette.get("SERVICE"))
  })

  test("every role in a full wheel gets a distinct hue", () => {
    const roles = Array.from({ length: ROLE_HUE_COUNT }, (_, i) => `ROLE_${i}`)
    const palette = buildRolePalette(roles)
    expect(new Set(palette.values()).size).toBe(ROLE_HUE_COUNT)
  })

  test("a role keeps its hue when unrelated roles join", () => {
    // Adding a role must not repaint the ones a reader already learned, unless
    // the newcomer actually collides with one.
    const before = buildRolePalette(["ADMIN", "USER"])
    const after = buildRolePalette(["ADMIN", "USER", "AUDITOR"])
    expect(after.get("USER")).toBe(before.get("USER"))
  })
})
