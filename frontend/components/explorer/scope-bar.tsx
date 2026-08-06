"use client"

// Scope switchers (the SaaS project-switcher pattern): system and snapshot
// live in the chrome, not in the content flow — the panes get the canvas.
//
// These render INLINE inside `AppHeader` rather than owning a bar of their
// own: two stacked chrome rows cost 7rem before any content and made the
// reader correlate two lines to know what they were looking at.
import {
  Check,
  ChevronsUpDown,
  Database,
  GitCommitHorizontal,
} from "lucide-react"

import type { Snapshot, System } from "@/lib/wadi/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"

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
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="sm" className="gap-2 px-2 font-medium">
            <Database className="size-3.5 text-muted-foreground" />
            {system ? system.name : "Select system"}
            <ChevronsUpDown className="size-3 text-muted-foreground" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-72">
          <DropdownMenuLabel className="text-xs uppercase tracking-wider text-muted-foreground">
            Systems
          </DropdownMenuLabel>
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
              className="justify-between"
            >
              <span className="truncate">{s.name}</span>
              <span className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground">
                  {s.repos.length} repo(s)
                </span>
                {s.id === props.systemId ? (
                  <Check className="size-3.5" />
                ) : null}
              </span>
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>

      <span className="text-subtle-foreground">/</span>

      <DropdownMenu>
        <DropdownMenuTrigger asChild disabled={!props.systemId}>
          <Button
            variant="ghost"
            size="sm"
            className="gap-2 px-2 font-mono text-xs"
          >
            <GitCommitHorizontal className="size-3.5 text-muted-foreground" />
            {snapshot ? `${snapshot.id.slice(5, 17)}` : "snapshot"}
            {snapshot ? (
              <Badge
                variant={
                  snapshot.status === "succeeded"
                    ? "default"
                    : snapshot.status === "failed"
                      ? "destructive"
                      : "secondary"
                }
                className="px-1.5 py-0 text-2xs"
              >
                {snapshot.status ?? "pending"}
              </Badge>
            ) : null}
            <ChevronsUpDown className="size-3 text-muted-foreground" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-96">
          <DropdownMenuLabel className="text-xs uppercase tracking-wider text-muted-foreground">
            Snapshots — newest first
          </DropdownMenuLabel>
          <DropdownMenuSeparator />
          {props.snapshots.map((s) => (
            <DropdownMenuItem
              key={s.id}
              onSelect={() => props.onSnapshot(s.id)}
              className="justify-between gap-3"
            >
              <span className="truncate font-mono text-xs">{s.id}</span>
              <span className="flex shrink-0 items-center gap-2">
                <span className="text-xs text-muted-foreground">
                  {s.created_at
                    ? new Date(s.created_at).toLocaleDateString()
                    : ""}
                </span>
                <Badge
                  variant={
                    s.status === "succeeded"
                      ? "default"
                      : s.status === "failed"
                        ? "destructive"
                        : "secondary"
                  }
                  className="px-1.5 py-0 text-2xs"
                >
                  {s.status ?? "pending"}
                </Badge>
                {s.id === props.snapshotId ? (
                  <Check className="size-3.5" />
                ) : null}
              </span>
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}
