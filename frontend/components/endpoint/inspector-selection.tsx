"use client"

// Inspector · Selection tab (§11 Phase 2.8): everything known about the
// selected canvas node — identity, construct/sink facts, governing
// conditions, per-edge remote resolution with confidence/provenance, and the
// escalating source ladder: anchor snippet → "Open in source" (full lens).
import { useMemo } from "react"
import { ArrowUpRight, Split } from "lucide-react"

import type { Icfg } from "@/lib/generated/icfg.schema"
import type { EndpointDetailView } from "@/lib/wadi/api"
import { conditionLabel, governingConditions } from "@/lib/wadi/conditions"
import { rollupMethods, shortSignature } from "@/lib/wadi/rollup"
import { unopenableCopy } from "@/lib/wadi/unopenable"
import { Chip } from "@/components/ui/chip"
import { MethodBadge } from "@/components/explorer/method-badge"
import { EmptyState } from "@/components/shared/empty-state"
import { SectionHeading } from "@/components/shared/section-heading"
import { SourceSnippet } from "@/components/source/source-viewer"

import { useWorkspaceStore, useWorkspaceStoreApi } from "./workspace-store"

type IcfgNode = Icfg["nodes"][number]
type OutboundEdge = NonNullable<EndpointDetailView["outbound"]>[number]

function ResolutionLine({ edge }: { edge: OutboundEdge }) {
  return (
    <div className="space-y-1 rounded-md border p-2">
      <div className="flex flex-wrap items-center gap-1.5">
        {edge.http_verb ? <MethodBadge method={edge.http_verb} /> : null}
        <code className="min-w-0 flex-1 truncate font-mono text-2xs">
          {edge.url ?? "(no url recovered)"}
        </code>
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        {edge.target_kind === "analyzed" ? (
          <Chip variant="outline">
            → {edge.target_service_name ?? edge.target_service_id}
            {edge.target_simplified_uri
              ? ` · ${edge.target_simplified_uri}`
              : ""}
          </Chip>
        ) : edge.target_kind === "external" ? (
          <Chip variant="outline">external · {edge.external_host}</Chip>
        ) : (
          <Chip variant="unknown">
            {edge.target_kind === "placeholder"
              ? "placeholder service"
              : "undetermined — see coverage for the reason"}
          </Chip>
        )}
        <Chip variant="mono">
          {edge.mechanism} · {edge.confidence}
        </Chip>
        <Chip variant="mono">{edge.provenance}</Chip>
      </div>
      {edge.evidence ? (
        <p className="font-mono text-[10px] text-muted-foreground">
          {edge.evidence}
        </p>
      ) : null}
    </div>
  )
}

