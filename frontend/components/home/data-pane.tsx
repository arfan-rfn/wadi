"use client"

// The system Data view (§5.2.17): which endpoints may create, read, update or
// delete each entity, as one entity × operation matrix. Each cell is a count
// of endpoints and opens onto them; each endpoint opens its workspace in the
// Data pane with the entity already selected, so its call sites are lit.
//
// The Notes column is the part that could overclaim. "No detected delete
// call" is a statement about what was detected over an extraction that is not
// complete, so the service's unresolved counts sit beside it (C6): a verb that
// was not read could be the delete, and a call in no endpoint flow is a call
// no endpoint is credited with.
import { useMemo, useState } from "react"
import Link from "next/link"

import type { EntityOperation } from "@/lib/generated/entity_usage.schema"
import { cn } from "@/lib/utils"
import {
  deriveEntityMatrixState,
  ENTITY_ACCESS_LIMITS,
  ENTITY_OPERATIONS,
  OPERATION_HINT,
  OPERATION_LABEL,
  OUTCOME_BUCKETS,
  withheldColumns,
  type MatrixRow,
  type MatrixTotals,
  type UnresolvedCounts,
  type WithheldColumns,
} from "@/lib/wadi/entity-access"
import { useCoverage, useEntityUsage } from "@/lib/wadi/hooks"
import { endpointPath } from "@/lib/wadi/routes"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { MethodBadge } from "@/components/explorer/method-badge"
import { PanelHeader } from "@/components/shared/panel-header"

const COLUMN_COUNT = ENTITY_OPERATIONS.length + 3

function columnLabel(label: string): string {
  return label.charAt(0).toUpperCase() + label.slice(1)
}

function plural(count: number, one: string, many = `${one}s`): string {
  return `${count} ${count === 1 ? one : many}`
}

const WITHHELD_HINT =
  "Withheld: saves are published as create or update until the split is scored, so this column counts only what query text states. A zero here is not measured."

/** What the footer may say a zero means (review C6). A gated column's zero
 * may be a save counted under create-or-update instead, and with no coverage
 * report it is not known which columns are gated, so neither is vouched for. */
function zeroClaim(withheld: WithheldColumns): string {
  const measured = "A zero is measured for Spring Data repositories only"
  if (withheld.kind === "unread")
    return `${measured}. The coverage report has not said whether saves are withheld from create and update, so a zero under create or update is not measured.`
  if (withheld.operations.length === 0) return `${measured}.`
  const columns = withheld.operations.map((op) => OPERATION_LABEL[op])
  return `${measured}, and not in a withheld column (${columns.join(", ")}). Saves are published as create or update until the split is scored, so a save that would count there is counted under create or update.`
}

function Totals({
  totals,
  servicesPredating,
  servicesFailed,
  endpointsPredating,
}: {
  totals: MatrixTotals | null
  servicesPredating: number
  servicesFailed: number
  endpointsPredating: number
}) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-5 gap-y-1 border-b px-4 py-2.5 text-2xs text-muted-foreground">
      {totals ? (
        <>
          <span>
            <span className="font-medium text-foreground">
              Repository calls
            </span>{" "}
            <span className="font-mono tabular-nums">{totals.callSites}</span>
          </span>
          {/* Every call has exactly one outcome, so these add up to the
              number before them (review C2). */}
          <ul
            aria-label="What each repository call became"
            className="flex flex-wrap items-baseline gap-x-5 gap-y-1"
          >
            {OUTCOME_BUCKETS.map((bucket) => (
              <li key={bucket.key} title={bucket.hint}>
                {bucket.label}{" "}
                <span className="font-mono tabular-nums">
                  {totals[bucket.key]}
                </span>
              </li>
            ))}
          </ul>
          <span
            className="border-l pl-5"
            title="A second split of the same calls, by whether some endpoint's flow reaches them (a call inside a lambda body reaches none). It overlaps the outcomes and is not added to them."
          >
            of these, in no endpoint flow{" "}
            <span className="font-mono tabular-nums">
              {totals.inNoEndpointFlow}
            </span>
          </span>
        </>
      ) : (
        <span>No service reports repository-call accounting.</span>
      )}
      {/* Why a service is in no sum, by its status (review C3). A library
          is not listed: its calls count in its dependents' accounting. */}
      {servicesPredating > 0 ? (
        <span className="text-warn">
          {plural(servicesPredating, "service")}{" "}
          {servicesPredating === 1 ? "predates" : "predate"} entity facts
        </span>
      ) : null}
      {servicesFailed > 0 ? (
        <span className="text-warn">
          {plural(servicesFailed, "service")} failed extraction;{" "}
          {servicesFailed === 1 ? "its" : "their"} data access was never
          examined
        </span>
      ) : null}
      {endpointsPredating > 0 ? (
        <span className="text-warn">
          {plural(endpointsPredating, "endpoint")} predate entity facts and are
          in no cell
        </span>
      ) : null}
    </div>
  )
}

