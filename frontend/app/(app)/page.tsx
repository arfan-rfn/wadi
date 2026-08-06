"use client"

// The root resolver (§11 Phase 2.8): `/` owns no UI — it forwards to the
// newest succeeded snapshot's overview home. Also the one legacy shim: old
// pre-2.8 deep links carried `?snapshot=` / `?endpoint=` query state; those
// two keys forward to the new routes, everything else is declared broken
// (pre-1.0 internal tool).
import { Suspense, useEffect } from "react"
import { useRouter, useSearchParams } from "next/navigation"

import { useNewestSnapshot, useSnapshots } from "@/lib/wadi/hooks"
import { endpointPath, newestSucceeded, snapshotPath } from "@/lib/wadi/routes"
import { Skeleton } from "@/components/ui/skeleton"
import { AppHeader } from "@/components/app-header"
import { EmptyState } from "@/components/shared/empty-state"

function RootResolver() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const legacySnapshot = searchParams.get("snapshot")
  const legacyEndpoint = searchParams.get("endpoint")
  const requestedSystem = searchParams.get("system")

  // `?system=` pins the resolver to one system; otherwise we look across all
  // of them, because the first system in the list is not necessarily one that
  // has ever been analyzed.
  const scoped = useSnapshots(
    legacySnapshot || !requestedSystem ? null : requestedSystem
  )
  const global = useNewestSnapshot()

  const target = requestedSystem
    ? newestSucceeded(scoped.data ?? [])
    : global.snapshot
  const resolving = requestedSystem ? scoped.isPending : global.pending

  useEffect(() => {
    if (legacySnapshot) {
      router.replace(
        legacyEndpoint
          ? endpointPath(legacySnapshot, legacyEndpoint)
          : snapshotPath(legacySnapshot)
      )
      return
    }
    if (!target) return
    router.replace(snapshotPath(target.id))
  }, [legacySnapshot, legacyEndpoint, target, router])

  // A failed fetch is not an answer about the data. Rendering "no systems yet"
  // when the orchestrator is unreachable states an analysis result nobody
  // obtained, on the page every visitor lands on first (P10).
  const failure = requestedSystem
    ? ((scoped.error ?? null) as Error | null)
    : global.error
  if (!legacySnapshot && failure) {
    return (
      <EmptyState className="p-8">
        Could not reach the wadi API — {failure.message}. This says nothing
        about whether snapshots exist; retry once it is back.
      </EmptyState>
    )
  }
  if (global.noSystems) {
    return (
      <EmptyState className="p-8">
        No systems yet — run{" "}
        <code className="rounded-sm bg-muted px-1 font-mono">wadi analyze .</code>{" "}
        to create the first snapshot.
      </EmptyState>
    )
  }
  if (!legacySnapshot && !resolving && !target) {
    return (
      <EmptyState className="p-8">
        {requestedSystem
          ? "This system has no snapshots yet — run "
          : "No snapshots yet in any system — run "}
        <code className="rounded-sm bg-muted px-1 font-mono">wadi analyze .</code>
      </EmptyState>
    )
  }
  return (
    <div className="space-y-3 p-8">
      <Skeleton className="h-8 w-64" />
      <Skeleton className="h-48 w-full" />
    </div>
  )
}

export default function RootPage() {
  return (
    <>
      <AppHeader />
      <Suspense>
        <RootResolver />
      </Suspense>
    </>
  )
}
