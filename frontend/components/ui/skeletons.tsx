import { Skeleton } from "./skeleton"
import { cn } from "@/lib/utils"

export function ProfileSkeleton({ className }: { className?: string }) {
  return (
    <div className={cn("min-h-screen p-4", className)}>
      <div className="w-full max-w-md mx-auto pt-20">
        <div className="text-center space-y-8">
          {/* Avatar skeleton */}
          <Skeleton className="size-24 rounded-full mx-auto" />

          {/* Name and email skeletons */}
          <div className="space-y-3">
            <Skeleton className="h-8 w-48 mx-auto" />
            <Skeleton className="h-5 w-56 mx-auto" />
          </div>

          {/* Buttons skeleton */}
          <div className="flex gap-3 justify-center">
            <Skeleton className="h-10 w-[150px]" />
            <Skeleton className="h-10 w-[150px]" />
          </div>
        </div>
      </div>
    </div>
  )
}

export function CardSkeleton({
  className,
  showHeader = true,
  contentRows = 3,
  headerWidth = "w-64"
}: {
  className?: string
  showHeader?: boolean
  contentRows?: number
  headerWidth?: string
}) {
  return (
    <div className={cn("rounded-lg border bg-card p-6 space-y-4", className)}>
      {showHeader && (
        <div className="space-y-2">
          <Skeleton className={cn("h-6", headerWidth)} />
          <Skeleton className="h-4 w-full max-w-sm" />
        </div>
      )}
      <div className="space-y-3">
        {Array.from({ length: contentRows }).map((_, i) => (
          <Skeleton key={i} className="h-4 w-full" />
        ))}
      </div>
    </div>
  )
}

export function AccountInfoSkeleton({ className }: { className?: string }) {
  return (
    <div className={cn("space-y-6", className)}>
      {/* Account Information Card */}
      <div className="rounded-lg border bg-card p-6 space-y-6">
        {/* Header */}
        <div className="space-y-2">
          <Skeleton className="h-6 w-48" />
          <Skeleton className="h-4 w-64" />
        </div>

        {/* Content grid */}
        <div className="grid gap-6">
          <div className="grid gap-4 sm:grid-cols-2">
            {/* Name field */}
            <div className="flex items-start gap-3">
              <Skeleton className="size-4 mt-0.5 shrink-0" />
              <div className="space-y-2 flex-1">
                <Skeleton className="h-4 w-12" />
                <Skeleton className="h-4 w-32" />
              </div>
            </div>

            {/* Email field */}
            <div className="flex items-start gap-3">
              <Skeleton className="size-4 mt-0.5 shrink-0" />
              <div className="space-y-2 flex-1">
                <Skeleton className="h-4 w-20" />
                <Skeleton className="h-4 w-48" />
              </div>
            </div>

            {/* Date field */}
            <div className="flex items-start gap-3">
              <Skeleton className="size-4 mt-0.5 shrink-0" />
              <div className="space-y-2 flex-1">
                <Skeleton className="h-4 w-24" />
                <Skeleton className="h-4 w-36" />
              </div>
            </div>

            {/* ID field */}
            <div className="flex items-start gap-3 sm:col-span-2">
              <Skeleton className="size-4 mt-0.5 shrink-0" />
              <div className="space-y-2 flex-1">
                <Skeleton className="h-4 w-20" />
                <Skeleton className="h-4 w-full max-w-lg" />
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Danger Zone Card */}
      <div className="rounded-lg border border-destructive/20 bg-card p-6 space-y-4">
        <div className="space-y-2">
          <Skeleton className="h-6 w-32" />
          <Skeleton className="h-4 w-80" />
        </div>

        <div className="space-y-4">
          {/* Sign out section */}
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div className="space-y-2 flex-1">
              <Skeleton className="h-5 w-20" />
              <Skeleton className="h-4 w-64" />
            </div>
            <Skeleton className="h-10 w-full sm:w-24" />
          </div>

          <Skeleton className="h-px w-full" />

          {/* Delete account section */}
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div className="space-y-2 flex-1">
              <Skeleton className="h-5 w-28" />
              <Skeleton className="h-4 w-72" />
            </div>
            <Skeleton className="h-10 w-full sm:w-32" />
          </div>
        </div>
      </div>
    </div>
  )
}

export function ListSkeleton({
  items = 5,
  className
}: {
  items?: number
  className?: string
}) {
  return (
    <div className={cn("space-y-3", className)}>
      {Array.from({ length: items }).map((_, i) => (
        <div key={i} className="flex items-center gap-3 p-3 rounded-lg border">
          <Skeleton className="size-10 rounded-full shrink-0" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-4 w-3/4" />
            <Skeleton className="h-3 w-1/2" />
          </div>
          <Skeleton className="h-8 w-20" />
        </div>
      ))}
    </div>
  )
}

export function TableSkeleton({
  rows = 5,
  columns = 4,
  className
}: {
  rows?: number
  columns?: number
  className?: string
}) {
  return (
    <div className={cn("space-y-3", className)}>
      {/* Header */}
      <div className="flex gap-4 pb-2 border-b">
        {Array.from({ length: columns }).map((_, i) => (
          <Skeleton key={i} className="h-4 flex-1" />
        ))}
      </div>

      {/* Rows */}
      {Array.from({ length: rows }).map((_, rowIndex) => (
        <div key={rowIndex} className="flex gap-4 py-2">
          {Array.from({ length: columns }).map((_, colIndex) => (
            <Skeleton key={colIndex} className="h-4 flex-1" />
          ))}
        </div>
      ))}
    </div>
  )
}