// The system auth view (§5.2.9): "which endpoints here are unprotected?" as one
// screen. The filter is the whole point of the pane — a reader arrives asking
// one of five questions, and picking the wrong bucket for a row answers the
// wrong one. `withheld` and `unknown` are separate filters for the same reason
// they carry separate words everywhere else: one is a gap in wadi, the other a
// possible hole in the system.
import { fireEvent, within } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import type { SystemAuthView } from "@/lib/generated/system_auth.schema"
import { AuthPane } from "@/components/home/auth-pane"

import { renderWithQuery } from "./utils"

const view = {
  totals: {
    endpoints: 6,
    authenticated: 2,
    denied: 1,
    unauthenticated: 1,
    withheld: 1,
    no_evidence: 1,
  },
  rows: [
    {
      endpoint_id: "ep_protected",
      service_id: "svc_a",
      service_name: "ts-order-service",
      http_method: "POST",
      full_uri: "/api/v1/orderservice/order",
      authenticated: true,
      roles: ["ADMIN"],
      mechanism_kinds: ["jwt-bearer"],
      unread_kinds: [],
    },
    {
      endpoint_id: "ep_relational",
      service_id: "svc_a",
      service_name: "ts-order-service",
      http_method: "POST",
      full_uri: "/contest/{contestId}/camp/create",
      authenticated: true,
      roles: [],
      authorities: ["CONTEST_CREATE_SUBCONTEST"],
      relationships: [
        {
          relation: "contest-manager",
          resource_type: "Contest",
          authorities: ["CONTEST_CREATE_SUBCONTEST"],
        },
        { relation: "site-manager", resource_type: "Site", authorities: [] },
      ],
      composition_unresolved: true,
      mechanism_kinds: [],
      unread_kinds: [],
    },
    {
      endpoint_id: "ep_open",
      service_id: "svc_a",
      service_name: "ts-order-service",
      http_method: "GET",
      full_uri: "/api/v1/orderservice/welcome",
      authenticated: false,
      roles: [],
      mechanism_kinds: [],
      unread_kinds: [],
    },
    {
      endpoint_id: "ep_withheld",
      service_id: "svc_b",
      service_name: "ts-travel-service",
      http_method: "DELETE",
      full_uri: "/api/v1/travelservice/trips/{tripId}",
      authenticated: null,
      roles: [],
      mechanism_kinds: [],
      unread_kinds: ["interceptor"],
    },
    {
      endpoint_id: "ep_denied",
      service_id: "svc_a",
      service_name: "ts-order-service",
      http_method: "DELETE",
      full_uri: "/api/v1/orderservice/legacy",
      authenticated: true,
      denied: true,
      roles: [],
      mechanism_kinds: [],
      unread_kinds: [],
    },
    {
      endpoint_id: "ep_unknown",
      service_id: "svc_b",
      service_name: "ts-travel-service",
      http_method: "GET",
      full_uri: "/api/v1/travelservice/trips",
      authenticated: null,
      roles: [],
      mechanism_kinds: [],
      unread_kinds: [],
    },
  ],
} as unknown as SystemAuthView

vi.mock("@/lib/wadi/hooks", () => ({
  useSystemAuth: () => ({ data: view, isPending: false, isError: false }),
}))

function renderPane() {
  const { container } = renderWithQuery(<AuthPane snapshotId="snap_x" active />)
  return { view: within(container), container }
}

/** The headline counts, read as {label: value}. Queried structurally because
 *  the words are deliberately repeated — "unprotected" and "withheld" are also
 *  a filter button and a sentence in the explainer, and that repetition is what
 *  ties the three together for the reader. */
function statsOf(container: HTMLElement): Record<string, string> {
  const values = container.querySelectorAll<HTMLElement>("[class~='text-2xl']")
  return Object.fromEntries(
    Array.from(values, (value) => [
      value.nextElementSibling?.textContent ?? "",
      value.textContent ?? "",
    ])
  )
}

const uris = (v: ReturnType<typeof renderPane>["view"]) =>
  v
    .getAllByRole("link")
    .map((link) => link.textContent ?? "")
    .join(" | ")

