"use client"

import * as React from "react"
import { ScrollArea as ScrollAreaPrimitive } from "@base-ui/react/scroll-area"

import { cn } from "@/lib/utils"

const ScrollArea = React.forwardRef<
  React.ComponentRef<typeof ScrollAreaPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof ScrollAreaPrimitive.Root> & {
    /** The scrolling element itself. Virtualizers and IntersectionObservers
     *  need it — the real scroller is nested one level below Root, so without
     *  this a caller can only ever reach the wrong element. */
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
      className={cn("relative overflow-hidden", className)}
      {...props}
    >
      <ScrollAreaPrimitive.Viewport
        ref={viewportRef}
        // Base UI's viewport is a plain box. Radix wrapped children in
        // `display: table; min-width: 100%`, which is shrink-to-fit and so
        // GREW past the viewport for any unbreakable string — a long URI, an
        // access rule, a deep file path. Children then sized against that
        // wider box, `truncate` and `break-all` measured the wrong width, and
        // the overflow was clipped by Root with no bar to scroll it back.
        // The `[&>div]:!block` override that existed to undo it is gone with
        // the behaviour that required it.
        className={cn(
          "size-full rounded-[inherit] focus-visible:outline-none",
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
ScrollArea.displayName = "ScrollArea"

const ScrollBar = React.forwardRef<
  React.ComponentRef<typeof ScrollAreaPrimitive.Scrollbar>,
  React.ComponentPropsWithoutRef<typeof ScrollAreaPrimitive.Scrollbar>
>(({ className, orientation = "vertical", ...props }, ref) => (
  <ScrollAreaPrimitive.Scrollbar
    ref={ref}
    orientation={orientation}
    // Bars stay out of the layout and fade in on approach — a permanently
    // reserved native gutter is exactly the chrome this replaces. Radix drove
    // this with `type="hover"` + `scrollHideDelay`; Base UI publishes the same
    // facts as data attributes, so it is expressed in CSS instead of config.
    className={cn(
      "z-10 flex touch-none p-0.5 opacity-0 transition-opacity duration-150 select-none",
      "data-[hovering]:opacity-100 data-[scrolling]:opacity-100",
      "motion-reduce:transition-none",
      orientation === "vertical" && "w-2",
      orientation === "horizontal" && "h-2 flex-col",
      className
    )}
    {...props}
  >
    <ScrollAreaPrimitive.Thumb
      className={cn(
        "relative flex-1 rounded-full bg-muted-foreground/30 transition-colors",
        "hover:bg-muted-foreground/50"
      )}
    />
  </ScrollAreaPrimitive.Scrollbar>
))
ScrollBar.displayName = "ScrollBar"

export { ScrollArea, ScrollBar }
