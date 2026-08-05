"use client"

// The endpoint row's metadata: two chips that each say one whole thing.
//
// This started as five separate marks — an auth icon, loose role dots, a
// dependency count, and `2p`/`req`/`res` — which is five things to parse for
// two facts. Access and its roles are ONE fact ("ADMIN can call this"), so
// they are one chip; the shape marks were dropped entirely because a param
// count answers a question nobody asks from a list, and both shapes are one
// click away in the peek.
//
// The chips are labelled, not iconographic: "1 service" is legible on first
// sight in a way a bare `⚲ 1` never was. The icon stays as the fast visual
// key; the word is what makes it unambiguous.
//
// The two no-claim states carry DIFFERENT words — "Unreadable guard" vs "No
// guard found" — even though both mean `authenticated: null`. Labelling both
// "No claim" would have collapsed the §5.2.9 distinction into the tooltip,
// and that distinction is the whole point: one is a gap in wadi, the other a
// possible hole in the system.
import {
  Ban,
  Globe,
  Lock,
  Network,
  ShieldQuestion,
  ShieldX,
} from "lucide-react"

import type { EndpointDependency } from "@/lib/generated/endpoint_dependencies.schema"
import { cn } from "@/lib/utils"
import { useRoleSwatchStyle } from "@/lib/wadi/role-colors"
import {
  HoverCard,
  HoverCardContent,
  HoverCardTrigger,
} from "@/components/ui/hover-card"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import type { AuthState } from "@/components/shared/auth-chip"

const ACCESS: Record<
  AuthState,
  {
    icon: typeof Lock
    tone: string
    fallback: string
    title: string
    detail: string
  }
> = {
  required: {
    icon: Lock,
    tone: "border-emerald-500/30 text-emerald-700 dark:text-emerald-400",
    fallback: "Authenticated",
    title: "Authentication required",
    detail:
      "A guard in scope demands an authenticated caller before this endpoint runs.",
  },
  denied: {
    icon: Ban,
    tone: "border-red-500/30 text-red-700 dark:text-red-400",
    fallback: "Denied to all",
    title: "Denied to every caller",
    detail:
      "A rule that was read denies every request, authenticated or not. This route is unreachable — dead surface, not protected surface.",
  },
  open: {
    icon: Globe,
    tone: "border-amber-500/30 text-amber-700 dark:text-amber-400",
    fallback: "Public",
    title: "Public — no authentication",
    detail:
      "Every guard that could cover this endpoint was read, and none of them gates it. Anyone who can reach the service can call it.",
  },
  withheld: {
    icon: ShieldX,
    tone: "border-dashed text-muted-foreground",
    fallback: "Unreadable guard",
    title: "No claim — a guard could not be read",
    detail:
      "Something guards this endpoint, but its effect could not be determined, so wadi makes no claim either way. This is a gap in the analysis, not necessarily in the system.",
  },
  unknown: {
    icon: ShieldQuestion,
    tone: "border-dashed text-muted-foreground",
    fallback: "No guard found",
    title: "No claim — nothing gating was found",
    detail:
      "No security rule, annotation or filter that could cover this endpoint was found at all. That may be a real hole.",
  },
}

function RoleName({ role }: { role: string }) {
  const swatch = useRoleSwatchStyle(role)
  return (
    <span className="inline-flex items-center gap-1">
      <span
        aria-hidden
        className="size-[6px] shrink-0 rounded-full"
        style={swatch}
      />
      {role}
    </span>
  )
}

/** Who can call this endpoint — the state and who it admits, as one chip.
 *
 * Roles and authorities both name a grant the caller must hold, so they read
 * as one list here; the tooltip keeps them apart, because `hasRole("ADMIN")`
 * and `hasAuthority("ADMIN")` match different grants in Spring. */
export function AccessChip({
  state,
  roles,
  authorities = [],
}: {
  state: AuthState
  roles: readonly string[]
  authorities?: readonly string[]
}) {
  const { icon: Icon, tone, fallback, title, detail } = ACCESS[state]
  // Deduped: one rule can require the role ADMIN while another requires the
  // authority ADMIN, and rendering the same name twice reads as two grants —
  // besides colliding on the React key.
  const granted = [...new Set([...roles, ...authorities])]
  const named = state === "required" && granted.length > 0
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          tabIndex={0}
          aria-label={named ? `${title}: ${granted.join(", ")}` : title}
          className={cn(
            "inline-flex cursor-help items-center gap-1.5 rounded-full border px-2 py-0.5 font-mono text-2xs",
            "focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
            tone
          )}
        >
          <Icon aria-hidden className="size-3 shrink-0" />
          {named ? (
            granted.map((name) => <RoleName key={name} role={name} />)
          ) : (
            <span>{fallback}</span>
          )}
        </span>
      </TooltipTrigger>
      <TooltipContent>
        <p className="font-medium">{title}</p>
        <p className="mt-1 text-muted-foreground">{detail}</p>
        {roles.length > 0 ? (
          <p className="mt-1 font-mono text-2xs">Roles: {roles.join(", ")}</p>
        ) : null}
        {authorities.length > 0 ? (
          <p className="mt-1 font-mono text-2xs">
            Authorities: {authorities.join(", ")}
          </p>
        ) : null}
      </TooltipContent>
    </Tooltip>
  )
}

const KIND_NOTE: Record<string, string> = {
  analyzed: "another analyzed service in this snapshot",
  external: "an external host, outside the analyzed system",
  placeholder: "a service named in config but not analyzed",
  undetermined: "target could not be resolved — see coverage for the reason",
}

/** How many services this endpoint reaches, and which. Cross-service calls are
 *  the core extracted fact, so the count is spelled out rather than iconified. */
export function DependencyChip({
  dependencies,
}: {
  dependencies: readonly EndpointDependency[]
}) {
  if (dependencies.length === 0) return null
  const label = `${dependencies.length} service${dependencies.length === 1 ? "" : "s"}`
  return (
    <HoverCard>
      <HoverCardTrigger asChild>
        <span
          tabIndex={0}
          className={cn(
            "inline-flex cursor-help items-center gap-1.5 rounded-full border px-2 py-0.5 font-mono text-2xs text-muted-foreground transition-colors",
            "hover:border-muted-foreground/60 hover:text-foreground",
            "focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          )}
        >
          <Network aria-hidden className="size-3 shrink-0" />
          <span className="tabular-nums">{label}</span>
        </span>
      </HoverCardTrigger>
      <HoverCardContent className="w-80">
        <p className="text-2xs font-semibold tracking-[0.08em] text-muted-foreground uppercase">
          Calls {label}
        </p>
        <ul className="mt-2 space-y-1.5">
          {dependencies.map((dependency) => (
            <li key={dependency.label} className="flex items-baseline gap-2">
              <span className="min-w-0 flex-1 truncate font-mono text-xs">
                {dependency.label}
              </span>
              <span
                className="shrink-0 rounded-full border px-1.5 text-[10px] text-muted-foreground"
                title={KIND_NOTE[dependency.target_kind]}
              >
                {dependency.confidence}
              </span>
            </li>
          ))}
        </ul>
        <p className="mt-2 text-2xs text-muted-foreground">
          Confidence is how sure the match is, not how often it runs. Open the
          endpoint to see where in the flow each call sits.
        </p>
      </HoverCardContent>
    </HoverCard>
  )
}