function unresolvedText(serviceName: string, counts: UnresolvedCounts) {
  switch (counts.kind) {
    case "predates":
      return `${serviceName}: call accounting predates entity facts`
    case "extraction-failed":
      return `${serviceName}: extraction failed, so its data access was never examined`
    case "library":
      return `${serviceName}: a library, so its calls are counted in the services that depend on it`
    case "counted":
      return `${serviceName}: ${counts.unknownVerb} verb unknown · ${counts.implementedInProject} body in the project, verb not read · ${counts.undeterminedEntity} entity undetermined · ${counts.inNoEndpointFlow} in no endpoint flow`
  }
}

function Unresolved({
  serviceName,
  counts,
}: {
  serviceName: string
  counts: UnresolvedCounts
}) {
  return (
    <p
      className="text-2xs whitespace-normal text-subtle-foreground"
      title="Calls in this service the matrix cannot attribute. Any of them could be the operation the note says was not detected. Both verb unknown and body in the project (a custom method such as archiveOld) publish a verb that was not read, so either may hold the missing delete."
    >
      {unresolvedText(serviceName, counts)}
    </p>
  )
}

function EntityRow({
  row,
  snapshotId,
  withheld,
  open,
  onOpen,
}: {
  row: MatrixRow
  snapshotId: string
  withheld: readonly EntityOperation[]
  open: string | null
  onOpen: (operation: string | null) => void
}) {
  const openCell = row.cells.find((cell) => cell.operation === open) ?? null
  return (
    <>
      <TableRow>
        <TableCell
          title={
            row.qualifiedName ??
            "Repository calls whose entity type could not be bound to a class"
          }
        >
          <span
            className={cn(
              "font-medium",
              row.undetermined && "font-normal text-muted-foreground italic"
            )}
          >
            {row.name}
          </span>
          {row.storageName ? (
            <span className="ml-2 font-mono text-2xs text-subtle-foreground">
              {row.storageName}
            </span>
          ) : null}
        </TableCell>
        <TableCell className="font-mono text-2xs text-muted-foreground">
          {row.serviceName}
        </TableCell>
        {row.cells.map((cell) => {
          const count = cell.endpoints.length
          const label = OPERATION_LABEL[cell.operation]
          return (
            <TableCell key={cell.operation} className="text-center">
              {count === 0 ? (
                <span
                  className="font-mono text-xs text-subtle-foreground tabular-nums"
                  title={
                    withheld.includes(cell.operation)
                      ? "Not a measured zero. Saves are withheld from this column"
                      : undefined
                  }
                >
                  0
                </span>
              ) : (
                <button
                  type="button"
                  aria-label={`${row.name}, ${label}: ${plural(count, "endpoint")}`}
                  aria-expanded={open === cell.operation}
                  onClick={() =>
                    onOpen(open === cell.operation ? null : cell.operation)
                  }
                  className={cn(
                    "min-w-8 cursor-pointer rounded-md px-2 py-0.5 font-mono text-xs tabular-nums transition-colors",
                    "hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
                    open === cell.operation && "bg-muted ring-1 ring-primary/30"
                  )}
                >
                  {count}
                </button>
              )}
            </TableCell>
          )
        })}
        <TableCell className="space-y-0.5 text-2xs">
          {row.notes.map((note) => (
            <p key={note} className="whitespace-normal text-muted-foreground">
              {note}
            </p>
          ))}
          {row.unresolved ? (
            <Unresolved serviceName={row.serviceName} counts={row.unresolved} />
          ) : null}
        </TableCell>
      </TableRow>
      {openCell ? (
        <TableRow className="bg-muted/30 hover:bg-muted/30">
          <TableCell colSpan={COLUMN_COUNT} className="whitespace-normal">
            <p className="mb-1 text-2xs text-muted-foreground">
              Endpoints that may {OPERATION_LABEL[openCell.operation]}{" "}
              {row.name}:
            </p>
            <ul className="space-y-0.5">
              {openCell.endpoints.map((endpoint) => (
                <li
                  key={endpoint.endpoint_id}
                  className="flex items-center gap-2"
                >
                  <Link
                    href={endpointPath(snapshotId, endpoint.endpoint_id, {
                      pane: "data",
                      entity: row.entityKey,
                    })}
                    className="flex min-w-0 items-center gap-2 rounded-sm px-1 py-0.5 transition-colors hover:bg-muted"
                  >
                    <MethodBadge method={endpoint.http_method} />
                    <span className="truncate font-mono text-xs">
                      {endpoint.full_uri}
                    </span>
                  </Link>
                  {/* The calls that perform THIS operation (review C1). A
                      summary written before 1.27.0 counted per entity only,
                      and that count under one operation would overstate it. */}
                  {endpoint.call_sites === null ? (
                    <span
                      className="shrink-0 text-2xs text-subtle-foreground italic"
                      title="count not recorded; re-analyze. This endpoint's summary was written before per-operation counts."
                    >
                      count not recorded
                    </span>
                  ) : (
                    <span
                      className="shrink-0 font-mono text-2xs text-subtle-foreground"
                      title={`Calls in this endpoint that may ${OPERATION_LABEL[openCell.operation]} ${row.name}`}
                    >
                      {plural(endpoint.call_sites, "call")}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </TableCell>
        </TableRow>
      ) : null}
    </>
  )
}

export function DataPane({
  snapshotId,
  active,
}: {
  snapshotId: string
  active: boolean
}) {
  const usage = useEntityUsage(active, snapshotId)
  // The coverage tab's query, so the report is read once per snapshot.
  const coverage = useCoverage(snapshotId)
  const withheld = useMemo(
    () => withheldColumns(coverage.data),
    [coverage.data]
  )
  const withheldOperations = withheld.kind === "read" ? withheld.operations : []
  const [filter, setFilter] = useState("")
  const [open, setOpen] = useState<{ row: string; operation: string } | null>(
    null
  )

  const state = useMemo(
    () =>
      deriveEntityMatrixState({
        data: usage.data,
        error: usage.isError ? (usage.error as Error) : null,
      }),
    [usage.data, usage.isError, usage.error]
  )

  const rows = useMemo(() => {
    if (state.kind !== "populated") return []
    const query = filter.trim().toLowerCase()
    if (!query) return state.rows
    return state.rows.filter((row) =>
      [row.name, row.qualifiedName ?? "", row.serviceName].some((text) =>
        text.toLowerCase().includes(query)
      )
    )
  }, [state, filter])

  switch (state.kind) {
    case "pending":
      return (
        <div className="w-full space-y-3 p-4">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-64 w-full" />
        </div>
      )
    case "fetch-failed":
      return (
        <div className="space-y-1.5 p-4">
          <p className="text-sm text-warn">
            Could not load the entity view — {state.message}
          </p>
          <p className="text-2xs text-muted-foreground">
            No claim is shown: nothing here says what any endpoint touches.
          </p>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-6 px-2 text-2xs"
            onClick={() => void usage.refetch()}
          >
            Retry
          </Button>
        </div>
      )
    case "predates":
      return (
        <p className="p-4 text-sm text-muted-foreground">
          This snapshot predates entity facts. Analyze the system again to see
          which endpoints touch which entities.
        </p>
      )
    case "populated":
      return (
        <div className="flex min-h-0 w-full flex-col">
          <Totals
            totals={state.totals}
            servicesPredating={state.servicesPredating}
            servicesFailed={state.servicesFailed}
            endpointsPredating={state.endpointsPredating}
          />
          <PanelHeader
            label="Entities"
            count={state.rows.length}
            filter={filter}
            onFilter={setFilter}
            placeholder="Filter entities"
          />
          <ScrollArea className="min-h-0 flex-1">
            {state.rows.length === 0 ? (
              <p className="p-4 text-sm text-muted-foreground">
                No entity was found and no repository call was read in this
                snapshot.
              </p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Entity</TableHead>
                    <TableHead>Service</TableHead>
                    {ENTITY_OPERATIONS.map((operation) => {
                      const gated = withheldOperations.includes(operation)
                      return (
                        <TableHead
                          key={operation}
                          className="text-center"
                          title={
                            gated
                              ? `${WITHHELD_HINT} ${OPERATION_HINT[operation]}`
                              : OPERATION_HINT[operation]
                          }
                        >
                          {columnLabel(OPERATION_LABEL[operation])}
                          {gated ? " · withheld" : null}
                        </TableHead>
                      )
                    })}
                    <TableHead>Notes</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((row) => (
                    <EntityRow
                      key={row.key}
                      row={row}
                      snapshotId={snapshotId}
                      withheld={withheldOperations}
                      open={open?.row === row.key ? open.operation : null}
                      onOpen={(operation) =>
                        setOpen(operation ? { row: row.key, operation } : null)
                      }
                    />
                  ))}
                </TableBody>
              </Table>
            )}
            {state.rows.length > 0 && rows.length === 0 ? (
              <p className="p-4 text-sm text-muted-foreground">
                No entity matches &ldquo;{filter}&rdquo;
              </p>
            ) : null}
            <p className="px-4 py-3 text-2xs text-subtle-foreground">
              A cell counts the endpoints where some path may perform the
              operation. {zeroClaim(withheld)} {ENTITY_ACCESS_LIMITS}
            </p>
          </ScrollArea>
        </div>
      )
  }
}
