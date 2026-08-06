import { beforeEach, describe, expect, it } from "vitest"

import {
  applyDensity,
  DENSITY_INIT_SCRIPT,
  readDensity,
  writeDensity,
} from "@/lib/wadi/density"

describe("density preference", () => {
  beforeEach(() => {
    window.localStorage.clear()
    document.documentElement.removeAttribute("data-density")
  })

  it("defaults to comfortable when nothing is stored", () => {
    expect(readDensity()).toBe("comfortable")
  })

  it("round-trips a stored preference", () => {
    writeDensity("compact")
    expect(readDensity()).toBe("compact")
    writeDensity("comfortable")
    expect(readDensity()).toBe("comfortable")
  })

  it("falls back to comfortable on a corrupt stored value", () => {
    // A value written by an older build, or by hand. It must not become an
    // attribute the CSS has no rule for.
    window.localStorage.setItem("wadi.density", "ultra")
    expect(readDensity()).toBe("comfortable")
  })

  it("expresses comfortable as the ABSENCE of the attribute", () => {
    // Comfortable is the `:root` baseline, so there is exactly one override to
    // read rather than two competing states.
    applyDensity("compact")
    expect(document.documentElement.getAttribute("data-density")).toBe("compact")
    applyDensity("comfortable")
    expect(document.documentElement.hasAttribute("data-density")).toBe(false)
  })

  it("the pre-paint script stamps compact and survives blocked storage", () => {
    window.localStorage.setItem("wadi.density", "compact")
    // eslint-disable-next-line no-new-func
    new Function(DENSITY_INIT_SCRIPT)()
    expect(document.documentElement.getAttribute("data-density")).toBe("compact")

    // The script is wrapped in try/catch precisely because localStorage throws
    // outright in some privacy modes; a themed page must still render.
    document.documentElement.removeAttribute("data-density")
    const original = window.localStorage.getItem
    window.localStorage.getItem = () => {
      throw new Error("storage blocked")
    }
    expect(() => new Function(DENSITY_INIT_SCRIPT)()).not.toThrow()
    window.localStorage.getItem = original
  })

  it("never emits a size token — density is spacing only", () => {
    // The guarantee that makes compact safe: it may not shrink type. If a
    // font-size ever appears in the compact block this test is the tripwire.
    expect(DENSITY_INIT_SCRIPT).not.toMatch(/font|text|size/i)
  })
})
