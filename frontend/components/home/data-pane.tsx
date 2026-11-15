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

import { cn } from "@/lib/utils"
import {
  deriveEntityMatrixState,
  ENTITY_ACCESS_LIMITS,
  ENTITY_OPERATIONS,
  OPERATION_HINT,
  OPERATION_LABEL,
  type MatrixRow,
  type MatrixTotals,
  type UnresolvedCounts,
} from "@/lib/wadi/entity-access"
import { useEntityUsage } from "@/lib/wadi/hooks"
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

function Totals({
  totals,
  endpointsPredating,
}: {
  totals: MatrixTotals | null
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
          <span>
            bound to an entity and a verb{" "}
            <span className="font-mono tabular-nums">{totals.bound}</span>
          </span>
          <span>
            create or update{" "}
            <span className="font-mono tabular-nums">
              {totals.createOrUpdate}
            </span>
          </span>
          <span>
            verb unknown{" "}
            <span className="font-mono tabular-nums">{totals.unknownVerb}</span>
          </span>
          <span>
            entity undetermined{" "}
            <span className="font-mono tabular-nums">
              {totals.undeterminedEntity}
            </span>
          </span>
          <span>
            in no endpoint flow{" "}
            <span className="font-mono tabular-nums">
              {totals.inNoEndpointFlow}
            </span>
          </span>
          {totals.servicesPredating > 0 ? (
            <span className="text-warn">
              {plural(totals.servicesPredating, "service")} not counted: their
              accounting predates entity facts
            </span>
          ) : null}
        </>
      ) : (
        <span>No service reports repository-call accounting.</span>
      )}
      {endpointsPredating > 0 ? (
        <span className="text-warn">
          {plural(endpointsPredating, "endpoint")} predate entity facts and are
          in no cell
        </span>
      ) : null}
    </div>
  )
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
      title="Calls in this service the matrix cannot attribute. Any of them could be the operation the note says was not detected."
    >
      {counts.kind === "predates"
        ? `${serviceName}: call accounting predates entity facts`
        : `${serviceName}: ${counts.unknownVerb} verb unknown · ${counts.undeterminedEntity} entity undetermined · ${counts.inNoEndpointFlow} in no endpoint flow`}
    </p>
  )
}

function EntityRow({
  row,
  snapshotId,
  open,
  onOpen,
}: {
  row: MatrixRow
  snapshotId: string
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
                <span className="font-mono text-xs text-subtle-foreground tabular-nums">
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
                  <span className="shrink-0 font-mono text-2xs text-subtle-foreground">
                    {plural(endpoint.call_sites, "call")}
                  </span>
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
                    {ENTITY_OPERATIONS.map((operation) => (
                      <TableHead
                        key={operation}
                        className="text-center"
                        title={OPERATION_HINT[operation]}
                      >
                        {columnLabel(OPERATION_LABEL[operation])}
                      </TableHead>
                    ))}
                    <TableHead>Notes</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((row) => (
                    <EntityRow
                      key={row.key}
                      row={row}
                      snapshotId={snapshotId}
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
              operation. A zero is measured for Spring Data repositories only.{" "}
              {ENTITY_ACCESS_LIMITS}
            </p>
          </ScrollArea>
        </div>
      )
  }
}
