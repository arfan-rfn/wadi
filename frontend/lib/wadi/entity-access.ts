// Entity access in the UI (§5.2.17): the workspace Data list's states and the
// one ordered operation vocabulary every entity surface renders from. Pure, so
// the states are pinned by unit tests rather than by reading markup.

import type {
  EndpointDetailView,
  EndpointEntityAccess,
  RemoteEdgeItem,
} from "@/lib/generated/endpoint_detail.schema"
import type {
  EntityAccessAccounting,
  EntityOperation,
  EntityUsageEndpoint,
  EntityUsageView,
} from "@/lib/generated/entity_usage.schema"
import type { EntityAccessBasis, Icfg } from "@/lib/generated/icfg.schema"
import { UNDETERMINED_ENTITY_KEY, type WorkspacePane } from "@/lib/wadi/routes"

/**
 * Every `EntityOperation`, in the contract's declaration order. It is the
 * order of the home matrix's columns and of the chips on a Data-list row.
 *
 * Typed against the generated union and checked both ways: an entry the
 * union lacks fails `satisfies`, and a union member missing here fails
 * {@link EntityOperationsAreExhaustive}. A new value in the contract therefore
 * breaks `tsc` instead of silently dropping a column (the hand-synced-list
 * failure the plan names).
 */
export const ENTITY_OPERATIONS = [
  "create",
  "read",
  "update",
  "delete",
  "create-or-update",
  "unknown",
] as const satisfies readonly EntityOperation[]

type AssertNever<T extends never> = T
/** Compile-time only: `never` unless the contract grew an operation. */
export type EntityOperationsAreExhaustive = AssertNever<
  Exclude<EntityOperation, (typeof ENTITY_OPERATIONS)[number]>
>

/** What a reader sees for each operation. `create-or-update` is one save the
 * analysis could not split, so it is one label, never "create" + "update";
 * `unknown` is a verb that was not read, which is what it says. */
export const OPERATION_LABEL = {
  create: "create",
  read: "read",
  update: "update",
  delete: "delete",
  "create-or-update": "create or update",
  unknown: "verb not read",
} as const satisfies Record<EntityOperation, string>

export const OPERATION_HINT = {
  create: "Some path through this code may insert a new record",
  read: "Some path through this code may read records",
  update: "Some path through this code may change an existing record",
  delete: "Some path through this code may delete records",
  "create-or-update":
    "A save the analysis could not split: it inserts or updates depending on whether the record already exists",
  unknown:
    "A repository call whose verb was not read (an annotated query wadi does not parse yet, for example)",
} as const satisfies Record<EntityOperation, string>

/** What v1 does not read, so an absence is never mistaken for a negative
 * (R1-7, C6). Shared by the Data list and the home matrix. */
export const ENTITY_ACCESS_LIMITS =
  "Not read: persistence outside Spring Data repositories, updates through setters on a loaded entity, repository calls inside lambdas, cascades."

/** `com.acme.pets.Pet` → `Pet`. */
export function simpleTypeName(qualified: string): string {
  return qualified.slice(qualified.lastIndexOf(".") + 1)
}

/** The URL key for an entity (R1-26): its qualified name, or the
 * undetermined row's sentinel. */
export function entityKeyOf(entity: string | null): string {
  return entity ?? UNDETERMINED_ENTITY_KEY
}

export interface DataListRow {
  /** `entity=` value: qualified type name or `~undetermined`. */
  key: string
  entity: string | null
  /** Simple type name, or "entity not determined". */
  name: string
  qualifiedName: string | null
  operations: EntityOperation[]
  callSites: number
  /** R1-25: the verb was read, the entity was not. */
  undetermined: boolean
  /** Some call touching this entity has a verb that was not read. */
  verbNotRead: boolean
}

export interface ForwardTarget {
  key: string
  /** `<VERB> <service> <path>`, each part only when known. */
  label: string
}

export type DataListState =
  | { kind: "pending" }
  | { kind: "fetch-failed"; message: string }
  /** `entity_access` is null/absent: the snapshot never looked (R1-6). */
  | { kind: "predates" }
  /** `[]` and no outbound call: looked, found no repository call (R1-7). */
  | { kind: "no-repository-call" }
  /** `[]` with outbound calls: the data work happens elsewhere (Q26). */
  | { kind: "forwards-only"; forwards: ForwardTarget[] }
  | { kind: "populated"; rows: DataListRow[]; forwards: ForwardTarget[] }

function rowOf(access: EndpointEntityAccess): DataListRow {
  return {
    key: entityKeyOf(access.entity),
    entity: access.entity,
    name:
      access.entity === null
        ? "entity not determined"
        : simpleTypeName(access.entity),
    qualifiedName: access.entity,
    operations: [...access.operations],
    callSites: access.call_sites,
    undetermined: access.entity === null,
    verbNotRead: access.operations.includes("unknown"),
  }
}

