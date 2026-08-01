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

export function useEndpoints(snapshotId: string | null, serviceId: string | null) {
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
