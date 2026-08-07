"use client"

// The system auth view (§5.2.9): "which endpoints here are unprotected?" as
// one screen instead of a walk over every endpoint. The five states are kept
// visually distinct on purpose — "unprotected", "we could not tell" and
// "nobody can reach it" call for opposite responses, and a UI that blurs them
// makes the honest state meaningless.
import { useMemo, useState } from "react"
import Link from "next/link"
import { UserCheck } from "lucide-react"

import type { AuthEndpointRow } from "@/lib/generated/system_auth.schema"
import { cn } from "@/lib/utils"
import { useSystemAuth } from "@/lib/wadi/hooks"
import { endpointPath } from "@/lib/wadi/routes"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Skeleton } from "@/components/ui/skeleton"
import { MethodBadge } from "@/components/explorer/method-badge"
import {
  AuthChip,
  authStateOf,
  withheldReason,
  type AuthState,
} from "@/components/shared/auth-chip"

type Filter = "all" | AuthState

const FILTERS: { id: Filter; label: string; hint: string }[] = [
  { id: "all", label: "all", hint: "Every endpoint in the snapshot" },
  {
    id: "open",
    label: "unprotected",
    hint: "Every guard in scope was read, and none of them gates this endpoint",
  },
  {
    id: "withheld",
    label: "withheld",
    hint: "A guard was found but could not be read — a gap in wadi, not necessarily in the system",
  },
  {
    id: "unknown",
    label: "no evidence",
    hint: "Nothing that could gate these endpoints was found at all",
  },
  { id: "required", label: "protected", hint: "Authentication is required" },
  {
    id: "denied",
    label: "denied",
    hint: "A rule that was read admits nobody — the endpoint is unreachable, not protected",
  },
]

function stateOf(row: AuthEndpointRow): AuthState {
  return authStateOf(row.authenticated, row.unread_kinds ?? [], row.denied)
}

function Stat({
  value,
  label,
  tone,
}: {
  value: number
  label: string
  tone?: "warn" | "muted"
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <span
        className={cn(
          "font-mono text-2xl tabular-nums",
          tone === "warn" && "text-warn",
          tone === "muted" && "text-muted-foreground"
        )}
      >
        {value}
      </span>
      <span className="text-2xs text-muted-foreground">{label}</span>
    </div>
  )
}

