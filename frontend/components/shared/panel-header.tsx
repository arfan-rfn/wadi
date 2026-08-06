"use client"

import { Search } from "lucide-react"

import { useMounted } from "@/lib/hooks/use-mounted"
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
  // one. See `useMounted` for why this is gated on mount rather than on the
  // count being defined.
  const mounted = useMounted()
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
