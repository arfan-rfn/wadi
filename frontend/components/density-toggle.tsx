"use client"

// The density control (§11 Phase 2.10). Sits beside the theme toggle because
// it is the same KIND of choice: how this reader wants to look at the app,
// not what the app is showing them.

import { useEffect, useState } from "react"
import { Rows2, Rows3 } from "lucide-react"

import { cn } from "@/lib/utils"
import {
  applyDensity,
  readDensity,
  writeDensity,
  type Density,
} from "@/lib/wadi/density"

export function DensityToggle({ className }: { className?: string }) {
  // The inline head script has already stamped the attribute before paint, so
  // this state exists only to drive the button's own label and pressed state.
  // Starting it at the default and correcting after mount keeps the server and
  // first client render identical — the same rule the header's scope pickers
  // and the panel header's count follow.
  const [density, setDensity] = useState<Density>("comfortable")
  const [mounted, setMounted] = useState(false)

  useEffect(() => {
    setDensity(readDensity())
    setMounted(true)
  }, [])

  function toggle() {
    const next: Density = density === "compact" ? "comfortable" : "compact"
    setDensity(next)
    writeDensity(next)
    applyDensity(next)
  }

  const compact = mounted && density === "compact"
  const Icon = compact ? Rows3 : Rows2
  const label = compact ? "Switch to comfortable rows" : "Switch to compact rows"

  return (
    <button
      type="button"
      onClick={toggle}
      aria-pressed={compact}
      aria-label={label}
      title={`${label} — spacing only, text size never changes`}
      className={cn(
        "inline-flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-sm",
        "text-muted-foreground transition-colors hover:bg-accent hover:text-foreground",
        "focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
        className
      )}
    >
      <Icon aria-hidden className="size-4" />
    </button>
  )
}
