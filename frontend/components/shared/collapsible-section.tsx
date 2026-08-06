"use client"

import { useId, useState } from "react"
import { ChevronRight } from "lucide-react"

import { cn } from "@/lib/utils"

// A titled, collapsible block with a count (the LangSmith inspector pattern).
//
// Sections beat a single scroll here because the payloads are wildly uneven:
// a 17-field request body would otherwise push the response below the fold on
// every endpoint that has one. The count in the header is what lets you decide
// whether opening it is worth the scroll.

export function CollapsibleSection({
  title,
  count,
  defaultOpen = true,
  hint,
  children,
}: {
  title: string
  /** Shown right-aligned in the header. Omit when a count is meaningless. */
  count?: number | null
  defaultOpen?: boolean
  /** Short qualifier after the title, e.g. a shape's type name. */
  hint?: string
  children: React.ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)
  const bodyId = useId()
  return (
    <section className="border-b last:border-b-0">
      <h3>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          aria-controls={bodyId}
          className={cn(
            "flex w-full cursor-pointer items-center gap-2 px-3.5 py-2.5 text-left text-muted-foreground transition-colors",
            "hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none focus-visible:-outline-offset-2"
          )}
        >
          <ChevronRight
            aria-hidden
            className={cn(
              "size-3 shrink-0 text-muted-foreground transition-transform motion-reduce:transition-none",
              open && "rotate-90"
            )}
          />
          <span className="text-2xs font-semibold tracking-[0.08em] uppercase">
            {title}
          </span>
          {hint ? (
            <span className="truncate font-mono text-2xs text-muted-foreground">
              {hint}
            </span>
          ) : null}
          {count != null ? (
            <span className="ml-auto font-mono text-2xs tabular-nums text-muted-foreground">
              {count}
            </span>
          ) : null}
        </button>
      </h3>
      <div id={bodyId} hidden={!open} className="px-3.5 pb-3.5">
        {children}
      </div>
    </section>
  )
}
