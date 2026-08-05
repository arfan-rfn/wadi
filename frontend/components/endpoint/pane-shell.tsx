"use client"

// A workspace panel and its collapsed form (§5.2.9 UI).
//
// The pair is one component so the two states can never disagree about the
// panel's name — a rail labelled differently from the header it restores is
// how a reader loses track of what they closed. Collapsing must be reversible
// from the same place it happened, so the rail sits exactly where the panel
// was, is the full height of it, and is a single large click target.
import { ChevronLeft, ChevronRight } from "lucide-react"

import { cn } from "@/lib/utils"

export function PaneShell({
  label,
  side,
  onCollapse,
  children,
}: {
  label: string
  /** Which way the collapse chevron points — outward, toward the edge. */
  side: "left" | "right"
  onCollapse: () => void
  children: React.ReactNode
}) {
  const Chevron = side === "left" ? ChevronLeft : ChevronRight
  return (
    <>
      <div className="flex shrink-0 items-center gap-2 border-b px-2.5 py-1.5">
        <span className="text-2xs font-medium tracking-[0.08em] text-muted-foreground uppercase">
          {label}
        </span>
        <button
          type="button"
          onClick={onCollapse}
          aria-label={`Collapse ${label}`}
          title={`Collapse ${label}`}
          className={cn(
            "ml-auto cursor-pointer rounded p-1 text-muted-foreground/70 transition-colors",
            "hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          )}
        >
          <Chevron aria-hidden className="size-3.5" />
        </button>
      </div>
      {children}
    </>
  )
}

export function PaneRail({
  label,
  side,
  onExpand,
}: {
  label: string
  side: "left" | "right"
  onExpand: () => void
}) {
  // Points inward — the direction the panel will grow when restored.
  const Chevron = side === "left" ? ChevronRight : ChevronLeft
  return (
    <button
      type="button"
      onClick={onExpand}
      aria-label={`Expand ${label}`}
      title={`Expand ${label}`}
      className={cn(
        "flex w-9 shrink-0 cursor-pointer flex-col items-center gap-2.5 border-r bg-muted/25 py-2.5 transition-colors",
        "hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none focus-visible:-outline-offset-2",
        side === "right" && "border-r-0 border-l"
      )}
    >
      <Chevron aria-hidden className="size-3.5 shrink-0 text-muted-foreground/70" />
      <span
        className="text-2xs tracking-[0.1em] whitespace-nowrap text-muted-foreground uppercase"
        style={{ writingMode: "vertical-rl" }}
      >
        {label}
      </span>
    </button>
  )
}
