"use client"

// The snapshot's role vocabulary, with counts — and a filter (§5.2.9 UI).
//
// The legend exists so a colour can be *learned*: seeing "ADMIN 95" once
// makes every rose dot in the list readable without a tooltip. It doubles as
// the filter because "show me the ADMIN endpoints" is the question the colour
// makes you want to ask, and making the reader retype it in the search box
// would waste the affordance.
import { useMemo } from "react"

import type { SystemAuthView } from "@/lib/generated/system_auth.schema"
import { cn } from "@/lib/utils"
import { useRoleSwatchStyle } from "@/lib/wadi/role-colors"

export type RoleFilter =
  { kind: "role"; role: string } | { kind: "open" } | null

export function rolesInSnapshot(
  auth: SystemAuthView | undefined
): { role: string; count: number }[] {
  const counts = new Map<string, number>()
  for (const row of auth?.rows ?? [])
    for (const role of row.roles ?? [])
      counts.set(role, (counts.get(role) ?? 0) + 1)
  return (
    [...counts.entries()]
      .map(([role, count]) => ({ role, count }))
      // Most-used first: the roles worth learning are the ones you will meet.
      .sort((a, b) => b.count - a.count || a.role.localeCompare(b.role))
  )
}

export function RoleLegend({
  auth,
  value,
  onChange,
  className,
}: {
  auth: SystemAuthView | undefined
  value: RoleFilter
  onChange: (next: RoleFilter) => void
  className?: string
}) {
  const roles = useMemo(() => rolesInSnapshot(auth), [auth])
  const unauthenticated = auth?.totals?.unauthenticated ?? 0
  if (roles.length === 0 && unauthenticated === 0) return null

  const toggle = (next: RoleFilter) => {
    const same =
      next?.kind === "role" && value?.kind === "role"
        ? next.role === value.role
        : next?.kind === value?.kind
    onChange(same ? null : next)
  }

  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b bg-muted/25 px-3 py-2",
        className
      )}
    >
      <span className="text-2xs font-medium tracking-[0.08em] text-muted-foreground uppercase">
        Roles
      </span>
      {roles.map(({ role, count }) => (
        <LegendRole
          key={role}
          role={role}
          count={count}
          active={value?.kind === "role" && value.role === role}
          onToggle={() => toggle({ kind: "role", role })}
        />
      ))}
      {unauthenticated > 0 ? (
        <button
          type="button"
          aria-pressed={value?.kind === "open"}
          onClick={() => toggle({ kind: "open" })}
          title="Every guard in scope was read, and none of them gates these endpoints"
          className={cn(
            "inline-flex cursor-pointer items-center gap-1.5 rounded-full border border-transparent px-2 py-0.5 text-2xs transition-colors",
            "hover:border-border focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
            value?.kind === "open" && "border-border bg-background"
          )}
        >
          <span
            aria-hidden
            className="size-2 shrink-0 rounded-full border border-dashed border-muted-foreground"
          />
          no auth
          <span className="font-mono text-2xs tabular-nums text-muted-foreground">
            {unauthenticated}
          </span>
        </button>
      ) : null}
    </div>
  )
}

/** One role in the legend. Split out so the swatch can use the palette hook,
 *  which has to be called from a component rather than inside a map. */
function LegendRole({
  role,
  count,
  active,
  onToggle,
}: {
  role: string
  count: number
  active: boolean
  onToggle: () => void
}) {
  const swatch = useRoleSwatchStyle(role)
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onToggle}
      title={`${count} endpoint${count === 1 ? "" : "s"} require ${role}`}
      className={cn(
        "inline-flex cursor-pointer items-center gap-1.5 rounded-full border border-transparent px-2 py-0.5 text-2xs transition-colors",
        "hover:border-border focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
        active && "border-border bg-background"
      )}
    >
      <span
        aria-hidden
        className="size-2 shrink-0 rounded-full"
        style={swatch}
      />
      {role}
      <span className="font-mono text-2xs tabular-nums text-muted-foreground">
        {count}
      </span>
    </button>
  )
}
