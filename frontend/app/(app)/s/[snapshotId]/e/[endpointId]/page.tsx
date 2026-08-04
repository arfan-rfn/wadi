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
      {/* `key`: the workspace store is created once per mount and holds node
          ids scoped to ONE endpoint. Today the router remounts on an
          endpointId change so nothing leaks, but the correctness of every
          selection would rest on that framework behaviour — and the first
          endpoint→endpoint link would silently carry endpoint 1's selection
          into endpoint 2's URL. Keying it costs nothing. */}
      <EndpointWorkspace
        key={`${snapshotId}/${endpointId}`}
        snapshotId={snapshotId}
        endpointId={endpointId}
      />
    </Suspense>
  )
}
