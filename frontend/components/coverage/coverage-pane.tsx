"use client"

// The coverage report, surfaced FIRST (§5.4, P10): what the map knows it
// doesn't know. Layout follows the recorded M6 research patterns: stat tiles
// with "N of M" context (Vanta), labeled count chips for edge kinds
// (Adaline), explicit "unknown" states (Databricks) — palette stays calm per
// the workbench rule (method chips are the only saturated element).
import { AlertTriangle, ExternalLink, HelpCircle } from "lucide-react"

import type { CoverageReport } from "@/lib/wadi/api"
import { useCoverage } from "@/lib/wadi/hooks"
import { Skeleton } from "@/components/ui/skeleton"
import {
  authGapLabel,
  requestPolicyLabel,
  unreadLabel,
} from "@/components/shared/auth-chip"
import { SectionHeading } from "@/components/shared/section-heading"
import { SourceSnippet } from "@/components/source/source-viewer"

function StatTile({
  label,
  value,
  context,
  percent,
}: {
  label: string
  value: string
  context: string
  percent: number | null
}) {
  return (
    <div className="rounded-lg border bg-card p-4">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 flex items-baseline gap-2">
        <span className="text-2xl font-semibold tabular-nums">{value}</span>
        <span className="text-xs text-muted-foreground">{context}</span>
      </div>
      {percent !== null && (
        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted">
          <div
            className="h-1.5 rounded-full bg-primary/70"
            style={{ width: `${Math.min(percent, 100)}%` }}
          />
        </div>
      )}
    </div>
  )
}

function KindChip({ label, count }: { label: string; count: number }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs">
      <span className="font-medium tabular-nums">{count}</span>
      <span className="text-muted-foreground">{label}</span>
    </span>
  )
}

