"use client"

// Snapshot scope chrome (§11 Phase 2.8): the system/snapshot pickers are
// NAVIGATIONS now — changing scope changes the URL, so every page under
// /s/[snapshotId] is shareable and browser back walks real history.
import { useParams, useRouter } from "next/navigation"

import {
  useServices,
  useSnapshot,
  useSnapshots,
  useSystems,
} from "@/lib/wadi/hooks"
import { snapshotPath } from "@/lib/wadi/routes"
import { AppHeader } from "@/components/app-header"
import { ScopeBar } from "@/components/explorer/scope-bar"

export default function SnapshotLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const router = useRouter()
  const params = useParams<{ snapshotId: string }>()
  const snapshotId = params.snapshotId

  const snapshot = useSnapshot(snapshotId)
  const systemId = snapshot.data?.system_id ?? null
  const systems = useSystems()
  const snapshots = useSnapshots(systemId)
  const services = useServices(snapshotId)

  const totalEndpoints = (services.data ?? []).reduce(
    (sum, s) => sum + (s.endpoint_count ?? 0),
    0
  )

  return (
    <div className="flex h-dvh flex-col">
      <AppHeader
        summary={
          services.data
            ? `${services.data.length} services · ${totalEndpoints} endpoints`
            : undefined
        }
        scope={
          <ScopeBar
            systems={systems.data ?? []}
            snapshots={snapshots.data ?? []}
            systemId={systemId}
            snapshotId={snapshotId}
            onSystem={(id) => router.push(`/?system=${id}`)}
            onSnapshot={(id) => router.push(snapshotPath(id))}
          />
        }
      />
      {snapshot.isError ? (
        <p className="border-b bg-destructive/5 px-4 py-2 text-sm text-destructive">
          {String(snapshot.error)}
        </p>
      ) : null}
      <div className="flex min-h-0 flex-1 flex-col">{children}</div>
    </div>
  )
}
