// Selecting a Data-list row lights its call sites on the canvas (§5.2.17 UI):
// the ICFG nodes whose `entity_access_sites` hold an access to that entity.
// The canvas lights nodes, not sites, since a statement making two repository
// calls is one place on the canvas. The operations listed are only the ones on
// the SELECTED entity, because a query that deletes Invoice while reading
// Customer does not delete Customer.
import { describe, expect, test } from "vitest"

import type { Icfg } from "@/lib/generated/icfg.schema"
import { entityHighlightNodeIds, entitySites } from "@/lib/wadi/entity-access"
import { UNDETERMINED_ENTITY_KEY } from "@/lib/wadi/routes"

import { flowIcfg } from "./fixtures/flow-fixture"

const PET = "com.acme.pets.Pet"

function withSites(sites: Record<string, unknown[]>): Icfg {
  return {
    ...flowIcfg,
    nodes: flowIcfg.nodes.map((node) =>
      sites[node.id] ? { ...node, entity_access_sites: sites[node.id] } : node
    ),
  } as unknown as Icfg
}

const icfg = withSites({
  "m1:s1": [
    {
      repository: "com.acme.pets.PetRepository",
      method_name: "findById",
      basis: "method-name",
      accesses: [{ entity: PET, data_model_id: null, operation: "read" }],
    },
  ],
  "m1:s2": [
    {
      repository: "com.acme.billing.InvoiceRepository",
      method_name: "purgeForCustomer",
      basis: "query-text",
      accesses: [
        {
          entity: "com.acme.billing.Invoice",
          data_model_id: null,
          operation: "delete",
        },
        {
          entity: "com.acme.billing.Customer",
          data_model_id: null,
          operation: "read",
        },
      ],
    },
  ],
  "m1:r1": [
    {
      repository: "com.acme.pets.PetRepository",
      method_name: "save",
      basis: "argument-origin",
      accesses: [
        {
          entity: PET,
          data_model_id: null,
          operation: "create-or-update",
          candidate_operation: "update",
        },
      ],
    },
  ],
  "m2:s1": [
    {
      repository: "com.acme.misc.LegacyRepository",
      method_name: "save",
      basis: "argument-origin",
      entity_type_text: "T",
      accesses: [
        { entity: null, data_model_id: null, operation: "create-or-update" },
      ],
    },
  ],
})

describe("entity call sites on the ICFG", () => {
  test("every node touching the entity, in flow order, with its call", () => {
    expect(entitySites(icfg, PET)).toEqual([
      {
        nodeId: "m1:s1",
        call: "PetRepository.findById",
        operations: ["read"],
        basis: "method-name",
        file: "src/A.java",
        line: 2,
      },
      {
        nodeId: "m1:r1",
        call: "PetRepository.save",
        operations: ["create-or-update"],
        basis: "argument-origin",
        file: "src/A.java",
        line: 7,
      },
    ])
  })

  test("a two-entity query lists only the selected entity's operation", () => {
    expect(entitySites(icfg, "com.acme.billing.Customer")).toEqual([
      expect.objectContaining({ nodeId: "m1:s2", operations: ["read"] }),
    ])
  })

  test("the undetermined row selects the accesses with no entity", () => {
    expect(
      entitySites(icfg, UNDETERMINED_ENTITY_KEY).map((s) => s.nodeId)
    ).toEqual(["m2:s1"])
  })

  test("an entity this flow never touches selects nothing", () => {
    expect(entitySites(icfg, "com.acme.Nope")).toEqual([])
    // A graph written before 1.26.0 carries no sites at all.
    expect(entitySites(flowIcfg, PET)).toEqual([])
  })
})

describe("which nodes the canvas lights for a selected entity", () => {
  test("in the Data pane: exactly the nodes holding a call on it", () => {
    expect(entityHighlightNodeIds(icfg, "data", PET)).toEqual(
      new Set(["m1:s1", "m1:r1"])
    )
  })

  test("on the call tree, or with no entity selected, nothing overrides the trace", () => {
    expect(entityHighlightNodeIds(icfg, "calls", PET)).toBeNull()
    expect(entityHighlightNodeIds(icfg, "data", null)).toBeNull()
  })

  test("an entity with no call drawn here dims nothing", () => {
    // A stale `entity=` link must not grey out the whole canvas, which would
    // read as "this flow touches nothing".
    expect(entityHighlightNodeIds(icfg, "data", "com.acme.Nope")).toBeNull()
    expect(entityHighlightNodeIds(undefined, "data", PET)).toBeNull()
  })
})
