"use client"

// The endpoint peek (§5.2.9 UI): the contract, without leaving the list.
//
// The middle tier of a three-step read — skim the rows, peek the contract,
// then commit to the flow. It answers "what does this accept, what does it
// return, and who can call it" from one detail fetch, and it is also where
// the endpoint-level honesty surfaces live now that the workspace is purely
// the flow: the auth evidence with its source anchor, and the count of calls
// whose bodies cannot be opened (§5.4.2 T5).
import Link from "next/link"
import {
  ArrowRight,
  CornerDownRight,
  ExternalLink,
  KeyRound,
} from "lucide-react"

import { cn } from "@/lib/utils"
import type { Endpoint } from "@/lib/wadi/api"
import { useEndpointDetail } from "@/lib/wadi/hooks"
import { endpointPath } from "@/lib/wadi/routes"
import { unopenableCopy } from "@/lib/wadi/unopenable"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Skeleton } from "@/components/ui/skeleton"
import { MethodBadge } from "@/components/explorer/method-badge"
import {
  authorityModelNote,
  gatesRequests,
} from "@/components/shared/auth-chip"
import { CollapsibleSection } from "@/components/shared/collapsible-section"
import { EmptyState } from "@/components/shared/empty-state"

import { SecurityLine } from "./endpoint-list"
import { SchemaTree } from "./schema-tree"

const TARGET_NOTE: Record<string, string> = {
  analyzed: "Another analyzed service in this snapshot — its endpoint is known",
  external: "A host outside the analyzed system",
  placeholder: "Named in config but not analyzed — no endpoints known",
  undetermined:
    "The target could not be resolved; the coverage report says why",
}

function ParamRow({
  name,
  location,
  typeName,
  required,
}: {
  name: string
  location: string
  typeName: string | null | undefined
  required: boolean
}) {
  return (
    // Borderless rows (the GitBook API-reference idiom): a hairline between
    // entries, no cell grid. The grid was what made this read as a spreadsheet.
    <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 border-t py-1.5 first:border-t-0">
      <span className="font-mono text-xs">{name}</span>
      <span className="font-mono text-2xs text-muted-foreground">
        {location}
        {typeName
          ? ` · ${typeName.substring(typeName.lastIndexOf(".") + 1)}`
          : ""}
      </span>
      {required ? (
        <span className="rounded-full border border-warn/35 px-1.5 text-2xs tracking-wide text-warn uppercase">
          required
        </span>
      ) : null}
    </div>
  )
}

