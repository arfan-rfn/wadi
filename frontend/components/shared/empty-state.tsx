import { cn } from "@/lib/utils"

/** The one way panes say "nothing here, and here's why" — a stated state,
 * never a blank (P10). */
export function EmptyState({
  children,
  className,
}: {
  children: React.ReactNode
  className?: string
}) {
  return (
    <p className={cn("px-3 py-6 text-sm text-muted-foreground", className)}>
      {children}
    </p>
  )
}
