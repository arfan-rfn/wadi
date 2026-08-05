"use client"

import * as React from "react"
import * as ScrollAreaPrimitive from "@radix-ui/react-scroll-area"

import { cn } from "@/lib/utils"

const ScrollArea = React.forwardRef<
  React.ElementRef<typeof ScrollAreaPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof ScrollAreaPrimitive.Root> & {
    /** The scrolling element itself. Virtualizers and IntersectionObservers
     *  need it — Radix nests the real scroller one level below Root, so
     *  without this a caller can only ever reach the wrong element. */
    viewportRef?: React.Ref<HTMLDivElement>
    /** Render a horizontal bar too (code, wide tables). */
    orientation?: "vertical" | "horizontal" | "both"
    viewportClassName?: string
  }
>(
  (
    {
      className,
      children,
      viewportRef,
      orientation = "vertical",
      viewportClassName,
      ...props
    },
    ref
  ) => (
    <ScrollAreaPrimitive.Root
      ref={ref}
      // `type="hover"` keeps the bars out of the layout entirely and fades
      // them in on approach. A permanently-reserved native gutter is exactly
      // the chrome this replaces.
      type="hover"
      scrollHideDelay={400}
      className={cn("relative overflow-hidden", className)}
      {...props}
    >
      <ScrollAreaPrimitive.Viewport
        ref={viewportRef}
        className={cn(
          "size-full rounded-[inherit]",
          // Radix wraps children in `display: table; min-width: 100%`. A table
          // box is shrink-to-fit, so it GROWS past the viewport for any
          // unbreakable string — a long URI, an access rule, a deep file path.
          // Children then size against that wider box, so `truncate` and
          // `break-all` measure the wrong width and the overflow is clipped by
          // Root's `overflow-hidden` with no bar to scroll it back. Content
          // simply disappears off the right edge.
          //
          // Only correct when there is no horizontal bar: with one, the table
          // box is exactly what makes wide content reachable. So this follows
          // the orientation the caller already declared rather than being a
          // blanket override.
          orientation === "vertical" && "[&>div]:!block",
          viewportClassName
        )}
      >
        {children}
      </ScrollAreaPrimitive.Viewport>
      {orientation !== "horizontal" ? <ScrollBar /> : null}
      {orientation !== "vertical" ? (
        <ScrollBar orientation="horizontal" />
      ) : null}
      <ScrollAreaPrimitive.Corner />
    </ScrollAreaPrimitive.Root>
  )
)
ScrollArea.displayName = ScrollAreaPrimitive.Root.displayName

const ScrollBar = React.forwardRef<
  React.ElementRef<typeof ScrollAreaPrimitive.ScrollAreaScrollbar>,
  React.ComponentPropsWithoutRef<typeof ScrollAreaPrimitive.ScrollAreaScrollbar>
>(({ className, orientation = "vertical", ...props }, ref) => (
  <ScrollAreaPrimitive.ScrollAreaScrollbar
    ref={ref}
    orientation={orientation}
    className={cn(
      "z-10 flex touch-none p-0.5 transition-opacity select-none",
      "data-[state=hidden]:opacity-0 motion-reduce:transition-none",
      orientation === "vertical" && "w-2",
      orientation === "horizontal" && "h-2 flex-col",
      className
    )}
    {...props}
  >
    <ScrollAreaPrimitive.ScrollAreaThumb
      className={cn(
        "relative flex-1 rounded-full bg-muted-foreground/30 transition-colors",
        "hover:bg-muted-foreground/50"
      )}
    />
  </ScrollAreaPrimitive.ScrollAreaScrollbar>
))
ScrollBar.displayName = ScrollAreaPrimitive.ScrollAreaScrollbar.displayName

export { ScrollArea, ScrollBar }
