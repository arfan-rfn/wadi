// The home `?view=data` matrix as a derivation over `EntityUsageView`
// (§5.2.17 UI). The notes are the part that can lie: "no detected delete
// call" is a statement about what was DETECTED, so the service's unresolved
// counts sit beside it (C6). An unknown verb could be the delete, and a call
// outside every endpoint flow is a call no endpoint is credited with.
import { describe, expect, test } from "vitest"

import type {
  EntityOperation,
  EntityUsageEndpoint,
  EntityUsageRow,
  EntityUsageView,
} from "@/lib/generated/entity_usage.schema"
import {
  deriveEntityMatrixState,
  OUTCOME_BUCKETS,
  withheldColumns,
} from "@/lib/wadi/entity-access"

import {
  CRUD_MATRIX_ENTITIES,
  CRUD_MATRIX_ENTITY_COVERAGE,
} from "./fixtures/crud-matrix-entities"
import {
  SYNTHETIC_ACCOUNTING as accounting,
  accountingViolations,
} from "./fixtures/entity-accounting"

const endpoint = (
  id: string,
  method: EntityUsageEndpoint["http_method"],
  uri: string
): EntityUsageEndpoint => ({
  endpoint_id: id,
  http_method: method,
  full_uri: uri,
  call_sites: 1,
})

/** The API lists all six operations in enum order (the contract's validator).
 * This fixture lists them deliberately OUT of it, so a column that read the
 * API's order instead of the one vocabulary would show it. */
const SHUFFLED: EntityOperation[] = [
  "unknown",
  "delete",
  "create-or-update",
  "update",
  "read",
  "create",
]

function row({
  ops = {},
  ...fields
}: Partial<Omit<EntityUsageRow, "operations">> & {
  ops?: Partial<Record<EntityOperation, EntityUsageEndpoint[]>>
}): EntityUsageRow {
  return {
    service_id: "svc_order",
    entity: "com.acme.order.Order",
    name: "Order",
    data_model_id: null,
    storage_name: null,
    declared_by: "annotation",
    operations: SHUFFLED.map((operation) => ({
      operation,
      endpoints: ops[operation] ?? [],
    })),
    ...fields,
  }
}

function view(partial: Partial<EntityUsageView>): EntityUsageView {
  return {
    snapshot_id: "snap_x",
    analyzed: true,
    endpoints_predating: 0,
    entities: [],
    services: [
      {
        service_id: "svc_order",
        service_name: "ts-order-service",
        status: "reporting",
        accounting,
      },
      {
        service_id: "svc_old",
        service_name: "ts-old-service",
        status: "predating",
        accounting: null,
      },
    ],
    ...partial,
  }
}

