// A loading state has to be VISIBLE, and it has to be distinguishable from an
// answer. Both halves regressed at once when the wire shapes moved off the
// list row (§5.2.15): the skeleton was `bg-muted`, a 3% step against the
// `bg-card` panel it sits on, and a collapsed section rendered no body at all
// — so "still fetching" and "fetched, and there is nothing here" looked the
// same. These pin the affordance, not the styling: the assertion is that a
// reader is told, in text, which sections are still coming.
import { fireEvent, within } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import type { Endpoint } from "@/lib/generated/endpoint.schema"
import { EndpointPeek } from "@/components/home/endpoint-peek"
import { CollapsibleSection } from "@/components/shared/collapsible-section"

import { renderWithQuery } from "./utils"

const detailState = vi.hoisted(() => ({
  current: {
    data: undefined,
    isPending: true,
    isError: false,
    refetch: () => {},
  } as {
    data: undefined
    isPending: boolean
    isError: boolean
    refetch: () => void
  },
}))

vi.mock("@/lib/wadi/hooks", () => ({
  useEndpointDetail: () => detailState.current,
}))

beforeEach(() => {
  detailState.current = {
    data: undefined,
    isPending: true,
    isError: false,
    refetch: () => {},
  }
})

function makeEndpoint(): Endpoint {
  return {
    id: "ep_" + "a".repeat(16),
    snapshot_id: "snap_x",
    service_id: "svc_" + "a".repeat(16),
    http_method: "POST",
    full_uri: "/pets",
    simplified_uri: "/pets",
    handler: { id: "m_" + "a".repeat(16), signature: "create:void(Pet)" },
  } as Endpoint
}

describe("CollapsibleSection — the pending affordance", () => {
  it("says it is loading, in words, not only by animation", () => {
    const view = within(
      renderWithQuery(
        <CollapsibleSection title="Response" pending>
          <p>body</p>
        </CollapsibleSection>
      ).container
    )
    expect(view.getByText("loading")).toBeInTheDocument()
  })

  it("keeps the signal in the HEADER, so a collapsed section still shows it", () => {
    // The regression this exists for: the body is the one thing a closed
    // section does not render, so a body-only skeleton made a loading section
    // indistinguishable from a finished empty one.
    const view = within(
      renderWithQuery(
        <CollapsibleSection title="Response" pending defaultOpen={false}>
          <p>body</p>
        </CollapsibleSection>
      ).container
    )
    expect(view.getByText("loading")).toBeInTheDocument()
    expect(view.queryByText("body")).not.toBeVisible()
  })

  it("does not show a count while pending — the count is not known yet", () => {
    // They share the header slot on purpose. A count rendered beside a spinner
    // would be a number nobody computed.
    const view = within(
      renderWithQuery(
        <CollapsibleSection title="Response" count={7} pending>
          <p>body</p>
        </CollapsibleSection>
      ).container
    )
    expect(view.queryByText("7")).toBeNull()
    expect(view.getByText("loading")).toBeInTheDocument()
  })

  it("shows the count once it is known, and drops the indicator", () => {
    const view = within(
      renderWithQuery(
        <CollapsibleSection title="Response" count={7}>
          <p>body</p>
        </CollapsibleSection>
      ).container
    )
    expect(view.getByText("7")).toBeInTheDocument()
    expect(view.queryByText("loading")).toBeNull()
  })

  it("marks the body busy for assistive tech", () => {
    const { container } = renderWithQuery(
      <CollapsibleSection title="Response" pending>
        <p>body</p>
      </CollapsibleSection>
    )
    expect(container.querySelector("[aria-busy='true']")).not.toBeNull()
  })
})

describe("endpoint peek — a pending contract is never stated as a result", () => {
  it("shows the sections as loading rather than claiming their content", () => {
    // "No request body on this endpoint" and "Response shape unknown" are
    // claims about the analysis. They were safe while the shapes rode in on
    // the list row, because they were always present by render time; they now
    // arrive with a fetch, so asserting either one early describes an endpoint
    // that has not been read yet (P10).
    const view = within(
      renderWithQuery(
        <EndpointPeek snapshotId="snap_x" endpoint={makeEndpoint()} />
      ).container
    )
    expect(view.queryByText(/No request body on this endpoint/)).toBeNull()
    expect(view.queryByText(/Response shape unknown/)).toBeNull()
    // Every section fed by that one fetch says so for itself, because they sit
    // at different scroll positions and a reader sees whichever is on screen.
    expect(view.getAllByText("loading").length).toBeGreaterThanOrEqual(3)
  })
})

describe("endpoint peek — a failed contract fetch is not an empty one", () => {
  it("says the fetch failed instead of claiming there is no request body", () => {
    // The defect this exists for: `isPending` false and no data fell straight
    // through to the empty-result copy, so a request that never completed
    // rendered as a finding about the endpoint. Hit for real when the detail
    // route could not reach Neo4j — a spinner through the retry backoff, then
    // a confident, wrong answer.
    detailState.current = {
      data: undefined,
      isPending: false,
      isError: true,
      refetch: () => {},
    }
    const view = within(
      renderWithQuery(
        <EndpointPeek snapshotId="snap_x" endpoint={makeEndpoint()} />
      ).container
    )
    expect(view.queryByText(/No request body on this endpoint/)).toBeNull()
    expect(view.queryByText(/Response shape unknown/)).toBeNull()
    expect(
      view.getAllByText(/nothing here is a result/).length
    ).toBeGreaterThan(0)
  })

  it("offers a retry, because one fetch backs three sections", () => {
    let retries = 0
    detailState.current = {
      data: undefined,
      isPending: false,
      isError: true,
      refetch: () => {
        retries += 1
      },
    }
    const view = within(
      renderWithQuery(
        <EndpointPeek snapshotId="snap_x" endpoint={makeEndpoint()} />
      ).container
    )
    fireEvent.click(view.getAllByRole("button", { name: "Retry" })[0])
    expect(retries).toBe(1)
  })

  it("shows loading, not the failure, while the fetch is still in flight", () => {
    const view = within(
      renderWithQuery(
        <EndpointPeek snapshotId="snap_x" endpoint={makeEndpoint()} />
      ).container
    )
    expect(view.queryByText(/nothing here is a result/)).toBeNull()
    expect(view.getAllByText("loading").length).toBeGreaterThanOrEqual(3)
  })
})
