// The home `?view=data` matrix as a derivation over `EntityUsageView`
// (§5.2.17 UI). The notes are the part that can lie: "no detected delete
// call" is a statement about what was DETECTED, so the service's unresolved
// counts sit beside it (C6). An unknown verb could be the delete, and a call
// outside every endpoint flow is a call no endpoint is credited with.
import { describe, expect, test } from "vitest"

import type {
  EntityAccessAccounting,
  EntityUsageRow,
  EntityUsageView,
} from "@/lib/generated/entity_usage.schema"
import { deriveEntityMatrixState } from "@/lib/wadi/entity-access"

const accounting = {
  call_sites: 20,
  in_endpoint_flow: 15,
  in_no_endpoint_flow: 5,
  flush: 0,
  implemented_in_project: 1,
  entity_undetermined: 2,
  unknown_operation: 3,
  create_or_update: 4,
  bound: 10,
  accesses_by_operation: {},
  sites_by_basis: {},
  rules_version: "r1",
  gate_flags: [],
} as EntityAccessAccounting

const endpoint = (id: string, method: string, uri: string) => ({
  endpoint_id: id,
  http_method: method,
  full_uri: uri,
  call_sites: 1,
})

/** Rows carry all six operations; this fixture lists them deliberately OUT
 * of enum order, so a column that read the API's order would show it. */
function row(
  partial: Partial<EntityUsageRow> & {
    ops?: Partial<Record<string, ReturnType<typeof endpoint>[]>>
  }
): EntityUsageRow {
  const ops = partial.ops ?? {}
  return {
    service_id: "svc_order",
    entity: "com.acme.order.Order",
    name: "Order",
    data_model_id: null,
    storage_name: null,
    declared_by: "annotation",
    operations: [
      "unknown",
      "delete",
      "create-or-update",
      "update",
      "read",
      "create",
    ].map((operation) => ({ operation, endpoints: ops[operation] ?? [] })),
    ...partial,
  } as EntityUsageRow
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
        accounting,
      },
      {
        service_id: "svc_old",
        service_name: "ts-old-service",
        accounting: null,
      },
    ],
    ...partial,
  } as EntityUsageView
}

describe("entity matrix", () => {
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
    expect(state.rows[0].unresolved).toEqual({
      kind: "counted",
      unknownVerb: 3,
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
      undeterminedEntity: 2,
      inNoEndpointFlow: 5,
      servicesPredating: 1,
    })
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
