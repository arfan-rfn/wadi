// The CURRENT value's row must be distinguishable from the row the pointer
// happens to be over. Those are different facts, and before this they were
// not separable: selection was a lone tick at the far right of a 380px row,
// hundreds of pixels from where reading starts, in a list of 35 near-identical
// hashes. These pin the affordance so it cannot silently regress to that.
import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
} from "@/components/ui/dropdown-menu"

function openMenu(selectedValue: string) {
  return render(
    <DropdownMenu open>
      <DropdownMenuContent>
        <DropdownMenuGroup>
          {["alpha", "beta"].map((value) => (
            <DropdownMenuItem key={value} selected={value === selectedValue}>
              {value}
            </DropdownMenuItem>
          ))}
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function rowFor(label: string): HTMLElement {
  const row = screen.getByText(label).closest('[role="menuitem"]')
  if (!(row instanceof HTMLElement)) throw new Error(`no row for ${label}`)
  return row
}

describe("dropdown selected state", () => {
  it("marks only the current value as selected", () => {
    openMenu("alpha")
    expect(rowFor("alpha").getAttribute("aria-selected")).toBe("true")
    expect(rowFor("beta").getAttribute("aria-selected")).toBe("false")
  })

  it("carries a visible fill and ring, not a one-sided bar", () => {
    // A coloured left border reads as a decorative rule rather than as state,
    // and vanishes the moment the row is also hover-highlighted. Inset fill
    // plus a ring survives both.
    openMenu("alpha")
    const cls = rowFor("alpha").className
    expect(cls).toContain("bg-accent/60")
    expect(cls).toContain("ring-inset")
    expect(cls).not.toMatch(/border-l-|border-l\b/)
  })

  it("reserves the tick gutter on every row, selected or not", () => {
    // Without a permanent gutter each row shifts sideways as the selection
    // moves, which makes a column of hashes impossible to compare.
    openMenu("alpha")
    for (const label of ["alpha", "beta"]) {
      const gutter = rowFor(label).querySelector("span[aria-hidden]")
      expect(gutter, `${label} has no gutter`).not.toBeNull()
      expect((gutter as HTMLElement).className).toContain("w-4")
    }
  })

  it("leaves rows untouched when `selected` is not passed at all", () => {
    // Menus that are not value pickers (actions, links) must not grow a
    // gutter they have no use for.
    render(
      <DropdownMenu open>
        <DropdownMenuContent>
          <DropdownMenuItem>just an action</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    )
    const row = rowFor("just an action")
    expect(row.getAttribute("aria-selected")).toBeNull()
    expect(row.querySelector("span[aria-hidden]")).toBeNull()
  })
})