describe("entity matrix", () => {
  test("every accounting fixture is accounting the API can send (C9)", () => {
    const real = CRUD_MATRIX_ENTITIES.services.flatMap((s) =>
      s.accounting ? [s.accounting] : []
    )
    expect(real).toHaveLength(1)
    for (const a of [accounting, ...real])
      expect(accountingViolations(a)).toEqual([])
  })

  test("on the crud-matrix payload the outcome buckets sum to the repository calls", () => {
    const state = deriveEntityMatrixState({
      data: CRUD_MATRIX_ENTITIES,
      error: null,
    })
    if (state.kind !== "populated") throw new Error(state.kind)
    // The live accounting: 68 calls, of which 1 is flush() and 2 call a
    // method with a body in the project. 1.26.0's strip left both out and
    // showed buckets summing to 65 (review C2).
    expect(state.totals).toEqual({
      callSites: 68,
      bound: 33,
      createOrUpdate: 18,
      unknownVerb: 13,
      implementedInProject: 2,
      undeterminedEntity: 1,
      flush: 1,
      inNoEndpointFlow: 1,
    })
    const totals = state.totals
    if (!totals) throw new Error("no totals")
    expect(
      OUTCOME_BUCKETS.reduce((sum, bucket) => sum + totals[bucket.key], 0)
    ).toBe(68)
    // The other partition is not an outcome: adding it would count a call twice.
    expect(OUTCOME_BUCKETS.map((b) => b.key)).not.toContain("inNoEndpointFlow")
  })

  test("cells follow the operation enum, whatever order the rows arrive in", () => {
    const state = deriveEntityMatrixState({
      data: view({
        entities: [
          row({
            ops: {
              read: [endpoint("ep_1", "GET", "/orders/{id}")],
              "create-or-update": [endpoint("ep_2", "PUT", "/orders")],
            },
          }),
        ],
      }),
      error: null,
    })
    expect(state.kind).toBe("populated")
    if (state.kind !== "populated") return
    const [order] = state.rows
    expect(order.cells.map((c) => c.operation)).toEqual([
      "create",
      "read",
      "update",
      "delete",
      "create-or-update",
      "unknown",
    ])
    // create-or-update is its own column: the PUT is not counted as a
    // create or as an update.
    expect(order.cells.map((c) => c.endpoints.length)).toEqual([
      0, 1, 0, 0, 1, 0,
    ])
    expect(order.serviceName).toBe("ts-order-service")
  })

  test("no detected delete call, with the service's unresolved counts beside it", () => {
    const state = deriveEntityMatrixState({
      data: view({
        entities: [
          row({ ops: { read: [endpoint("ep_1", "GET", "/orders/{id}")] } }),
        ],
      }),
      error: null,
    })
    if (state.kind !== "populated") throw new Error(state.kind)
    expect(state.rows[0].notes).toEqual(["no detected delete call"])
    // Both buckets whose verb was not read travel with the note: a custom
    // method with a body in the project is exactly where a delete can hide.
    expect(state.rows[0].unresolved).toEqual({
      kind: "counted",
      unknownVerb: 3,
      implementedInProject: 1,
      undeterminedEntity: 2,
      inNoEndpointFlow: 5,
    })
  })

  test("declared, no detected access; and repository only, no annotation", () => {
    const state = deriveEntityMatrixState({
      data: view({
        entities: [
          row({
            entity: "com.acme.order.Ghost",
            name: "Ghost",
            declared_by: "repository-argument",
          }),
        ],
      }),
      error: null,
    })
    if (state.kind !== "populated") throw new Error(state.kind)
    expect(state.rows[0].notes).toEqual([
      "declared, no detected access",
      "repository only, no annotation",
    ])
  })

  test("a row with a detected delete makes no absence claim and carries no counts", () => {
    const state = deriveEntityMatrixState({
      data: view({
        entities: [
          row({
            ops: { delete: [endpoint("ep_9", "DELETE", "/orders/{id}")] },
          }),
        ],
      }),
      error: null,
    })
    if (state.kind !== "populated") throw new Error(state.kind)
    expect(state.rows[0].notes).toEqual([])
    expect(state.rows[0].unresolved).toBeNull()
  })

  test("a service whose accounting predates the phase says so instead of zeros", () => {
    const state = deriveEntityMatrixState({
      data: view({
        entities: [
          row({
            service_id: "svc_old",
            ops: { read: [endpoint("ep_1", "GET", "/x")] },
          }),
        ],
      }),
      error: null,
    })
    if (state.kind !== "populated") throw new Error(state.kind)
    expect(state.rows[0].unresolved).toEqual({ kind: "predates" })
  })

  test("the undetermined bucket is a row with the ~undetermined key and no notes", () => {
    const state = deriveEntityMatrixState({
      data: view({
        entities: [
          row({
            entity: null,
            name: "entity not determined",
            declared_by: null,
            ops: { read: [endpoint("ep_1", "GET", "/x")] },
          }),
        ],
      }),
      error: null,
    })
    if (state.kind !== "populated") throw new Error(state.kind)
    expect(state.rows[0]).toMatchObject({
      entityKey: "~undetermined",
      undetermined: true,
      notes: [],
    })
  })

  test("totals sum the services that report, and count the ones that predate", () => {
    const state = deriveEntityMatrixState({ data: view({}), error: null })
    if (state.kind !== "populated") throw new Error(state.kind)
    expect(state.totals).toEqual({
      callSites: 20,
      bound: 10,
      createOrUpdate: 4,
      unknownVerb: 3,
      implementedInProject: 1,
      undeterminedEntity: 2,
      flush: 0,
      inNoEndpointFlow: 5,
    })
    expect(state.servicesPredating).toBe(1)
  })

  test("services without accounting are counted by why: predating and failed apart, libraries not at all (C3)", () => {
    const base = view({})
    const state = deriveEntityMatrixState({
      data: view({
        services: [
          ...base.services,
          {
            service_id: "svc_broken",
            service_name: "ts-broken-service",
            status: "extraction-failed",
            accounting: null,
          },
          {
            service_id: "svc_common",
            service_name: "ts-common",
            status: "library",
            accounting: null,
          },
        ],
        entities: [
          row({
            service_id: "svc_broken",
            ops: { read: [endpoint("ep_1", "GET", "/x")] },
          }),
          row({
            service_id: "svc_common",
            entity: "com.acme.common.Audit",
            name: "Audit",
            ops: { read: [endpoint("ep_2", "GET", "/y")] },
          }),
        ],
      }),
      error: null,
    })
    if (state.kind !== "populated") throw new Error(state.kind)
    // Four services listed, one reporting: 1.26.0's UI said "3 not counted,
    // their accounting predates entity facts", true of one of the three.
    expect(state.servicesPredating).toBe(1)
    expect(state.servicesFailed).toBe(1)
    // The totals are the reporting service's alone either way.
    expect(state.totals?.callSites).toBe(20)
    expect(state.rows.map((r) => r.unresolved)).toEqual([
      { kind: "extraction-failed" },
      { kind: "library" },
    ])
  })

  test("analyzed=false is 'predates', never an empty matrix (R1-6)", () => {
    expect(
      deriveEntityMatrixState({
        data: view({ analyzed: false, endpoints_predating: 12 }),
        error: null,
      })
    ).toEqual({ kind: "predates" })
  })

  test("a failed fetch is a failure, not a matrix", () => {
    expect(
      deriveEntityMatrixState({ data: undefined, error: new Error("503: x") })
    ).toEqual({ kind: "fetch-failed", message: "503: x" })
    expect(deriveEntityMatrixState({ data: undefined, error: null })).toEqual({
      kind: "pending",
    })
  })
})

