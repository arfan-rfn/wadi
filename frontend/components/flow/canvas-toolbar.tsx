"use client"

// Canvas toolbar (§11 Phase 2.8): search with next/prev over the FULL closure
// (hits inside collapsed methods auto-expand), bulk disclosure (expand-all
// behind a budget confirm — an actionable gate, not a passive banner),
// depth-1 as the middle gear, and the trace toggle.
import { useState } from "react"
import {
  ChevronDown,
  ChevronUp,
  FoldVertical,
  Route,
  Rows3,
  Search,
  UnfoldVertical,
} from "lucide-react"

import { cn } from "@/lib/utils"
import type { FlowSearchMatch } from "@/lib/wadi/flow-search"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Input } from "@/components/ui/input"

export const NODE_BUDGET = 150

export function CanvasToolbar({
  search,
  onSearch,
  matches,
  activeMatch,
  onStep,
  traceEnabled,
  onTrace,
  projectedFullCount,
  onExpandAll,
  onCollapseAll,
  onExpandDepth1,
}: {
  search: string
  onSearch: (query: string) => void
  matches: FlowSearchMatch[]
  activeMatch: number
  onStep: (direction: 1 | -1) => void
  traceEnabled: boolean
  onTrace: (enabled: boolean) => void
  projectedFullCount: number
  onExpandAll: () => void
  onCollapseAll: () => void
  onExpandDepth1: () => void
}) {
  const [confirmOpen, setConfirmOpen] = useState(false)
  const overBudget = projectedFullCount > NODE_BUDGET

  return (
    // `min-w-0` + `flex-wrap`: the centre panel resizes down to 26%, and a
    // nowrap row of nine controls would otherwise spill across the separator
    // into the inspector — the same class as the long-code-line blowout.
    <div className="flex min-w-0 flex-wrap items-center gap-1.5">
      <div className="relative min-w-0 flex-1 basis-32">
        <Search className="absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-subtle-foreground" />
        <Input
          value={search}
          onChange={(event) => onSearch(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") onStep(event.shiftKey ? -1 : 1)
            if (event.key === "Escape") onSearch("")
          }}
          placeholder="Search flow ( / )"
          data-flow-search
          className="h-7 w-full min-w-0 max-w-48 border-none bg-muted/50 pl-7 text-xs shadow-none focus-visible:ring-1"
        />
        {search.trim().length >= 2 ? (
          <span className="absolute right-2 top-1/2 -translate-y-1/2 font-mono text-2xs tabular-nums text-muted-foreground">
            {matches.length === 0
              ? "0/0"
              : `${activeMatch + 1}/${matches.length}`}
          </span>
        ) : null}
      </div>
      <button
        className="rounded-sm p-1 text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-40"
        onClick={() => onStep(-1)}
        disabled={matches.length === 0}
        title="Previous match (Shift+Enter)"
      >
        <ChevronUp className="size-3.5" />
      </button>
      <button
        className="rounded-sm p-1 text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-40"
        onClick={() => onStep(1)}
        disabled={matches.length === 0}
        title="Next match (Enter)"
      >
        <ChevronDown className="size-3.5" />
      </button>

      <span className="mx-0.5 h-4 w-px bg-border" />

      <button
        className="inline-flex items-center gap-1 rounded-sm px-1.5 py-1 text-2xs text-muted-foreground hover:bg-muted hover:text-foreground"
        onClick={() => (overBudget ? setConfirmOpen(true) : onExpandAll())}
        title="Expand every method"
      >
        <UnfoldVertical className="size-3.5" />
        all
      </button>
      <button
        className="inline-flex items-center gap-1 rounded-sm px-1.5 py-1 text-2xs text-muted-foreground hover:bg-muted hover:text-foreground"
        onClick={onExpandDepth1}
        title="Expand the handler and its direct callees"
      >
        <Rows3 className="size-3.5" />
        depth 1
      </button>
      <button
        className="inline-flex items-center gap-1 rounded-sm px-1.5 py-1 text-2xs text-muted-foreground hover:bg-muted hover:text-foreground"
        onClick={onCollapseAll}
        title="Collapse every method"
      >
        <FoldVertical className="size-3.5" />
        none
      </button>

      <span className="mx-0.5 h-4 w-px bg-border" />

      <button
        className={cn(
          "inline-flex items-center gap-1 rounded-sm px-1.5 py-1 text-2xs transition-colors",
          traceEnabled
            ? "bg-muted text-foreground"
            : "text-muted-foreground hover:bg-muted hover:text-foreground"
        )}
        onClick={() => onTrace(!traceEnabled)}
        aria-pressed={traceEnabled}
        title="Highlight the path from the handler to the selected node"
      >
        <Route className="size-3.5" />
        trace
      </button>

      <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              Expand all {projectedFullCount} nodes?
            </AlertDialogTitle>
            <AlertDialogDescription>
              This flow is larger than the {NODE_BUDGET}-node comfort budget — a
              fully expanded canvas will be hard to read. Focusing on one method
              (the crosshair on a lane header) is usually the better tool.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep it readable</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                setConfirmOpen(false)
                onExpandAll()
              }}
            >
              Expand anyway
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
