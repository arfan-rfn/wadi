import * as React from "react"
import { Menu as MenuPrimitive } from "@base-ui/react/menu"
import { Check, ChevronRight, Circle } from "lucide-react"

import { cn } from "@/lib/utils"

// Base UI calls this primitive `Menu`; the exported API keeps the
// `DropdownMenu*` names the app already calls. Two structural differences
// from Radix are worth knowing when editing this file:
//
//  1. Placement lives on a `Positioner` between Portal and Popup, not on the
//     content element itself.
//  2. Transition phase is published as `data-starting-style` /
//     `data-ending-style` rather than `data-state=open|closed`, and the
//     highlighted item carries `data-highlighted` rather than `:focus`.

const DropdownMenu = MenuPrimitive.Root

const DropdownMenuTrigger = MenuPrimitive.Trigger

const DropdownMenuGroup = MenuPrimitive.Group

const DropdownMenuPortal = MenuPrimitive.Portal

const DropdownMenuSub = MenuPrimitive.SubmenuRoot

const DropdownMenuRadioGroup = MenuPrimitive.RadioGroup

/** Shared item chrome: one row, one highlight rule. */
const itemClass = cn(
  "relative flex cursor-default items-center rounded-sm px-2 py-1.5 text-sm select-none",
  "outline-none transition-colors",
  "data-[highlighted]:bg-accent data-[highlighted]:text-accent-foreground",
  "data-[disabled]:pointer-events-none data-[disabled]:opacity-50"
)

/** Shared popup chrome for the menu and its submenus.
 *
 * The height cap is load-bearing: a menu listing every snapshot in a system
 * runs past the viewport, and without a bound it simply overflowed with no
 * way to reach the items below the fold. `--available-height` is published by
 * the Positioner — it is the room actually left between the anchor and the
 * viewport edge on the side the menu opened — so the cap follows the trigger
 * up and down the page instead of being a guessed constant. */
const popupClass = cn(
  "min-w-32 rounded-md border bg-popover p-1 text-popover-foreground shadow-md",
  "max-h-[var(--available-height)] overflow-x-hidden overflow-y-auto overscroll-contain",
  "origin-[var(--transform-origin)] transition-[opacity,transform] duration-150",
  "data-[ending-style]:scale-95 data-[ending-style]:opacity-0",
  "data-[starting-style]:scale-95 data-[starting-style]:opacity-0",
  "motion-reduce:transition-none"
)

const DropdownMenuSubTrigger = React.forwardRef<
  React.ComponentRef<typeof MenuPrimitive.SubmenuTrigger>,
  React.ComponentPropsWithoutRef<typeof MenuPrimitive.SubmenuTrigger> & {
    inset?: boolean
  }
>(({ className, inset, children, ...props }, ref) => (
  <MenuPrimitive.SubmenuTrigger
    ref={ref}
    className={cn(itemClass, "data-[popup-open]:bg-accent", inset && "pl-8", className)}
    {...props}
  >
    {children}
    <ChevronRight className="ml-auto size-4" />
  </MenuPrimitive.SubmenuTrigger>
))
DropdownMenuSubTrigger.displayName = "DropdownMenuSubTrigger"

const DropdownMenuSubContent = React.forwardRef<
  React.ComponentRef<typeof MenuPrimitive.Popup>,
  React.ComponentPropsWithoutRef<typeof MenuPrimitive.Popup>
>(({ className, ...props }, ref) => (
  <MenuPrimitive.Portal>
    <MenuPrimitive.Positioner className="z-50" sideOffset={4}>
      <MenuPrimitive.Popup ref={ref} className={cn(popupClass, className)} {...props} />
    </MenuPrimitive.Positioner>
  </MenuPrimitive.Portal>
))
DropdownMenuSubContent.displayName = "DropdownMenuSubContent"

const DropdownMenuContent = React.forwardRef<
  React.ComponentRef<typeof MenuPrimitive.Popup>,
  React.ComponentPropsWithoutRef<typeof MenuPrimitive.Popup> &
    Pick<
      React.ComponentPropsWithoutRef<typeof MenuPrimitive.Positioner>,
      "side" | "align" | "sideOffset" | "alignOffset"
    >
>(({ className, side, align, sideOffset = 4, alignOffset, ...props }, ref) => (
  <MenuPrimitive.Portal>
    <MenuPrimitive.Positioner
      className="z-50"
      side={side}
      align={align}
      sideOffset={sideOffset}
      alignOffset={alignOffset}
    >
      <MenuPrimitive.Popup ref={ref} className={cn(popupClass, className)} {...props} />
    </MenuPrimitive.Positioner>
  </MenuPrimitive.Portal>
))
DropdownMenuContent.displayName = "DropdownMenuContent"

const DropdownMenuItem = React.forwardRef<
  React.ComponentRef<typeof MenuPrimitive.Item>,
  React.ComponentPropsWithoutRef<typeof MenuPrimitive.Item> & {
    inset?: boolean
  }
