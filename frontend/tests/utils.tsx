import type { ReactElement } from "react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, type RenderResult } from "@testing-library/react"

import { TooltipProvider } from "@/components/ui/tooltip"

/** Render a component that uses TanStack Query hooks. Retries are off so
 * error states surface immediately in tests. */
export function renderWithQuery(ui: ReactElement): RenderResult {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  // TooltipProvider mirrors the app layout: Radix throws without it, and a
  // component that renders a tooltip in production must be testable as it ships.
  return render(
    <QueryClientProvider client={client}>
      <TooltipProvider>{ui}</TooltipProvider>
    </QueryClientProvider>
  )
}
