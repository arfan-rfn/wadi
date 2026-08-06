// Honesty surfaces that used to stop at the API (§5.2.10, §7).
//
// Each of these was already computed, stored and served — and rendered
// nowhere, which is the same as not having it: a blind-spot counter nobody
// can see does not make a blind spot visible. The three differ in what they
// mean, and the tests pin that difference rather than mere presence:
//
//   * endpoint collisions report data the analysis found and then LOST;
//   * unread guards report enforcement it saw and could not interpret;
//   * extraction gaps report enforcement it appears to have missed entirely.
import { within } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import type { CoverageReport } from "@/lib/generated/coverage_report.schema"
import { CoveragePane } from "@/components/coverage/coverage-pane"

import { renderWithQuery } from "./utils"

const mockCoverage = vi.hoisted(() => ({ current: undefined as unknown }))

vi.mock("@/lib/wadi/hooks", () => ({
  useCoverage: () => ({
    data: mockCoverage.current,
    isLoading: false,
    isError: false,
  }),
}))

// SourceSnippet fetches; the facts under test are all on the report itself.
vi.mock("@/components/source/source-viewer", () => ({
  SourceSnippet: () => null,
}))

function makeReport(overrides: Partial<CoverageReport> = {}): CoverageReport {
  return {
    schema_version: "1.18.0",
    snapshot_id: "snap_x",
    created_at: "2026-08-05T00:00:00Z",
    totals: {
      edges: 0,
      analyzed: 0,
      external: 0,
      placeholder: 0,
      undetermined: 0,
      by_confidence: {},
    },
    ...overrides,
  } as CoverageReport
}

function renderPane(report: CoverageReport) {
  mockCoverage.current = report
  return renderWithQuery(<CoveragePane snapshotId="snap_x" />)
}

describe("endpoint collisions (§7)", () => {
  it("names the handlers that were dropped, not just the count", () => {
    // The loss happens at the storage key, downstream of every other counter,
    // so a number alone would leave a reader with nowhere to look.
    const { container } = renderPane(
      makeReport({
        endpoint_collisions: [
          {
            endpoint_id: "ep_" + "a".repeat(16),
            http_method: "GET",
            uri: "/search",
            kept_handler: "PersonController.search:void()",
            dropped_handlers: ["TeamController.search:void()"],
          },
        ],
      })
    )
    const view = within(container)
    expect(view.getByText(/could not all be stored/i)).toBeInTheDocument()
    expect(view.getByText(/TeamController.search/)).toBeInTheDocument()
    expect(view.getByText(/PersonController.search/)).toBeInTheDocument()
    // It must read as loss, not as an unknown — everything else on this page
    // is "we could not read X", and conflating them sends a reader to fix the
    // wrong thing.
    expect(view.getByText(/missing from the inventory/i)).toBeInTheDocument()
  })

  it("stays silent when nothing collided", () => {
    const { container } = renderPane(makeReport({ endpoint_collisions: [] }))
    expect(within(container).queryByText(/could not all be stored/i)).toBeNull()
  })
})

describe("unread guards, system-wide", () => {
  it("rolls the per-endpoint kinds up into one readable count", () => {
    // Previously only reachable endpoint by endpoint, so "this system has 40
    // unreadable interceptors" was undiscoverable.
    const { container } = renderPane(
      makeReport({
        auth_coverage: {
          endpoints: 100,
          authenticated: 60,
          unauthenticated: 30,
          withheld: 10,
          no_evidence: 0,
          unread_by_kind: { "security-dsl": 7, interceptor: 3 },
        },
      })
    )
    const view = within(container)
    expect(view.getByText(/7 a security rule/)).toBeInTheDocument()
    expect(view.getByText(/3 a request interceptor/)).toBeInTheDocument()
  })
})

describe("extraction gaps — the only counter that reports a miss", () => {
  it("explains gap codes in words and keeps them apart from unknowns", () => {
    const { container } = renderPane(
      makeReport({
        auth_coverage: {
          endpoints: 10,
          authenticated: 10,
          unauthenticated: 0,
          withheld: 0,
          no_evidence: 0,
          extraction_gaps: { "unemitted-access-site": 4 },
        },
      })
    )
    const view = within(container)
    expect(
      view.getByText(/access rules named in a security config/i)
    ).toBeInTheDocument()
    // The distinction that makes this section worth having at all.
    expect(
      view.getByText(/reports a miss rather than an unknown/i)
    ).toBeInTheDocument()
  })

  it("stays silent when the oracle found nothing", () => {
    const { container } = renderPane(
      makeReport({
        auth_coverage: {
          endpoints: 10,
          authenticated: 10,
          unauthenticated: 0,
          withheld: 0,
          no_evidence: 0,
          extraction_gaps: {},
        },
      })
    )
    expect(
      within(container).queryByText(/the source names but the map lacks/i)
    ).toBeNull()
  })
})
