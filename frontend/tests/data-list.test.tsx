// The workspace Data list as a reader meets it (§5.2.17 UI). The derivation
// is pinned in data-list-state.test.ts; this pins what each state SAYS, and
// above all what it must not say: a failed fetch and a pre-phase snapshot
// make no claim about the code, and one create-or-update save is one chip.
import { fireEvent, render, within } from "@testing-library/react"
import { describe, expect, test, vi } from "vitest"

import type { EndpointDetailView } from "@/lib/generated/endpoint_detail.schema"
import {
  deriveDataListState,
  type DataListRow,
  type EntitySiteRef,
} from "@/lib/wadi/entity-access"
import { UNDETERMINED_ENTITY_KEY } from "@/lib/wadi/routes"
import { DataList } from "@/components/explorer/data-list"

const record: DataListRow = {
  id: "com.acme.consign.ConsignRecord#no-model",
  key: "com.acme.consign.ConsignRecord",
  entity: "com.acme.consign.ConsignRecord",
  name: "ConsignRecord",
  qualifiedName: "com.acme.consign.ConsignRecord",
  operations: ["read", "update"],
  callSites: 3,
  undetermined: false,
  verbNotRead: false,
}

const price: DataListRow = {
  id: "com.acme.consign.ConsignPrice#no-model",
  key: "com.acme.consign.ConsignPrice",
  entity: "com.acme.consign.ConsignPrice",
  name: "ConsignPrice",
  qualifiedName: "com.acme.consign.ConsignPrice",
  operations: ["create-or-update"],
  callSites: 1,
  undetermined: false,
  verbNotRead: false,
}

const undetermined: DataListRow = {
  id: `${UNDETERMINED_ENTITY_KEY}#no-model`,
  key: UNDETERMINED_ENTITY_KEY,
  entity: null,
  name: "entity not determined",
  qualifiedName: null,
  operations: ["delete"],
  callSites: 1,
  undetermined: true,
  verbNotRead: false,
}

const topic: DataListRow = {
  id: "com.acme.notify.Topic#no-model",
  key: "com.acme.notify.Topic",
  entity: "com.acme.notify.Topic",
  name: "Topic",
  qualifiedName: "com.acme.notify.Topic",
  operations: ["unknown"],
  callSites: 1,
  undetermined: false,
  verbNotRead: true,
}

const recordSites: EntitySiteRef[] = [
  {
    nodeId: "n_find",
    call: "ConsignRepository.findById",
    operations: ["read"],
    basis: "method-name",
    file: "src/ConsignServiceImpl.java",
    line: 79,
  },
]

function renderList(
  props: Partial<React.ComponentProps<typeof DataList>> = {}
) {
  const handlers = {
    onSelectEntity: vi.fn(),
    onSelectSite: vi.fn(),
    onRetry: vi.fn(),
  }
  const { container } = render(
    <DataList
      state={{ kind: "populated", rows: [record, price], forwards: [] }}
      selectedEntity={null}
      sitesOf={() => recordSites}
      flowAvailable
      {...handlers}
      {...props}
    />
  )
  return { view: within(container), handlers }
}

