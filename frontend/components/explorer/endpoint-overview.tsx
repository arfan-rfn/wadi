"use client"

// The endpoint's end-to-end story on one screen (M6): what it accepts, how
// it's protected, what it returns, who it calls (with per-call resolution
// honesty), and where those claims anchor in source. Unknown is a rendered
// state everywhere — never a blank (P10).
import {
  ArrowRight,
  ShieldAlert,
  ShieldCheck,
  ShieldQuestion,
  Split,
} from "lucide-react"

import type { RemoteEdgeItem } from "@/lib/generated/remote_edges_view.schema"
import type { Endpoint, Icfg, RemoteEdgesView } from "@/lib/wadi/api"
import {
  conditionLabel,
  governingConditions,
  type GoverningCondition,
} from "@/lib/wadi/conditions"
import { unopenableCopy } from "@/lib/wadi/unopenable"
import { Chip } from "@/components/ui/chip"
import { Skeleton } from "@/components/ui/skeleton"
import { SectionHeading } from "@/components/shared/section-heading"
import { SourceSnippet } from "@/components/source/source-viewer"

import { MethodBadge } from "./method-badge"
import { ShapeTree } from "./shape-tree"

function AuthSection({
  endpoint,
  snapshotId,
  serviceId,
}: {
  endpoint: Endpoint
  snapshotId: string
  serviceId: string
}) {
  const auth = endpoint.auth
  const state =
    auth?.authenticated === true
      ? "required"
      : auth?.authenticated === false
        ? "open"
        : "unknown"
  return (
    <section className="space-y-2">
      <SectionHeading>Authentication</SectionHeading>
      <div className="flex flex-wrap items-center gap-2">
        {state === "required" && (
          <span className="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs">
            <ShieldCheck className="size-3.5" aria-hidden />
            authentication required
          </span>
        )}
        {state === "open" && (
          <span className="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs">
            <ShieldAlert className="size-3.5" aria-hidden />
            no authentication (evidenced)
          </span>
        )}
        {state === "unknown" && (
          <span className="inline-flex items-center gap-1.5 rounded-full border border-dashed px-2.5 py-0.5 text-xs text-muted-foreground">
            <ShieldQuestion className="size-3.5" aria-hidden />
            unknown — analysis found no auth evidence either way
          </span>
        )}
        {(auth?.roles ?? []).map((role) => (
          <span
            key={role}
            className="rounded-full bg-muted px-2.5 py-0.5 font-mono text-[11px]"
          >
            {role}
          </span>
        ))}
      </div>
      {(auth?.evidence ?? []).length > 0 && (
        <ul className="space-y-1.5">
          {(auth?.evidence ?? []).map((item, index) => (
            <li key={index} className="space-y-1">
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
                  {item.kind}
                </span>
                <code className="text-[11px]">{item.detail}</code>
              </div>
              {item.anchor && (
                <SourceSnippet
                  snapshotId={snapshotId}
                  serviceId={serviceId}
                  anchor={item.anchor}
                />
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

const TARGET_LABEL: Record<string, string> = {
  analyzed: "resolved",
  external: "external",
  placeholder: "placeholder",
  undetermined: "undetermined",
}

function CallRow({
  edges,
  anchor,
  conditions,
  snapshotId,
  serviceId,
}: {
  edges: RemoteEdgeItem[]
  anchor: { file: string; start_line: number; end_line: number } | null
  conditions: GoverningCondition[]
  snapshotId: string
  serviceId: string
}) {
  const first = edges[0]
  return (
    <li className="space-y-1.5 px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-2">
        {first.http_verb ? (
          <MethodBadge method={first.http_verb} />
        ) : (
          <span className="w-14 shrink-0 text-center text-[10px] text-muted-foreground">
            verb?
          </span>
        )}
        <span className="min-w-0 flex-1 truncate font-mono text-xs">
          {first.url ?? "target undetermined"}
        </span>
        <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
          {first.mechanism}
        </span>
      </div>
      {conditions.length > 0 ? (
        <div className="flex flex-wrap items-center gap-1.5 pl-16">
          {conditions.map((condition) => (
            <span
              key={conditionLabel(condition)}
              className="inline-flex max-w-full items-center gap-1 rounded border border-amber-500/40 bg-amber-500/5 px-1.5 py-0.5 font-mono text-[10px] text-amber-700 dark:text-amber-400"
              title="Nearest governing branch (§11 heuristic — nearest branch, not full dominance)"
            >
              <Split className="size-2.5 shrink-0" />
              <span className="truncate">{conditionLabel(condition)}</span>
            </span>
          ))}
        </div>
      ) : null}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 pl-16 text-[11px] text-muted-foreground">
        {edges.map((edge) => (
          <span key={edge.edge_id} className="inline-flex items-center gap-1">
            <ArrowRight className="size-3" aria-hidden />
            {edge.target_kind === "analyzed" ? (
              <>
                <span className="font-medium text-foreground">
                  {edge.target_service_name ?? edge.target_service_id}
                </span>
                <span className="font-mono">
                  {edge.target_simplified_uri ?? ""}
                </span>
              </>
            ) : edge.target_kind === "external" ? (
              <span className="font-mono">{edge.external_host}</span>
            ) : edge.target_kind === "placeholder" ? (
              <span>
                {edge.target_service_name ?? "unanalyzed service"} (placeholder)
              </span>
            ) : (
              <span>undetermined — see coverage for the reason</span>
            )}
            <span className="rounded bg-muted px-1 py-px text-[10px]">
              {TARGET_LABEL[edge.target_kind] ?? edge.target_kind} ·{" "}
              {edge.confidence}
            </span>
          </span>
        ))}
      </div>
      {anchor && (
        <div className="pl-16">
          <SourceSnippet
            snapshotId={snapshotId}
            serviceId={serviceId}
            anchor={anchor}
          />
        </div>
      )}
    </li>
  )
}

export function EndpointOverview({
  endpoint,
  icfg,
  remoteEdges,
  edgesLoading,
  snapshotId,
  serviceId,
  unopenableCalls,
}: {
  endpoint: Endpoint
  icfg: Icfg | undefined
  remoteEdges: RemoteEdgesView | undefined
  edgesLoading: boolean
  snapshotId: string
  serviceId: string
  /** §5.4.2 T5 — call sites with no interior, by reason (the endpoint-level
   *  honesty surface). Absent/empty means nothing needs explaining. */
  unopenableCalls?: { reason: string; call_count: number }[]
}) {
  // Closure semantics (§5.2): this endpoint's calls are the call sites inside
  // ITS ICFG — a shared helper's call appears under every endpoint that
  // reaches it, which is the honest reading, not a double-count.
  const callAnchors = new Map<
    string,
    { file: string; start_line: number; end_line: number }
  >()
  const callNodeIds = new Map<string, string>()
  for (const node of icfg?.nodes ?? []) {
    for (const callId of node.remote_call_ids ?? []) {
      if (!callAnchors.has(callId)) {
        callAnchors.set(callId, node.anchor)
        callNodeIds.set(callId, node.id)
      }
    }
  }
  // §11 Phase 2.7 M5: under which branch does each outbound call run?
  const conditionsByNode = icfg
    ? governingConditions(icfg)
    : new Map<string, GoverningCondition[]>()
  const outbound = (remoteEdges?.outbound ?? []).filter((edge) =>
    callAnchors.has(edge.remote_call_id)
  )
  const grouped = new Map<string, RemoteEdgeItem[]>()
  for (const edge of outbound) {
    const group = grouped.get(edge.remote_call_id) ?? []
    group.push(edge)
    grouped.set(edge.remote_call_id, group)
  }
  const downstream = new Map<string, Set<string>>()
  for (const edge of outbound) {
    if (edge.target_kind === "analyzed" && edge.target_service_name) {
      const set = downstream.get(edge.target_service_name) ?? new Set<string>()
      if (edge.target_simplified_uri) {
        set.add(
          `${edge.target_http_method ?? ""} ${edge.target_simplified_uri}`
        )
      }
      downstream.set(edge.target_service_name, set)
    }
  }

  return (
    <div className="space-y-6 p-4">
      {unopenableCalls && unopenableCalls.length > 0 ? (
        <div className="space-y-1.5">
          <SectionHeading>Calls with no source to analyse</SectionHeading>
          <div className="flex flex-wrap gap-1.5">
            {unopenableCalls.map((entry) => {
              const copy = unopenableCopy(entry.reason)
              return (
                <Chip key={entry.reason} variant="outline" title={copy?.detail}>
                  {entry.call_count} {copy?.badge ?? entry.reason}
                </Chip>
              )
            })}
          </div>
          <p className="text-[10px] text-muted-foreground">
            These call sites are drawn in the flow — they run — but their bodies
            are generated, inherited, or third-party, so there is no source to
            open. Counted here so the map states what it cannot show.
          </p>
        </div>
      ) : null}
      <AuthSection
        endpoint={endpoint}
        snapshotId={snapshotId}
        serviceId={serviceId}
      />

      {(endpoint.params ?? []).length > 0 && (
        <section className="space-y-2">
          <SectionHeading>Parameters</SectionHeading>
          <ul className="space-y-1">
            {(endpoint.params ?? []).map((param) => (
              <li
                key={`${param.location}-${param.name}`}
                className="flex flex-wrap items-baseline gap-2 text-xs"
              >
                <span className="font-mono">{param.name}</span>
                <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                  {param.location}
                </span>
                {param.type_name && (
                  <span className="font-mono text-[11px] text-muted-foreground">
                    {param.type_name.substring(
                      param.type_name.lastIndexOf(".") + 1
                    )}
                  </span>
                )}
                {param.required === false && (
                  <span className="text-[10px] text-muted-foreground">
                    optional
                  </span>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="space-y-2">
        <SectionHeading>Request body</SectionHeading>
        {endpoint.request_schema ? (
          <ShapeTree shape={endpoint.request_schema} />
        ) : (
          <p className="text-xs text-muted-foreground">No request body.</p>
        )}
      </section>

      <section className="space-y-2">
        <SectionHeading>Response</SectionHeading>
        {endpoint.response_schema ? (
          <ShapeTree shape={endpoint.response_schema} />
        ) : (
          <p className="text-xs text-muted-foreground">
            Response shape unknown (analyzed before contract recovery, or no
            declared return).
          </p>
        )}
      </section>

      <section className="space-y-2">
        <SectionHeading>
          Outbound calls in this endpoint&apos;s flow
        </SectionHeading>
        {edgesLoading ? (
          <Skeleton className="h-16 w-full" />
        ) : grouped.size === 0 ? (
          <p className="text-xs text-muted-foreground">
            No remote calls reached from this endpoint.
          </p>
        ) : (
          <ul className="divide-y rounded-lg border">
            {Array.from(grouped.entries()).map(([callId, edges]) => (
              <CallRow
                key={callId}
                edges={edges}
                anchor={callAnchors.get(callId) ?? null}
                conditions={
                  conditionsByNode.get(callNodeIds.get(callId) ?? "") ?? []
                }
                snapshotId={snapshotId}
                serviceId={serviceId}
              />
            ))}
          </ul>
        )}
      </section>

      {downstream.size > 0 && (
        <section className="space-y-2">
          <SectionHeading>Downstream endpoints</SectionHeading>
          <ul className="space-y-1">
            {Array.from(downstream.entries()).map(([service, uris]) => (
              <li key={service} className="text-xs">
                <span className="font-medium">{service}</span>
                <span className="text-muted-foreground">
                  {" — "}
                  {Array.from(uris).join(", ") || "endpoint set pending"}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
