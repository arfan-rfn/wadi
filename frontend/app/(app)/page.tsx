import { Suspense } from "react"

import { Explorer } from "@/components/explorer/explorer"

// Suspense boundary: Explorer reads the deep-link URL state via
// useSearchParams (§11 Phase 2.7), which Next requires to suspend during
// prerender.
export default function ExplorerPage() {
  return (
    <Suspense>
      <Explorer />
    </Suspense>
  )
}
