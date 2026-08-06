"use client"

// The overview home (§11 Phase 2.8, §5.2.9 UI): orientation, and the first
// two tiers of the endpoint read — skim the rows (security on line 2), then
// peek the contract in place. The third tier, the flow, is its own routed
// page; opening it is a NAVIGATION, so browser back returns here.
//
// Responsive shape: the SMALL layout is the baseline (one column at a time,
// drilled into) and widens into services | endpoints | peek at xl. That
// direction matters — `useMediaQuery` reports false until after hydration, so
// the pre-hydration frame must be the narrow layout, never a broken wide one.
import { useEffect, useMemo, useState } from "react"
import { useSearchParams } from "next/navigation"
import { ArrowLeft } from "lucide-react"

import { BREAKPOINT, useMediaQuery } from "@/lib/hooks/use-media-query"
import { useMounted } from "@/lib/hooks/use-mounted"
import { cn } from "@/lib/utils"
import {
  useEndpointDependencies,
  useEndpoints,
  useServices,
  useSystemAuth,
} from "@/lib/wadi/hooks"
import { RolePaletteProvider } from "@/lib/wadi/role-colors"
import { constrain, HOME_VIEWS, type HomeView } from "@/lib/wadi/routes"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"
import { CoveragePane } from "@/components/coverage/coverage-pane"
import { SystemMapPane } from "@/components/map/system-map"
import { EmptyState } from "@/components/shared/empty-state"
import { PanelHeader } from "@/components/shared/panel-header"

import { AuthPane } from "./auth-pane"
import { EndpointRow, unreadKindsOf } from "./endpoint-list"
import { EndpointPeek } from "./endpoint-peek"
import { RoleLegend, rolesInSnapshot, type RoleFilter } from "./role-legend"

