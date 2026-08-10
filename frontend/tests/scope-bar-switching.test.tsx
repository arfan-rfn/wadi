// The scope switchers must actually switch.
//
// Both rows were wired with `onSelect`, which is Radix's menu-item callback.
// This menu is Base UI (`@base-ui/react/menu`), whose item exposes `onClick`
// and `closeOnClick` and has no `onSelect` at all. The prop was therefore
// spread onto the underlying element, where React DOM recognised it as the
// *text-selection* handler — so it typechecked, attached silently, and never
// fired for a click. The menus opened, highlighted and closed correctly
// (Base UI owns all of that), and only the app's handler was dead: clicking
// any system or snapshot did nothing at all.
//
// Nothing caught it. `selected` was covered (dropdown-selected.test.tsx),
// the rendering was covered, and the one thing the control exists to do was
// not. These tests fire a real click and assert the callback runs, which is
// the only assertion that can tell `onClick` from `onSelect`.
import { fireEvent, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import type { Snapshot } from "@/lib/generated/snapshot.schema"
import type { System } from "@/lib/generated/system.schema"
import { ScopeBar } from "@/components/explorer/scope-bar"

import { renderWithQuery } from "./utils"

function makeSystem(id: string, name: string): System {
  return {
    schema_version: "1.0.0",
    id,
    name,
    repos: [{ source: `/repos/${name}`, branch: null, cred_ref: null }],
    created_at: "2026-08-01T00:00:00Z",
  }
}

function makeSnapshot(id: string, systemId: string, created: string): Snapshot {
  return {
    schema_version: "1.0.0",
    id,
    system_id: systemId,
    commits: {},
    status: "succeeded",
    created_at: created,
  }
}

const SYSTEMS = [makeSystem("sys_a", "alpha"), makeSystem("sys_b", "beta")]
// Hash-shaped ids, like the real ones: the rows render the id with `snap_`
// stripped, so short numeric stand-ins would collide with the repo counts and
// timestamps elsewhere in the menu.
const SNAPSHOTS = [
  makeSnapshot("snap_aaaa1111", "sys_a", "2026-08-06T10:00:00Z"),
  makeSnapshot("snap_bbbb2222", "sys_a", "2026-08-05T10:00:00Z"),
]

function renderBar(overrides: Partial<Parameters<typeof ScopeBar>[0]> = {}) {
  const onSystem = vi.fn()
  const onSnapshot = vi.fn()
  renderWithQuery(
    <ScopeBar
      systems={SYSTEMS}
      snapshots={SNAPSHOTS}
      systemId="sys_a"
      snapshotId="snap_aaaa1111"
      onSystem={onSystem}
      onSnapshot={onSnapshot}
      {...overrides}
    />
  )
  return { onSystem, onSnapshot }
}

/** Open a closed menu by its trigger label and return its rows. */
function openMenu(triggerText: string): HTMLElement[] {
  fireEvent.click(screen.getByText(triggerText))
  return screen.getAllByRole("menuitem")
}

/** The menu row carrying `label`. Scoped to rows on purpose: the trigger
 *  shows the current value too, so a bare text query matches it as well. */
function rowFor(label: string): HTMLElement {
  const rows = screen
    .getAllByRole("menuitem")
    .filter((row) => row.textContent?.includes(label))
  if (rows.length !== 1)
    throw new Error(`expected exactly one row for ${label}, got ${rows.length}`)
  return rows[0]
}

describe("scope bar switching", () => {
  it("calls onSystem with the clicked system's id", () => {
    const { onSystem } = renderBar()
    openMenu("alpha")
    fireEvent.click(rowFor("beta"))
    expect(onSystem).toHaveBeenCalledWith("sys_b")
  })

  it("calls onSnapshot with the clicked snapshot's id", () => {
    const { onSnapshot } = renderBar()
    // Rows render the id with the `snap_` prefix stripped.
    openMenu("aaaa1111")
    fireEvent.click(rowFor("bbbb2222"))
    expect(onSnapshot).toHaveBeenCalledWith("snap_bbbb2222")
  })

  it("still fires for the row that is already current", () => {
    // Re-picking the current value is a legitimate way to get back to it
    // after drilling in, so the handler must not be suppressed for it.
    const { onSystem } = renderBar()
    openMenu("alpha")
    fireEvent.click(rowFor("alpha"))
    expect(onSystem).toHaveBeenCalledWith("sys_a")
  })

  it("wires the handler to click, not to the text-selection event", () => {
    // The exact regression: `onSelect` on a div is React's selection event,
    // which a pointer click never triggers. Asserting the click path alone
    // would pass again if someone reintroduced `onSelect` *alongside* it, so
    // pin that a bare select event moves nothing.
    const { onSystem } = renderBar()
    openMenu("alpha")
    fireEvent.select(rowFor("beta"))
    expect(onSystem).not.toHaveBeenCalled()
  })
})
