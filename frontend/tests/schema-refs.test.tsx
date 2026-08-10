// Shapes travel as a graph since §5.2.16: each type defined once in the
// endpoint's `type_defs`, referenced wherever it occurs, because inline
// expansion of an entity model is exponentially redundant — one real response
// wrote 2,365 object definitions of which 113 were distinct.
//
// A reader that does not resolve refs shows a row naming a type and no fields,
// which looks exactly like a type we failed to recover. These pin that the
// panel resolves, and that it stays honest when it cannot.
import { within } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import type { TypeShape } from "@/lib/generated/endpoint.schema"
import { SchemaTree } from "@/components/home/schema-tree"

import { renderWithQuery } from "./utils"

const SITE: TypeShape = {
  kind: "object",
  type_name: "Site",
  fields: [
    { name: "city", shape: { kind: "scalar", type_name: "String" } },
    { name: "code", shape: { kind: "scalar", type_name: "String" } },
  ],
} as TypeShape

function render(shape: TypeShape, defs?: Record<string, TypeShape>) {
  return within(
    renderWithQuery(<SchemaTree shape={shape} defs={defs} />).container
  )
}

describe("SchemaTree — type references", () => {
  it("renders a referenced type's fields, not just its name", () => {
    const shape = {
      kind: "object",
      type_name: "Contest",
      fields: [{ name: "site", shape: { kind: "ref", type_name: "Site" } }],
    } as TypeShape
    const view = render(shape, { Site: SITE })
    expect(view.getByText("city")).toBeInTheDocument()
    expect(view.getByText("code")).toBeInTheDocument()
  })

  it("resolves the same type everywhere it appears", () => {
    // The whole point of sharing: two uses, one definition, both complete.
    const shape = {
      kind: "object",
      type_name: "Contest",
      fields: [
        { name: "home", shape: { kind: "ref", type_name: "Site" } },
        { name: "away", shape: { kind: "ref", type_name: "Site" } },
      ],
    } as TypeShape
    const view = render(shape, { Site: SITE })
    expect(view.getAllByText("city")).toHaveLength(2)
  })

  it("resolves refs inside collections", () => {
    const shape = {
      kind: "array",
      type_name: "List",
      element: { kind: "ref", type_name: "Site" },
    } as TypeShape
    expect(render(shape, { Site: SITE }).getByText("city")).toBeInTheDocument()
  })

  it("says so when the definition is missing, rather than showing an empty type", () => {
    // P10: an unresolvable ref is a stated gap, not a type with no fields.
    const shape = { kind: "ref", type_name: "Missing" } as TypeShape
    const view = render(shape, {})
    expect(
      view.getByText(/referenced type was not included with this endpoint/)
    ).toBeInTheDocument()
  })

  it("renders pre-1.25.0 inline shapes unchanged, with no definitions at all", () => {
    // Old snapshots carry no refs; passing no `defs` must not change them.
    const view = render(SITE)
    expect(view.getByText("city")).toBeInTheDocument()
  })
})
