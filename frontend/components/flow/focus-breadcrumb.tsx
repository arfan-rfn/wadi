"use client"

// Focus breadcrumb (§11 Phase 2.8): the call path from the handler to the
// focused method, file-path style — every crumb clickable, the first crumb
// clears focus. What makes aggressive re-rooting safe to use.
import { ChevronRight, X } from "lucide-react"

import type { CallTreeNode } from "@/lib/wadi/call-tree"
import { shortSignature } from "@/lib/wadi/rollup"

export function FocusBreadcrumb({
  path,
  onFocus,
  onClear,
}: {
  path: CallTreeNode[]
  onFocus: (methodId: string) => void
  onClear: () => void
}) {
  if (path.length === 0) return null
  return (
    <div className="flex items-center gap-0.5 rounded-md border px-1.5 py-0.5">
      {path.map((node, index) => (
        <span
          key={`${node.methodId}-${index}`}
          className="flex items-center gap-0.5"
        >
          {index > 0 ? (
            <ChevronRight
              className="size-3 text-subtle-foreground"
              aria-hidden
            />
          ) : null}
          <button
            className="rounded-sm px-1 py-0.5 font-mono text-2xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            onClick={() => (index === 0 ? onClear() : onFocus(node.methodId))}
            title={node.signature}
          >
            {shortSignature(node.signature)}
          </button>
        </span>
      ))}
      <button
        className="ml-1 rounded-sm p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
        onClick={onClear}
        title="Clear focus (Esc)"
      >
        <X className="size-3" aria-hidden />
      </button>
    </div>
  )
}
