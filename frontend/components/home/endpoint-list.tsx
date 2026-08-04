"use client"

// Endpoint summary rows (§11 Phase 2.8): browsing surface only — everything
// here is already on the Endpoint artifact (no extra fetches). Auth is
// tri-state (P10): required / open / unknown all render distinctly.
import { ShieldAlert, ShieldCheck, ShieldQuestion } from "lucide-react"

import { cn } from "@/lib/utils"
import type { Endpoint } from "@/lib/wadi/api"
import { Chip } from "@/components/ui/chip"
import { MethodBadge } from "@/components/explorer/method-badge"

function AuthChip({ endpoint }: { endpoint: Endpoint }) {
  const authenticated = endpoint.auth?.authenticated ?? null
  if (authenticated === true)
    return (
      <Chip variant="outline" title="Authentication required">
        <ShieldCheck aria-hidden />
        auth
      </Chip>
    )
  if (authenticated === false)
    return (
      <Chip variant="outline" title="No authentication (evidenced)">
        <ShieldAlert aria-hidden />
        open
      </Chip>
    )
  return (
    <Chip
      variant="unknown"
      title="Unknown — analysis found no auth evidence either way"
    >
      <ShieldQuestion aria-hidden />
      auth?
    </Chip>
  )
}

export function EndpointRow({
  endpoint,
  onOpen,
}: {
  endpoint: Endpoint
  onOpen: (endpoint: Endpoint) => void
}) {
  const paramCount = endpoint.params?.length ?? 0
  return (
    <button
      onClick={() => onOpen(endpoint)}
      className={cn(
        "flex w-full items-center gap-2.5 border-l-2 border-transparent px-3 py-2 text-left transition-colors hover:bg-muted/50"
      )}
    >
      <MethodBadge method={endpoint.http_method} />
      <span className="min-w-0 flex-1 truncate font-mono text-xs">
        {endpoint.full_uri}
      </span>
      <span className="flex shrink-0 items-center gap-1.5">
        {paramCount > 0 ? (
          <Chip variant="mono">
            {paramCount} param{paramCount === 1 ? "" : "s"}
          </Chip>
        ) : null}
        {endpoint.request_schema ? (
          <Chip variant="mono" title="Request body shape recovered">
            req
          </Chip>
        ) : null}
        {endpoint.response_schema ? (
          <Chip variant="mono" title="Response shape recovered">
            res
          </Chip>
        ) : null}
        <AuthChip endpoint={endpoint} />
      </span>
    </button>
  )
}
