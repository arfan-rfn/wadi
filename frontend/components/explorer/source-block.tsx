"use client"

// Source-on-demand (§5.3): fetched only when opened, served from wadi's
// pinned-SHA store — the EXACT text analysis saw, so the comparison between
// code and claims always lines up. Delombok'd variants are flagged.
import { useState } from "react"
import { ChevronDown, ChevronRight } from "lucide-react"

import type { SourceAnchor } from "@/lib/generated/icfg.schema"
import { cn } from "@/lib/utils"
import { useSource } from "@/lib/wadi/hooks"
import { Skeleton } from "@/components/ui/skeleton"

export function SourceBlock({
  snapshotId,
  serviceId,
  anchor,
  context = 3,
}: {
  snapshotId: string
  serviceId: string
  anchor: SourceAnchor
  context?: number
}) {
  const [open, setOpen] = useState(false)
  const startLine = Math.max(1, anchor.start_line - context)
  const endLine = anchor.end_line + context
  const source = useSource(
    open,
    snapshotId,
    serviceId,
    anchor.file,
    startLine,
    endLine
  )

  return (
    <div className="min-w-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1 font-mono text-[11px] text-muted-foreground hover:text-foreground"
        aria-expanded={open}
      >
        {open ? (
          <ChevronDown className="size-3" aria-hidden />
        ) : (
          <ChevronRight className="size-3" aria-hidden />
        )}
        {anchor.file}:{anchor.start_line}
      </button>
      {open && (
        <div className="mt-1.5 overflow-x-auto rounded-md border bg-muted/40">
          {source.isLoading && (
            <div className="space-y-1 p-2">
              <Skeleton className="h-3 w-3/4" />
              <Skeleton className="h-3 w-2/3" />
            </div>
          )}
          {source.isError && (
            <p className="p-2 text-[11px] text-muted-foreground">
              Source unavailable: {(source.error as Error).message}
            </p>
          )}
          {source.data && (
            <>
              {source.data.variant !== "original" && (
                <div className="border-b px-2 py-1 text-[10px] text-muted-foreground">
                  {source.data.variant} variant — the text analysis actually saw
                  (anchors align with this, not the raw file)
                </div>
              )}
              <pre className="p-0 text-[11px] leading-5">
                {source.data.content.split("\n").map((line, index) => {
                  const lineNo = source.data.start_line + index
                  const inAnchor =
                    lineNo >= anchor.start_line && lineNo <= anchor.end_line
                  return (
                    <div
                      key={lineNo}
                      className={cn(
                        "flex gap-3 px-2",
                        inAnchor && "bg-amber-500/10"
                      )}
                    >
                      <span className="w-8 shrink-0 select-none text-right text-muted-foreground/60">
                        {lineNo}
                      </span>
                      <code className="whitespace-pre">{line || " "}</code>
                    </div>
                  )
                })}
              </pre>
            </>
          )}
        </div>
      )}
    </div>
  )
}
