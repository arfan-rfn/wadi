// The workspace Data list (§5.2.17 UI), as a pure derivation from the detail
// aggregate the workspace already fetches. Seven states, and the reason they
// are pinned one by one is that four of them are some flavour of "nothing to
// list" and each means something different: the snapshot never looked
// (R1-6), it looked and found no repository call (R1-7), the endpoint hands
// its data work to another service (Q26), or the request failed and nothing
// is known at all. Rendering any two of them alike states a finding that was
// never made (P10).
import { describe, expect, test } from "vitest"

import type {
  EndpointDetailView,
  RemoteEdgeItem,
} from "@/lib/generated/endpoint_detail.schema"
import { deriveDataListState } from "@/lib/wadi/entity-access"
import { UNDETERMINED_ENTITY_KEY } from "@/lib/wadi/routes"

function detailWith(
  entityAccess: unknown,
  outbound: Partial<RemoteEdgeItem>[] = []
): EndpointDetailView {
  return {
    snapshot_id: "snap_x",
    system_id: "sys_x",
    service_id: "svc_consign",
    service_name: "ts-consign-service",
    icfg_available: true,
    stitched: true,
    outbound: outbound as RemoteEdgeItem[],
    endpoint: {
      id: "ep_" + "a".repeat(16),
      snapshot_id: "snap_x",
      service_id: "svc_consign",
      http_method: "PUT",
      full_uri: "/api/v1/consignservice/consigns",
      simplified_uri: "/api/v1/consignservice/consigns",
      handler: { id: "m_" + "a".repeat(16), signature: "update:void()" },
      ...(entityAccess === undefined ? {} : { entity_access: entityAccess }),
    },
  } as unknown as EndpointDetailView
}

const forward: Partial<RemoteEdgeItem> = {
  edge_id: "edge_1",
  http_verb: "PUT",
  target_service_name: "ts-station-service",
  target_simplified_uri: "/api/v1/stationservice/stations",
}

describe("Data list states", () => {
  test("populated: one row per entity, simple name shown, qualified kept", () => {
    const state = deriveDataListState({
      detail: detailWith([
        {
          entity: "com.acme.consign.ConsignRecord",
          data_model_id: "dm_" + "1".repeat(16),
          operations: ["read", "update"],
          call_sites: 3,
        },
        {
          entity: "com.acme.consign.ConsignPrice",
          data_model_id: null,
          operations: ["create-or-update"],
          call_sites: 1,
        },
      ]),
      error: null,
    })
    expect(state.kind).toBe("populated")
    if (state.kind !== "populated") return
    expect(state.rows.map((r) => [r.name, r.qualifiedName])).toEqual([
      ["ConsignRecord", "com.acme.consign.ConsignRecord"],
      ["ConsignPrice", "com.acme.consign.ConsignPrice"],
    ])
    expect(state.rows[0]).toMatchObject({
      key: "com.acme.consign.ConsignRecord",
      operations: ["read", "update"],
      callSites: 3,
      undetermined: false,
      verbNotRead: false,
    })
    // create-or-update is ONE operation, never a create plus an update.
    expect(state.rows[1].operations).toEqual(["create-or-update"])
  })

  test("entity not determined: listed with its verbs, under the ~undetermined key", () => {
    // R1-25: a call whose verb was read but whose entity was not is still a
    // database call this endpoint makes; dropping it would understate it.
    const state = deriveDataListState({
      detail: detailWith([
        {
          entity: null,
          data_model_id: null,
          operations: ["read", "delete"],
          call_sites: 2,
        },
      ]),
      error: null,
    })
    expect(state.kind).toBe("populated")
    if (state.kind !== "populated") return
    expect(state.rows).toEqual([
      expect.objectContaining({
        key: UNDETERMINED_ENTITY_KEY,
        entity: null,
        name: "entity not determined",
        qualifiedName: null,
        operations: ["read", "delete"],
        callSites: 2,
        undetermined: true,
      }),
    ])
  })

  test("verb not read: a row whose operations include unknown says so", () => {
    const state = deriveDataListState({
      detail: detailWith([
        {
          entity: "com.acme.notify.Topic",
          data_model_id: null,
          operations: ["read", "unknown"],
          call_sites: 2,
        },
      ]),
      error: null,
    })
    expect(state.kind).toBe("populated")
    if (state.kind !== "populated") return
    expect(state.rows[0].verbNotRead).toBe(true)
    expect(state.rows[0].undetermined).toBe(false)
  })

  test("forwards only: no local entities, names each outbound call (Q26)", () => {
    const state = deriveDataListState({
      detail: detailWith(
        [],
        [
          forward,
          // The same target from a second call site is one place it forwards.
          { ...forward, edge_id: "edge_2" },
          {
            edge_id: "edge_3",
            http_verb: null,
            target_http_method: null,
            target_service_name: null,
            external_host: "api.payments.example",
            url: "https://api.payments.example/charge",
          },
        ]
      ),
      error: null,
    })
    expect(state).toEqual({
      kind: "forwards-only",
      forwards: [
        {
          key: "edge_1",
          label: "PUT ts-station-service /api/v1/stationservice/stations",
        },
        {
          key: "edge_3",
          label: "api.payments.example https://api.payments.example/charge",
        },
      ],
    })
  })

  test("no repository call found: analyzed, nothing local, nothing forwarded", () => {
    expect(
      deriveDataListState({ detail: detailWith([]), error: null })
    ).toEqual({ kind: "no-repository-call" })
  })

  test("snapshot predates entity facts: null or absent is not an empty list", () => {
    // R1-6: [] is "looked, found nothing"; None is "never looked".
    expect(
      deriveDataListState({ detail: detailWith(null, [forward]), error: null })
    ).toEqual({ kind: "predates" })
    expect(
      deriveDataListState({ detail: detailWith(undefined), error: null })
    ).toEqual({ kind: "predates" })
  })

  test("fetch failed: an error, never an empty state", () => {
    expect(
      deriveDataListState({
        detail: undefined,
        error: new Error("502: Bad Gateway"),
      })
    ).toEqual({ kind: "fetch-failed", message: "502: Bad Gateway" })
  })

  test("still loading is its own state, not an empty list", () => {
    expect(deriveDataListState({ detail: undefined, error: null })).toEqual({
      kind: "pending",
    })
  })

  test("a populated endpoint that also forwards keeps both facts", () => {
    const state = deriveDataListState({
      detail: detailWith(
        [
          {
            entity: "com.acme.consign.ConsignRecord",
            data_model_id: null,
            operations: ["read"],
            call_sites: 1,
          },
        ],
        [forward]
      ),
      error: null,
    })
    expect(state.kind).toBe("populated")
    if (state.kind !== "populated") return
    expect(state.forwards.map((f) => f.label)).toEqual([
      "PUT ts-station-service /api/v1/stationservice/stations",
    ])
  })
})