describe("withheld columns (C6)", () => {
  test("the coverage report names the operations no save may publish", () => {
    // Every gate flag in the crud-matrix run is off: a save publishes as
    // create-or-update, so create and update hold only what query text says.
    expect(
      withheldColumns({ entity_coverage: CRUD_MATRIX_ENTITY_COVERAGE })
    ).toEqual({ kind: "read", operations: ["create", "update"] })
  })

  test("they come back in column order, whatever order the report lists", () => {
    expect(
      withheldColumns({
        entity_coverage: {
          ...CRUD_MATRIX_ENTITY_COVERAGE,
          gated_operations: ["update", "create"],
        },
      })
    ).toEqual({ kind: "read", operations: ["create", "update"] })
  })

  test("a scored split withholds nothing", () => {
    expect(
      withheldColumns({
        entity_coverage: {
          ...CRUD_MATRIX_ENTITY_COVERAGE,
          gated_operations: [],
        },
      })
    ).toEqual({ kind: "read", operations: [] })
  })

  test("no report, no section, or a report from before the field: not known", () => {
    const { gated_operations: _omitted, ...before127 } =
      CRUD_MATRIX_ENTITY_COVERAGE
    expect(withheldColumns(undefined)).toEqual({ kind: "unread" })
    expect(withheldColumns({ entity_coverage: null })).toEqual({
      kind: "unread",
    })
    expect(withheldColumns({ entity_coverage: before127 })).toEqual({
      kind: "unread",
    })
  })
})
