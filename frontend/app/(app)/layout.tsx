"use client"

// Workbench layout: full-bleed content, no marketing footer — the explorer
// owns the viewport below the header.
//
// The header is rendered by each ROUTE, not here, because the two routes need
// different ones (the snapshot layout fills in the system/snapshot pickers).
// An earlier version branched on `usePathname()` to decide — which rendered an
// extra header during SSR, shifting every Radix `useId` after it and producing
// a hydration mismatch on the scope pickers. No conditional, no mismatch.
import { TooltipProvider } from "@/components/ui/tooltip"

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    // One provider for the whole workbench: shared delay timing means moving
    // between adjacent icons feels continuous instead of re-arming a timer.
    <TooltipProvider>
      <div className="flex min-h-0 flex-1 flex-col">{children}</div>
    </TooltipProvider>
  )
}
