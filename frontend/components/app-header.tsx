"use client"

// One header line (recorded 2026-08-05).
//
// This used to be two stacked bars — branding + nav at 4rem, then the
// system/snapshot pickers at 3rem — which spent 7rem of vertical space and two
// horizontal rules before any content. They are one bar now: brand, then the
// scope you are looking at, then what is in it. The panes get the height back,
// and there is a single line to read left-to-right instead of two to correlate.
import { useEffect, useState } from "react"
import Link from "next/link"
import { GitMerge } from "lucide-react"

import { siteConfig } from "@/config/site"
import { cn } from "@/lib/utils"
import { ThemeToggle } from "@/components/theme-toggle"

export function AppHeader({
  scope,
  summary,
  className,
}: {
  /** Scope controls (system / snapshot pickers) rendered inline after the brand. */
  scope?: React.ReactNode
  /** Right-aligned counts, before the theme toggle. */
  summary?: React.ReactNode
  className?: string
}) {
  // The scope pickers are driven entirely by client-fetched data, so the
  // server has nothing real to render for them — and rendering the shell
  // anyway made the markup disagree with the client, which shifts every Radix
  // `useId` after it and surfaces as a hydration mismatch on the dropdown
  // triggers. Mounting them after hydration is not a workaround: it matches
  // where the data actually comes from.
  const [mounted, setMounted] = useState(false)
  useEffect(() => setMounted(true), [])
  return (
    <header
      className={cn(
        "sticky top-0 z-40 flex h-12 w-full shrink-0 items-center gap-2 border-b bg-background px-3 sm:px-4",
        className
      )}
    >
      <Link
        href="/"
        className={cn(
          "flex shrink-0 items-center gap-2 rounded-md px-1 py-1 font-semibold transition-colors",
          "hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        )}
      >
        <GitMerge aria-hidden className="size-4 text-primary" />
        <span className="text-sm">{siteConfig.name}</span>
      </Link>

      {scope && mounted ? (
        <>
          <span aria-hidden className="text-muted-foreground/40">
            /
          </span>
          <div className="flex min-w-0 items-center gap-1.5">{scope}</div>
        </>
      ) : null}

      <div className="ml-auto flex shrink-0 items-center gap-2">
        {summary ? (
          <span className="hidden text-2xs text-muted-foreground sm:inline">
            {summary}
          </span>
        ) : null}
        <ThemeToggle />
      </div>
    </header>
  )
}
