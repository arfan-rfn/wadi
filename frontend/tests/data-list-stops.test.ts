// Where an empty Data list's flow stopped (§5.2.17, pre-landing review #5).
//
// `[]` means no repository call was found in the flow wadi could OPEN. When
// that flow ends at project calls wadi could not open, a repository call may
// sit behind one of them, and "No repository call found" alone would state an
// absence the analysis never measured (P10). The other states are pinned in
// data-list-state.test.ts; this file pins only the count beside the two empty
// ones, and which unopenable calls it counts.
import { describe, expect, test } from "vitest"

import type {
  EndpointDetailView,
  RemoteEdgeItem,
  UnopenableCallCount,
} from "@/lib/generated/endpoint_detail.schema"
import {
  deriveDataListState,
  ENTITY_ACCESS_LIMITS,
  unopenedProjectCalls,
} from "@/lib/wadi/entity-access"

function detailWith(
  entityAccess: unknown,
  unopenable: UnopenableCallCount[],
  outbound: Partial<RemoteEdgeItem>[] = []
): EndpointDetailView {
  return {
    snapshot_id: "snap_x",
    system_id: "sys_x",
    service_id: "svc_route",
    service_name: "ts-route-service",
    icfg_available: true,
    stitched: true,
    outbound: outbound as RemoteEdgeItem[],
    unopenable_calls: unopenable,
    icfg_schema_version: "1.27.0",
    endpoint: {
      id: "ep_" + "b".repeat(16),
      snapshot_id: "snap_x",
      service_id: "svc_route",
      http_method: "GET",
      full_uri: "/api/v1/routeservice/routes",
      simplified_uri: "/api/v1/routeservice/routes",
      handler: { id: "m_" + "b".repeat(16), signature: "list:void()" },
      entity_access: entityAccess,
    },
  } as unknown as EndpointDetailView
}

const forward: Partial<RemoteEdgeItem> = {
  edge_id: "edge_1",
  http_verb: "GET",
  target_service_name: "ts-station-service",
  target_simplified_uri: "/api/v1/stationservice/stations",
}

describe("an empty Data list says where its flow stopped", () => {
  test("no repository call found, with project calls wadi could not open", () => {
    const state = deriveDataListState({
      detail: detailWith(
        [],
        [
          { reason: "declared-not-bound", call_count: 2 },
          { reason: "ambiguous-overload", call_count: 1 },
        ]
      ),
      error: null,
    })
    expect(state).toEqual({ kind: "no-repository-call", unopenedCalls: 3 })
  })

  test("forwards only, with project calls wadi could not open", () => {
    const state = deriveDataListState({
      detail: detailWith(
        [],
        [{ reason: "unresolved-receiver", call_count: 4 }],
        [forward]
      ),
      error: null,
    })
    expect(state).toEqual({
      kind: "forwards-only",
      forwards: [
        {
          key: "edge_1",
          label: "GET ts-station-service /api/v1/stationservice/stations",
        },
      ],
      unopenedCalls: 4,
    })
  })

  test("calls that cannot hide project code leave the empty state as it was", () => {
    // A Lombok accessor, an enum's values(), a framework supertype's save and
    // a JDK method have no project body, so no repository call is behind them.
    const state = deriveDataListState({
      detail: detailWith(
        [],
        [
          { reason: "lombok-generated", call_count: 40 },
          { reason: "compiler-generated", call_count: 1 },
          { reason: "inherited-external", call_count: 3 },
          { reason: "third-party", call_count: 9 },
        ]
      ),
      error: null,
    })
    expect(state).toEqual({ kind: "no-repository-call" })
    expect("unopenedCalls" in state).toBe(false)
  })

  test("a populated list is not qualified: the rows are what it found", () => {
    const state = deriveDataListState({
      detail: detailWith(
        [
          {
            entity: "com.acme.route.Route",
            data_model_id: null,
            operations: ["read"],
            call_sites: 1,
          },
        ],
        [{ reason: "declared-not-bound", call_count: 2 }]
      ),
      error: null,
    })
    expect(state.kind).toBe("populated")
    expect("unopenedCalls" in state).toBe(false)
  })
})

describe("which unopenable calls may hide a repository call", () => {
  test("only the reasons that do not rule out a project body count", () => {
    expect(
      unopenedProjectCalls([
        { reason: "lombok-generated", call_count: 10 },
        { reason: "inherited-external", call_count: 10 },
        { reason: "compiler-generated", call_count: 10 },
        { reason: "third-party", call_count: 10 },
        { reason: "declared-not-bound", call_count: 1 },
        { reason: "ambiguous-overload", call_count: 2 },
        { reason: "unresolved-receiver", call_count: 3 },
        { reason: "not-declared", call_count: 4 },
        { reason: "unparseable-callee", call_count: 5 },
      ])
    ).toBe(15)
  })

  test("a reason this build does not know is counted, never assumed harmless", () => {
    expect(
      unopenedProjectCalls([
        {
          reason: "some-future-reason" as UnopenableCallCount["reason"],
          call_count: 2,
        },
      ])
    ).toBe(2)
  })

  test("nothing listed counts nothing", () => {
    expect(unopenedProjectCalls([])).toBe(0)
    expect(unopenedProjectCalls(undefined)).toBe(0)
  })
})

describe("the Limits line names the case", () => {
  test("repository calls behind calls wadi could not open are not read", () => {
    expect(ENTITY_ACCESS_LIMITS).toMatch(/behind calls wadi could not open/)
  })
})