describe("Data list", () => {
  test("one type summarized with and without its model id is two rows, keyed apart (C7)", () => {
    // The fold groups by (entity, data_model_id) as the sites wrote them, so
    // one type can arrive twice. Keyed by entity alone, React reused one row
    // for both and warned about the duplicate key.
    const order = "com.acme.order.Order"
    const detail: EndpointDetailView = {
      snapshot_id: "snap_x",
      system_id: "sys_x",
      service_id: "svc_order",
      service_name: "ts-order-service",
      icfg_available: true,
      stitched: true,
      outbound: [],
      endpoint: {
        id: "ep_" + "b".repeat(16),
        snapshot_id: "snap_x",
        service_id: "svc_order",
        http_method: "PUT",
        full_uri: "/orders",
        simplified_uri: "/orders",
        handler: { id: "m_" + "b".repeat(16), signature: "put:void()" },
        entity_access: [
          {
            entity: order,
            data_model_id: "dm_" + "1".repeat(16),
            operations: ["read"],
            call_sites: 1,
            call_sites_by_operation: { read: 1 },
          },
          {
            entity: order,
            data_model_id: null,
            operations: ["create-or-update"],
            call_sites: 1,
            call_sites_by_operation: { "create-or-update": 1 },
          },
        ],
      },
    }
    const state = deriveDataListState({ detail, error: null })
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {})
    try {
      const { view } = renderList({ state })
      expect(view.getAllByRole("button", { name: /^Order/ })).toHaveLength(2)
      const duplicateKeys = consoleError.mock.calls.filter((args) =>
        args.some((arg) => String(arg).includes("same key"))
      )
      expect(duplicateKeys).toEqual([])
    } finally {
      consoleError.mockRestore()
    }
  })

  test("populated: simple name shown, qualified name on hover, chips and call count", () => {
    const { view } = renderList()
    const row = view.getByRole("button", { name: /ConsignRecord/ })
    expect(row).toHaveAttribute("title", "com.acme.consign.ConsignRecord")
    expect(within(row).getByText("read")).toBeInTheDocument()
    expect(within(row).getByText("update")).toBeInTheDocument()
    expect(within(row).getByText("3 calls")).toBeInTheDocument()
  })

  test("create-or-update is ONE chip, never a create chip plus an update chip", () => {
    const { view } = renderList()
    const row = view.getByRole("button", { name: /ConsignPrice/ })
    expect(within(row).getByText("create or update")).toBeInTheDocument()
    expect(within(row).queryByText("create")).toBeNull()
    expect(within(row).queryByText("update")).toBeNull()
    expect(within(row).getByText("1 call")).toBeInTheDocument()
  })

  test("entity not determined: listed by that name, with its verbs", () => {
    const { view } = renderList({
      state: { kind: "populated", rows: [undetermined], forwards: [] },
    })
    const row = view.getByRole("button", { name: /entity not determined/ })
    expect(within(row).getByText("delete")).toBeInTheDocument()
  })

  test("verb not read: the row says so", () => {
    const { view } = renderList({
      state: { kind: "populated", rows: [topic], forwards: [] },
    })
    const row = view.getByRole("button", { name: /Topic/ })
    expect(within(row).getByText("verb not read")).toBeInTheDocument()
  })

  test("selecting a row reports its key; selecting it again clears it", () => {
    const { view, handlers } = renderList()
    fireEvent.click(view.getByRole("button", { name: /ConsignRecord/ }))
    expect(handlers.onSelectEntity).toHaveBeenCalledWith(
      "com.acme.consign.ConsignRecord"
    )
    const selected = renderList({ selectedEntity: record.key })
    const pressed = selected.view.getByRole("button", {
      name: /ConsignRecord/,
      pressed: true,
    })
    fireEvent.click(pressed)
    expect(selected.handlers.onSelectEntity).toHaveBeenCalledWith(null)
  })

  test("the selected row lists its calls, and a call selects its node", () => {
    const { view, handlers } = renderList({ selectedEntity: record.key })
    const call = view.getByRole("button", {
      name: /ConsignRepository\.findById/,
    })
    expect(within(call).getByText("method name")).toBeInTheDocument()
    fireEvent.click(call)
    expect(handlers.onSelectSite).toHaveBeenCalledWith(recordSites[0])
  })

  test("forwards only: no local entities, and where the work goes (Q26)", () => {
    const { view } = renderList({
      state: {
        kind: "forwards-only",
        forwards: [
          {
            key: "edge_1",
            label: "PUT ts-station-service /api/v1/stationservice/stations",
          },
        ],
      },
    })
    expect(view.getByText(/No local entities/)).toBeInTheDocument()
    expect(
      view.getByText("PUT ts-station-service /api/v1/stationservice/stations")
    ).toBeInTheDocument()
  })

  test("no repository call found: says what v1 does not read beside it", () => {
    const { view } = renderList({ state: { kind: "no-repository-call" } })
    expect(view.getByText("No repository call found.")).toBeInTheDocument()
    expect(view.getByText(/Not read:/)).toHaveTextContent(/setters/)
    expect(view.getByText(/Not read:/)).toHaveTextContent(/lambdas/)
    expect(view.getByText(/Not read:/)).toHaveTextContent(/cascades/)
  })

  test("predates: says the snapshot never looked, and nothing that reads as a finding", () => {
    const { view } = renderList({ state: { kind: "predates" } })
    expect(
      view.getByText(/This snapshot predates entity facts/)
    ).toBeInTheDocument()
    expect(view.queryByText(/No repository call/)).toBeNull()
    expect(view.queryByText(/No local entities/)).toBeNull()
    expect(view.queryByText(/Not read:/)).toBeNull()
  })

  test("fetch failed: an error with retry, and no claim", () => {
    const { view, handlers } = renderList({
      state: { kind: "fetch-failed", message: "502: Bad Gateway" },
    })
    expect(view.getByText(/Could not load entity access/)).toHaveTextContent(
      "502: Bad Gateway"
    )
    fireEvent.click(view.getByRole("button", { name: "Retry" }))
    expect(handlers.onRetry).toHaveBeenCalled()
    expect(view.queryByText(/No repository call/)).toBeNull()
    expect(view.queryByText(/predates/)).toBeNull()
  })
})
