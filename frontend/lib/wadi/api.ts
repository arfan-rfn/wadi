// Thin typed fetch layer over the orchestrator REST API (§14).
// Types come from the generated contract schemas — never hand-written (§7).

import type { CoverageReport } from "@/lib/generated/coverage_report.schema"
import type { EndpointDetailView } from "@/lib/generated/endpoint_detail.schema"
import type { Endpoint } from "@/lib/generated/endpoint.schema"
import type { Icfg } from "@/lib/generated/icfg.schema"
import type { RemoteEdgesView } from "@/lib/generated/remote_edges_view.schema"
import type { ServiceSummary } from "@/lib/generated/service_summary.schema"
import type { Snapshot } from "@/lib/generated/snapshot.schema"
import type { SourceView } from "@/lib/generated/source_view.schema"
import type { SystemGraphView } from "@/lib/generated/system_graph.schema"
import type { System } from "@/lib/generated/system.schema"

async function get<T>(path: string): Promise<T> {
  const response = await fetch(path, { cache: "no-store" })
  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = (await response.json()) as { detail?: string }
      if (body.detail) detail = body.detail
    } catch {
      // non-JSON error body — keep statusText
    }
    throw new Error(`${response.status}: ${detail}`)
  }
  return (await response.json()) as T
}

export const wadiApi = {
  systems: () => get<System[]>("/api/v1/systems"),
  snapshots: (systemId: string) =>
    get<Snapshot[]>(`/api/v1/systems/${systemId}/snapshots`),
  snapshot: (snapshotId: string) =>
    get<Snapshot>(`/api/v1/snapshots/${snapshotId}`),
  services: (snapshotId: string) =>
    get<ServiceSummary[]>(`/api/v1/snapshots/${snapshotId}/services`),
  endpoints: (snapshotId: string, serviceId: string) =>
    get<Endpoint[]>(
      `/api/v1/snapshots/${snapshotId}/services/${serviceId}/endpoints`
    ),
  icfg: (snapshotId: string, endpointId: string) =>
    get<Icfg>(`/api/v1/snapshots/${snapshotId}/endpoints/${endpointId}/icfg`),
  // The workspace aggregate (§11 Phase 2.8): endpoint + its outbound edges +
  // touched-file names in one read. ICFG and source stay separate fetches.
  endpointDetail: (snapshotId: string, endpointId: string) =>
    get<EndpointDetailView>(
      `/api/v1/snapshots/${snapshotId}/endpoints/${endpointId}/detail`
    ),
  coverage: (snapshotId: string) =>
    get<CoverageReport>(`/api/v1/snapshots/${snapshotId}/coverage`),
  systemGraph: (snapshotId: string) =>
    get<SystemGraphView>(`/api/v1/snapshots/${snapshotId}/graph`),
  remoteEdges: (snapshotId: string, serviceId: string) =>
    get<RemoteEdgesView>(
      `/api/v1/snapshots/${snapshotId}/services/${serviceId}/remote-edges`
    ),
  source: (
    snapshotId: string,
    serviceId: string,
    file: string,
    startLine: number,
    endLine: number
  ) =>
    get<SourceView>(
      `/api/v1/snapshots/${snapshotId}/services/${serviceId}/source?` +
        new URLSearchParams({
          file,
          start_line: String(startLine),
          end_line: String(endLine),
        }).toString()
    ),
  // Whole-file window (§11 Phase 2.7): end_line omitted — the server returns
  // up to its cap with total_lines + truncated so the client pages honestly.
  sourceFile: (
    snapshotId: string,
    serviceId: string,
    file: string,
    startLine = 1
  ) =>
    get<SourceView>(
      `/api/v1/snapshots/${snapshotId}/services/${serviceId}/source?` +
        new URLSearchParams({
          file,
          start_line: String(startLine),
        }).toString()
    ),
}

export type {
  CoverageReport,
  Endpoint,
  EndpointDetailView,
  Icfg,
  RemoteEdgesView,
  ServiceSummary,
  Snapshot,
  SourceView,
  System,
  SystemGraphView,
}
