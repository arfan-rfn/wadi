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

function SectionHeading({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
      {children}
    </h3>
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
                  <span className="inline-flex items-center gap-1 rounded bg-amber-500/10 px-1.5 py-0.5 font-mono text-[11px] text-amber-700 dark:text-amber-400">
                    <AlertTriangle className="size-3" aria-hidden />
                    {entry.reason_code}
                  </span>
                  <span className="font-mono text-xs text-muted-foreground">
                    {entry.site.file}:{entry.site.start_line}
                  </span>
                </div>
                <p className="text-xs text-muted-foreground">{entry.reason}</p>
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
