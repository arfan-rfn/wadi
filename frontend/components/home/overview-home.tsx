"use client"

// The overview home (§11 Phase 2.8): orientation only — coverage first
// (§5.4), the system map, and a 2-column services/endpoints browser. The
// endpoint deep-dive lives on its own routed page; opening an endpoint is a
// NAVIGATION, so browser back returns here.
import { useEffect, useMemo, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"

import { cn } from "@/lib/utils"
import { useEndpoints, useServices } from "@/lib/wadi/hooks"
import {
  constrain,
  endpointPath,
  HOME_VIEWS,
  type HomeView,
} from "@/lib/wadi/routes"
import { Skeleton } from "@/components/ui/skeleton"
import { CoveragePane } from "@/components/coverage/coverage-pane"
import { SystemMapPane } from "@/components/map/system-map"
import { EmptyState } from "@/components/shared/empty-state"
import { PanelHeader } from "@/components/shared/panel-header"

import { EndpointRow } from "./endpoint-list"

export function OverviewHome({ snapshotId }: { snapshotId: string }) {
  const router = useRouter()
  const searchParams = useSearchParams()
  // Read once (lazy useState): after mount the URL mirrors state, never
  // drives it — the pre-2.8 idiom, kept for the peer views of one scope.
  const [initial] = useState(() => ({
    view: constrain(searchParams.get("view"), HOME_VIEWS, "coverage"),
    service: searchParams.get("service"),
  }))
  const [view, setView] = useState<HomeView>(initial.view)
  const [serviceId, setServiceId] = useState<string | null>(initial.service)
  const [serviceFilter, setServiceFilter] = useState("")
  const [endpointFilter, setEndpointFilter] = useState("")

  useEffect(() => {
    if (typeof window === "undefined") return
    const params = new URLSearchParams()
    if (view !== "coverage") params.set("view", view)
    if (serviceId) params.set("service", serviceId)
    const query = params.toString()
    const next = query
      ? `${window.location.pathname}?${query}`
      : window.location.pathname
    const current = `${window.location.pathname}${window.location.search}`
    if (next !== current) window.history.replaceState(null, "", next)
  }, [view, serviceId])

  const services = useServices(snapshotId)
  const endpoints = useEndpoints(snapshotId, serviceId)

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

  return (
    <>
      <div className="flex shrink-0 items-center gap-1 border-b px-4 py-1.5">
        {(
          [
            ["coverage", "Coverage"],
            ["map", "Map"],
            ["services", "Services"],
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
          <span className="ml-2 text-2xs text-muted-foreground">
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
              setView("services")
            }}
          />
        </div>
      ) : (
        <div className="flex min-h-0 flex-1 divide-x">
          <section className="flex w-72 shrink-0 flex-col lg:w-80">
            <PanelHeader
              label="Services"
              count={services.data?.length}
              filter={serviceFilter}
              onFilter={setServiceFilter}
              placeholder="Filter services"
            />
            <div className="min-h-0 flex-1 overflow-y-auto">
              {services.isPending ? <ListSkeleton /> : null}
              {filteredServices.map((service) => (
                <button
                  key={service.service_id}
                  onClick={() => {
                    setServiceId(service.service_id)
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
                    <p className="truncate font-mono text-2xs text-muted-foreground">
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
                      "shrink-0 rounded-full px-2 py-0.5 font-mono text-2xs tabular-nums",
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
                <EmptyState>
                  No match for &ldquo;{serviceFilter}&rdquo;
                </EmptyState>
              ) : null}
            </div>
          </section>

          <section className="flex min-w-0 flex-1 flex-col">
            <PanelHeader
              label="Endpoints"
              count={endpoints.data?.length}
              filter={endpointFilter}
              onFilter={setEndpointFilter}
              placeholder="Filter endpoints"
              hint={selectedService?.name}
            />
            <div className="min-h-0 flex-1 overflow-y-auto">
              {endpoints.isPending && serviceId ? <ListSkeleton /> : null}
              {!serviceId ? (
                <EmptyState>
                  Select a service to browse its endpoints — open one for the
                  full end-to-end flow.
                </EmptyState>
              ) : null}
              {endpoints.data?.length === 0 ? (
                <EmptyState>No endpoints extracted for this service</EmptyState>
              ) : null}
              {filteredEndpoints.map((endpoint) => (
                <EndpointRow
                  key={endpoint.id}
                  endpoint={endpoint}
                  onOpen={(e) => router.push(endpointPath(snapshotId, e.id))}
                />
              ))}
              {endpoints.data &&
              filteredEndpoints.length === 0 &&
              endpoints.data.length > 0 ? (
                <EmptyState>
                  No match for &ldquo;{endpointFilter}&rdquo;
                </EmptyState>
              ) : null}
            </div>
          </section>
        </div>
      )}
    </>
  )
}

function ListSkeleton() {
  return (
    <div className="space-y-2 p-3">
      {Array.from({ length: 6 }).map((_, index) => (
        <Skeleton key={index} className="h-9 w-full" />
      ))}
    </div>
  )
}
