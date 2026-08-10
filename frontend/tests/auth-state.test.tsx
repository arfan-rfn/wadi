// The §5.2.9 claim states, pinned at the two places a reader meets them: the
// pure classifier every surface derives from, and the row chip that is the
// first thing anyone sees about an endpoint.
//
// The load-bearing case throughout is `withheld` vs `unknown`. Both are
// `authenticated: null`, and both mean "no claim" — but one is a gap in wadi
// (a guard was found and could not be read, so the endpoint may well be
// protected) and the other is a possible hole in the system (nothing that
// could gate it was found at all). Collapsing them sends a reader to fix the
// wrong thing, so every layer keeps them apart and every layer is tested for it.
import { within } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import type { EndpointDependency } from "@/lib/generated/endpoint_dependencies.schema"
import { AccessChip, DependencyChip } from "@/components/home/endpoint-meta"
import {
  authStateOf,
  unreadLabel,
  withheldReason,
} from "@/components/shared/auth-chip"

import { renderWithQuery } from "./utils"

describe("authStateOf — the five claim states", () => {
  it("reads a positive claim as required, whatever else was found", () => {
    // An unread guard can only ADD restriction, so it never unseats a `true`.
    expect(authStateOf(true, [])).toBe("required")
    expect(authStateOf(true, ["interceptor"])).toBe("required")
  })

  it("splits a denial out of the positive claim", () => {
    // denyAll() admits nobody: unreachable, not protected. Same
    // `authenticated: true` underneath, different answer for a reader.
    expect(authStateOf(true, [], true)).toBe("denied")
    expect(authStateOf(true, [], false)).toBe("required")
    expect(authStateOf(true, [])).toBe("required")
  })

  it("reads an evidenced negative as open", () => {
    expect(authStateOf(false, [])).toBe("open")
  })

  it("splits no-claim by whether a guard was actually seen", () => {
    expect(authStateOf(null, ["security-dsl"])).toBe("withheld")
    expect(authStateOf(null, [])).toBe("unknown")
  })

  it("treats absent fields as no-evidence rather than guessing", () => {
    // An older artifact with no `auth` block must not read as "public" (P10).
    expect(authStateOf(undefined, undefined)).toBe("unknown")
    expect(authStateOf(null, undefined)).toBe("unknown")
  })
})

describe("unreadLabel", () => {
  it("names each detectable guard in plain language", () => {
    expect(unreadLabel("security-dsl")).toBe("a security rule")
    expect(unreadLabel("in-handler")).toBe("a check inside the handler")
    expect(unreadLabel("chain-bypass")).toBe("a security-chain bypass")
  })

  it("falls back to the raw kind rather than dropping an unknown one", () => {
    // A kind added to the contract before the UI knows about it must still
    // reach the reader — silently omitting it would understate the guard set.
    expect(unreadLabel("future-kind")).toBe("future-kind")
  })
})

describe("withheldReason", () => {
  it("reads as a sentence for one, two, and three guards", () => {
    expect(withheldReason(["aspect"])).toMatch(
      /^an aspect guards this endpoint/
    )
    expect(withheldReason(["aspect", "interceptor"])).toMatch(
      /^an aspect and a request interceptor guards/
    )
    expect(withheldReason(["aspect", "interceptor", "gateway"])).toMatch(
      /^an aspect, a request interceptor and a gateway rule guards/
    )
  })

  it("never renders an empty subject", () => {
    // Defensive: the caller only reaches this with a non-empty list today, but
    // a bare "guards this endpoint" would be a broken sentence on screen.
    expect(withheldReason([])).toMatch(/^something guards this endpoint/)
  })

  it("always says no claim is made either way", () => {
    expect(withheldReason(["security-dsl"])).toMatch(
      /no claim is made either way/
    )
  })
})