export function InspectorSelection({
  icfg,
  detail,
}: {
  icfg: Icfg | undefined
  detail: EndpointDetailView
}) {
  const selectedNodeId = useWorkspaceStore((s) => s.selectedNodeId)
  const conditions = useMemo(
    () => (icfg ? governingConditions(icfg) : new Map<string, never>()),
    [icfg]
  )
  const rollups = useMemo(
    () => new Map((icfg ? rollupMethods(icfg) : []).map((r) => [r.id, r])),
    [icfg]
  )
  const nodeById = useMemo(
    () => new Map((icfg?.nodes ?? []).map((n) => [n.id, n])),
    [icfg]
  )

  if (!selectedNodeId) {
    return (
      <EmptyState>
        Select a node on the canvas — or a method in the call tree — to see what
        analysis knows about it.
      </EmptyState>
    )
  }

  if (selectedNodeId.startsWith("ghost:")) {
    const key = selectedNodeId.slice("ghost:".length)
    const edges = (detail.outbound ?? []).filter(
      (edge) =>
        edge.target_service_id === key ||
        edge.external_host === key ||
        edge.remote_call_id === key
    )
    return (
      <div className="space-y-3 p-3">
        <SectionHeading>Remote target</SectionHeading>
        {edges.length === 0 ? (
          <Chip variant="unknown">
            unresolved call — not stitched to any target
          </Chip>
        ) : (
          edges.map((edge) => <ResolutionLine key={edge.edge_id} edge={edge} />)
        )}
      </div>
    )
  }

  if (selectedNodeId.startsWith("method:")) {
    const methodId = selectedNodeId.slice("method:".length)
    const rollup = rollups.get(methodId)
    if (!rollup) return <EmptyState>Unknown method.</EmptyState>
    return (
      <div className="space-y-3 p-3">
        <SectionHeading>Method</SectionHeading>
        <p className="break-all font-mono text-xs">{rollup.signature}</p>
        <div className="flex flex-wrap gap-1.5">
          <Chip variant="mono">{rollup.statementCount} statements</Chip>
          <Chip variant="mono">{rollup.branchCount} branches</Chip>
          <Chip variant="mono">{rollup.loopCount} loops</Chip>
          {rollup.sinks.map((sink) => (
            <Chip key={sink} variant="outline">
              {sink}
            </Chip>
          ))}
          {rollup.badges.map((badge) => (
            <Chip key={badge} variant="outline">
              {badge}
            </Chip>
          ))}
        </div>
        {rollup.file && rollup.line ? (
          <>
            <SourceSnippet
              snapshotId={detail.snapshot_id}
              serviceId={detail.service_id}
              anchor={{
                file: rollup.file,
                start_line: rollup.line,
                end_line: rollup.line,
                variant: "original",
              }}
            />
            <OpenInSource file={rollup.file} line={rollup.line} />
          </>
        ) : null}
      </div>
    )
  }

  if (selectedNodeId.startsWith("run:")) {
    const headId = selectedNodeId.slice("run:".length)
    const head = nodeById.get(headId)
    if (!head) return <EmptyState>Unknown node.</EmptyState>
    return (
      <div className="space-y-3 p-3">
        <SectionHeading>Condensed statements</SectionHeading>
        <p className="text-2xs text-muted-foreground">
          A linear run of plain statements in{" "}
          <span className="font-mono">
            {shortSignature(head.method.signature)}
          </span>{" "}
          — click it on the canvas to expand. Condensation never hides branches,
          loops, calls, or sinks.
        </p>
        <SourceSnippet
          snapshotId={detail.snapshot_id}
          serviceId={detail.service_id}
          anchor={head.anchor}
        />
        <OpenInSource file={head.anchor.file} line={head.anchor.start_line} />
      </div>
    )
  }

  const icfgNode: IcfgNode | undefined = selectedNodeId.startsWith("stmt:")
    ? nodeById.get(selectedNodeId.slice("stmt:".length))
    : undefined
  if (!icfgNode) return <EmptyState>Nothing known about this node.</EmptyState>

  const nodeConditions = conditions.get(icfgNode.id) ?? []
  const remoteIds = new Set(icfgNode.remote_call_ids ?? [])
  const nodeEdges = (detail.outbound ?? []).filter((edge) =>
    remoteIds.has(edge.remote_call_id)
  )

  const unopenable = unopenableCopy(icfgNode.callee_unbound_reason)
  return (
    <div className="space-y-3 p-3">
      <SectionHeading>Statement</SectionHeading>
      <code className="block break-all rounded-md bg-muted/50 p-2 font-mono text-2xs">
        {icfgNode.source_text.trim()}
      </code>
      <div className="flex flex-wrap gap-1.5">
        <Chip variant="mono">
          {icfgNode.anchor.file}:{icfgNode.anchor.start_line}
        </Chip>
        <Chip variant="mono">{shortSignature(icfgNode.method.signature)}</Chip>
        {icfgNode.construct_kind ? (
          <Chip variant="outline">{icfgNode.construct_kind}</Chip>
        ) : null}
        {icfgNode.sink ? <Chip variant="outline">{icfgNode.sink}</Chip> : null}
      </div>
      {unopenable ? (
        // §5.4.2 T5: the node is on the canvas because the call runs; it has
        // no interior because there is no source to analyse. Saying which,
        // and why, is what separates "generated code" from a hole in the map.
        <div className="space-y-1 rounded-md border border-dashed p-2">
          <SectionHeading>No source to analyse</SectionHeading>
          <p className="text-2xs text-muted-foreground">{unopenable.detail}</p>
          {icfgNode.callee ? (
            <Chip variant="mono">
              {shortSignature(icfgNode.callee.signature)}
            </Chip>
          ) : null}
        </div>
      ) : null}
      {icfgNode.condition?.expression ? (
        <p className="flex items-start gap-1.5 text-2xs text-muted-foreground">
          <Split className="mt-0.5 size-3 shrink-0" aria-hidden />
          <span>
            branches on{" "}
            <code className="font-mono">{icfgNode.condition.expression}</code>
          </span>
        </p>
      ) : null}
      {nodeConditions.length > 0 ? (
        <div className="space-y-1">
          <SectionHeading>Governing conditions</SectionHeading>
          <div className="flex flex-wrap gap-1">
            {nodeConditions.map((condition) => (
              <Chip key={conditionLabel(condition)} variant="condition">
                <Split aria-hidden />
                {conditionLabel(condition)}
              </Chip>
            ))}
          </div>
          <p className="text-[10px] text-muted-foreground">
            Nearest governing branch on each path — a recorded heuristic, not
            full dominance analysis.
          </p>
        </div>
      ) : null}
      {nodeEdges.length > 0 ? (
        <div className="space-y-1.5">
          <SectionHeading>Remote calls at this site</SectionHeading>
          {nodeEdges.map((edge) => (
            <ResolutionLine key={edge.edge_id} edge={edge} />
          ))}
        </div>
      ) : null}
      <SourceSnippet
        snapshotId={detail.snapshot_id}
        serviceId={detail.service_id}
        anchor={icfgNode.anchor}
      />
      <OpenInSource
        file={icfgNode.anchor.file}
        line={icfgNode.anchor.start_line}
      />
    </div>
  )
}

function OpenInSource({ file, line }: { file: string; line: number }) {
  const storeApi = useWorkspaceStoreApi()
  return (
    <button
      className="inline-flex items-center gap-1 text-2xs text-muted-foreground transition-colors hover:text-foreground"
      onClick={() => storeApi.getState().revealSource(file, line)}
    >
      <ArrowUpRight className="size-3" aria-hidden />
      Open in source
    </button>
  )
}