export function EndpointPeek({
  snapshotId,
  endpoint,
  className,
}: {
  snapshotId: string
  endpoint: Endpoint | null
  className?: string
}) {
  const detail = useEndpointDetail(snapshotId, endpoint?.id ?? null)

  if (!endpoint)
    return (
      <div className={cn("flex min-h-0 flex-col", className)}>
        <EmptyState className="p-6">
          Select an endpoint to see what it accepts, what it returns, and who
          can call it.
        </EmptyState>
      </div>
    )

  const params = endpoint.params ?? []
  const allEvidence = endpoint.auth?.evidence ?? []
  // Split by whether the record GATES. An authority-model says what a grant
  // means, not who gets through, so listing it here would claim a
  // UserDetailsService guards the endpoint — and would hide the "nothing gates
  // this" state on a route that really has no guard (§5.2.10 T7).
  const evidence = allEvidence.filter((item) => gatesRequests(item.kind))
  const authorityModel = allEvidence.filter(
    (item) => item.kind === "authority-model"
  )
  const mechanisms = endpoint.auth?.mechanisms ?? []
  const unopenable = detail.data?.unopenable_calls ?? []
  const outbound = detail.data?.outbound ?? []

  return (
    <div className={cn("flex min-h-0 flex-col bg-card", className)}>
      <header className="flex shrink-0 flex-col gap-2 border-b p-3.5">
        <div className="flex flex-wrap items-center gap-2">
          <MethodBadge method={endpoint.http_method} />
          <SecurityLine endpoint={endpoint} />
        </div>
        <h2 className="font-mono text-sm leading-snug break-all">
          {endpoint.full_uri}
        </h2>
        <p
          className="truncate font-mono text-2xs text-muted-foreground"
          title={endpoint.handler.signature}
        >
          {endpoint.handler.signature.split(":")[0]}
        </p>
      </header>

      <ScrollArea className="min-h-0 flex-1">
        <CollapsibleSection
          title="Calls out"
          count={detail.isPending ? null : outbound.length}
        >
          {detail.isPending ? (
            <Skeleton className="h-10 w-full" />
          ) : outbound.length === 0 ? (
            <p className="text-2xs text-muted-foreground">
              {detail.data?.stitched === false
                ? "The stitcher has not run for this snapshot, so outbound calls are not yet known."
                : "No remote calls are reached from this endpoint."}
            </p>
          ) : (
            <ul className="space-y-1.5">
              {outbound.map((edge) => (
                <li
                  key={edge.edge_id}
                  className="rounded-md border bg-muted/25 px-2 py-1.5"
                >
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    {edge.http_verb ? (
                      <MethodBadge method={edge.http_verb} className="w-11" />
                    ) : (
                      <span className="w-11 shrink-0 text-center font-mono text-2xs text-muted-foreground">
                        verb?
                      </span>
                    )}
                    <span className="min-w-0 flex-1 truncate font-mono text-xs">
                      {edge.target_service_name ??
                        edge.external_host ??
                        "target undetermined"}
                    </span>
                    <span
                      className="shrink-0 rounded-full border px-1.5 text-2xs text-muted-foreground"
                      title={TARGET_NOTE[edge.target_kind]}
                    >
                      {edge.target_kind}
                    </span>
                    <span
                      className="shrink-0 rounded-full border px-1.5 text-2xs text-muted-foreground"
                      title="How sure the match is — not how often it runs"
                    >
                      {edge.confidence}
                    </span>
                    {/* Whether the caller's credentials cross THIS call. The
                        negative is only shown where it is provable, so absence
                        of a chip is not a claim either way (§5.2.11 T4). */}
                    {edge.auth_propagation_state &&
                      edge.auth_propagation_state !== "undetermined" && (
                        <span
                          className="shrink-0 rounded-full border px-1.5 text-2xs text-muted-foreground"
                          title={
                            edge.auth_propagation_state === "forwarded"
                              ? `The caller's credentials are passed on${edge.auth_propagation ? ` (${edge.auth_propagation})` : ""}`
                              : "This call builds its request with no headers at all — the caller's token does not travel with it"
                          }
                        >
                          {edge.auth_propagation_state === "forwarded"
                            ? "token fwd"
                            : "no token"}
                        </span>
                      )}
                  </div>
                  {edge.target_simplified_uri ? (
                    <p className="mt-1 flex items-center gap-1.5 pl-[3.25rem] font-mono text-2xs text-muted-foreground">
                      <CornerDownRight
                        aria-hidden
                        className="size-2.5 shrink-0"
                      />
                      <span className="truncate">
                        {edge.target_http_method ?? ""}{" "}
                        {edge.target_simplified_uri}
                      </span>
                    </p>
                  ) : edge.url ? (
                    <p className="mt-1 truncate pl-[3.25rem] font-mono text-2xs text-muted-foreground">
                      {edge.url}
                    </p>
                  ) : null}
                  {edge.auth_propagation ? (
                    <p className="mt-1 flex items-center gap-1.5 pl-[3.25rem] text-2xs text-muted-foreground">
                      <KeyRound aria-hidden className="size-2.5 shrink-0" />
                      forwards the caller&apos;s credentials
                    </p>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
          {unopenable.length > 0 ? (
            <div className="mt-2.5 space-y-1">
              <div className="flex flex-wrap gap-1.5">
                {unopenable.map((entry) => {
                  const copy = unopenableCopy(entry.reason)
                  return (
                    <span
                      key={entry.reason}
                      title={copy?.detail}
                      className="rounded-full border px-2 py-0.5 font-mono text-2xs text-muted-foreground"
                    >
                      {entry.call_count} {copy?.badge ?? entry.reason}
                    </span>
                  )
                })}
              </div>
              <p className="text-2xs text-muted-foreground">
                Drawn in the flow — they run — but their bodies are generated,
                inherited or third-party, so there is no source to open.
              </p>
            </div>
          ) : null}
        </CollapsibleSection>
        <CollapsibleSection title="Access">
          {evidence.length === 0 ? (
            <p className="text-2xs text-muted-foreground">
              Nothing that gates this endpoint was found — no security rule, no
              annotation, no filter.
            </p>
          ) : (
            <ul className="space-y-2">
              {evidence.map((item, index) => (
                <li key={index} className="space-y-1">
                  <p
                    className={cn(
                      "rounded-md bg-muted px-2 py-1.5 font-mono text-2xs leading-relaxed break-all",
                      item.active === false &&
                        "text-muted-foreground line-through"
                    )}
                  >
                    {item.detail}
                  </p>
                  {item.active === false ? (
                    <p className="text-2xs text-muted-foreground">
                      not in effect — {item.inactive_reason}
                    </p>
                  ) : item.resolution === "opaque" ? (
                    <p className="text-2xs text-warn">
                      could not be read — no claim is made either way
                    </p>
                  ) : item.resolution === "partial" ? (
                    <p className="text-2xs text-warn">
                      partly read — the role list may be incomplete
                    </p>
                  ) : null}
                  {/* Scope, not readability (§5.2.13). A rule read perfectly
                      can still cover part of a route: `/contest/public/**`
                      reaches `/contest/{contestId}/camp/create` only when that
                      id is literally `public`. Without this line the reader
                      sees a `permitAll` sitting on a protected endpoint and
                      has to open the code to find out why it did not win. */}
                  {item.active !== false && item.covers_route === false ? (
                    <p className="text-2xs text-muted-foreground">
                      covers part of this route — it applies to some requests
                      this endpoint serves, not all of them
                    </p>
                  ) : null}
                  {item.anchor ? (
                    <p className="font-mono text-2xs break-all text-muted-foreground">
                      ↳ {item.anchor.file}:{item.anchor.start_line}
                    </p>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
          {authorityModel.length > 0 ? (
            <div className="mt-2.5 space-y-1 border-t pt-2.5">
              {authorityModel.map((item, index) => {
                const note = authorityModelNote(item.resolution)
                return (
                  <div key={`authority-${index}`} className="space-y-0.5">
                    <p
                      className={cn(
                        "text-2xs",
                        note.incomplete ? "text-warn" : "text-muted-foreground"
                      )}
                    >
                      {note.text}
                    </p>
                    <p className="font-mono text-2xs break-all text-muted-foreground">
                      {item.detail}
                    </p>
                    {item.anchor ? (
                      <p className="font-mono text-2xs break-all text-muted-foreground">
                        ↳ {item.anchor.file}:{item.anchor.start_line}
                      </p>
                    ) : null}
                  </div>
                )
              })}
            </div>
          ) : null}
          {mechanisms.length > 0 ? (
            <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
              <span className="text-2xs text-muted-foreground">
                authenticates via
              </span>
              {mechanisms.map((mechanism, index) => (
                <span
                  key={`${mechanism.kind}-${index}`}
                  title={
                    mechanism.active === false
                      ? `${mechanism.detail} — ${mechanism.inactive_reason}`
                      : mechanism.detail
                  }
                  className={cn(
                    "rounded-full border px-2 py-0.5 text-2xs text-muted-foreground",
                    mechanism.active === false &&
                      "border-dashed text-subtle-foreground line-through"
                  )}
                >
                  {mechanism.kind}
                </span>
              ))}
            </div>
          ) : null}
        </CollapsibleSection>

        <CollapsibleSection title="Parameters" count={params.length}>
          {params.length === 0 ? (
            <p className="text-2xs text-muted-foreground">
              This endpoint declares no parameters.
            </p>
          ) : (
            params.map((param) => (
              <ParamRow
                key={`${param.location}-${param.name}`}
                name={param.name}
                location={param.location}
                typeName={param.type_name}
                required={param.required !== false}
              />
            ))
          )}
        </CollapsibleSection>

        <CollapsibleSection
          title="Request body"
          count={endpoint.request_schema?.fields?.length ?? null}
        >
          {endpoint.request_schema ? (
            <SchemaTree shape={endpoint.request_schema} />
          ) : (
            <p className="text-2xs text-muted-foreground">
              No request body on this endpoint.
            </p>
          )}
        </CollapsibleSection>

        <CollapsibleSection title="Response">
          {(endpoint.declared_statuses ?? []).length > 0 && (
            <div className="mb-2.5">
              <div className="flex flex-wrap gap-1">
                {(endpoint.declared_statuses ?? []).map((status) => (
                  <span
                    key={`${status.code}:${status.origin}`}
                    className={cn(
                      "rounded-full border px-1.5 py-0.5 font-mono text-2xs",
                      status.code < 300
                        ? "text-muted-foreground"
                        : "border-warn/40 text-warn"
                    )}
                    title={`${status.detail} — read from the ${status.origin}`}
                  >
                    {status.code}
                  </span>
                ))}
              </div>
              {/* The list is what the handler NAMES. A 500 from an uncaught
                  exception, a 403 from the security layer and a 404 from the
                  dispatcher are in no handler source, so silence here is not
                  a claim that this endpoint cannot fail (P10). */}
              <p className="mt-1 text-2xs text-muted-foreground">
                Named in the handler — errors raised elsewhere are not listed.
              </p>
            </div>
          )}
          {endpoint.response_schema ? (
            <SchemaTree shape={endpoint.response_schema} />
          ) : (
            <p className="text-2xs text-muted-foreground">
              Response shape unknown — analyzed before contract recovery, or no
              declared return.
            </p>
          )}
        </CollapsibleSection>
      </ScrollArea>

      {/* The one primary action on this panel, and it must look like it.
          It used to be a tinted outline (`border-primary/40 bg-primary/10`),
          which reads as one more chip in a panel already full of chips — the
          eye has no reason to land on it. A SOLID fill is unambiguous, and it
          is affordable precisely because the accent is achromatic: this is
          the loudest element on the surface without spending a hue that
          data needs. The panel edge is a real shoulder above it (thicker top
          rule, deeper ground) so the action reads as a footer, not as the
          next row in the list. */}
      <footer className="shrink-0 border-t-2 bg-panel px-3.5 pt-3 pb-3.5">
        <Button
          size="lg"
          render={<Link href={endpointPath(snapshotId, endpoint.id)} />}
          className="group h-10 w-full gap-2 px-3 text-sm font-semibold shadow-sm"
        >
          Open full flow
          <ArrowRight
            aria-hidden
            className="size-4 transition-transform group-hover:translate-x-0.5 motion-reduce:transition-none"
          />
        </Button>
        <p className="mt-2 flex items-center justify-center gap-1.5 text-center text-2xs text-subtle-foreground">
          <ExternalLink aria-hidden className="size-3" />
          call tree · flow graph · source
        </p>
      </footer>
    </div>
  )
}
