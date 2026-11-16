"use client"

// The workspace Data list (§5.2.17 UI): which entities this endpoint may
// create, read, update or delete, beside the call tree it is an alternative
// reading of. Presentational over `deriveDataListState`, which decides every
// state and is pinned by tests. This file only says each one.
//
// Four of the states are some flavour of "nothing to list", and they stay
// visibly different because they ask for different responses: the snapshot
// never looked (re-analyze), it looked and found nothing (read the limits),
// the work happens in another service (follow the call), or the request
// failed (retry, since nothing is known). Rendering any two alike states a
// finding that was never made (P10). The two that looked also say when the
// flow they looked at stops at calls wadi could not open (review #5).
import { Database, Forward } from "lucide-react"

import type { EntityOperation } from "@/lib/generated/entity_usage.schema"
import { cn } from "@/lib/utils"
import {
  ENTITY_ACCESS_LIMITS,
  OPERATION_HINT,
  OPERATION_LABEL,
  type DataListRow,
  type DataListState,
  type EntitySiteRef,
  type ForwardTarget,
} from "@/lib/wadi/entity-access"
import { Button } from "@/components/ui/button"
import { Chip } from "@/components/ui/chip"
import { Skeleton } from "@/components/ui/skeleton"

const BASIS_LABEL: Record<EntitySiteRef["basis"], string> = {
  "method-name": "method name",
  "query-text": "query text",
  "argument-origin": "saved object's origin",
  "existence-guard": "existence check",
}

export function OperationChip({ operation }: { operation: EntityOperation }) {
  return (
    <Chip
      // A verb that was not read is an unresolved fact and must look like one;
      // create-or-update is a save the analysis declined to split, so it is
      // dashed too, but in the neutral tone, because it is a measured "either".
      variant={operation === "unknown" ? "unknown" : "outline"}
      className={cn(operation === "create-or-update" && "border-dashed")}
      title={OPERATION_HINT[operation]}
    >
      {OPERATION_LABEL[operation]}
    </Chip>
  )
}

function Limits() {
  return (
    <p className="text-2xs text-subtle-foreground">{ENTITY_ACCESS_LIMITS}</p>
  )
}

/** Beside an empty state whose flow stops at calls that may hide a
 * repository call (§5.2.17): `[]` covers only the flow wadi could open. */
function StopsAt({ calls }: { calls: number | undefined }) {
  if (!calls) return null
  return (
    <p className="text-2xs text-muted-foreground">
      {calls === 1
        ? "The flow stops at 1 call wadi could not open, so a repository call may sit behind it."
        : `The flow stops at ${calls} calls wadi could not open, so a repository call may sit behind one of them.`}
    </p>
  )
}

function Forwards({ forwards }: { forwards: ForwardTarget[] }) {
  return (
    <ul className="space-y-1">
      {forwards.map((target) => (
        <li
          key={target.key}
          className="flex items-start gap-1.5 font-mono text-2xs break-all text-muted-foreground"
        >
          <Forward aria-hidden className="mt-0.5 size-3 shrink-0" />
          <span>{target.label}</span>
        </li>
      ))}
    </ul>
  )
}

