"use client"

// Scope switchers (the SaaS project-switcher pattern): system and snapshot
// live in the chrome, not in the content flow — the panes get the canvas.
//
// These render INLINE inside `AppHeader` rather than owning a bar of their
// own: two stacked chrome rows cost 7rem before any content and made the
// reader correlate two lines to know what they were looking at.
import { format } from "date-fns"
import { ChevronsUpDown, Database, GitCommitHorizontal } from "lucide-react"

import type { Snapshot, System } from "@/lib/wadi/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuGroupLabel,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"

/**
 * Status, weighted by how much it tells you.
 *
 * The list rendered a filled "succeeded" badge on every row — 33 of 35 in the
 * live snapshot list — which spends the strongest visual weight in the menu on
 * the one thing that is almost always true, and leaves the single `failed` run
 * to compete against a wall of green. The green path is a dot; anything that
 * is NOT the green path keeps the full badge, so the exception is what the eye
 * catches. The word itself is not lost — it is on the row's title attribute
 * and, for the dot, its own label.
 */
function SnapshotStatus({ status }: { status?: string | null }) {
  const value = status ?? "pending"
  if (value === "succeeded") {
    return (
      <span
        aria-label="succeeded"
        title="succeeded"
        className="size-1.5 shrink-0 rounded-full bg-ok"
      />
    )
  }
  return (
    <Badge
      variant={value === "failed" ? "bad" : "warn"}
      className="shrink-0 px-1.5 py-0 text-2xs"
    >
      {value}
    </Badge>
  )
}

/** Date AND time: a dozen rows share one day, so the day alone separates
 *  nothing. Tabular figures keep the column aligned. */
function formatStamp(iso?: string | null): string {
  if (!iso) return ""
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ""
  return format(date, "MMM d HH:mm")
}

interface ScopeBarProps {
  systems: System[]
  snapshots: Snapshot[]
  systemId: string | null
  snapshotId: string | null
  onSystem: (id: string) => void
  onSnapshot: (id: string) => void
}

export function ScopeBar(props: ScopeBarProps) {
  const system = props.systems.find((s) => s.id === props.systemId)
  const snapshot = props.snapshots.find((s) => s.id === props.snapshotId)

  return (
    <div className="flex min-w-0 items-center gap-1">
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button
              variant="ghost"
              size="sm"
              className="gap-2 px-2 font-medium"
            />
          }
        >
          <Database className="size-3.5 text-muted-foreground" />
          {system ? system.name : "Select system"}
          <ChevronsUpDown className="size-3 text-muted-foreground" />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-72">
          {/* A real group: the heading names the list below it, so screen
              readers announce "Systems, list, 3 items" instead of reading a
              stray heading and then an unlabelled menu. */}
          <DropdownMenuGroup>
            <DropdownMenuGroupLabel className="text-xs tracking-wider text-muted-foreground uppercase">
              Systems
            </DropdownMenuGroupLabel>
            <DropdownMenuSeparator />
            {props.systems.length === 0 ? (
              <DropdownMenuItem disabled>
                No systems yet — run{" "}
                <code className="ml-1 rounded-sm bg-muted px-1 font-mono">
                  wadi analyze .
                </code>
              </DropdownMenuItem>
            ) : null}
            {props.systems.map((s) => (
              <DropdownMenuItem
                key={s.id}
                onSelect={() => props.onSystem(s.id)}
                selected={s.id === props.systemId}
                className="gap-3"
              >
                <span className="min-w-0 flex-1 truncate">{s.name}</span>
                <span className="shrink-0 font-mono text-2xs text-subtle-foreground tabular-nums">
                  {s.repos.length} repo{s.repos.length === 1 ? "" : "s"}
                </span>
              </DropdownMenuItem>
            ))}
          </DropdownMenuGroup>
        </DropdownMenuContent>
      </DropdownMenu>

      <span className="text-subtle-foreground">/</span>

      <DropdownMenu>
        <DropdownMenuTrigger
          disabled={!props.systemId}
          render={
            <Button
              variant="ghost"
              size="sm"
              className="gap-2 px-2 font-mono text-xs"
            />
          }
        >
          <GitCommitHorizontal className="size-3.5 text-muted-foreground" />
          {snapshot ? `${snapshot.id.slice(5, 17)}` : "snapshot"}
          {snapshot ? (
            <Badge
              variant={
                snapshot.status === "succeeded"
                  ? "ok"
                  : snapshot.status === "failed"
                    ? "bad"
                    : "warn"
              }
              className="px-1.5 py-0 text-2xs"
            >
              {snapshot.status ?? "pending"}
            </Badge>
          ) : null}
          <ChevronsUpDown className="size-3 text-muted-foreground" />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-96">
          <DropdownMenuGroup>
            <DropdownMenuGroupLabel className="text-xs tracking-wider text-muted-foreground uppercase">
              Snapshots — newest first
            </DropdownMenuGroupLabel>
            <DropdownMenuSeparator />
            {props.snapshots.map((s) => (
              <DropdownMenuItem
                key={s.id}
                onSelect={() => props.onSnapshot(s.id)}
                selected={s.id === props.snapshotId}
                title={`${s.id} — ${s.status ?? "pending"}`}
                className="gap-3"
              >
                {/* The `snap_` prefix is on all 35 rows and distinguishes
                    none of them; it is five characters of noise per line in a
                    column the reader is scanning for a difference. The full id
                    stays in the row's title. */}
                <span className="min-w-0 flex-1 truncate font-mono text-xs">
                  {s.id.replace(/^snap_/, "")}
                </span>
                <span className="shrink-0 font-mono text-2xs text-subtle-foreground tabular-nums">
                  {formatStamp(s.created_at)}
                </span>
                <SnapshotStatus status={s.status} />
              </DropdownMenuItem>
            ))}
          </DropdownMenuGroup>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}