describe("AuthPane", () => {
  it("shows every endpoint, grouped by service, before any filter", () => {
    const { view: v } = renderPane()
    expect(v.getAllByRole("link")).toHaveLength(6)
    expect(v.getByText("ts-order-service")).toBeInTheDocument()
    expect(v.getByText("ts-travel-service")).toBeInTheDocument()
  })

  it("reports the totals it was given rather than recomputing them", () => {
    // The totals come from the contract's partition-validated aggregate; the
    // pane must not quietly disagree with the API it is displaying.
    const { container } = renderPane()
    expect(statsOf(container)).toEqual({
      endpoints: "6",
      protected: "2",
      unprotected: "1",
      denied: "1",
      withheld: "1",
      "no evidence": "1",
    })
  })

  it("filters to the evidenced-open endpoints", () => {
    const { view: v } = renderPane()
    fireEvent.click(v.getByRole("button", { name: "unprotected" }))
    expect(uris(v)).toContain("/api/v1/orderservice/welcome")
    expect(uris(v)).not.toContain("/api/v1/orderservice/order")
  })

  it("keeps withheld and no-evidence in SEPARATE buckets", () => {
    // Both rows are `authenticated: null`. Pooling them would make the honest
    // state meaningless — the two call for opposite responses.
    const { view: v } = renderPane()

    fireEvent.click(v.getByRole("button", { name: "withheld" }))
    expect(uris(v)).toContain("/api/v1/travelservice/trips/{tripId}")
    expect(uris(v)).not.toContain("/api/v1/travelservice/trips ")
    expect(v.getAllByRole("link")).toHaveLength(1)

    fireEvent.click(v.getByRole("button", { name: "no evidence" }))
    expect(v.getAllByRole("link")).toHaveLength(1)
    expect(uris(v)).toContain("/api/v1/travelservice/trips")
    expect(uris(v)).not.toContain("{tripId}")
  })

  it("filters denied apart from protected — dead surface is not live surface", () => {
    const { view: v } = renderPane()
    fireEvent.click(v.getByRole("button", { name: "denied" }))
    expect(v.getAllByRole("link")).toHaveLength(1)
    expect(uris(v)).toContain("/api/v1/orderservice/legacy")

    fireEvent.click(v.getByRole("button", { name: "protected" }))
    expect(uris(v)).not.toContain("/api/v1/orderservice/legacy")
  })

  it("filters to the protected endpoints and keeps their roles", () => {
    const { view: v } = renderPane()
    fireEvent.click(v.getByRole("button", { name: "protected" }))
    expect(v.getAllByRole("link")).toHaveLength(2)
    expect(v.getByText("ADMIN")).toBeInTheDocument()
    expect(v.getByText("jwt-bearer")).toBeInTheDocument()
  })

  it("marks the active filter for assistive tech, not only by colour", () => {
    const { view: v } = renderPane()
    const unprotected = v.getByRole("button", { name: "unprotected" })
    expect(unprotected).toHaveAttribute("aria-pressed", "false")
    fireEvent.click(unprotected)
    expect(unprotected).toHaveAttribute("aria-pressed", "true")
    expect(v.getByRole("button", { name: "all" })).toHaveAttribute(
      "aria-pressed",
      "false"
    )
  })

  it("names the RELATION on a relationally-guarded row, not a bare 'protected'", () => {
    // §5.2.12. This row is `authenticated: true` with an empty role list, and
    // without the relation it renders identically to an endpoint any logged-in
    // caller may hit. On ICPC that shape is 562 of 804 rows — the exact
    // misreading the tranche exists to remove.
    const { view: v } = renderPane()
    fireEvent.click(v.getByRole("button", { name: "protected" }))
    expect(v.getByText("contest-manager")).toBeInTheDocument()
    expect(v.getByText("site-manager")).toBeInTheDocument()
    // The resource it is required ON — a relation with no object is half a fact.
    expect(v.getByText("·Contest")).toBeInTheDocument()
    expect(v.getByText("·Site")).toBeInTheDocument()
  })

  it("says when several guards apply and their combination was not read", () => {
    // Two relations are listed; whether the caller needs BOTH or EITHER is
    // unread. Rendering them silently would overstate what a caller must have,
    // and an over-restrictive answer is still a wrong one.
    const { view: v } = renderPane()
    fireEvent.click(v.getByRole("button", { name: "protected" }))
    expect(v.getByText("combination unread")).toBeInTheDocument()
  })

  it("keeps a role-guarded row free of relationship chrome", () => {
    // The counterweight: the ADMIN row has no relationships, so it must not
    // grow a combination warning or an empty relation chip.
    const { view: v } = renderPane()
    fireEvent.click(v.getByRole("button", { name: "protected" }))
    const adminRow = v.getByText("ADMIN").closest("a")
    expect(adminRow).not.toBeNull()
    expect(
      within(adminRow as HTMLElement).queryByText("combination unread")
    ).toBeNull()
  })
})
