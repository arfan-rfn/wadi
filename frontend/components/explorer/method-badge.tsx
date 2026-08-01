import { cn } from "@/lib/utils"

// One saturated element in the whole UI: HTTP-method chips. Everything else
// stays calm so these carry the scannability.
const METHOD_STYLES: Record<string, string> = {
  GET: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400",
  POST: "bg-sky-500/15 text-sky-600 dark:text-sky-400",
  PUT: "bg-amber-500/15 text-amber-600 dark:text-amber-400",
  PATCH: "bg-violet-500/15 text-violet-600 dark:text-violet-400",
  DELETE: "bg-red-500/15 text-red-600 dark:text-red-400",
}

export function MethodBadge({ method, className }: { method: string; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex w-14 shrink-0 items-center justify-center rounded px-1.5 py-0.5 font-mono text-[11px] font-semibold tracking-wide",
        METHOD_STYLES[method] ?? "bg-muted text-muted-foreground",
        className
      )}
    >
      {method}
    </span>
  )
}
