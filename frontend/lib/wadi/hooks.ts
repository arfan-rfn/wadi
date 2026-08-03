"use client"

// TanStack Query hooks over the wadi API (the template's data-fetching idiom).
import { useQuery } from "@tanstack/react-query"

import { QUERY_KEYS } from "@/config/query-keys"
import { wadiApi } from "@/lib/wadi/api"

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
