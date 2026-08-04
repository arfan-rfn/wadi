import { Suspense } from "react"

import { EndpointWorkspace } from "@/components/endpoint/workspace"

// Suspense boundary: the workspace hydrates its store from useSearchParams,
// which Next requires to suspend during prerender.
export default async function EndpointWorkspacePage({
  params,
}: {
  params: Promise<{ snapshotId: string; endpointId: string }>
}) {
  const { snapshotId, endpointId } = await params
  return (
    <Suspense>
      <EndpointWorkspace snapshotId={snapshotId} endpointId={endpointId} />
    </Suspense>
  )
}