export function AuthPane({
  snapshotId,
  active,
}: {
  snapshotId: string
  active: boolean
}) {
  const auth = useSystemAuth(active, snapshotId)
  const [filter, setFilter] = useState<Filter>("all")

  const rows = useMemo(() => {
    const all = auth.data?.rows ?? []
    return filter === "all" ? all : all.filter((row) => stateOf(row) === filter)
  }, [auth.data, filter])

  const byService = useMemo(() => {
    const grouped = new Map<string, AuthEndpointRow[]>()
    for (const row of rows) {
      const bucket = grouped.get(row.service_name) ?? []
      bucket.push(row)
      grouped.set(row.service_name, bucket)
    }
    return Array.from(grouped.entries())
  }, [rows])

  if (auth.isPending)
    return (
      <div className="w-full space-y-3 p-4">
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    )

  if (auth.isError)
    return (
      <p className="p-4 text-sm text-muted-foreground">
        Could not load the auth view — {(auth.error as Error).message}
      </p>
    )

  const totals = auth.data?.totals
  return (
    <div className="flex min-h-0 w-full flex-col">
      <div className="flex flex-wrap items-end gap-x-8 gap-y-3 border-b px-4 py-3">
        <Stat value={totals?.endpoints ?? 0} label="endpoints" />
        <Stat value={totals?.authenticated ?? 0} label="protected" />
        <Stat
          value={totals?.unauthenticated ?? 0}
          label="unprotected"
          tone="warn"
        />
        <Stat value={totals?.denied ?? 0} label="denied" tone="muted" />
        <Stat value={totals?.withheld ?? 0} label="withheld" tone="muted" />
        <Stat
          value={totals?.no_evidence ?? 0}
          label="no evidence"
          tone="muted"
        />
        <p className="max-w-md text-2xs text-muted-foreground">
          <span className="font-medium">withheld</span> means a guard was found
          but could not be read, so no claim is made — that is a gap in the
          analysis. <span className="font-medium">no evidence</span> means
          nothing gating was found at all, which may be a real hole.{" "}
          <span className="font-medium">denied</span> means a rule admits
          nobody, so the route is unreachable rather than protected.
        </p>
      </div>

      <div className="flex shrink-0 items-center gap-1 border-b px-3 py-1.5">
        {FILTERS.map((option) => (
          <button
            key={option.id}
            onClick={() => setFilter(option.id)}
            title={option.hint}
            aria-pressed={filter === option.id}
            className={cn(
              "cursor-pointer rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
              "focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
              filter === option.id
                ? "bg-muted text-foreground"
                : "text-muted-foreground hover:bg-muted/50 hover:text-foreground"
            )}
          >
            {option.label}
          </button>
        ))}
      </div>

      <ScrollArea className="min-h-0 flex-1">
        {byService.length === 0 ? (
          <p className="p-4 text-sm text-muted-foreground">
            No endpoints in this state.
          </p>
        ) : (
          byService.map(([service, serviceRows]) => (
            <section key={service}>
              <h3 className="sticky top-0 z-10 border-b bg-background/95 px-4 py-1.5 text-2xs font-medium text-muted-foreground backdrop-blur">
                {service}
                <span className="ml-2 font-mono">{serviceRows.length}</span>
              </h3>
              <ul className="divide-y">
                {serviceRows.map((row) => {
                  const state = stateOf(row)
                  return (
                    <li key={row.endpoint_id}>
                      <Link
                        href={endpointPath(snapshotId, row.endpoint_id)}
                        className="flex flex-wrap items-center gap-2 px-4 py-2 transition-colors hover:bg-muted/50"
                      >
                        <MethodBadge method={row.http_method} />
                        <span className="min-w-0 flex-1 truncate font-mono text-xs">
                          {row.full_uri}
                        </span>
                        {(row.roles ?? []).map((role) => (
                          <span
                            key={role}
                            className="rounded-full bg-muted px-2 py-0.5 font-mono text-2xs"
                          >
                            {role}
                          </span>
                        ))}
                        {(row.authorities ?? []).map((authority) => (
                          <span
                            key={authority}
                            title="Required authority (hasAuthority), not a role"
                            className="rounded-full border border-dashed px-2 py-0.5 font-mono text-2xs text-muted-foreground"
                          >
                            {authority}
                          </span>
                        ))}
                        {/* §5.2.12. Without these the whole table reads
                            `protected` with nothing beside it on any system
                            whose policy is relational — 562 of 804 rows on
                            ICPC — which is the exact misreading the tranche
                            exists to remove. */}
                        {(row.relationships ?? []).map((relationship) => (
                          <span
                            key={`${relationship.relation}:${relationship.resource_type ?? ""}`}
                            title={
                              relationship.resource_type
                                ? `Must be ${relationship.relation} of the ${relationship.resource_type} this request names — a relation, not a role the caller holds everywhere`
                                : `Must be ${relationship.relation} for the resource this request names`
                            }
                            className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 font-mono text-2xs"
                          >
                            <UserCheck
                              aria-hidden
                              className="size-2.5 opacity-70"
                            />
                            {relationship.relation}
                            {relationship.resource_type ? (
                              <span className="opacity-60">
                                ·{relationship.resource_type}
                              </span>
                            ) : null}
                          </span>
                        ))}
                        {row.composition_unresolved ? (
                          <span
                            title="Several guards apply and how they combine was not read — these may be alternatives rather than all required"
                            className="rounded-full border border-dashed px-2 py-0.5 font-mono text-2xs text-warn"
                          >
                            combination unread
                          </span>
                        ) : null}
                        {(row.mechanism_kinds ?? []).map((kind) => (
                          <span
                            key={kind}
                            className="rounded-sm bg-muted px-1.5 py-0.5 text-2xs text-muted-foreground"
                          >
                            {kind}
                          </span>
                        ))}
                        <AuthChip
                          state={state}
                          title={
                            state === "withheld"
                              ? withheldReason(row.unread_kinds ?? [])
                              : undefined
                          }
                        />
                      </Link>
                    </li>
                  )
                })}
              </ul>
            </section>
          ))
        )}
      </ScrollArea>
    </div>
  )
}