export function OverviewHome({ snapshotId }: { snapshotId: string }) {
  const searchParams = useSearchParams()
  // Read once (lazy useState): after mount the URL mirrors state, never
  // drives it — the pre-2.8 idiom, kept for the peer views of one scope.
  const [initial] = useState(() => ({
    view: constrain(searchParams.get("view"), HOME_VIEWS, "coverage"),
    service: searchParams.get("service"),
    endpoint: searchParams.get("endpoint"),
  }))
  const [view, setView] = useState<HomeView>(initial.view)
  const [serviceId, setServiceId] = useState<string | null>(initial.service)
  const [endpointId, setEndpointId] = useState<string | null>(initial.endpoint)
  const [serviceFilter, setServiceFilter] = useState("")
  const [endpointFilter, setEndpointFilter] = useState("")
  const [roleFilter, setRoleFilter] = useState<RoleFilter>(null)
  // xl is where three columns stop being cramped; below it the peek is a
  // sheet so it never squeezes the list it exists to annotate.
  const inlinePeek = useMediaQuery(BREAKPOINT.xl)

  useEffect(() => {
    if (typeof window === "undefined") return
    const params = new URLSearchParams()
    if (view !== "coverage") params.set("view", view)
    if (serviceId) params.set("service", serviceId)
    if (endpointId) params.set("endpoint", endpointId)
    const query = params.toString()
    const next = query
      ? `${window.location.pathname}?${query}`
      : window.location.pathname
    const current = `${window.location.pathname}${window.location.search}`
    if (next !== current) window.history.replaceState(null, "", next)
  }, [view, serviceId, endpointId])

  const services = useServices(snapshotId)
  const endpoints = useEndpoints(snapshotId, serviceId)
  // The snapshot-wide role vocabulary powers the legend; it is the same read
  // the Auth view uses, so switching between them costs nothing.
  const auth = useSystemAuth(view === "services" || view === "auth", snapshotId)
  // One read per service: cross-service calls are the core extracted fact, so
  // the rows show them rather than hiding them behind a click.
  const dependencies = useEndpointDependencies(
    view === "services" ? snapshotId : null,
    serviceId
  )

  // Every list below comes from a client fetch, so the server renders the
  // skeleton. Hydrating against a warm query cache, the client would have the
  // rows on its FIRST render and emit `<button>` where the server emitted a
  // `<div>` — a DOM-shape disagreement, which fails hydration outright and
  // regenerates the tree. Holding the lists empty until mounted makes the
  // first client render identical to the server's, warm cache or cold.
  const mounted = useMounted()
  const servicesPending = !mounted || services.isPending
  const endpointsPending = !mounted || endpoints.isPending

  const filteredServices = useMemo(() => {
    if (!mounted) return []
    const list = services.data ?? []
    const query = serviceFilter.trim().toLowerCase()
    return query
      ? list.filter((s) => s.name.toLowerCase().includes(query))
      : list
  }, [mounted, services.data, serviceFilter])

  const filteredEndpoints = useMemo(() => {
    if (!mounted) return []
    const list = endpoints.data ?? []
    const query = endpointFilter.trim().toLowerCase()
    const byText = query
      ? list.filter(
          (e) =>
            e.full_uri.toLowerCase().includes(query) ||
            e.http_method.toLowerCase().includes(query)
        )
      : list
    if (!roleFilter) return byText
    if (roleFilter.kind === "open")
      return byText.filter(
        (e) => e.auth?.authenticated === false && unreadKindsOf(e).length === 0
      )
    return byText.filter((e) => (e.auth?.roles ?? []).includes(roleFilter.role))
  }, [mounted, endpoints.data, endpointFilter, roleFilter])

  const selectedService = services.data?.find((s) => s.service_id === serviceId)
  const selectedEndpoint =
    endpoints.data?.find((e) => e.id === endpointId) ?? null

  // A selection from another service is stale the moment the service changes.
  useEffect(() => {
    setEndpointId(null)
  }, [serviceId])

  const snapshotRoles = useMemo(
    () => rolesInSnapshot(auth.data).map((entry) => entry.role),
    [auth.data]
  )

  const peek = (
    <EndpointPeek
      snapshotId={snapshotId}
      endpoint={selectedEndpoint}
      className="h-full"
    />
  )

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
              "cursor-pointer rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
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
        ) : view === "auth" ? (
          <span className="ml-2 text-2xs text-muted-foreground">
            who can reach what — and where the answer is withheld
          </span>
        ) : null}
      </div>

      {view === "coverage" ? (
        <div className="flex min-h-0 flex-1">
          <CoveragePane snapshotId={snapshotId} />
        </div>
      ) : view === "auth" ? (
        <div className="flex min-h-0 flex-1">
          <AuthPane snapshotId={snapshotId} active={view === "auth"} />
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
        // One palette for the whole snapshot: colours are assigned against
        // the full role SET, so a role never changes hue as you move between
        // services (and two roles can never share one, §5.2.9 UI).
        <RolePaletteProvider roles={snapshotRoles}>
          <div className="flex min-h-0 flex-1 divide-x">
            {/* Below md the services list yields entirely once a service is
              picked — one column at a time is the only honest narrow layout,
              and the picker in the endpoints header gets you back. */}
            <section
              className={cn(
                "flex shrink-0 flex-col md:w-56 lg:w-64 xl:w-72",
                serviceId ? "hidden md:flex" : "flex w-full"
              )}
            >
              <PanelHeader
                label="Services"
                count={services.data?.length}
                filter={serviceFilter}
                onFilter={setServiceFilter}
                placeholder="Filter services"
              />
              <ScrollArea className="min-h-0 flex-1">
                {servicesPending ? <ListSkeleton /> : null}
                {/* Without this the pane renders BLANK on a failed fetch: every
                  empty state below is guarded on `.data`, which is undefined,
                  and `isPending` is already false. */}
                {mounted && services.isError ? (
                  <EmptyState>
                    Could not load services —{" "}
                    {(services.error as Error).message}
                  </EmptyState>
                ) : null}
                {filteredServices.map((service) => (
                  <button
                    key={service.service_id}
                    onClick={() => {
                      setServiceId(service.service_id)
                      setEndpointFilter("")
                    }}
                    type="button"
                    aria-current={
                      serviceId === service.service_id ? "true" : undefined
                    }
                    className={cn(
                      // Symmetric selection: an inset rounded-sm block, fill plus a
                      // full ring. Never an edge bar.
                      "mx-1.5 my-0.5 flex w-[calc(100%-0.75rem)] cursor-pointer items-center gap-2 rounded-lg px-2 py-2 text-left transition-colors",
                      "hover:bg-muted/50 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
                      serviceId === service.service_id &&
                        "bg-muted/80 ring-1 ring-primary/30 ring-inset"
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
                            {(service.async_roots ?? []).length === 1
                              ? ""
                              : "s"}
                          </span>
                        )}
                      </p>
                      {/* What this service lets REACH it — CORS/CSRF are
                          declared per service, so the coverage rollup cannot
                          say which one declared what. On its own row: appended
                          to the line above it fell off the end of a `truncate`
                          and was invisible on every service that had one. */}
                      {(service.request_policies ?? []).length > 0 && (
                        <div className="mt-1 flex flex-wrap gap-1">
                          {[
                            ...new Set(
                              (service.request_policies ?? []).map(
                                (p) => p.kind
                              )
                            ),
                          ].map((kind) => (
                            <span
                              key={kind}
                              className="rounded-full border px-1.5 font-mono text-2xs text-muted-foreground"
                              title="Gates which origin or request shape may reach this service — not which principal"
                            >
                              {kind}
                            </span>
                          ))}
                        </div>
                      )}
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
              </ScrollArea>
            </section>

            <section
              className={cn(
                "flex min-w-0 flex-1 flex-col",
                serviceId ? "flex" : "hidden md:flex"
              )}
            >
              <PanelHeader
                label="Endpoints"
                count={endpoints.data?.length}
                filter={endpointFilter}
                onFilter={setEndpointFilter}
                placeholder="Filter endpoints"
                hint={selectedService?.name}
              />
              {/* Narrow only: the way back out of the drill-down. */}
              {serviceId ? (
                <button
                  type="button"
                  onClick={() => setServiceId(null)}
                  className={cn(
                    "flex items-center gap-1.5 border-b px-3 py-1.5 text-left text-2xs text-muted-foreground transition-colors md:hidden",
                    "hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                  )}
                >
                  <ArrowLeft aria-hidden className="size-3" />
                  All services
                </button>
              ) : null}
              <RoleLegend
                auth={auth.data}
                value={roleFilter}
                onChange={setRoleFilter}
              />
              <ScrollArea className="min-h-0 flex-1">
                {endpointsPending && serviceId ? <ListSkeleton /> : null}
                {mounted && endpoints.isError ? (
                  <EmptyState>
                    Could not load endpoints —{" "}
                    {(endpoints.error as Error).message}
                  </EmptyState>
                ) : null}
                {!serviceId ? (
                  <EmptyState>
                    Select a service to browse its endpoints — open one for the
                    full end-to-end flow.
                  </EmptyState>
                ) : null}
                {mounted && endpoints.data?.length === 0 ? (
                  <EmptyState>
                    No endpoints extracted for this service
                  </EmptyState>
                ) : null}
                {filteredEndpoints.map((endpoint) => (
                  <EndpointRow
                    key={endpoint.id}
                    endpoint={endpoint}
                    dependencies={
                      dependencies.data?.dependencies?.[endpoint.id]
                    }
                    selected={endpoint.id === endpointId}
                    onOpen={(e) => setEndpointId(e.id)}
                  />
                ))}
                {endpoints.data &&
                filteredEndpoints.length === 0 &&
                endpoints.data.length > 0 ? (
                  <EmptyState>
                    {roleFilter
                      ? "No endpoint here matches that role filter."
                      : `No match for \u201c${endpointFilter}\u201d`}
                  </EmptyState>
                ) : null}
              </ScrollArea>
            </section>

            {/* The peek is one component in one place in the tree — only its
              PRESENTATION changes with width, so selection, scroll position
              and open sections survive a resize. */}
            {inlinePeek ? (
              <section className="flex w-[22rem] shrink-0 flex-col 2xl:w-[26rem]">
                {peek}
              </section>
            ) : (
              <Sheet
                open={selectedEndpoint !== null}
                onOpenChange={(open) => {
                  if (!open) setEndpointId(null)
                }}
              >
                <SheetContent
                  side="right"
                  className="w-full gap-0 p-0 sm:max-w-[26rem]"
                >
                  <SheetTitle className="sr-only">
                    {selectedEndpoint
                      ? `${selectedEndpoint.http_method} ${selectedEndpoint.full_uri}`
                      : "Endpoint details"}
                  </SheetTitle>
                  {peek}
                </SheetContent>
              </Sheet>
            )}
          </div>
        </RolePaletteProvider>
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
