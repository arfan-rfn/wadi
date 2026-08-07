"use client"

// Endpoint rows: identity on line 1, who can reach it on line 2 (§5.2.9 UI).
//
// The single-line row could only afford an auth *icon*, which told you an
// endpoint was guarded but never by what — so answering "which of these is
// ADMIN-only" meant opening all of them. Line 2 carries the roles themselves,
// coloured from the role NAME so a swatch means the same thing in every
// service. Everything here is already on the Endpoint artifact; the row costs
// no extra fetch.
import type { EndpointDependency } from "@/lib/generated/endpoint_dependencies.schema"
import { cn } from "@/lib/utils"
import type { Endpoint } from "@/lib/wadi/api"
import { useRoleSwatchStyle } from "@/lib/wadi/role-colors"
import { MethodBadge } from "@/components/explorer/method-badge"
import { authStateOf, type AuthState } from "@/components/shared/auth-chip"

import { AccessChip, DependencyChip } from "./endpoint-meta"

export function unreadKindsOf(endpoint: Endpoint): string[] {
  return (endpoint.auth?.evidence ?? [])
    .filter((item) => item.active !== false && item.resolution === "opaque")
    .map((item) => item.kind)
}

export function RoleDot({ role }: { role: string }) {
  const swatch = useRoleSwatchStyle(role)
  return (
    <span className="inline-flex items-center gap-1.5 font-mono text-2xs">
      <span
        aria-hidden
        className="size-[7px] shrink-0 rounded-full"
        style={swatch}
      />
      {role}
    </span>
  )
}

/** The security line. Kept exported so the peek header can reuse it verbatim. */
export function SecurityLine({
  endpoint,
  dependencies = [],
  className,
}: {
  endpoint: Endpoint
  dependencies?: readonly EndpointDependency[]
  className?: string
}) {
  const unread = unreadKindsOf(endpoint)
  const state: AuthState = authStateOf(
    endpoint.auth?.authenticated,
    unread,
    endpoint.auth?.denied
  )
  const roles = endpoint.auth?.roles ?? []
  const authorities = endpoint.auth?.authorities ?? []
  return (
    <span className={cn("flex flex-wrap items-center gap-1.5", className)}>
      <AccessChip
        state={state}
        roles={roles}
        authorities={authorities}
        relationships={endpoint.auth?.relationships ?? []}
        compositionUnresolved={endpoint.auth?.composition_unresolved ?? false}
      />
      <DependencyChip dependencies={dependencies} />
    </span>
  )
}

export function EndpointRow({
  endpoint,
  dependencies,
  selected = false,
  onOpen,
}: {
  endpoint: Endpoint
  dependencies?: readonly EndpointDependency[]
  selected?: boolean
  onOpen: (endpoint: Endpoint) => void
}) {
  return (
    <button
      type="button"
      onClick={() => onOpen(endpoint)}
      aria-current={selected ? "true" : undefined}
      className={cn(
        // Selection is the row itself: an inset rounded-sm block whose fill
        // deepens and whose ring closes all the way round. Never an edge bar.
        "mx-1.5 my-0.5 grid w-[calc(100%-0.75rem)] cursor-pointer grid-cols-[3.25rem_minmax(0,1fr)] items-center gap-x-2.5 gap-y-1 rounded-lg px-2 py-pad-y text-left transition-colors",
        "hover:bg-muted/45 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
        selected && "bg-muted/80 ring-1 ring-primary/30 ring-inset"
      )}
    >
      <MethodBadge method={endpoint.http_method} className="w-full" />
      <span
        className={cn(
          "col-start-2 col-end-4 min-w-0 truncate font-mono text-xs",
          selected && "font-medium"
        )}
        title={endpoint.full_uri}
      >
        {endpoint.full_uri}
      </span>
      <SecurityLine
        endpoint={endpoint}
        dependencies={dependencies}
        className="col-start-2 col-end-4"
      />
    </button>
  )
}