/** The places an endpoint forwards to, one per distinct target. Two call
 * sites hitting one route are one place, and naming it twice reads as two. */
export function forwardTargets(
  outbound: readonly RemoteEdgeItem[]
): ForwardTarget[] {
  const seen = new Set<string>()
  const targets: ForwardTarget[] = []
  for (const edge of outbound) {
    const label = [
      edge.http_verb ?? edge.target_http_method ?? null,
      edge.target_service_name ?? edge.external_host ?? "target undetermined",
      edge.target_simplified_uri ?? edge.url ?? null,
    ]
      .filter((part): part is string => Boolean(part))
      .join(" ")
    if (seen.has(label)) continue
    seen.add(label)
    targets.push({ key: edge.edge_id, label })
  }
  return targets
}

/**
 * Which of the Data list's states an endpoint is in.
 *
 * Detail wins over error: a cached aggregate whose background refetch failed
 * is still the fact on screen. Only with no detail at all is the failure the
 * whole story, and the list says it as a failure, never as an empty list.
 */
export function deriveDataListState({
  detail,
  error,
}: {
  detail: EndpointDetailView | undefined
  error: Error | null
}): DataListState {
  if (!detail)
    return error
      ? { kind: "fetch-failed", message: error.message }
      : { kind: "pending" }
  const access = detail.endpoint.entity_access
  if (access == null) return { kind: "predates" }
  const forwards = forwardTargets(detail.outbound ?? [])
  if (access.length === 0)
    return forwards.length > 0
      ? { kind: "forwards-only", forwards }
      : { kind: "no-repository-call" }
  return { kind: "populated", rows: access.map(rowOf), forwards }
}

/** One repository call touching the selected entity, where the canvas draws it. */
export interface EntitySiteRef {
  /** The ICFG node making the call, which the trace highlight lights. */
  nodeId: string
  /** `PetRepository.findById` */
  call: string
  /** This call's operations on the SELECTED entity only, in enum order. */
  operations: EntityOperation[]
  basis: EntityAccessBasis
  file: string
  line: number
}

/**
 * The repository calls in this flow that touch one entity, in ICFG order.
 *
 * One entry per call, not per node: a statement making two repository calls
 * is two calls (R1-2), though it is one place on the canvas. `key` is the
 * Data list's: a qualified type name, or `~undetermined` for the accesses
 * whose entity could not be bound. A graph written before 1.26.0 has no
 * sites, and yields none.
 */
export function entitySites(icfg: Icfg, key: string): EntitySiteRef[] {
  const wanted = key === UNDETERMINED_ENTITY_KEY ? null : key
  const refs: EntitySiteRef[] = []
  for (const node of icfg.nodes) {
    for (const site of node.entity_access_sites ?? []) {
      const ops = new Set(
        site.accesses
          .filter((access) => access.entity === wanted)
          .map((access) => access.operation)
      )
      if (ops.size === 0) continue
      refs.push({
        nodeId: node.id,
        call: `${simpleTypeName(site.repository)}.${site.method_name}`,
        operations: ENTITY_OPERATIONS.filter((op) => ops.has(op)),
        basis: site.basis,
        file: node.anchor.file,
        line: node.anchor.start_line,
      })
    }
  }
  return refs
}

/**
 * The ICFG nodes the canvas's trace highlight lights for a selected entity,
 * or null when the entity selection has nothing to say and the ordinary
 * trace (if on) applies.
 *
 * Only while the Data pane shows: the row is what explains the lit nodes.
 * And never an empty set. Dimming every node for an entity with no call in
 * this graph (a stale link, a pre-1.26.0 ICFG) would read as "this flow
 * touches nothing", which the Data list does not claim.
 */
export function entityHighlightNodeIds(
  icfg: Icfg | undefined,
  pane: WorkspacePane,
  selectedEntity: string | null
): ReadonlySet<string> | null {
  if (!icfg || pane !== "data" || selectedEntity === null) return null
  const ids = new Set(entitySites(icfg, selectedEntity).map((s) => s.nodeId))
  return ids.size > 0 ? ids : null
}

// --- the home `?view=data` matrix ---------------------------------------------

export interface MatrixCell {
  operation: EntityOperation
  /** The endpoints that may perform it; the cell shows how many. */
  endpoints: EntityUsageEndpoint[]
}

/** A service's calls the matrix cannot attribute, from its accounting. They
 * sit beside an absence note because each could be the missing operation
 * (C6). `predates` = the service's boundary was written before accounting. */
export type UnresolvedCounts =
  | {
      kind: "counted"
      unknownVerb: number
      undeterminedEntity: number
      inNoEndpointFlow: number
    }
  | { kind: "predates" }

