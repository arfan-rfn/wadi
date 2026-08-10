import { cn } from "@/lib/utils"

/** A loading placeholder.
 *
 * `bg-skeleton`, not `bg-muted`: see the token's note in globals.css. The
 * pulse is deliberately kept — motion is what separates "still loading" from
 * "an empty box that failed to fill", and colour alone cannot say that.
 */
function Skeleton({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("animate-pulse rounded-md bg-skeleton", className)}
      {...props}
    />
  )
}

export { Skeleton }
