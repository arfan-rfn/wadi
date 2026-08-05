import { Ban, ShieldAlert, ShieldCheck, ShieldQuestion, ShieldX } from "lucide-react"

import type { AuthEvidenceKind } from "@/lib/generated/endpoint.schema"
import { Chip } from "@/components/ui/chip"

/** The five states an endpoint's auth answer can be in (§5.2.9).
 *
 * `withheld` and `unknown` both mean "no claim", and keeping them apart is the
 * point: withheld says wadi saw a guard it could not read (so the endpoint may
 * well be protected, and the gap is wadi's), while unknown says wadi found
 * nothing that gates this endpoint at all (which may be a real hole in the
 * system). Collapsing them sends a reader to fix the wrong thing.
 *
 * `denied` is split out of `required` for the same reason: `denyAll()` admits
 * nobody, so the route is unreachable rather than protected. Rendering the two
 * identically tells an auditor a dead endpoint is live surface.
 */
export type AuthState = "required" | "denied" | "open" | "withheld" | "unknown"

export function authStateOf(
  authenticated: boolean | null | undefined,
  unreadKinds: readonly string[] | null | undefined,
  denied?: boolean | null
): AuthState {
  if (authenticated === true) return denied ? "denied" : "required"
  if (authenticated === false) return "open"
  return (unreadKinds?.length ?? 0) > 0 ? "withheld" : "unknown"
}

/** Plain-language names for the guards we can detect but not interpret. */
const UNREAD_LABELS: Record<string, string> = {
  "security-dsl": "a security rule",
  annotation: "a security annotation",
  interceptor: "a request interceptor",
  "servlet-filter": "a servlet filter",
  aspect: "an aspect",
  "in-handler": "a check inside the handler",
  "chain-bypass": "a security-chain bypass",
  gateway: "a gateway rule",
  config: "a config-defined rule",
}

export function unreadLabel(kind: AuthEvidenceKind | string): string {
  return UNREAD_LABELS[kind] ?? kind
}

/** Why a claim was withheld, in a sentence a reader can act on. */
export function withheldReason(unreadKinds: readonly string[]): string {
  const named = unreadKinds.map(unreadLabel)
  const list =
    named.length <= 1
      ? (named[0] ?? "something")
      : `${named.slice(0, -1).join(", ")} and ${named[named.length - 1]}`
  return `${list} guards this endpoint, but its effect could not be read — so no claim is made either way`
}

const PRESENTATION: Record<
  AuthState,
  { icon: typeof ShieldCheck; label: string; title: string; unknown?: boolean }
> = {
  required: {
    icon: ShieldCheck,
    label: "auth required",
    title: "Authentication required",
  },
  denied: {
    icon: Ban,
    label: "denied to all",
    title: "A rule denies every caller — this endpoint is unreachable",
  },
  open: {
    icon: ShieldAlert,
    label: "no auth (evidenced)",
    title: "No authentication — every guard in scope was read, and none gates this",
  },
  withheld: {
    icon: ShieldX,
    label: "auth withheld",
    title: "A guard was found but could not be read, so no claim is made",
    unknown: true,
  },
  unknown: {
    icon: ShieldQuestion,
    label: "auth unknown",
    title: "Analysis found nothing that gates this endpoint",
    unknown: true,
  },
}

export function AuthChip({
  state,
  compact = false,
  title,
}: {
  state: AuthState
  /** Endpoint rows are dense — drop the qualifier, keep the icon and state. */
  compact?: boolean
  title?: string
}) {
  const { icon: Icon, label, title: defaultTitle, unknown } = PRESENTATION[state]
  return (
    <Chip variant={unknown ? "unknown" : "outline"} title={title ?? defaultTitle}>
      <Icon aria-hidden />
      {compact ? label.split(" ")[0] === "no" ? "no auth" : label.split(" ")[0] : label}
    </Chip>
  )
}
