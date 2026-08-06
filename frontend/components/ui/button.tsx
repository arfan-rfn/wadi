import * as React from "react"
import { useRender } from "@base-ui/react/use-render"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

const buttonVariants = cva(
  cn(
    "inline-flex cursor-pointer items-center justify-center rounded-md text-sm font-medium",
    "ring-offset-background transition-colors",
    "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:outline-hidden",
    "disabled:pointer-events-none disabled:opacity-50"
  ),
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground hover:bg-primary/90",
        destructive:
          "bg-destructive text-destructive-foreground hover:bg-destructive/90",
        outline:
          "border border-input hover:bg-accent hover:text-accent-foreground",
        secondary:
          "bg-secondary text-secondary-foreground hover:bg-secondary/80",
        ghost: "hover:bg-accent hover:text-accent-foreground",
        link: "text-primary underline-offset-4 hover:underline",
        chip: "shadow-chip w-max overflow-hidden border-0 bg-muted hover:brightness-90",
      },
      size: {
        default: "h-10 px-4 py-2",
        sm: "h-9 rounded-md px-3",
        lg: "h-11 rounded-md px-8",
        icon: "size-10",
        text: "h-auto",
        round: "h-8 rounded-full px-3",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

export interface ButtonProps
  extends
    React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  /**
   * Replace the rendered `<button>` with another element, merging this
   * component's props into it.
   *
   * Base UI's composition primitive, in place of Radix's `asChild`. The
   * difference is where the element goes: `asChild` cloned the single child,
   * so the shell and the content were the same node; `render` takes the shell
   * as a prop and leaves `children` free. That is what lets a trigger own its
   * own content while still rendering as a Button.
   */
  render?: useRender.RenderProp
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, render, ...props }, ref) =>
    useRender({
      render: render ?? <button />,
      ref,
      props: {
        className: cn(buttonVariants({ variant, size, className })),
        ...props,
      },
    })
)
Button.displayName = "Button"

export { Button, buttonVariants }