>(({ className, inset, ...props }, ref) => (
  <MenuPrimitive.Item
    ref={ref}
    className={cn(itemClass, inset && "pl-8", className)}
    {...props}
  />
))
DropdownMenuItem.displayName = "DropdownMenuItem"

const DropdownMenuCheckboxItem = React.forwardRef<
  React.ComponentRef<typeof MenuPrimitive.CheckboxItem>,
  React.ComponentPropsWithoutRef<typeof MenuPrimitive.CheckboxItem>
>(({ className, children, checked, ...props }, ref) => (
  <MenuPrimitive.CheckboxItem
    ref={ref}
    className={cn(itemClass, "py-1.5 pr-2 pl-8", className)}
    checked={checked}
    {...props}
  >
    <span className="absolute left-2 flex size-3.5 items-center justify-center">
      <MenuPrimitive.CheckboxItemIndicator>
        <Check className="size-4" />
      </MenuPrimitive.CheckboxItemIndicator>
    </span>
    {children}
  </MenuPrimitive.CheckboxItem>
))
DropdownMenuCheckboxItem.displayName = "DropdownMenuCheckboxItem"

const DropdownMenuRadioItem = React.forwardRef<
  React.ComponentRef<typeof MenuPrimitive.RadioItem>,
  React.ComponentPropsWithoutRef<typeof MenuPrimitive.RadioItem>
>(({ className, children, ...props }, ref) => (
  <MenuPrimitive.RadioItem
    ref={ref}
    className={cn(itemClass, "py-1.5 pr-2 pl-8", className)}
    {...props}
  >
    <span className="absolute left-2 flex size-3.5 items-center justify-center">
      <MenuPrimitive.RadioItemIndicator>
        <Circle className="size-2 fill-current" />
      </MenuPrimitive.RadioItemIndicator>
    </span>
    {children}
  </MenuPrimitive.RadioItem>
))
DropdownMenuRadioItem.displayName = "DropdownMenuRadioItem"

const labelClass = "px-2 py-1.5 text-sm font-semibold"

/**
 * A standalone heading inside a menu — presentational, no group semantics.
 *
 * This renders a plain element ON PURPOSE. Base UI's `Menu.GroupLabel` throws
 * "MenuGroupContext is missing" unless it has a `Menu.Group` ancestor, and
 * Radix's `Menu.Label` had no such requirement — so the direct port turned a
 * label that had always been legal into a crash the moment the header's
 * system picker opened. A component that explodes based on where it is placed
 * is a trap; when the heading really does name a set of items, use
 * `DropdownMenuGroup` + `DropdownMenuGroupLabel`, which associates the two for
 * assistive tech.
 */
const DropdownMenuLabel = React.forwardRef<
  HTMLDivElement,
  React.ComponentPropsWithoutRef<"div"> & { inset?: boolean }
>(({ className, inset, ...props }, ref) => (
  <div ref={ref} className={cn(labelClass, inset && "pl-8", className)} {...props} />
))
DropdownMenuLabel.displayName = "DropdownMenuLabel"

/** The accessible heading for a `DropdownMenuGroup`. Must be inside one. */
const DropdownMenuGroupLabel = React.forwardRef<
  React.ComponentRef<typeof MenuPrimitive.GroupLabel>,
  React.ComponentPropsWithoutRef<typeof MenuPrimitive.GroupLabel> & {
    inset?: boolean
  }
>(({ className, inset, ...props }, ref) => (
  <MenuPrimitive.GroupLabel
    ref={ref}
    className={cn(labelClass, inset && "pl-8", className)}
    {...props}
  />
))
DropdownMenuGroupLabel.displayName = "DropdownMenuGroupLabel"

const DropdownMenuSeparator = React.forwardRef<
  React.ComponentRef<typeof MenuPrimitive.Separator>,
  React.ComponentPropsWithoutRef<typeof MenuPrimitive.Separator>
>(({ className, ...props }, ref) => (
  <MenuPrimitive.Separator
    ref={ref}
    className={cn("-mx-1 my-1 h-px bg-border", className)}
    {...props}
  />
))
DropdownMenuSeparator.displayName = "DropdownMenuSeparator"

const DropdownMenuShortcut = ({
  className,
  ...props
}: React.HTMLAttributes<HTMLSpanElement>) => {
  return (
    <span
      className={cn(
        "ml-auto font-mono text-2xs tracking-widest text-subtle-foreground",
        className
      )}
      {...props}
    />
  )
}
DropdownMenuShortcut.displayName = "DropdownMenuShortcut"

export {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuCheckboxItem,
  DropdownMenuRadioItem,
  DropdownMenuLabel,
  DropdownMenuGroupLabel,
  DropdownMenuSeparator,
  DropdownMenuShortcut,
  DropdownMenuGroup,
  DropdownMenuPortal,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuRadioGroup,
}
