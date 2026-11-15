// The home `?view=data` matrix as a reader meets it (§5.2.17 UI): entity ×
// operation, each cell a count of endpoints that opens onto the endpoints
// themselves. The derivation is pinned in entity-matrix.test.ts; this pins the
// columns a reader sees, what a cell click shows, and that the two non-matrix
// states say what they are.
import { fireEvent, within } from "@testing-library/react"
import { beforeEach, describe, expect, test, vi } from "vitest"

import type { EntityUsageView } from "@/lib/generated/entity_usage.schema"
import { DataPane } from "@/components/home/data-pane"

import {
  CRUD_MATRIX_ENTITIES,
  CRUD_MATRIX_ENTITY_COVERAGE,
} from "./fixtures/crud-matrix-entities"
import { SYNTHETIC_ACCOUNTING } from "./fixtures/entity-accounting"
import { renderWithQuery } from "./utils"

const usage: EntityUsageView = {
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
      status: "reporting",
      accounting: SYNTHETIC_ACCOUNTING,
    },
  ],
}

const query = vi.hoisted(() => ({
  current: {} as Record<string, unknown>,
  coverage: {} as Record<string, unknown>,
  refetch: (() => undefined) as () => unknown,
}))

vi.mock("@/lib/wadi/hooks", () => ({
  useEntityUsage: () => query.current,
  useCoverage: () => query.coverage,
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
  // The coverage report still loading: which columns are withheld is not
  // known yet, so no header is marked.
  query.coverage = { data: undefined, isPending: true, isError: false }
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

  test("a gated operation's column says withheld, and its zeros are not called measured (C6)", () => {
    query.current = { ...query.current, data: CRUD_MATRIX_ENTITIES }
    query.coverage = {
      data: { entity_coverage: CRUD_MATRIX_ENTITY_COVERAGE },
      isPending: false,
      isError: false,
    }
    const view = renderPane()
    const headers = view.getAllByRole("columnheader")
    expect(headers.map((h) => h.textContent)).toEqual([
      "Entity",
      "Service",
      "Create · withheld",
      "Read",
      "Update · withheld",
      "Delete",
      "Create or update",
      "Verb not read",
      "Notes",
    ])
    expect(headers[2].getAttribute("title")).toMatch(
      /saves are published as create or update until the split is scored/
    )
    const footer = view.getByText(/A zero is measured/)
    expect(footer).toHaveTextContent(/not in a withheld column/)
    expect(footer).toHaveTextContent(/create, update/)
  })

  test("with no coverage report, the footer does not vouch for create or update zeros", () => {
    const view = renderPane()
    expect(view.getByText(/A zero is measured/)).toHaveTextContent(
      /a zero under create or update is not measured/
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

  test("under an operation, an endpoint's count is that operation's calls (C1)", () => {
    // POST /crud/inherited-method-table touches Order at 11 calls: 5 read, 3
    // delete, 3 save. Under delete it is 3, never the entity's 11.
    query.current = { ...query.current, data: CRUD_MATRIX_ENTITIES }
    const view = renderPane()
    fireEvent.click(
      view.getByRole("button", { name: "Order, delete: 4 endpoints" })
    )
    const item = view
      .getByRole("link", { name: /\/crud\/inherited-method-table/ })
      .closest("li")
    expect(item).toHaveTextContent(/3 calls$/)
    expect(item).not.toHaveTextContent(/11/)
  })

  test("a count written before 1.27.0 shows no number, and says to re-analyze", () => {
    const [order] = usage.entities
    query.current = {
      ...query.current,
      data: {
        ...usage,
        entities: [
          {
            ...order,
            operations: order.operations.map((usage) =>
              usage.operation === "read"
                ? {
                    ...usage,
                    endpoints: usage.endpoints.map((endpoint) => ({
                      ...endpoint,
                      call_sites: null,
                    })),
                  }
                : usage
            ),
          },
        ],
      },
    }
    const view = renderPane()
    fireEvent.click(
      view.getByRole("button", { name: "Order, read: 2 endpoints" })
    )
    const item = view
      .getByRole("link", { name: /\/orders\/\{id\}/ })
      .closest("li")
    if (!item) throw new Error("the endpoint is not in a list item")
    expect(item).not.toHaveTextContent(/\d/)
    expect(item).not.toHaveTextContent(/null/)
    expect(
      within(item).getByTitle(/count not recorded; re-analyze/)
    ).toBeInTheDocument()
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

  test("the absence note names both buckets whose verb was not read (C2)", () => {
    // On the crud-matrix payload, OrderRepository.archiveOld and findAndTouch
    // have bodies in the project: 2 calls that publish `unknown` outside the
    // 13 "verb unknown" ones, and either could be the delete not detected.
    query.current = { ...query.current, data: CRUD_MATRIX_ENTITIES }
    const view = renderPane()
    const [account] = view.getAllByRole("row", { name: /^Account/ })
    const note = within(account).getByText(/spring-data-crud-matrix:/)
    expect(note).toHaveTextContent("13 verb unknown")
    expect(note).toHaveTextContent("2 body in the project, verb not read")
    expect(note.getAttribute("title")).toMatch(/verb unknown/)
    expect(note.getAttribute("title")).toMatch(/body in the project/)
  })

  test("the strip's outcome buckets sum to its repository calls, on a real payload", () => {
    query.current = { ...query.current, data: CRUD_MATRIX_ENTITIES }
    const view = renderPane()
    expect(view.getByText("Repository calls").parentElement).toHaveTextContent(
      "Repository calls 68"
    )
    const outcomes = view.getByRole("list", {
      name: "What each repository call became",
    })
    const counts = within(outcomes)
      .getAllByRole("listitem")
      .map((item) => Number(/(\d+)$/.exec(item.textContent ?? "")?.[1]))
    // bound, create or update, verb unknown, body in the project, entity
    // undetermined, flush: 33 + 18 + 13 + 2 + 1 + 1.
    expect(counts).toEqual([33, 18, 13, 2, 1, 1])
    expect(counts.reduce((sum, n) => sum + n, 0)).toBe(68)
    // Flow membership is the other partition of the same 68: shown, but
    // apart, so nobody adds it to the outcomes.
    expect(within(outcomes).queryByText(/endpoint flow/)).toBeNull()
    expect(view.getByText(/of these, in no endpoint flow/)).toHaveTextContent(
      /1$/
    )
  })

  test("the strip says why a service has no accounting, and never blames a library (C3)", () => {
    query.current = {
      ...query.current,
      data: {
        ...usage,
        services: [
          ...usage.services,
          {
            service_id: "svc_old",
            service_name: "ts-old-service",
            status: "predating",
            accounting: null,
          },
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
      },
    }
    const view = renderPane()
    expect(view.getByText("1 service predates entity facts")).toHaveClass(
      "text-warn"
    )
    expect(
      view.getByText(
        "1 service failed extraction; its data access was never examined"
      )
    ).toHaveClass("text-warn")
    expect(view.queryByText(/not counted/)).toBeNull()
    expect(view.queryByText(/3 services/)).toBeNull()
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
