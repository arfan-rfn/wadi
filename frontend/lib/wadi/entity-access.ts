// Entity access in the UI (§5.2.17): the workspace Data list's states and the
// one ordered operation vocabulary every entity surface renders from. Pure, so
// the states are pinned by unit tests rather than by reading markup.

import type { CoverageReport } from "@/lib/generated/coverage_report.schema"
import type {
  CalleeUnboundReason,
  EndpointDetailView,
  EndpointEntityAccess,
  RemoteEdgeItem,
  UnopenableCallCount,
} from "@/lib/generated/endpoint_detail.schema"
import type {
  EntityAccessAccounting,
  EntityOperation,
  EntityUsageEndpoint,
  EntityUsageService,
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
 * (R1-7, C6). Shared by the Data list and the home matrix. A repository call
 * behind a call wadi could not open is in neither: it is not in any flow the
 * analysis opened (pre-landing review #5). */
export const ENTITY_ACCESS_LIMITS =
  "Not read: persistence outside Spring Data repositories, updates through setters on a loaded entity, repository calls inside lambdas or behind calls wadi could not open, cascades."

/**
 * Whether a call with this unbound reason may have a project body behind it,
 * and so a repository call wadi never saw (§5.2.17, pre-landing review #5).
 *
 * `false` only where the reason rules a project body out: a Lombok accessor
 * and an enum's `values()` have no source by construction, a method declared
 * by a framework supertype (Spring Data's `save`) is the framework's, and a
 * third-party callee is outside every analyzed source root. Every other
 * reason names project code wadi saw and could not connect, or a callee it
 * could not name at all, which may be the project's (§5.4.2 T5).
 *
 * A `Record` over the generated union, so a reason the contract adds breaks
 * `tsc` here until someone decides it. MCP `endpoint_detail` keeps the same
 * table in Python (`wadi_mcp.service`); the two must agree.
 */
const MAY_HIDE_PROJECT_CODE = {
  "lombok-generated": false,
  "compiler-generated": false,
  "inherited-external": false,
  "third-party": false,
  "ambiguous-overload": true,
  "declared-not-bound": true,
  "not-declared": true,
  "unresolved-receiver": true,
  "unparseable-callee": true,
} as const satisfies Record<CalleeUnboundReason, boolean>

/**
 * How many of an endpoint's unopenable calls may hide a repository call.
 *
 * A reason this build does not know counts: an unread reason is not evidence
 * that nothing is behind the call (P10).
 */
export function unopenedProjectCalls(
  unopenable: readonly UnopenableCallCount[] | undefined
): number {
  // Widened to any string: the wire can carry a reason newer than this build.
  const mayHide: Partial<Record<string, boolean>> = MAY_HIDE_PROJECT_CODE
  let calls = 0
  for (const entry of unopenable ?? []) {
    if (mayHide[entry.reason] ?? true) calls += entry.call_count
  }
  return calls
}

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
  /** Unique within the list: the entity and its model id together. The
   * summary groups by both, so one type can arrive as two rows, one with a
   * model id and one without, and `key` alone collided (review C7). */
  id: string
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
  /** `[]` and no outbound call: looked, found no repository call (R1-7).
   * `unopenedCalls` is set, and only set, when the flow stops at calls that
   * may hide one (review #5). */
  | { kind: "no-repository-call"; unopenedCalls?: number }
  /** `[]` with outbound calls: the data work happens elsewhere (Q26), unless
   * it sits behind one of `unopenedCalls`. */
  | { kind: "forwards-only"; forwards: ForwardTarget[]; unopenedCalls?: number }
  | { kind: "populated"; rows: DataListRow[]; forwards: ForwardTarget[] }

function rowOf(access: EndpointEntityAccess): DataListRow {
  return {
    id: `${entityKeyOf(access.entity)}#${access.data_model_id ?? "no-model"}`,
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
 *
 * `[]` means no repository call in the flow wadi could open. The two empty
 * states carry how many calls that flow stops at which may hide one, because
 * "no repository call found" alone reads as an absence nobody measured
 * (§5.2.17 "An empty summary says where the flow stopped").
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
  if (access.length === 0) {
    const unopened = unopenedProjectCalls(detail.unopenable_calls)
    // Absent rather than 0 when there is nothing to say, so the state reads
    // the same as before for every flow that opened to its leaves.
    const stops = unopened > 0 ? { unopenedCalls: unopened } : {}
    return forwards.length > 0
      ? { kind: "forwards-only", forwards, ...stops }
      : { kind: "no-repository-call", ...stops }
  }
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
 * (C6). Two buckets publish a verb that was not read: `unknownVerb` and
 * `implementedInProject`, a method with a body in the project such as
 * `archiveOld`, which is exactly where a delete can hide (review C2).
 * Without accounting, the service's `status` says why (review C3):
 * `predates` = its boundary was written before accounting, `extraction-failed`
 * = nothing in it was examined, `library` = its calls count in the services
 * that depend on it (§5.2.14). */
export type UnresolvedCounts =
  | {
      kind: "counted"
      unknownVerb: number
      implementedInProject: number
      undeterminedEntity: number
      inNoEndpointFlow: number
    }
  | { kind: "predates" }
  | { kind: "extraction-failed" }
  | { kind: "library" }

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

/** The reporting services' accounting, summed. */
export interface MatrixTotals {
  callSites: number
  bound: number
  createOrUpdate: number
  unknownVerb: number
  implementedInProject: number
  undeterminedEntity: number
  flush: number
  /** The flow partition: a second split of the same `callSites`, not an
   * outcome, so it is never added to {@link OUTCOME_BUCKETS}. */
  inNoEndpointFlow: number
}

export interface OutcomeBucket {
  key: Exclude<keyof MatrixTotals, "callSites" | "inNoEndpointFlow">
  label: string
  hint: string
}

/**
 * The outcome partition of the accounting, in the order the home strip shows
 * it. Every repository call has exactly one outcome, so these sum to
 * `callSites` (review C2). The strip once showed four of the six, and its
 * numbers added up to 65 of 68 on the crud-matrix fixture: what was missing
 * was `flush()` and the calls whose method has a body in the project.
 */
export const OUTCOME_BUCKETS = [
  {
    key: "bound",
    label: "bound to an entity and a verb",
    hint: "Every access has an entity and a single create, read, update or delete",
  },
  {
    key: "createOrUpdate",
    label: "create or update",
    hint: "A save the analysis could not split into create or update",
  },
  {
    key: "unknownVerb",
    label: "verb unknown",
    hint: "A repository call whose verb was not read, such as a query wadi does not parse",
  },
  {
    key: "implementedInProject",
    label: "body in the project, verb not read",
    hint: "The called repository method has a body in this project (a default method or a custom fragment such as archiveOld). Its verb is not read, so it publishes as verb unknown",
  },
  {
    key: "undeterminedEntity",
    label: "entity undetermined",
    hint: "The verb was read but the entity type could not be bound to a class",
  },
  {
    key: "flush",
    label: "flush, not an entity operation",
    hint: "flush() writes pending changes and names no entity",
  },
] as const satisfies readonly OutcomeBucket[]

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
      /** Services whose boundary predates entity facts, so are in no sum. */
      servicesPredating: number
      /** Services whose extraction failed: in no sum, and never examined. A
       * library is neither; it is analyzed inside its dependents (C3). */
      servicesFailed: number
      endpointsPredating: number
    }

/**
 * Which matrix columns a save is withheld from (review C6).
 *
 * While a gate flag is off, the save split's verb is evidence only and the
 * save publishes as create-or-update (rule 5). So in a gated column a zero is
 * not a measured absence: the save that creates is counted under
 * create-or-update instead.
 * The coverage report names those operations; this reads them. `unread` is
 * every case where it cannot say: the report has not loaded or failed, no
 * service reports accounting, or the report predates the field (1.27.0).
 */
export type WithheldColumns =
  { kind: "read"; operations: EntityOperation[] } | { kind: "unread" }

export function withheldColumns(
  report: Pick<CoverageReport, "entity_coverage"> | undefined
): WithheldColumns {
  const gated = report?.entity_coverage?.gated_operations
  // `undefined` when the section lacks the key, `null` when the API sends a
  // pre-1.27.0 report: both mean the report never computed it.
  if (gated === undefined || gated === null) return { kind: "unread" }
  const set = new Set<EntityOperation>(gated)
  return {
    kind: "read",
    operations: ENTITY_OPERATIONS.filter((op) => set.has(op)),
  }
}

const NO_DELETE = "no detected delete call"
const NO_ACCESS = "declared, no detected access"
const REPOSITORY_ONLY = "repository only, no annotation"

function unresolvedOf(
  service: EntityUsageService | undefined
): UnresolvedCounts {
  const accounting = service?.accounting
  if (accounting)
    return {
      kind: "counted",
      unknownVerb: accounting.unknown_operation,
      implementedInProject: accounting.implemented_in_project,
      undeterminedEntity: accounting.entity_undetermined,
      inNoEndpointFlow: accounting.in_no_endpoint_flow,
    }
  switch (service?.status) {
    case "extraction-failed":
      return { kind: "extraction-failed" }
    case "library":
      return { kind: "library" }
    default:
      // `predating`, or a service the view does not list: nothing says it
      // was examined, which is what "predates" claims.
      return { kind: "predates" }
  }
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
      unresolved: claimsAbsence ? unresolvedOf(service) : null,
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
          implementedInProject: sum((a) => a.implemented_in_project),
          undeterminedEntity: sum((a) => a.entity_undetermined),
          flush: sum((a) => a.flush),
          inNoEndpointFlow: sum((a) => a.in_no_endpoint_flow),
        }

  return {
    kind: "populated",
    rows,
    totals,
    // Counted by status, never as `services - reporting`: `/entities` lists
    // libraries and failed extractions too, and neither predates anything.
    servicesPredating: data.services.filter((s) => s.status === "predating")
      .length,
    servicesFailed: data.services.filter(
      (s) => s.status === "extraction-failed"
    ).length,
    endpointsPredating: data.endpoints_predating,
  }
}
