"use client"

// The wadi workbench: scope switchers in the chrome (system / snapshot),
// three fixed panes below — services, endpoints, endpoint detail. Panes never
// collapse or squeeze; scope changes happen in dropdowns, not columns.
// Deep links (§11 Phase 2.7): the URL is read ONCE on mount and mirrored on
// every selection change — reload restores the exact workspace.
import { useEffect, useMemo, useState } from "react"
import { useSearchParams } from "next/navigation"
import { Search } from "lucide-react"

import { cn } from "@/lib/utils"
import {
  useEndpoints,
  useIcfg,
  useRemoteEdges,
  useServices,
  useSnapshots,
  useSystems,
} from "@/lib/wadi/hooks"
import { constrain, parseUrlState, writeUrlState } from "@/lib/wadi/url-state"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { CoveragePane } from "@/components/coverage/coverage-pane"
import { SystemMapPane } from "@/components/map/system-map"

import { DetailPane } from "./detail-pane"
import { MethodBadge } from "./method-badge"
import { ScopeBar } from "./scope-bar"

const VIEWS = ["coverage", "map", "explorer"] as const
const TABS = ["overview", "flow", "methods", "json"] as const

export function Explorer() {
  const searchParams = useSearchParams()
  // Read once (lazy useState, never re-evaluated): after mount the URL is an
  // output of state, never an input.
  const [initial] = useState(() => parseUrlState(searchParams))

  const [systemId, setSystemId] = useState<string | null>(initial.system)
  const [snapshotId, setSnapshotId] = useState<string | null>(initial.snapshot)
  const [serviceId, setServiceId] = useState<string | null>(initial.service)
  const [endpointId, setEndpointId] = useState<string | null>(initial.endpoint)
  const [serviceFilter, setServiceFilter] = useState("")
  const [endpointFilter, setEndpointFilter] = useState("")
  // Coverage is the landing view (§5.4: every consumer surfaces it FIRST).
  const [view, setView] = useState<(typeof VIEWS)[number]>(
    constrain(initial.view, VIEWS, "coverage")
  )
  const [tab, setTab] = useState<(typeof TABS)[number]>(
    constrain(initial.tab, TABS, "overview")
  )
  // Flow-workspace method selection (§11 Phase 2.7 M3) — deep-linkable.
  const [nodeId, setNodeId] = useState<string | null>(initial.node)

  useEffect(() => {
    writeUrlState({
      system: systemId,
      snapshot: snapshotId,
      service: serviceId,
      endpoint: endpointId,
      view: view === "coverage" ? null : view,
      tab: tab === "overview" ? null : tab,
      node: nodeId,
    })
  }, [systemId, snapshotId, serviceId, endpointId, view, tab, nodeId])

  const systems = useSystems()
  const snapshots = useSnapshots(systemId)
  const services = useServices(snapshotId)
  const endpoints = useEndpoints(snapshotId, serviceId)
  const icfg = useIcfg(snapshotId, endpointId)
  const remoteEdges = useRemoteEdges(snapshotId, serviceId)

  // Sensible defaults: first system, its newest succeeded snapshot.
  useEffect(() => {
    if (systemId === null && systems.data && systems.data.length > 0) {
      setSystemId(systems.data[0].id)
    }
  }, [systemId, systems.data])

  useEffect(() => {
    if (
      systemId &&
      snapshotId === null &&
      snapshots.data &&
      snapshots.data.length > 0
    ) {
      const newest =
        snapshots.data.find((s) => s.status === "succeeded") ??
        snapshots.data[0]
      setSnapshotId(newest.id)
    }
  }, [systemId, snapshotId, snapshots.data])

  const filteredServices = useMemo(() => {
    const list = services.data ?? []
    const query = serviceFilter.trim().toLowerCase()
    return query
      ? list.filter((s) => s.name.toLowerCase().includes(query))
      : list
  }, [services.data, serviceFilter])

  const filteredEndpoints = useMemo(() => {
    const list = endpoints.data ?? []
    const query = endpointFilter.trim().toLowerCase()
    return query
      ? list.filter(
          (e) =>
            e.full_uri.toLowerCase().includes(query) ||
            e.http_method.toLowerCase().includes(query)
        )
      : list
  }, [endpoints.data, endpointFilter])

  const selectedService = services.data?.find((s) => s.service_id === serviceId)
  const selectedEndpoint = endpoints.data?.find((e) => e.id === endpointId)
  const totalEndpoints = (services.data ?? []).reduce(
    (sum, s) => sum + (s.endpoint_count ?? 0),
    0
  )

  const anyError = [systems, snapshots, services, endpoints, icfg].find(
    (q) => q.isError
  )

  return (
    <div className="flex h-[calc(100dvh-4rem)] flex-col">
      <ScopeBar
        systems={systems.data ?? []}
        snapshots={snapshots.data ?? []}
        systemId={systemId}
        snapshotId={snapshotId}
        onSystem={(id) => {
          setSystemId(id)
          setSnapshotId(null)
          setServiceId(null)
          setEndpointId(null)
        }}
        onSnapshot={(id) => {
          setSnapshotId(id)
          setServiceId(null)
          setEndpointId(null)
        }}
        summary={
          services.data
            ? `${services.data.length} services · ${totalEndpoints} endpoints`
            : undefined
        }
      />

      {anyError ? (
        <p className="border-b bg-destructive/5 px-4 py-2 text-sm text-destructive">
          {String(anyError.error)}
        </p>
      ) : null}

      <div className="flex shrink-0 items-center gap-1 border-b px-4 py-1.5">
        {(
          [
            ["coverage", "Coverage"],
            ["map", "Map"],
            ["explorer", "Explorer"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            onClick={() => setView(id)}
            className={cn(
              "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
              view === id
                ? "bg-muted text-foreground"
                : "text-muted-foreground hover:text-foreground"
            )}
            aria-pressed={view === id}
          >
            {label}
          </button>
        ))}
        {view === "coverage" ? (
          <span className="ml-2 text-[11px] text-muted-foreground">
            what the map knows it doesn&apos;t know — read this first
          </span>
        ) : null}
      </div>

      {view === "coverage" ? (
        <div className="flex min-h-0 flex-1">
          <CoveragePane snapshotId={snapshotId} />
        </div>
      ) : view === "map" ? (
        <div className="flex min-h-0 flex-1">
          <SystemMapPane
            snapshotId={snapshotId}
            active={view === "map"}
            onOpenService={(id) => {
              setServiceId(id)
              setEndpointId(null)
              setView("explorer")
            }}
          />
        </div>
      ) : (
        <div className="flex min-h-0 flex-1 divide-x">
          {/* Services */}
          <section className="flex w-72 shrink-0 flex-col lg:w-80">
            <PaneHeader
              label="Services"
              count={services.data?.length}
              filter={serviceFilter}
              onFilter={setServiceFilter}
              placeholder="Filter services"
            />
            <div className="min-h-0 flex-1 overflow-y-auto">
              {services.isPending && snapshotId ? <PaneSkeleton /> : null}
              {!snapshotId ? (
                <PaneEmpty>Select a system above</PaneEmpty>
              ) : null}
              {filteredServices.map((service) => (
                <button
                  key={service.service_id}
                  onClick={() => {
                    setServiceId(service.service_id)
                    setEndpointId(null)
                    setEndpointFilter("")
                  }}
                  className={cn(
                    "flex w-full items-center gap-2 border-l-2 border-transparent px-3 py-2 text-left transition-colors hover:bg-muted/50",
                    serviceId === service.service_id &&
                      "border-primary bg-muted/60"
                  )}
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">
                      {service.name}
                    </p>
                    <p className="truncate font-mono text-[11px] text-muted-foreground">
                      {service.build_root}
                      {(service.async_roots ?? []).length > 0 && (
                        <span>
                          {" · "}
                          {(service.async_roots ?? []).length} async root
                          {(service.async_roots ?? []).length === 1 ? "" : "s"}
                        </span>
                      )}
                    </p>
                  </div>
                  <span
                    className={cn(
                      "shrink-0 rounded-full px-2 py-0.5 font-mono text-[11px] tabular-nums",
                      service.endpoint_count
                        ? "bg-primary/10 text-primary"
                        : "bg-muted text-muted-foreground"
                    )}
                  >
                    {service.endpoint_count ?? 0}
                  </span>
                </button>
              ))}
              {services.data &&
              filteredServices.length === 0 &&
              services.data.length > 0 ? (
                <PaneEmpty>No match for “{serviceFilter}”</PaneEmpty>
              ) : null}
            </div>
          </section>

          {/* Endpoints */}
          <section className="flex w-[24rem] shrink-0 flex-col xl:w-[28rem]">
            <PaneHeader
              label="Endpoints"
              count={endpoints.data?.length}
              filter={endpointFilter}
              onFilter={setEndpointFilter}
              placeholder="Filter endpoints"
              hint={selectedService?.name}
            />
            <div className="min-h-0 flex-1 overflow-y-auto">
              {endpoints.isPending && serviceId ? <PaneSkeleton /> : null}
              {!serviceId ? <PaneEmpty>Select a service</PaneEmpty> : null}
              {endpoints.data?.length === 0 ? (
                <PaneEmpty>No endpoints extracted for this service</PaneEmpty>
              ) : null}
              {filteredEndpoints.map((endpoint) => (
                <button
                  key={endpoint.id}
                  onClick={() => setEndpointId(endpoint.id)}
                  className={cn(
                    "flex w-full items-center gap-2.5 border-l-2 border-transparent px-3 py-2 text-left transition-colors hover:bg-muted/50",
                    endpointId === endpoint.id && "border-primary bg-muted/60"
                  )}
                >
                  <MethodBadge method={endpoint.http_method} />
                  <span className="min-w-0 flex-1 truncate font-mono text-xs">
                    {endpoint.full_uri}
                  </span>
                </button>
              ))}
              {endpoints.data &&
              filteredEndpoints.length === 0 &&
              endpoints.data.length > 0 ? (
                <PaneEmpty>No match for “{endpointFilter}”</PaneEmpty>
              ) : null}
            </div>
          </section>

          {/* Detail */}
          <section className="flex min-w-0 flex-1 flex-col">
            {selectedEndpoint ? (
              <DetailPane
                endpoint={selectedEndpoint}
                icfg={icfg.data}
                isLoading={icfg.isPending}
                remoteEdges={remoteEdges.data}
                edgesLoading={remoteEdges.isPending}
                snapshotId={snapshotId as string}
                serviceId={serviceId as string}
                tab={tab}
                onTabChange={(next) =>
                  setTab(constrain(next, TABS, "overview"))
                }
                selectedMethodId={nodeId}
                onSelectMethod={setNodeId}
              />
            ) : (
              <div className="flex flex-1 flex-col items-center justify-center gap-2 text-center">
                <p className="font-mono text-xs uppercase tracking-[0.2em] text-muted-foreground/60">
                  wadi · ground truth
                </p>
                <p className="max-w-64 text-sm text-muted-foreground">
                  Pick an endpoint to inspect its flow down to every database
                  and remote call.
                </p>
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  )
}

function PaneHeader(props: {
  label: string
  count?: number
  filter: string
  onFilter: (value: string) => void
  placeholder: string
  hint?: string
}) {
  return (
    <div className="shrink-0 space-y-2 border-b px-3 py-2.5">
      <div className="flex items-baseline justify-between">
        <h2 className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
          {props.label}
          {props.count !== undefined ? (
            <span className="ml-1.5 font-mono tabular-nums text-muted-foreground/60">
              {props.count}
            </span>
          ) : null}
        </h2>
        {props.hint ? (
          <span className="truncate pl-2 font-mono text-[11px] text-muted-foreground/60">
            {props.hint}
          </span>
        ) : null}
      </div>
      <div className="relative">
        <Search className="absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground/50" />
        <Input
          value={props.filter}
          onChange={(event) => props.onFilter(event.target.value)}
          placeholder={props.placeholder}
          className="h-7 border-none bg-muted/50 pl-7 text-xs shadow-none focus-visible:ring-1"
        />
      </div>
    </div>
  )
}

function PaneSkeleton() {
  return (
    <div className="space-y-2 p-3">
      {Array.from({ length: 6 }).map((_, index) => (
        <Skeleton key={index} className="h-9 w-full" />
      ))}
    </div>
  )
}

function PaneEmpty({ children }: { children: React.ReactNode }) {
  return <p className="px-3 py-6 text-sm text-muted-foreground">{children}</p>
}