function AnalysisCoverageSection({ report }: { report: CoverageReport }) {
  const section = report.analysis_coverage
  if (!section) {
    return (
      <p className="text-sm text-muted-foreground">
        Analysis coverage is unknown for this snapshot (it predates the metric).
        Re-analyze to measure it.
      </p>
    )
  }
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <StatTile
          label="Analysis coverage"
          value={
            section.coverage_percent !== null &&
            section.coverage_percent !== undefined
              ? `${section.coverage_percent}%`
              : "n/a"
          }
          context={`${section.reachable_methods} of ${section.production_methods} methods reached`}
          percent={section.coverage_percent ?? null}
        />
        <StatTile
          label="Call sites resolved"
          value={`${report.totals.analyzed}`}
          context={`of ${report.totals.edges} edges`}
          percent={
            report.totals.edges > 0
              ? (report.totals.analyzed / report.totals.edges) * 100
              : null
          }
        />
        <StatTile
          label="Unresolved calls"
          value={`${(report.unresolved ?? []).length}`}
          context="each with a machine-readable reason"
          percent={null}
        />
      </div>
      <p className="text-xs text-muted-foreground">
        Low coverage is a finding, not an error — unreached methods are dead
        code or flows analysis cannot yet root (schedulers, listeners).
      </p>
      <div className="space-y-1.5">
        {(section.services ?? []).map((entry) => (
          <div key={entry.service_id} className="flex items-center gap-3">
            <span className="w-44 truncate font-mono text-xs">
              {entry.name}
            </span>
            {entry.production_methods === null ||
            entry.production_methods === undefined ? (
              <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                <HelpCircle className="size-3.5" aria-hidden />
                unknown — no coverage fact
              </span>
            ) : (
              <>
                <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
                  <div
                    className="h-1.5 rounded-full bg-primary/60"
                    style={{ width: `${entry.coverage_percent ?? 0}%` }}
                  />
                </div>
                <span className="w-28 shrink-0 text-right text-xs tabular-nums text-muted-foreground">
                  {entry.reachable_methods}/{entry.production_methods}
                  {entry.coverage_percent !== null &&
                  entry.coverage_percent !== undefined
                    ? ` · ${entry.coverage_percent}%`
                    : " · n/a"}
                </span>
              </>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

export function CoveragePane({ snapshotId }: { snapshotId: string | null }) {
  const coverage = useCoverage(snapshotId)

  if (snapshotId === null) {
    return (
      <div className="p-6 text-sm text-muted-foreground">
        Pick a snapshot to see its coverage report.
      </div>
    )
  }
  if (coverage.isLoading) {
    return (
      <div className="space-y-3 p-6">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    )
  }
  if (coverage.isError) {
    return (
      <div className="p-6 text-sm text-muted-foreground">
        Coverage is not available for this snapshot yet:{" "}
        {(coverage.error as Error).message}. It appears once stitching
        completes.
      </div>
    )
  }
  const report = coverage.data
  if (!report) return null
  const totals = report.totals
  const placeholders = report.placeholders ?? []
  const externalApis = report.external_apis ?? []
  const unresolved = report.unresolved ?? []

  return (
    <div className="min-w-0 flex-1 space-y-8 overflow-y-auto p-6">
      <section className="space-y-3">
        <SectionHeading>What the map knows it doesn&apos;t know</SectionHeading>
        <AnalysisCoverageSection report={report} />
      </section>

      <section className="space-y-3">
        <SectionHeading>Edges by target</SectionHeading>
        <div className="flex flex-wrap gap-2">
          <KindChip label="analyzed" count={totals.analyzed} />
          <KindChip label="external" count={totals.external} />
          <KindChip label="placeholder" count={totals.placeholder} />
          <KindChip label="undetermined" count={totals.undetermined} />
          <KindChip
            label="unreachable (inventoried)"
            count={totals.unreachable_call_sites ?? 0}
          />
          {(totals.async_rooted_call_sites ?? 0) > 0 && (
            // Carved OUT of the unreachable count above, not added to it: these
            // run at startup or on a schedule, so no request reaches them — but
            // they are not dead, and one number for both said they were.
            <KindChip
              label="of those, startup/scheduled"
              count={totals.async_rooted_call_sites ?? 0}
            />
          )}
          <KindChip
            label="suspected"
            count={totals.suspected_call_sites ?? 0}
          />
        </div>
        <div className="flex flex-wrap gap-2">
          {Object.entries(totals.by_confidence ?? {}).map(([tier, count]) => (
            <KindChip key={tier} label={`confidence ${tier}`} count={count} />
          ))}
        </div>
      </section>

      {unresolved.length > 0 && (
        <section className="space-y-3">
          <SectionHeading>Unresolved calls</SectionHeading>
          <div className="divide-y rounded-lg border">
            {unresolved.map((entry) => (
              <div
                key={`${entry.remote_call_id}-${entry.reason_code}`}
                className="space-y-1 px-3 py-2"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="inline-flex items-center gap-1 rounded-sm bg-warn/10 px-1.5 py-0.5 font-mono text-2xs text-warn">
                    <AlertTriangle className="size-3" aria-hidden />
                    {entry.reason_code}
                  </span>
                </div>
                <p className="text-xs text-muted-foreground">{entry.reason}</p>
                {/* §11 Phase 2.7 M5: every anchor drills into source-on-demand. */}
                <SourceSnippet
                  snapshotId={snapshotId as string}
                  serviceId={entry.service_id}
                  anchor={entry.site}
                />
              </div>
            ))}
          </div>
        </section>
      )}

      {(placeholders.length > 0 || externalApis.length > 0) && (
        <section className="space-y-3">
          <SectionHeading>Beyond the analyzed set</SectionHeading>
          <div className="grid gap-3 sm:grid-cols-2">
            {placeholders.length > 0 && (
              <div className="rounded-lg border p-3">
                <div className="mb-2 text-xs font-medium">
                  Placeholder services
                  <span className="ml-1 font-normal text-muted-foreground">
                    — called by name, not analyzed. Grant access to include
                    them.
                  </span>
                </div>
                <ul className="space-y-1">
                  {placeholders.map((p) => (
                    <li key={p.placeholder_id} className="text-xs">
                      <span className="font-mono">{p.name}</span>{" "}
                      <span className="text-muted-foreground">
                        ({p.call_count} call{p.call_count === 1 ? "" : "s"},{" "}
                        {p.resolved_via})
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {externalApis.length > 0 && (
              <div className="rounded-lg border p-3">
                <div className="mb-2 text-xs font-medium">External APIs</div>
                <ul className="space-y-1">
                  {externalApis.map((e) => (
                    <li
                      key={e.host}
                      className="flex items-center gap-1.5 text-xs"
                    >
                      <ExternalLink
                        className="size-3 text-muted-foreground"
                        aria-hidden
                      />
                      <span className="font-mono">{e.host}</span>
                      <span className="text-muted-foreground">
                        ({e.call_count} call{e.call_count === 1 ? "" : "s"})
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </section>
      )}

      {(report.unmodelled_mechanisms ?? []).length > 0 && (
        <section className="space-y-3">
          <SectionHeading>Unmodelled client libraries</SectionHeading>
          <div className="rounded-lg border p-3">
            <p className="mb-2 text-xs text-muted-foreground">
              These HTTP clients appear in the code but no analysis pass models
              them yet — their calls are absent from the map, and that absence
              is recorded here rather than hidden.
            </p>
            <ul className="space-y-1">
              {(report.unmodelled_mechanisms ?? []).map((m) => (
                <li key={m.mechanism} className="text-xs">
                  <span className="font-mono">{m.mechanism}</span>{" "}
                  <span className="text-muted-foreground">
                    present in {m.service_ids.length} service
                    {m.service_ids.length === 1 ? "" : "s"}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </section>
      )}

      {report.cfg_anomalies &&
        Object.keys(report.cfg_anomalies.total_by_code ?? {}).length > 0 && (
          <section className="space-y-3">
            <SectionHeading>CFG anomalies</SectionHeading>
            <div className="rounded-lg border p-3">
              <p className="mb-2 text-xs text-muted-foreground">
                Structural invariants the control-flow graph violated for this
                code (§5.2.8) — where the graph itself says it can be trusted
                less. Facts, never silent.
              </p>
              <ul className="space-y-1">
                {Object.entries(report.cfg_anomalies.total_by_code ?? {}).map(
                  ([code, count]) => (
                    <li key={code} className="text-xs">
                      <span className="font-mono">{code}</span>{" "}
                      <span className="text-muted-foreground">×{count}</span>
                    </li>
                  )
                )}
              </ul>
              {/* §11 Phase 2.7 M5: sample sites drill into source-on-demand. */}
              <div className="mt-2 space-y-1.5">
                {(report.cfg_anomalies.services ?? [])
                  .filter((service) => (service.anomalies ?? []).length > 0)
                  .map((service) => (
                    <div key={service.service_id} className="space-y-1">
                      <p className="font-mono text-2xs text-muted-foreground">
                        {service.name}
                      </p>
                      {(service.anomalies ?? []).flatMap((anomaly) =>
                        (anomaly.sample_sites ?? [])
                          .slice(0, 2)
                          .map((site, index) => (
                            <SourceSnippet
                              key={`${anomaly.code}-${index}`}
                              snapshotId={snapshotId as string}
                              serviceId={service.service_id}
                              anchor={site}
                            />
                          ))
                      )}
                    </div>
                  ))}
              </div>
              {(report.cfg_anomalies.services ?? []).some(
                (s) => !s.checked
              ) && (
                <p className="mt-2 text-xs text-muted-foreground">
                  Never checked:{" "}
                  {(report.cfg_anomalies.services ?? [])
                    .filter((s) => !s.checked)
                    .map((s) => s.name)
                    .join(", ")}
                </p>
              )}
            </div>
          </section>
        )}

      {(report.endpoint_collisions ?? []).length > 0 && (
        <section className="space-y-3">
          <SectionHeading>
            Endpoints that could not all be stored
          </SectionHeading>
          <div className="rounded-lg border border-warn/40 bg-warn/5 p-3">
            <p className="mb-2 text-xs text-muted-foreground">
              These handlers derived the same content-derived id, so only one of
              each pair could be stored — the rest are{" "}
              <span className="font-medium">missing from the inventory</span>.
              Unlike everything else on this page, which reports what analysis
              could not read, this reports what it read and then lost: the
              collision happens at the storage key, downstream of every other
              counter here.
            </p>
            <ul className="space-y-2">
              {(report.endpoint_collisions ?? []).map((collision) => (
                <li key={collision.endpoint_id} className="text-xs">
                  <span className="font-mono">
                    {collision.http_method} {collision.uri}
                  </span>
                  <p className="mt-0.5 font-mono text-2xs text-muted-foreground">
                    kept {collision.kept_handler}
                  </p>
                  {(collision.dropped_handlers ?? []).map((handler) => (
                    <p key={handler} className="font-mono text-2xs text-warn">
                      dropped {handler}
                    </p>
                  ))}
                </li>
              ))}
            </ul>
          </div>
        </section>
      )}

      {report.auth_coverage &&
        Object.keys(report.auth_coverage.unread_by_kind ?? {}).length > 0 && (
          <section className="space-y-3">
            <SectionHeading>Guards that could not be read</SectionHeading>
            <div className="rounded-lg border p-3">
              <p className="mb-2 text-xs text-muted-foreground">
                Constructs that gate a request but whose effect analysis could
                not determine. Each one withholds an endpoint&rsquo;s auth
                answer rather than letting it fall through to whatever rule
                comes next — the count is how much of this system&rsquo;s access
                policy is still unreadable.
              </p>
              <div className="flex flex-wrap gap-1.5">
                {Object.entries(report.auth_coverage.unread_by_kind ?? {}).map(
                  ([kind, count]) => (
                    <span
                      key={kind}
                      className="rounded-full border px-2 py-0.5 font-mono text-2xs text-muted-foreground"
                    >
                      {count} {unreadLabel(kind)}
                    </span>
                  )
                )}
              </div>
            </div>
          </section>
        )}

      {report.auth_coverage &&
        Object.keys(report.auth_coverage.extraction_gaps ?? {}).length > 0 && (
          <section className="space-y-3">
            <SectionHeading>
              Auth the source names but the map lacks
            </SectionHeading>
            <div className="rounded-lg border p-3">
              <p className="mb-2 text-xs text-muted-foreground">
                Found by reading the source text independently of the code
                graph, then diffing. Every other auth counter is derived from
                what the analysis <em>emitted</em>, so none of them can see a
                construct that was dropped before emission — this one can, and
                it is the only number here that reports a miss rather than an
                unknown.
              </p>
              <ul className="space-y-1">
                {Object.entries(report.auth_coverage.extraction_gaps ?? {}).map(
                  ([code, count]) => (
                    <li key={code} className="text-xs">
                      <span className="font-mono">{count}</span>{" "}
                      <span className="text-muted-foreground">
                        {authGapLabel(code)}
                      </span>
                    </li>
                  )
                )}
              </ul>
            </div>
          </section>
        )}

      {report.auth_coverage &&
        Object.keys(report.auth_coverage.request_policies ?? {}).length > 0 && (
          <section className="space-y-3">
            <SectionHeading>Who may reach the service</SectionHeading>
            <div className="rounded-lg border p-3">
              <p className="mb-2 text-xs text-muted-foreground">
                CORS, CSRF and rejection handling — the third thing a security
                config declares. These decide which <em>origin</em> may call and
                which request shapes need a token; they never decide which{" "}
                <em>principal</em> may, so they are counted apart from every
                claim above and change none of those numbers.
              </p>
              <div className="flex flex-wrap gap-1.5">
                {Object.entries(
                  report.auth_coverage.request_policies ?? {}
                ).map(([kind, count]) => (
                  <span
                    key={kind}
                    className="rounded-full border px-2 py-0.5 font-mono text-2xs text-muted-foreground"
                  >
                    {count} {requestPolicyLabel(kind)}
                  </span>
                ))}
              </div>
            </div>
          </section>
        )}

      {(report.auth_coverage?.unexercised_vocabulary ?? []).length > 0 && (
        <section className="space-y-3">
          <SectionHeading>Zeros that prove nothing</SectionHeading>
          <div className="rounded-lg border p-3">
            <p className="mb-2 text-xs text-muted-foreground">
              This snapshot contains no instance of the facts below, so their
              counts above are zero for a reason no reader can see. A zero can
              mean the analysis looked and this system genuinely has none, or
              that nothing here exercises the idiom and the zero is evidence of
              nothing. These are the second kind.
            </p>
            <div className="flex flex-wrap gap-1.5">
              {(report.auth_coverage?.unexercised_vocabulary ?? []).map(
                (name) => (
                  <span
                    key={name}
                    className="rounded-full border border-dashed px-2 py-0.5 font-mono text-2xs text-muted-foreground"
                  >
                    {name}
                  </span>
                )
              )}
            </div>
          </div>
        </section>
      )}

      {(report.phonebook_conflicts ?? []).length > 0 && (
        <section className="space-y-3">
          <SectionHeading>Config conflicts</SectionHeading>
          <ul className="space-y-1">
            {(report.phonebook_conflicts ?? []).map((conflict) => (
              <li key={conflict} className="text-xs text-muted-foreground">
                {conflict}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
