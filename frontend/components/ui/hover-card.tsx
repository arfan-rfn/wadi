"use client"

import * as React from "react"
import { PreviewCard as PreviewCardPrimitive } from "@base-ui/react/preview-card"

import { cn } from "@/lib/utils"

// Base UI names this primitive `PreviewCard`. The exported API keeps the
// `HoverCard*` names the app already calls, so the migration does not ripple
// into call sites for a rename that carries no new meaning.

function HoverCard(
  props: React.ComponentProps<typeof PreviewCardPrimitive.Root>
) {
  return <PreviewCardPrimitive.Root data-slot="hover-card" {...props} />
}

// Base UI puts the open delay on the TRIGGER, not the root — a card can have
// several triggers and they need not share a hover latency. The 150ms default
// is preserved from the Radix configuration.
function HoverCardTrigger({
  delay = 150,
  ...props
}: React.ComponentProps<typeof PreviewCardPrimitive.Trigger>) {
  return (
    <PreviewCardPrimitive.Trigger
      data-slot="hover-card-trigger"
      delay={delay}
      {...props}
    />
  )
}

function HoverCardContent({
  className,
  align = "start",
  side,
  sideOffset = 6,
  ...props
}: React.ComponentProps<typeof PreviewCardPrimitive.Popup> &
  Pick<
    React.ComponentProps<typeof PreviewCardPrimitive.Positioner>,
    "side" | "align" | "sideOffset"
  >) {
  return (
    <PreviewCardPrimitive.Portal>
      <PreviewCardPrimitive.Positioner
        align={align}
        side={side}
        sideOffset={sideOffset}
        className="z-50"
      >
        <PreviewCardPrimitive.Popup
          data-slot="hover-card-content"
          className={cn(
            "w-72 rounded-lg border bg-popover p-3 text-popover-foreground shadow-md outline-none",
            "transition-opacity duration-150 data-[ending-style]:opacity-0 data-[starting-style]:opacity-0",
            "motion-reduce:transition-none",
            className
          )}
          {...props}
        />
      </PreviewCardPrimitive.Positioner>
    </PreviewCardPrimitive.Portal>
  )
}

export { HoverCard, HoverCardContent, HoverCardTrigger }
