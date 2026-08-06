import { cn } from "@/lib/utils"

// One saturated element in the whole UI: HTTP-method chips. Everything else
// stays calm so these carry the scannability — and since the app's accent is
// achromatic (see globals.css), nothing else on the surface competes for hue.
const METHOD_STYLES: Record<string, string> = {
  GET: "bg-verb-get/15 text-verb-get",
  POST: "bg-verb-post/15 text-verb-post",
  PUT: "bg-verb-put/15 text-verb-put",
  PATCH: "bg-verb-patch/15 text-verb-patch",
  DELETE: "bg-verb-delete/15 text-verb-delete",
}

export function MethodBadge({
  method,
  className,
}: {
  method: string
  className?: string
}) {
  return (
    <span
      className={cn(
        "inline-flex w-14 shrink-0 items-center justify-center rounded-sm px-1.5 py-0.5 font-mono text-2xs font-semibold tracking-wide",
        METHOD_STYLES[method] ?? "bg-muted text-muted-foreground",
        className
      )}
    >
      {method}
    </span>
  )
}
