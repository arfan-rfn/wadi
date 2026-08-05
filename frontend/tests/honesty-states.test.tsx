// The P10 rendering rules, pinned: unknown is a visible state (never a blank,
// never a false), honest terminals render as facts, and the two kinds of
// "no claim" stay apart on screen (§5.2.9).
import { within } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import type { Endpoint } from "@/lib/generated/endpoint.schema"
import { EndpointPeek } from "@/components/home/endpoint-peek"
import { SchemaTree } from "@/components/home/schema-tree"

import { renderWithQuery } from "./utils"

// The peek fetches its detail aggregate; every contract fact under test lives
// on the Endpoint artifact itself, so a pending fetch is the honest stand-in
// and keeps these tests about rendering.
vi.mock("@/lib/wadi/hooks", () => ({
  useEndpointDetail: () => ({ data: undefined, isPending: true }),
}))

function makeEndpoint(overrides: Partial<Endpoint> = {}): Endpoint {
  return {
    id: "ep_" + "a".repeat(16),
    snapshot_id: "snap_x",
    service_id: "svc_" + "a".repeat(16),
    http_method: "GET",
    full_uri: "/pets/{id}",
    simplified_uri: "/pets/{?}",
    handler: { id: "m_" + "a".repeat(16), signature: "getPet:void(String)" },
    ...overrides,
  } as Endpoint
}

function renderPeek(endpoint: Endpoint) {
  return renderWithQuery(
    <EndpointPeek snapshotId="snap_x" endpoint={endpoint} />
  )
}

describe("auth honesty", () => {
  it("renders UNKNOWN as an explicit state, never blank or false", () => {
    const { container } = renderPeek(
      makeEndpoint({ auth: { authenticated: null } })
    )
    const view = within(container)
    expect(view.getByText("No guard found")).toBeInTheDocument()
    expect(
      view.getByText(/Nothing that gates this endpoint was found/i)
    ).toBeInTheDocument()
    expect(view.queryByText("Public")).toBeNull()
  })

  it("renders evidenced-open distinctly from unknown", () => {
    const { container } = renderPeek(
      makeEndpoint({
        auth: {
          authenticated: false,
          evidence: [{ kind: "security-dsl", detail: "permitAll()" }],
        },
      })
    )
    expect(within(container).getByText("Public")).toBeInTheDocument()
  })

  it("distinguishes WITHHELD from unknown and names the unreadable guard", () => {
    // Both leave authenticated=null, but they send a reader to fix different
    // things — one is a gap in wadi, the other a possible hole in the system.
    const { container } = renderPeek(
      makeEndpoint({
        auth: {
          authenticated: null,
          evidence: [
            {
              kind: "interceptor",
              detail: "AuthInterceptor.preHandle",
              resolution: "opaque",
              effect: "unknown",
            },
          ],
        },
      })
    )
    const view = within(container)
    // The two no-claim states must stay apart ON SCREEN, not only in a
    // tooltip: one is a gap in wadi, the other a possible hole in the system.
    expect(view.getByText("Unreadable guard")).toBeInTheDocument()
    expect(view.getByText(/could not be read/i)).toBeInTheDocument()
    expect(view.queryByText("No guard found")).toBeNull()
  })

  it("marks an inert annotation as not in effect rather than dropping it", () => {
    // @Secured under securedEnabled=false enforces nothing. Reporting it as
    // enforcement would fabricate a fact; hiding it would lose the policy the
    // author wrote.
    const { container } = renderPeek(
      makeEndpoint({
        auth: {
          authenticated: false,
          evidence: [
            {
              kind: "annotation",
              detail: '@Secured("ROLE_ADMIN")',
              active: false,
              inactive_reason: "securedEnabled=false",
            },
            { kind: "security-dsl", detail: "permitAll()" },
          ],
        },
      })
    )
    expect(within(container).getByText(/not in effect/i)).toBeInTheDocument()
  })

  it("shows required roles alongside the claim", () => {
    const { container } = renderPeek(
      makeEndpoint({
        auth: {
          authenticated: true,
          roles: ["ADMIN", "USER"],
          evidence: [{ kind: "annotation", detail: "@PreAuthorize" }],
        },
      })
    )
    const view = within(container)
    expect(view.getByText("ADMIN")).toBeInTheDocument()
    expect(view.getByText("USER")).toBeInTheDocument()
    // Roles replace the generic label when they are known — the chip says
    // WHO can call it, not merely that someone must authenticate.
    expect(view.queryByText("Authenticated")).toBeNull()
  })

  it("carries a disabled mechanism as struck through, never as active", () => {
    const { container } = renderPeek(
      makeEndpoint({
        auth: {
          authenticated: true,
          evidence: [{ kind: "security-dsl", detail: 'hasRole("ADMIN")' }],
          mechanisms: [
            { kind: "jwt-bearer", detail: "JwtAuthFilter" },
            {
              kind: "http-basic",
              detail: "httpBasic()",
              active: false,
              inactive_reason: "disabled in chain",
            },
          ],
        },
      })
    )
    const view = within(container)
    expect(view.getByText("jwt-bearer")).toBeInTheDocument()
    expect(view.getByText("http-basic")).toHaveClass("line-through")
  })
})

describe("wire-shape honesty", () => {
  it("renders unresolved types as a named fact, never fabricated fields", () => {
    const { container } = renderWithQuery(
      <SchemaTree
        shape={{ kind: "unresolved", type_name: "com.external.VendorInfo" }}
      />
    )
    const view = within(container)
    expect(view.getByText("VendorInfo")).toBeInTheDocument()
    expect(view.getByText(/not in the analyzed code/i)).toBeInTheDocument()
    // The glyph is dashed, the way every unresolved fact in the UI is.
    expect(
      view.getByRole("img", { name: /type not in the CPG/i })
    ).toBeInTheDocument()
  })

  it("names a cycle instead of expanding it forever", () => {
    const { container } = renderWithQuery(
      <SchemaTree shape={{ kind: "cycle", type_name: "com.acme.Node" }} />
    )
    expect(
      within(container).getByText(/self-referencing type/i)
    ).toBeInTheDocument()
  })

  it("folds a long field list behind an explicit count", () => {
    // A 17-field body must not decide how much of the panel the response gets.
    const fields = Array.from({ length: 12 }, (_, i) => ({
      name: `field${i}`,
      shape: { kind: "scalar" as const, type_name: "String" },
    }))
    const { container } = renderWithQuery(
      <SchemaTree
        shape={{ kind: "object", type_name: "com.acme.Order", fields }}
      />
    )
    const view = within(container)
    expect(view.getByText("field0")).toBeInTheDocument()
    expect(view.queryByText("field11")).toBeNull()
    expect(
      view.getByRole("button", { name: /show 6 more fields/i })
    ).toBeInTheDocument()
  })
})
