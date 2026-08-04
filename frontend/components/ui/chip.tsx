import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

// The one shared small-label primitive (§11 Phase 2.8): every ad-hoc rounded
// span in the explorer converges here. The `unknown` variant is dashed on
// purpose — unresolved facts must LOOK unresolved (P10); `condition` is the
// governing-condition amber; nothing here is saturated (the one saturated
// element in the UI stays the HTTP-method chip).
const chipVariants = cva(
  // `max-w-full` + `break-all`: a chip carrying a deep repo path must wrap
  // inside its panel, not stretch it. `shrink-0` keeps chips from being
  // squeezed by their neighbours; without the max-width it also let one long
  // path push the whole inspector past its slot.
  "inline-flex w-fit max-w-full shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-2xs leading-4 break-all [&>svg]:size-3 [&>svg]:pointer-events-none",
  {
    variants: {
      variant: {
        outline: "text-muted-foreground",
        unknown: "border-dashed border-destructive/60 text-destructive",
        condition:
          "border-amber-500/40 bg-amber-500/5 text-amber-700 dark:text-amber-400",
        mono: "font-mono text-muted-foreground",
      },
    },
    defaultVariants: {
      variant: "outline",
    },
  }
)

function Chip({
  className,
  variant,
  ...props
}: React.ComponentProps<"span"> & VariantProps<typeof chipVariants>) {
  return (
    <span
      data-slot="chip"
      className={cn(chipVariants({ variant }), className)}
      {...props}
    />
  )
}

export { Chip }
