import * as React from "react"
import { useRender } from "@base-ui/react/use-render"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

const badgeVariants = cva(
  "inline-flex items-center justify-center rounded-md border px-2 py-0.5 text-xs font-medium w-fit whitespace-nowrap shrink-0 [&>svg]:size-3 gap-1 [&>svg]:pointer-events-none focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 aria-invalid:border-destructive transition-[color,box-shadow] overflow-hidden",
  {
    variants: {
      variant: {
        default:
          "border-transparent bg-primary text-primary-foreground [a&]:hover:bg-primary/90",
        secondary:
          "border-transparent bg-secondary text-secondary-foreground [a&]:hover:bg-secondary/90",
        destructive:
          "border-transparent bg-destructive text-white [a&]:hover:bg-destructive/90 focus-visible:ring-destructive/20 dark:focus-visible:ring-destructive/40 dark:bg-destructive/60",
        outline:
          "text-foreground [a&]:hover:bg-accent [a&]:hover:text-accent-foreground",

        // Status variants (added 2026-08-06 with the achromatic accent).
        //
        // A run's status used to wear `variant="default"`, which is the BRAND
        // fill. That was quietly wrong all along — "succeeded" is a fact about
        // the data, not a call to action — and the neutral rebuild made it
        // visible: with a near-white primary, a routine green-path status
        // became the single loudest element in the header, out-shouting the
        // endpoint it describes. These are tinted rather than filled, so the
        // status reads at a glance without competing for the eye.
        ok: "border-ok/30 bg-ok/10 text-ok",
        warn: "border-warn/30 bg-warn/10 text-warn",
        bad: "border-bad/30 bg-bad/10 text-bad",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

function Badge({
  className,
  variant,
  render,
  ...props
}: React.ComponentProps<"span"> &
  VariantProps<typeof badgeVariants> & {
    /** Base UI's composition primitive, in place of Radix's `asChild`. */
    render?: useRender.RenderProp
  }) {
  return useRender({
    render: render ?? <span />,
    props: {
      "data-slot": "badge",
      className: cn(badgeVariants({ variant }), className),
      ...props,
    },
  })
}

export { Badge, badgeVariants }
