// Thin typed fetch layer over the orchestrator REST API (§14).
// Types come from the generated contract schemas — never hand-written (§7).

import type { Endpoint } from "@/lib/generated/endpoint.schema"
import type { Icfg } from "@/lib/generated/icfg.schema"
import type { ServiceSummary } from "@/lib/generated/service_summary.schema"
import type { Snapshot } from "@/lib/generated/snapshot.schema"
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
  snapshots: (systemId: string) => get<Snapshot[]>(`/api/v1/systems/${systemId}/snapshots`),
  services: (snapshotId: string) =>
    get<ServiceSummary[]>(`/api/v1/snapshots/${snapshotId}/services`),
  endpoints: (snapshotId: string, serviceId: string) =>
    get<Endpoint[]>(`/api/v1/snapshots/${snapshotId}/services/${serviceId}/endpoints`),
  icfg: (snapshotId: string, endpointId: string) =>
    get<Icfg>(`/api/v1/snapshots/${snapshotId}/endpoints/${endpointId}/icfg`),
}

export type { Endpoint, Icfg, ServiceSummary, Snapshot, System }