export interface MatrixRow {
  /** Unique across the matrix: the same entity name can live in two services. */
  key: string
  /** The workspace's `entity=` value for this row. */
  entityKey: string
  serviceId: string
  serviceName: string
  name: string
  qualifiedName: string | null
  storageName: string | null
  undetermined: boolean
  /** One per operation, in {@link ENTITY_OPERATIONS} order. */
  cells: MatrixCell[]
  notes: string[]
  /** Set exactly when a note claims an absence. */
  unresolved: UnresolvedCounts | null
}

export interface MatrixTotals {
  callSites: number
  bound: number
  createOrUpdate: number
  unknownVerb: number
  undeterminedEntity: number
  inNoEndpointFlow: number
  /** Services whose accounting predates the phase, so are in no sum above. */
  servicesPredating: number
}

export type EntityMatrixState =
  | { kind: "pending" }
  | { kind: "fetch-failed"; message: string }
  /** `analyzed === false`: no endpoint carries entity facts (R1-6). */
  | { kind: "predates" }
  | {
      kind: "populated"
      rows: MatrixRow[]
      /** Null when no service reports accounting. */
      totals: MatrixTotals | null
      endpointsPredating: number
    }

const NO_DELETE = "no detected delete call"
const NO_ACCESS = "declared, no detected access"
const REPOSITORY_ONLY = "repository only, no annotation"

function unresolvedOf(
  accounting: EntityAccessAccounting | null | undefined
): UnresolvedCounts {
  return accounting
    ? {
        kind: "counted",
        unknownVerb: accounting.unknown_operation,
        undeterminedEntity: accounting.entity_undetermined,
        inNoEndpointFlow: accounting.in_no_endpoint_flow,
      }
    : { kind: "predates" }
}

/**
 * The entity × operation matrix over the reverse view.
 *
 * Cells are rebuilt in the one column order rather than read in the order the
 * API lists them, so the header and every row cannot disagree. Notes say only
 * what was detected: an entity with no detected delete is not one nothing
 * deletes, so the service's unresolved counts travel with that note.
 */
export function deriveEntityMatrixState({
  data,
  error,
}: {
  data: EntityUsageView | undefined
  error: Error | null
}): EntityMatrixState {
  if (!data)
    return error
      ? { kind: "fetch-failed", message: error.message }
      : { kind: "pending" }
  if (!data.analyzed) return { kind: "predates" }

  const services = new Map(data.services.map((s) => [s.service_id, s]))
  const rows = data.entities.map((entity): MatrixRow => {
    const byOperation = new Map(
      entity.operations.map((usage) => [usage.operation, usage.endpoints])
    )
    const cells = ENTITY_OPERATIONS.map((operation) => ({
      operation,
      endpoints: byOperation.get(operation) ?? [],
    }))
    const undetermined = entity.entity === null
    const notes: string[] = []
    if (!undetermined) {
      if (cells.every((cell) => cell.endpoints.length === 0))
        notes.push(NO_ACCESS)
      else if ((byOperation.get("delete") ?? []).length === 0)
        notes.push(NO_DELETE)
      if (entity.declared_by === "repository-argument")
        notes.push(REPOSITORY_ONLY)
    }
    const claimsAbsence = notes.includes(NO_ACCESS) || notes.includes(NO_DELETE)
    const service = services.get(entity.service_id)
    return {
      key: `${entity.service_id}::${entityKeyOf(entity.entity)}`,
      entityKey: entityKeyOf(entity.entity),
      serviceId: entity.service_id,
      serviceName: service?.service_name ?? entity.service_id,
      name: entity.name,
      qualifiedName: entity.entity,
      storageName: entity.storage_name,
      undetermined,
      cells,
      notes,
      unresolved: claimsAbsence ? unresolvedOf(service?.accounting) : null,
    }
  })

  const reporting = data.services.flatMap((s) =>
    s.accounting ? [s.accounting] : []
  )
  const sum = (pick: (a: EntityAccessAccounting) => number) =>
    reporting.reduce((total, a) => total + pick(a), 0)
  const totals: MatrixTotals | null =
    reporting.length === 0
      ? null
      : {
          callSites: sum((a) => a.call_sites),
          bound: sum((a) => a.bound),
          createOrUpdate: sum((a) => a.create_or_update),
          unknownVerb: sum((a) => a.unknown_operation),
          undeterminedEntity: sum((a) => a.entity_undetermined),
          inNoEndpointFlow: sum((a) => a.in_no_endpoint_flow),
          servicesPredating: data.services.length - reporting.length,
        }

  return {
    kind: "populated",
    rows,
    totals,
    endpointsPredating: data.endpoints_predating,
  }
}
