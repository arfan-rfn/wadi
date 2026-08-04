"use client"

// The workspace identity header (§11 Phase 2.8): who this page is about stays
// visible at all times — verb + URI, service, auth state, graph stats — plus
// the center-surface lens toggle and the raw-artifact escape hatch (the old
// Raw ICFG tab is now a download link to the API route itself).
import Link from "next/link"
import {
  ArrowLeft,
  Download,
  ShieldAlert,
  ShieldCheck,
  ShieldQuestion,
} from "lucide-react"

import { cn } from "@/lib/utils"
import {
  wadiApiPaths,
  type EndpointDetailView,
  type Icfg,
} from "@/lib/wadi/api"
import { rollupMethods, shortSignature } from "@/lib/wadi/rollup"
import { LENSES, snapshotPath, type Lens } from "@/lib/wadi/routes"
import { Chip } from "@/components/ui/chip"
import { Skeleton } from "@/components/ui/skeleton"
import { MethodBadge } from "@/components/explorer/method-badge"

function AuthChip({ detail }: { detail: EndpointDetailView }) {
  const authenticated = detail.endpoint.auth?.authenticated ?? null
  if (authenticated === true)
    return (
      <Chip variant="outline">
        <ShieldCheck aria-hidden />
        auth required
      </Chip>
    )
  if (authenticated === false)
    return (
      <Chip variant="outline">
        <ShieldAlert aria-hidden />
        no auth (evidenced)
      </Chip>
    )
  return (
    <Chip variant="unknown">
      <ShieldQuestion aria-hidden />
      auth unknown
    </Chip>
  )
}

export function IdentityHeader({
  snapshotId,
  endpointId,
  detail,
  icfg,
  lens,
  onLens,
}: {
  snapshotId: string
  endpointId: string
  detail: EndpointDetailView | undefined
  icfg: Icfg | undefined
  lens: Lens
  onLens: (lens: Lens) => void
}) {
  const methods = icfg ? rollupMethods(icfg) : null
  return (
    <header className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1.5 border-b px-4 py-2.5">
      <Link
        href={snapshotPath(snapshotId, {
          view: "services",
          serviceId: detail?.service_id ?? null,
        })}
        className="inline-flex items-center gap-1 text-2xs text-muted-foreground transition-colors hover:text-foreground"
        title="Back to the overview"
      >
        <ArrowLeft className="size-3.5" aria-hidden />
        {detail?.service_name ?? "overview"}
      </Link>
      <span className="text-muted-foreground/40">/</span>
      {detail ? (
        <span className="flex min-w-0 items-center gap-2">
          <MethodBadge method={detail.endpoint.http_method} />
          <span className="truncate font-mono text-sm font-medium">
            {detail.endpoint.full_uri}
          </span>
        </span>
      ) : (
        <Skeleton className="h-5 w-72" />
      )}
      {detail ? (
        <span className="hidden truncate font-mono text-2xs text-muted-foreground lg:inline">
          {shortSignature(detail.endpoint.handler.signature)}
        </span>
      ) : null}
      {detail ? <AuthChip detail={detail} /> : null}
      {icfg ? (
        <span className="font-mono text-2xs text-muted-foreground">
          {icfg.nodes.length} nodes · {(icfg.edges ?? []).length} edges ·{" "}
          {methods?.length ?? 0} methods
        </span>
      ) : detail?.icfg_available === false ? (
        <Chip variant="unknown">no flow graph extracted</Chip>
      ) : null}

      <span className="ml-auto flex items-center gap-2">
        <div
          role="tablist"
          aria-label="Center surface"
          className="flex items-center rounded-md border p-0.5"
        >
          {LENSES.map((id) => (
            <button
              key={id}
              role="tab"
              aria-selected={lens === id}
              onClick={() => onLens(id)}
              className={cn(
                "rounded px-2.5 py-1 text-xs font-medium capitalize transition-colors",
                lens === id
                  ? "bg-muted text-foreground"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              {id}
            </button>
          ))}
        </div>
        <a
          href={wadiApiPaths.icfg(snapshotId, endpointId)}
          download={`${endpointId}-icfg.json`}
          className="inline-flex items-center gap-1 rounded-md border px-2 py-1 text-2xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          title="Download the raw ICFG artifact"
        >
          <Download className="size-3" aria-hidden />
          ICFG JSON
        </a>
      </span>
    </header>
  )
}
