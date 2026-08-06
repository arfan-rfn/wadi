"use client"

import { useEffect, useState } from "react"
import { Search } from "lucide-react"

import { Input } from "@/components/ui/input"

/** Shared pane header: label + count, optional hint, optional filter input.
 * Used by the services rail, endpoint list, call-tree rail, and inspector. */
export function PanelHeader(props: {
  label: string
  count?: number
  hint?: string
  filter?: string
  onFilter?: (value: string) => void
  placeholder?: string
}) {
  // Every caller's count comes from a client fetch (`services.data?.length`
  // and friends), so the server has no number to render and omits the span
  // entirely — while the client, hydrating against a warm query cache, has
  // one. That is a DOM-shape disagreement, not just a different number, so it
  // fails hydration outright and React regenerates the tree.
  //
  // Same reasoning as the header's scope pickers: showing the count after
  // mount is not a workaround, it matches where the number actually comes
  // from. Gating on `mounted` rather than on `count` keeps the first client
  // render identical to the server's whether or not the cache is warm.
  const [mounted, setMounted] = useState(false)
  useEffect(() => setMounted(true), [])
  return (
    <div className="shrink-0 space-y-dense border-b px-pad-x py-pad-y">
      <div className="flex items-baseline justify-between">
        <h2 className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
          {props.label}
          {mounted && props.count !== undefined ? (
            <span className="ml-1.5 font-mono tabular-nums text-subtle-foreground">
              {props.count}
            </span>
          ) : null}
        </h2>
        {props.hint ? (
          <span className="truncate pl-2 font-mono text-2xs text-subtle-foreground">
            {props.hint}
          </span>
        ) : null}
      </div>
      {props.onFilter ? (
        <div className="relative">
          <Search className="absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-subtle-foreground" />
          <Input
            value={props.filter ?? ""}
            onChange={(event) => props.onFilter?.(event.target.value)}
            placeholder={props.placeholder}
            className="h-7 border-none bg-muted/50 pl-7 text-xs shadow-none focus-visible:ring-1"
          />
        </div>
      ) : null}
    </div>
  )
}
