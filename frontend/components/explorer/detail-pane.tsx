"use client"

// Endpoint detail: identity header, then the ICFG at method granularity
// (the useful view) with raw JSON one tab away.
import { ArrowRight, Database, Globe, MailWarning } from "lucide-react"

import type { Endpoint, Icfg, RemoteEdgesView } from "@/lib/wadi/api"
import { rollupMethods, shortSignature } from "@/lib/wadi/rollup"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"

import { EndpointOverview } from "./endpoint-overview"
import { MethodBadge } from "./method-badge"

const SINK_META: Record<string, { label: string; icon: typeof Database }> = {
  db: { label: "database", icon: Database },
  "http-client": { label: "http call", icon: Globe },
  mq: { label: "queue", icon: MailWarning },
}

export function DetailPane({
  endpoint,
  icfg,
  isLoading,
  remoteEdges,
  edgesLoading,
  snapshotId,
  serviceId,
}: {
  endpoint: Endpoint
  icfg: Icfg | undefined
  isLoading: boolean
  remoteEdges: RemoteEdgesView | undefined
  edgesLoading: boolean
  snapshotId: string
  serviceId: string
}) {
  const methods = icfg ? rollupMethods(icfg) : []

  return (
    <div className="flex h-full min-w-0 flex-col">
      <header className="shrink-0 space-y-2 border-b px-4 py-3">
        <div className="flex items-center gap-2">
          <MethodBadge method={endpoint.http_method} />
          <span className="truncate font-mono text-sm font-medium">
            {endpoint.full_uri}
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
          <span className="truncate font-mono">
            {shortSignature(endpoint.handler.signature)}
          </span>
          <span>
            auth:{" "}
            <span className="font-medium">
              {endpoint.auth?.authenticated == null
                ? "unknown"
                : endpoint.auth.authenticated
                  ? "required"
                  : "open"}
            </span>
          </span>
          {icfg ? (
            <span className="font-mono">
              {icfg.nodes.length} nodes · {icfg.edges?.length ?? 0} edges ·{" "}
              {methods.length} methods
            </span>
          ) : null}
        </div>
      </header>

      {isLoading ? (
        <div className="space-y-2 p-4">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
        </div>
      ) : null}

      {icfg ? (
        <Tabs
          defaultValue="overview"
          className="flex min-h-0 flex-1 flex-col gap-0"
        >
          <div className="shrink-0 border-b px-4 py-2">
            <TabsList className="h-8">
              <TabsTrigger value="overview" className="text-xs">
                Overview
              </TabsTrigger>
              <TabsTrigger value="methods" className="text-xs">
                Flow · methods
              </TabsTrigger>
              <TabsTrigger value="json" className="text-xs">
                Raw ICFG
              </TabsTrigger>
            </TabsList>
          </div>

          <TabsContent
            value="overview"
            className="min-h-0 flex-1 overflow-y-auto"
          >
            <EndpointOverview
              endpoint={endpoint}
              icfg={icfg}
              remoteEdges={remoteEdges}
              edgesLoading={edgesLoading}
              snapshotId={snapshotId}
              serviceId={serviceId}
            />
          </TabsContent>

          <TabsContent
            value="methods"
            className="min-h-0 flex-1 overflow-y-auto"
          >
            <ol className="divide-y divide-border/60">
              {methods.map((method, index) => (
                <li key={method.id} className="px-4 py-3">
                  <div className="flex items-start gap-3">
                    <span className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full bg-muted font-mono text-[10px] text-muted-foreground">
                      {index === 0 ? <ArrowRight className="size-3" /> : index}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-mono text-sm">
                        {shortSignature(method.signature)}
                        {method.isRoot ? (
                          <span className="ml-2 text-[10px] font-semibold uppercase tracking-wider text-primary">
                            handler
                          </span>
                        ) : null}
                      </p>
                      {method.file ? (
                        <p className="mt-0.5 truncate font-mono text-xs text-muted-foreground">
                          {method.file}
                          {method.line ? `:${method.line}` : ""}
                        </p>
                      ) : null}
                      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                        <span className="font-mono text-[11px] text-muted-foreground">
                          {method.statementCount} stmt · {method.branchCount}{" "}
                          branch · {method.callCount} call
                        </span>
                        {method.sinks.map((sink) => {
                          const meta = SINK_META[sink]
                          const Icon = meta?.icon ?? Database
                          return (
                            <Badge
                              key={sink}
                              variant="outline"
                              className="gap-1 px-1.5 py-0 text-[10px]"
                            >
                              <Icon className="size-2.5" />
                              {meta?.label ?? sink}
                            </Badge>
                          )
                        })}
                        {method.badges
                          .filter((badge) => badge !== "endpoint")
                          .map((badge) => (
                            <Badge
                              key={badge}
                              variant="secondary"
                              className="px-1.5 py-0 text-[10px]"
                            >
                              {badge}
                            </Badge>
                          ))}
                      </div>
                    </div>
                  </div>
                </li>
              ))}
            </ol>
          </TabsContent>

          <TabsContent value="json" className="min-h-0 flex-1 overflow-auto">
            <pre className="p-4 font-mono text-xs leading-relaxed text-muted-foreground">
              {JSON.stringify(icfg, null, 2)}
            </pre>
          </TabsContent>
        </Tabs>
      ) : null}
    </div>
  )
}