function Row({
  row,
  selected,
  sites,
  flowAvailable,
  onSelectEntity,
  onSelectSite,
}: {
  row: DataListRow
  selected: boolean
  sites: EntitySiteRef[]
  flowAvailable: boolean
  onSelectEntity: (key: string | null) => void
  onSelectSite: (site: EntitySiteRef) => void
}) {
  return (
    <li
      className={cn(
        "mx-1.5 my-1 rounded-lg border",
        // Symmetric selection, as the services list: fill plus a full ring.
        selected ? "bg-muted/70 ring-1 ring-primary/30 ring-inset" : "",
        row.undetermined && "border-dashed"
      )}
    >
      <button
        type="button"
        aria-pressed={selected}
        onClick={() => onSelectEntity(selected ? null : row.key)}
        title={
          row.qualifiedName ??
          "Repository calls whose entity type could not be bound to a class"
        }
        className={cn(
          "flex w-full cursor-pointer flex-col gap-1 rounded-lg px-2.5 py-2 text-left transition-colors",
          "hover:bg-muted/50 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        )}
      >
        <span className="flex min-w-0 items-baseline gap-2">
          <span
            className={cn(
              "truncate text-sm font-medium",
              row.undetermined && "font-normal text-muted-foreground italic"
            )}
          >
            {row.name}
          </span>
          <span className="ml-auto shrink-0 font-mono text-2xs text-muted-foreground tabular-nums">
            {row.callSites === 1 ? "1 call" : `${row.callSites} calls`}
          </span>
        </span>
        <span className="flex flex-wrap gap-1">
          {row.operations.map((operation) => (
            <OperationChip key={operation} operation={operation} />
          ))}
        </span>
      </button>
      {selected ? (
        <div className="border-t px-2.5 py-1.5">
          {sites.length > 0 ? (
            <ul className="space-y-0.5">
              {sites.map((site, index) => (
                <li key={`${site.nodeId}:${index}`}>
                  <button
                    type="button"
                    onClick={() => onSelectSite(site)}
                    title={`${site.file}:${site.line}`}
                    className={cn(
                      "flex w-full cursor-pointer flex-wrap items-baseline gap-x-2 rounded-sm px-1 py-0.5 text-left transition-colors",
                      "hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                    )}
                  >
                    <span className="font-mono text-2xs">{site.call}</span>
                    <span className="text-2xs text-muted-foreground">
                      {site.operations
                        .map((op) => OPERATION_LABEL[op])
                        .join(", ")}
                    </span>
                    <span className="text-2xs text-subtle-foreground">
                      {BASIS_LABEL[site.basis]}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-2xs text-muted-foreground">
              {flowAvailable
                ? "None of these calls is drawn in this flow graph."
                : "The flow graph is not loaded, so these calls cannot be pointed at."}
            </p>
          )}
        </div>
      ) : null}
    </li>
  )
}

export function DataList({
  state,
  selectedEntity,
  sitesOf,
  flowAvailable,
  onSelectEntity,
  onSelectSite,
  onRetry,
}: {
  state: DataListState
  selectedEntity: string | null
  /** The calls touching one entity, read from the ICFG the canvas draws. */
  sitesOf: (key: string) => EntitySiteRef[]
  flowAvailable: boolean
  onSelectEntity: (key: string | null) => void
  onSelectSite: (site: EntitySiteRef) => void
  onRetry: () => void
}) {
  switch (state.kind) {
    case "pending":
      return (
        <div className="space-y-2 p-3">
          {Array.from({ length: 3 }).map((_, index) => (
            <Skeleton key={index} className="h-12 w-full" />
          ))}
        </div>
      )
    case "fetch-failed":
      return (
        <div className="space-y-1.5 p-3">
          <p className="text-sm text-warn">
            Could not load entity access for this endpoint — {state.message}
          </p>
          <p className="text-2xs text-muted-foreground">
            No claim is shown: nothing here says what the endpoint touches.
          </p>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-6 px-2 text-2xs"
            onClick={onRetry}
          >
            Retry
          </Button>
        </div>
      )
    case "predates":
      return (
        <p className="p-3 text-sm text-muted-foreground">
          This snapshot predates entity facts. Analyze the system again to see
          which entities this endpoint may touch.
        </p>
      )
    case "no-repository-call":
      return (
        <div className="space-y-1.5 p-3">
          <p className="flex items-center gap-1.5 text-sm">
            <Database aria-hidden className="size-3.5 text-muted-foreground" />
            No repository call found.
          </p>
          <StopsAt calls={state.unopenedCalls} />
          <Limits />
        </div>
      )
    case "forwards-only":
      return (
        <div className="space-y-1.5 p-3">
          <p className="text-sm">
            No local entities. This endpoint forwards to:
          </p>
          <Forwards forwards={state.forwards} />
          <p className="text-2xs text-subtle-foreground">
            What those services touch is listed on their own endpoints.
          </p>
          <StopsAt calls={state.unopenedCalls} />
        </div>
      )
    case "populated":
      return (
        <div className="py-1">
          <ul>
            {state.rows.map((row) => (
              <Row
                key={row.id}
                row={row}
                selected={row.key === selectedEntity}
                sites={row.key === selectedEntity ? sitesOf(row.key) : []}
                flowAvailable={flowAvailable}
                onSelectEntity={onSelectEntity}
                onSelectSite={onSelectSite}
              />
            ))}
          </ul>
          {state.forwards.length > 0 ? (
            <div className="mx-1.5 my-1 space-y-1 rounded-lg border border-dashed px-2.5 py-2">
              <p className="text-2xs text-muted-foreground">
                Also forwards to (what those services touch is not listed here):
              </p>
              <Forwards forwards={state.forwards} />
            </div>
          ) : null}
          <div className="mx-3 mt-2 border-t pt-2">
            <Limits />
          </div>
        </div>
      )
  }
}
