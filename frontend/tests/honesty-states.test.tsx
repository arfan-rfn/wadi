// The P10 rendering rules, pinned: unknown is a visible state (never a blank,
// never a false), and honest terminals render as facts.
import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import type { Endpoint } from "@/lib/generated/endpoint.schema"
// AuthSection is internal to endpoint-overview; test through the overview
// with the minimum viable endpoint + no icfg/edges (loading-free path).
import { EndpointOverview } from "@/components/explorer/endpoint-overview"
import { ShapeTree } from "@/components/explorer/shape-tree"

function makeEndpoint(overrides: Partial<Endpoint> = {}): Endpoint {
  return {
    id: "ep_" + "a".repeat(16),
    snapshot_id: "snap_x",
    service_id: "svc_" + "a".repeat(16),
    http_method: "GET",
    full_uri: "/pets/{id}",
    simplified_uri: "/pets/{?}",
    handler: { id: "m_" + "a".repeat(16), signature: "getPet(String)" },
    ...overrides,
  } as Endpoint
}

describe("auth honesty", () => {
  it("renders UNKNOWN as an explicit state, never blank or false", () => {
    render(
      <EndpointOverview
        endpoint={makeEndpoint({ auth: { authenticated: null } })}
        icfg={undefined}
        remoteEdges={undefined}
        edgesLoading={false}
        snapshotId="snap_x"
        serviceId="svc_x"
      />
    )
    expect(
      screen.getByText(/unknown — analysis found no auth evidence/i)
    ).toBeInTheDocument()
    expect(screen.queryByText(/no authentication \(evidenced\)/i)).toBeNull()
  })

  it("renders evidenced-open distinctly from unknown", () => {
    render(
      <EndpointOverview
        endpoint={makeEndpoint({
          auth: {
            authenticated: false,
            evidence: [{ kind: "security-dsl", detail: "permitAll()" }],
          },
        })}
        icfg={undefined}
        remoteEdges={undefined}
        edgesLoading={false}
        snapshotId="snap_x"
        serviceId="svc_x"
      />
    )
    expect(
      screen.getByText(/no authentication \(evidenced\)/i)
    ).toBeInTheDocument()
  })

  it("shows required roles as chips", () => {
    render(
      <EndpointOverview
        endpoint={makeEndpoint({
          auth: {
            authenticated: true,
            roles: ["ADMIN"],
            evidence: [{ kind: "annotation", detail: "@PreAuthorize" }],
          },
        })}
        icfg={undefined}
        remoteEdges={undefined}
        edgesLoading={false}
        snapshotId="snap_x"
        serviceId="svc_x"
      />
    )
    expect(screen.getByText("ADMIN")).toBeInTheDocument()
    expect(screen.getByText(/authentication required/i)).toBeInTheDocument()
  })
})

describe("wire-shape honesty", () => {
  it("renders unresolved types as a named fact, never fabricated fields", () => {
    render(
      <ShapeTree
        shape={{ kind: "unresolved", type_name: "com.external.VendorInfo" }}
      />
    )
    expect(
      screen.getByText(/VendorInfo — unresolved \(outside the analyzed code\)/)
    ).toBeInTheDocument()
  })

  it("renders cycles as explicit recursive references", () => {
    render(
      <ShapeTree
        shape={{
          kind: "object",
          type_name: "Category",
          fields: [
            {
              name: "children",
              shape: {
                kind: "array",
                type_name: "List",
                element: { kind: "cycle", type_name: "Category" },
              },
            },
          ],
        }}
      />
    )
    expect(
      screen.getByText(/Category — recursive reference/)
    ).toBeInTheDocument()
  })

  it("keeps Jackson wire names primary with the java name as a footnote", () => {
    render(
      <ShapeTree
        shape={{
          kind: "object",
          type_name: "PetDetails",
          fields: [
            {
              name: "display_name",
              java_name: "name",
              shape: { kind: "scalar", type_name: "String" },
            },
          ],
        }}
      />
    )
    expect(screen.getByText("display_name")).toBeInTheDocument()
    expect(screen.getByText(/java: name/)).toBeInTheDocument()
  })
})
