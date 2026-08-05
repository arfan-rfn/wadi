"use client"

// Role → colour (§5.2.9 UI).
//
// A role's swatch must be LEARNABLE: see "ADMIN 95" in the legend once, and
// every rose dot in the list is readable without a tooltip afterwards. That
// rules out colouring by list position, which would repaint the whole system
// the moment one service gained a role.
//
// Hashing the name gets most of the way there, but not all: with eight hues
// and a handful of roles the birthday odds of a clash are around a third, and
// a clash is fatal — two roles wearing one colour is worse than no colour at
// all. `ADMIN` and `SERVICE` collide in exactly this way. So the hash picks a
// PREFERRED hue and a linear probe resolves collisions against the snapshot's
// actual role set: deterministic for a given set, stable as long as the set is,
// and collision-free up to the size of the wheel.
import { createContext, useContext, useMemo } from "react"

export const ROLE_HUE_COUNT = 8

/**
 * FNV-1a. Cheap, stable and well-distributed — the point is that it gives the
 * same answer in every browser and every build, which ad-hoc character sums do
 * not reliably do once a name contains non-ASCII.
 */
function hash(value: string): number {
  let h = 0x811c9dc5
  for (let i = 0; i < value.length; i++) {
    h ^= value.charCodeAt(i)
    h = Math.imul(h, 0x01000193)
  }
  return h >>> 0
}

/** The hue a role prefers, before any collision is resolved. */
export function preferredHue(role: string): number {
  return hash(role.toUpperCase()) % ROLE_HUE_COUNT
}

/**
 * Assign every role a distinct hue.
 *
 * Roles are sorted first so the result depends only on the SET, never on the
 * order they happened to arrive in — two components handed the same roles must
 * paint the same colours. Beyond `ROLE_HUE_COUNT` roles the wheel necessarily
 * repeats; that is stated here rather than hidden, and it is the point at which
 * colour stops being the right encoding.
 */
export function buildRolePalette(roles: Iterable<string>): Map<string, number> {
  const unique = [...new Set([...roles].map((role) => role.toUpperCase()))].sort()
  const palette = new Map<string, number>()
  const taken = new Set<number>()
  for (const role of unique) {
    let hue = preferredHue(role)
    for (let probe = 0; probe < ROLE_HUE_COUNT && taken.has(hue); probe++)
      hue = (hue + 1) % ROLE_HUE_COUNT
    taken.add(hue)
    palette.set(role, hue)
  }
  return palette
}

const RolePaletteContext = createContext<Map<string, number> | null>(null)

export function RolePaletteProvider({
  roles,
  children,
}: {
  roles: Iterable<string>
  children: React.ReactNode
}) {
  const key = [...new Set([...roles].map((r) => r.toUpperCase()))].sort().join(",")
  // Keyed on the role SET, so a re-render with the same roles keeps the exact
  // same Map identity and nothing downstream repaints.
  const palette = useMemo(() => buildRolePalette(key ? key.split(",") : []), [key])
  return (
    <RolePaletteContext.Provider value={palette}>
      {children}
    </RolePaletteContext.Provider>
  )
}

/**
 * The CSS custom property carrying this role's colour.
 *
 * Falls back to the unprobed hash when no provider is present, so a row still
 * renders a sensible colour in isolation (tests, a component used outside the
 * overview) rather than throwing or going colourless.
 */
export function useRoleColorVar(role: string): string {
  const palette = useContext(RolePaletteContext)
  const hue = palette?.get(role.toUpperCase()) ?? preferredHue(role)
  return `var(--role-${hue})`
}

export function useRoleSwatchStyle(role: string): React.CSSProperties {
  return { backgroundColor: useRoleColorVar(role) }
}
