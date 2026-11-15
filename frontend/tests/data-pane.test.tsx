// The home `?view=data` matrix as a reader meets it (§5.2.17 UI): entity ×
// operation, each cell a count of endpoints that opens onto the endpoints
// themselves. The derivation is pinned in entity-matrix.test.ts; this pins the
// columns a reader sees, what a cell click shows, and that the two non-matrix
// states say what they are.
import { fireEvent, within } from "@testing-library/react"
import { beforeEach, describe, expect, test, vi } from "vitest"

import type { EntityUsageView } from "@/lib/generated/entity_usage.schema"
import { DataPane } from "@/components/home/data-pane"

import { renderWithQuery } from "./utils"

const usage = {
  snapshot_id: "snap_x",
  analyzed: true,
  endpoints_predating: 0,
  entities: [
    {
      service_id: "svc_order",
      entity: "com.acme.order.Order",
      name: "Order",
      data_model_id: "dm_" + "1".repeat(16),
      storage_name: "orders",
      declared_by: "annotation",
      operations: [
        { operation: "create", endpoints: [] },
        {
          operation: "read",
          endpoints: [
            {
              endpoint_id: "ep_get",
              http_method: "GET",
              full_uri: "/orders/{id}",
              call_sites: 2,
            },
            {
              endpoint_id: "ep_list",
              http_method: "GET",
              full_uri: "/orders",
              call_sites: 1,
            },
          ],
        },
        { operation: "update", endpoints: [] },
        { operation: "delete", endpoints: [] },
        {
          operation: "create-or-update",
          endpoints: [
            {
              endpoint_id: "ep_put",
              http_method: "PUT",
              full_uri: "/orders",
              call_sites: 1,
            },
          ],
        },
        { operation: "unknown", endpoints: [] },
      ],
    },
  ],
  services: [
    {
      service_id: "svc_order",
      service_name: "ts-order-service",
      accounting: {
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
      },
    },
  ],
} as unknown as EntityUsageView

const query = vi.hoisted(() => ({
  current: {} as Record<string, unknown>,
  refetch: (() => undefined) as () => unknown,
}))

vi.mock("@/lib/wadi/hooks", () => ({
  useEntityUsage: () => query.current,
}))

beforeEach(() => {
  query.refetch = vi.fn()
  query.current = {
    data: usage,
    error: null,
    isError: false,
    isPending: false,
    refetch: query.refetch,
  }
})

function renderPane() {
  const { container } = renderWithQuery(<DataPane snapshotId="snap_x" active />)
  return within(container)
}

describe("DataPane", () => {
  test("columns follow the operation enum, create-or-update its own", () => {
    const view = renderPane()
    expect(view.getAllByRole("columnheader").map((h) => h.textContent)).toEqual(
      [
        "Entity",
        "Service",
        "Create",
        "Read",
        "Update",
        "Delete",
        "Create or update",
        "Verb not read",
        "Notes",
      ]
    )
  })

  test("each cell counts endpoints; the PUT save is in create-or-update only", () => {
    const view = renderPane()
    const order = view.getByRole("row", { name: /Order/ })
    const counts = within(order)
      .getAllByRole("cell")
      .slice(2, 8)
      .map((cell) => cell.textContent)
    expect(counts).toEqual(["0", "2", "0", "0", "1", "0"])
  })

  test("clicking a cell lists its endpoints, each linking to its workspace", () => {
    const view = renderPane()
    fireEvent.click(
      view.getByRole("button", { name: "Order, read: 2 endpoints" })
    )
    const link = view.getByRole("link", { name: /\/orders\/\{id\}/ })
    // Straight into the Data pane with this entity selected, so its call
    // sites are already lit when the workspace opens.
    expect(link).toHaveAttribute(
      "href",
      "/s/snap_x/e/ep_get?pane=data&entity=com.acme.order.Order"
    )
    expect(view.getByRole("link", { name: /GET\s*\/orders$/ })).toBeTruthy()
    expect(view.queryByRole("link", { name: /PUT/ })).toBeNull()
  })

  test("notes carry the service's unresolved counts beside an absence", () => {
    const view = renderPane()
    const order = view.getByRole("row", { name: /Order/ })
    const notes = within(order).getAllByRole("cell").at(-1)
    expect(notes).toHaveTextContent("no detected delete call")
    expect(notes).toHaveTextContent("3 verb unknown")
    expect(notes).toHaveTextContent("2 entity undetermined")
    expect(notes).toHaveTextContent("5 in no endpoint flow")
  })

  test("a snapshot that predates entity facts says so, with no matrix", () => {
    query.current = {
      ...query.current,
      data: { ...usage, analyzed: false, entities: [] },
    }
    const view = renderPane()
    expect(
      view.getByText(/This snapshot predates entity facts/)
    ).toBeInTheDocument()
    expect(view.queryByRole("table")).toBeNull()
  })

  test("a failed fetch is an error with retry, and no matrix", () => {
    query.current = {
      data: undefined,
      error: new Error("503: Service Unavailable"),
      isError: true,
      isPending: false,
      refetch: query.refetch,
    }
    const view = renderPane()
    expect(view.getByText(/Could not load the entity view/)).toHaveTextContent(
      "503: Service Unavailable"
    )
    fireEvent.click(view.getByRole("button", { name: "Retry" }))
    expect(query.refetch).toHaveBeenCalled()
    expect(view.queryByRole("table")).toBeNull()
    expect(view.queryByText(/predates/)).toBeNull()
  })
})
