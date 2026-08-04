"use client"

// TanStack Query hooks over the wadi API (the template's data-fetching idiom).
import { useQueries, useQuery } from "@tanstack/react-query"

import { QUERY_KEYS } from "@/config/query-keys"
import { wadiApi } from "@/lib/wadi/api"
import { newestSucceeded } from "@/lib/wadi/routes"

export function useSystems() {
  return useQuery({ queryKey: QUERY_KEYS.systems, queryFn: wadiApi.systems })
}

export function useSnapshots(systemId: string | null) {
  return useQuery({
    queryKey: QUERY_KEYS.snapshots(systemId ?? ""),
    queryFn: () => wadiApi.snapshots(systemId as string),
    enabled: systemId !== null,
  })
}

/**
 * The newest succeeded snapshot across EVERY system — what `/` forwards to.
 *
 * There is no global snapshot route (the orchestrator lists them per system),
 * so this fans out over the system list. Picking `systems[0]` instead would
 * strand the user on whichever system happens to sort first even when it has
 * no snapshots and six others do.
 *
 * `pending` stays true until every system has reported, so the caller never
 * renders an empty state over a half-loaded fan-out.
 */
export function useNewestSnapshot() {
  const systems = useSystems()
  const systemIds = systems.data?.map((s) => s.id) ?? []
  const results = useQueries({
    queries: systemIds.map((id) => ({
      queryKey: QUERY_KEYS.snapshots(id),
      queryFn: () => wadiApi.snapshots(id),
    })),
  })

  const pending =
    systems.isPending || results.some((r) => r.isPending && !r.isError)
  const snapshots = results.flatMap((r) => r.data ?? [])
  return {
    pending,
    noSystems: !systems.isPending && systemIds.length === 0,
    snapshot: pending ? null : newestSucceeded(snapshots),
  }
}

/** One snapshot by id — resolves its system for the scope chrome. */
export function useSnapshot(snapshotId: string | null) {
  return useQuery({
    queryKey: QUERY_KEYS.snapshot(snapshotId ?? ""),
    queryFn: () => wadiApi.snapshot(snapshotId as string),
    enabled: snapshotId !== null,
  })
}

export function useServices(snapshotId: string | null) {
  return useQuery({
    queryKey: QUERY_KEYS.services(snapshotId ?? ""),
    queryFn: () => wadiApi.services(snapshotId as string),
    enabled: snapshotId !== null,
  })
}

export function useEndpoints(
  snapshotId: string | null,
  serviceId: string | null
) {
  return useQuery({
    queryKey: QUERY_KEYS.endpoints(snapshotId ?? "", serviceId ?? ""),
    queryFn: () => wadiApi.endpoints(snapshotId as string, serviceId as string),
    enabled: snapshotId !== null && serviceId !== null,
  })
}

export function useIcfg(snapshotId: string | null, endpointId: string | null) {
  return useQuery({
    queryKey: QUERY_KEYS.icfg(snapshotId ?? "", endpointId ?? ""),
    queryFn: () => wadiApi.icfg(snapshotId as string, endpointId as string),
    enabled: snapshotId !== null && endpointId !== null,
  })
}

/** The endpoint workspace's one-read aggregate (§11 Phase 2.8). */
export function useEndpointDetail(
  snapshotId: string | null,
  endpointId: string | null
) {
  return useQuery({
    queryKey: QUERY_KEYS.endpointDetail(snapshotId ?? "", endpointId ?? ""),
    queryFn: () =>
      wadiApi.endpointDetail(snapshotId as string, endpointId as string),
    enabled: snapshotId !== null && endpointId !== null,
  })
}

export function useCoverage(snapshotId: string | null) {
  return useQuery({
    queryKey: QUERY_KEYS.coverage(snapshotId ?? ""),
    queryFn: () => wadiApi.coverage(snapshotId as string),
    enabled: snapshotId !== null,
  })
}

export function useRemoteEdges(
  snapshotId: string | null,
  serviceId: string | null
) {
  return useQuery({
    queryKey: QUERY_KEYS.remoteEdges(snapshotId ?? "", serviceId ?? ""),
    queryFn: () =>
      wadiApi.remoteEdges(snapshotId as string, serviceId as string),
    enabled: snapshotId !== null && serviceId !== null,
  })
}

/** The snapshot-wide service graph (§11 Phase 2.7 M4). */
export function useSystemGraph(enabled: boolean, snapshotId: string | null) {
  return useQuery({
    queryKey: QUERY_KEYS.systemGraph(snapshotId ?? "none"),
    queryFn: () => wadiApi.systemGraph(snapshotId as string),
    enabled: enabled && snapshotId !== null,
  })
}

/** Whole-file source-on-demand (§11 Phase 2.7): fetched only while the Flow
 * tab is active, never preloaded; the server caps the window and says so. */
export function useSourceFile(
  enabled: boolean,
  snapshotId: string,
  serviceId: string,
  file: string,
  startLine = 1
) {
  return useQuery({
    queryKey: QUERY_KEYS.sourceFile(snapshotId, serviceId, file, startLine),
    queryFn: () => wadiApi.sourceFile(snapshotId, serviceId, file, startLine),
    enabled,
    staleTime: Infinity, // pinned-SHA content never changes
  })
}

/** Source-on-demand (§5.3): fetched only when a panel opens, never preloaded. */
export function useSource(
  enabled: boolean,
  snapshotId: string,
  serviceId: string,
  file: string,
  startLine: number,
  endLine: number
) {
  return useQuery({
    queryKey: QUERY_KEYS.source(
      snapshotId,
      serviceId,
      file,
      startLine,
      endLine
    ),
    queryFn: () =>
      wadiApi.source(snapshotId, serviceId, file, startLine, endLine),
    enabled,
    staleTime: Infinity, // pinned-SHA content never changes
  })
}
