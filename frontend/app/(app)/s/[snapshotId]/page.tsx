import { Suspense } from "react"

import { OverviewHome } from "@/components/home/overview-home"

// Suspense boundary: OverviewHome reads `?view`/`?service` via
// useSearchParams, which Next requires to suspend during prerender.
export default async function SnapshotHomePage({
  params,
}: {
  params: Promise<{ snapshotId: string }>
}) {
  const { snapshotId } = await params
  return (
    <Suspense>
      <OverviewHome snapshotId={snapshotId} />
    </Suspense>
  )
}
