"use client"

// One header line (recorded 2026-08-05).
//
// This used to be two stacked bars — branding + nav at 4rem, then the
// system/snapshot pickers at 3rem — which spent 7rem of vertical space and two
// horizontal rules before any content. They are one bar now: brand, then the
// scope you are looking at, then what is in it. The panes get the height back,
// and there is a single line to read left-to-right instead of two to correlate.
import Link from "next/link"

import { siteConfig } from "@/config/site"
import { useMounted } from "@/lib/hooks/use-mounted"
import { cn } from "@/lib/utils"
import { DensityToggle } from "@/components/density-toggle"
import { ThemeToggle } from "@/components/theme-toggle"
import { WadiMark } from "@/components/wadi-mark"

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
  // anyway made the markup disagree with the client, which shifts every
  // `useId` after it and surfaces as a hydration mismatch on the dropdown
  // triggers. Mounting them after hydration is not a workaround: it matches
  // where the data actually comes from.
  const mounted = useMounted()
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
        {/* The brand lockup, built live: the mark beside the wordmark at the
            proportions the brand sheet specifies (Geist 600, lowercase,
            tracking -0.04em). Rendering it from the token rather than shipping
            a lockup image means it re-themes with the header and stays crisp
            at any zoom. */}
        <WadiMark className="size-4 shrink-0 text-primary" />
        <span className="text-sm tracking-[-0.04em] lowercase">
          {siteConfig.name}
        </span>
      </Link>

      {scope && mounted ? (
        <>
          <span aria-hidden className="text-subtle-foreground">
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
        <DensityToggle />
        <ThemeToggle />
      </div>
    </header>
  )
}
