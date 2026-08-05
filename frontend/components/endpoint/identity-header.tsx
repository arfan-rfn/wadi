"use client"

// The workspace identity header (§11 Phase 2.8): who this page is about stays
// visible at all times — verb + URI, service, auth state, graph stats — plus
// the raw-artifact escape hatch (a download link to the API route itself).
//
// The Graph/Source lens toggle that used to live here is gone: the workspace
// shows both permanently (§5.2.9 UI), so there is nothing left to switch.
import Link from "next/link"
import { ArrowLeft, Download } from "lucide-react"

import { cn } from "@/lib/utils"
import {
  wadiApiPaths,
  type EndpointDetailView,
  type Icfg,
} from "@/lib/wadi/api"
import { rollupMethods, shortSignature } from "@/lib/wadi/rollup"
import { snapshotPath } from "@/lib/wadi/routes"
import { Chip } from "@/components/ui/chip"
import { Skeleton } from "@/components/ui/skeleton"
import { MethodBadge } from "@/components/explorer/method-badge"
import {
  AuthChip,
  authStateOf,
  withheldReason,
} from "@/components/shared/auth-chip"

function EndpointAuthChip({ detail }: { detail: EndpointDetailView }) {
  const unread = (detail.endpoint.auth?.evidence ?? [])
    .filter((item) => item.active !== false && item.resolution === "opaque")
    .map((item) => item.kind)
  const state = authStateOf(
    detail.endpoint.auth?.authenticated,
    unread,
    detail.endpoint.auth?.denied
  )
  return (
    <AuthChip
      state={state}
      title={state === "withheld" ? withheldReason(unread) : undefined}
    />
  )
}

export function IdentityHeader({
  snapshotId,
  endpointId,
  detail,
  icfg,
}: {
  snapshotId: string
  endpointId: string
  detail: EndpointDetailView | undefined
  icfg: Icfg | undefined
}) {
  const methods = icfg ? rollupMethods(icfg) : null
  return (
    <header className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1.5 border-b px-4 py-2.5">
      {/* An actual button, not a breadcrumb crumb: it was reading as the
          first segment of a path, so its job — LEAVING this endpoint — was
          invisible. Border, label and icon now say "go back", and the service
          name says where back goes. */}
      <Link
        href={snapshotPath(snapshotId, {
          view: "services",
          serviceId: detail?.service_id ?? null,
        })}
        className={cn(
          "inline-flex shrink-0 cursor-pointer items-center gap-1.5 rounded-md border px-2 py-1 text-2xs transition-colors",
          "hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        )}
      >
        <ArrowLeft className="size-3.5 shrink-0" aria-hidden />
        <span className="font-medium">Back</span>
        {detail?.service_name ? (
          <span className="hidden max-w-40 truncate text-muted-foreground md:inline">
            to {detail.service_name}
          </span>
        ) : null}
      </Link>
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
      {detail ? <EndpointAuthChip detail={detail} /> : null}
      {icfg ? (
        <span className="font-mono text-2xs text-muted-foreground">
          {icfg.nodes.length} nodes · {(icfg.edges ?? []).length} edges ·{" "}
          {methods?.length ?? 0} methods
        </span>
      ) : detail?.icfg_available === false ? (
        <Chip variant="unknown">no flow graph extracted</Chip>
      ) : null}

      <span className="ml-auto flex items-center gap-2">
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