describe("AccessChip — the endpoint row's one auth fact", () => {
  const renderChip = (
    state: Parameters<typeof AccessChip>[0]["state"],
    roles: string[] = []
  ) =>
    within(
      renderWithQuery(<AccessChip state={state} roles={roles} />).container
    )

  it("names the roles instead of the generic label when they are known", () => {
    const view = renderChip("required", ["ADMIN", "USER"])
    expect(view.getByText("ADMIN")).toBeInTheDocument()
    expect(view.getByText("USER")).toBeInTheDocument()
    // The chip answers WHO can call this, not merely that someone must log in.
    expect(view.queryByText("Authenticated")).toBeNull()
  })

  it("names the RELATION when the policy is relational, not a bare label", () => {
    // §5.2.12. `authenticated: true` with an empty role list used to render as
    // "Authenticated", which reads as "any logged-in caller" — on ICPC that
    // was 562 of 804 endpoints, and it is the misreading this tranche removes.
    const view = within(
      renderWithQuery(
        <AccessChip
          state="required"
          roles={[]}
          relationships={[
            { relation: "contest-manager", resource_type: "Contest" },
          ]}
        />
      ).container
    )
    expect(view.getByText("contest-manager")).toBeInTheDocument()
    expect(view.getByText("·Contest")).toBeInTheDocument()
    expect(view.queryByText("Authenticated")).toBeNull()
  })

  it("keeps a relation legible when the resource could not be claimed", () => {
    // Two Class-valued arguments leave the resource ambiguous, and the pack
    // declines to guess (P10). The relation is still a policy worth showing.
    const view = within(
      renderWithQuery(
        <AccessChip
          state="required"
          roles={[]}
          relationships={[{ relation: "owner" }]}
        />
      ).container
    )
    expect(view.getByText("owner")).toBeInTheDocument()
    expect(view.queryByText("Authenticated")).toBeNull()
  })

  it("shows one chip when two guards differ only in fields it never renders", () => {
    // A class-level `@ContestManager` beside a method-level
    // `@ContestManager(acl = ...)` are two records by design — `authorities`
    // are conjunctive, and the contract keeps them apart so the conjunction
    // survives (§5.2.12). But the chip renders `relation` + `resource_type`
    // and nothing else, so both painted the identical string twice and
    // collided on the React key. 60 of ICPC's 804 endpoints hit this.
    const view = within(
      renderWithQuery(
        <AccessChip
          state="required"
          roles={[]}
          relationships={[
            {
              relation: "contest-manager",
              resource_type: "Contest",
              authorities: ["CONTEST_GRANT_PERMISSIONS"],
            },
            {
              relation: "contest-manager",
              resource_type: "Contest",
              authorities: [],
            },
          ]}
        />
      ).container
    )
    expect(view.getAllByText("contest-manager")).toHaveLength(1)
    expect(view.getAllByText("·Contest")).toHaveLength(1)
  })

  it("keeps relations that differ in what it DOES render", () => {
    // The dedupe must key on the rendered pair, not collapse to one chip: a
    // second relation, or the same relation on another resource, is a
    // different policy and has to stay visible.
    const view = within(
      renderWithQuery(
        <AccessChip
          state="required"
          roles={[]}
          relationships={[
            { relation: "contest-manager", resource_type: "Contest" },
            { relation: "contest-manager", resource_type: "Problem" },
            { relation: "owner", resource_type: "Contest" },
          ]}
        />
      ).container
    )
    expect(view.getAllByText("contest-manager")).toHaveLength(2)
    expect(view.getByText("owner")).toBeInTheDocument()
    expect(view.getByText("·Problem")).toBeInTheDocument()
  })

  it("labels a relational endpoint for assistive tech, not only visually", () => {
    const view = within(
      renderWithQuery(
        <AccessChip
          state="required"
          roles={[]}
          relationships={[
            { relation: "contest-manager", resource_type: "Contest" },
          ]}
        />
      ).container
    )
    expect(
      view.getByLabelText(/contest-manager on Contest/)
    ).toBeInTheDocument()
  })

  it("falls back to the state label when the roles are not known", () => {
    expect(
      renderChip("required").getByText("Authenticated")
    ).toBeInTheDocument()
    expect(renderChip("open").getByText("Public")).toBeInTheDocument()
  })

  it("names a denied route as unreachable, not as protected", () => {
    // The failure this prevents: an auditor counting dead surface as live.
    const view = renderChip("denied", ["ADMIN"])
    expect(view.getByText("Denied to all")).toBeInTheDocument()
    expect(view.queryByText("Authenticated")).toBeNull()
    expect(view.queryByText("ADMIN")).toBeNull()
  })

  it("keeps the two no-claim states apart in the visible label", () => {
    // Not in a tooltip — on screen. This is the §5.2.9 distinction and it must
    // survive at the densest surface in the app.
    expect(
      renderChip("withheld").getByText("Unreadable guard")
    ).toBeInTheDocument()
    expect(
      renderChip("unknown").getByText("No guard found")
    ).toBeInTheDocument()
  })

  it("ignores roles on a state that makes no claim", () => {
    // Roles alongside "no claim" would read as a claim about who can call it.
    const view = renderChip("withheld", ["ADMIN"])
    expect(view.getByText("Unreadable guard")).toBeInTheDocument()
    expect(view.queryByText("ADMIN")).toBeNull()
  })

  it("carries an accessible name that includes the roles", () => {
    const view = renderChip("required", ["ADMIN"])
    expect(
      view.getByLabelText(/Authentication required: ADMIN/)
    ).toBeInTheDocument()
  })

  it("shows authorities beside roles, and keeps them apart in the tooltip", () => {
    // `hasRole("X")` and `hasAuthority("X")` match different grants in Spring,
    // so the chip lists both but never calls an authority a role.
    const { container } = renderWithQuery(
      <AccessChip
        state="required"
        roles={["ADMIN"]}
        authorities={["ORDER_DELETE"]}
      />
    )
    const view = within(container)
    expect(view.getByText("ADMIN")).toBeInTheDocument()
    expect(view.getByText("ORDER_DELETE")).toBeInTheDocument()
    expect(
      view.getByLabelText(/Authentication required: ADMIN, ORDER_DELETE/)
    ).toBeInTheDocument()
  })

  it("shows a name once when it is both a role and an authority", () => {
    // One rule can require the ROLE ADMIN while another requires the
    // AUTHORITY ADMIN. Rendering it twice reads as two grants.
    const { container } = renderWithQuery(
      <AccessChip state="required" roles={["ADMIN"]} authorities={["ADMIN"]} />
    )
    expect(within(container).getAllByText("ADMIN")).toHaveLength(1)
  })

  it("names the authority alone when no role is required", () => {
    const { container } = renderWithQuery(
      <AccessChip state="required" roles={[]} authorities={["ORDER_DELETE"]} />
    )
    const view = within(container)
    expect(view.getByText("ORDER_DELETE")).toBeInTheDocument()
    expect(view.queryByText("Authenticated")).toBeNull()
  })
})

describe("DependencyChip — cross-service calls, spelled out", () => {
  const dependency = (label: string): EndpointDependency =>
    ({
      label,
      target_kind: "analyzed",
      confidence: "high",
    }) as EndpointDependency

  it("renders nothing when the endpoint reaches no other service", () => {
    // A "0 services" chip is noise on every leaf endpoint in the system.
    const { container } = renderWithQuery(<DependencyChip dependencies={[]} />)
    expect(container).toBeEmptyDOMElement()
  })

  it("spells the count out, and agrees in number", () => {
    const one = renderWithQuery(
      <DependencyChip dependencies={[dependency("ts-config-service")]} />
    )
    expect(within(one.container).getByText("1 service")).toBeInTheDocument()

    const two = renderWithQuery(
      <DependencyChip
        dependencies={[
          dependency("ts-config-service"),
          dependency("ts-order-service"),
        ]}
      />
    )
    expect(within(two.container).getByText("2 services")).toBeInTheDocument()
  })
})
