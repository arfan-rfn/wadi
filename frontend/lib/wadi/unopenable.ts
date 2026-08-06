// Human wording for why a call has no interior to open (§5.4.2 T5).
//
// The audit that produced this vocabulary began with a slice that looked like
// it had lost files. It had not: 92.9% of the calls that dead-end are Lombok
// accessors that have no source line anywhere. The node stays on the canvas
// either way — the call really does run — so what the UI owes the reader is
// the reason, phrased as a fact about the code rather than a failure of the
// analysis (P10).
import type { CalleeUnboundReason } from "@/lib/generated/icfg.schema"

interface UnopenableCopy {
  /** Terse badge text, shown on the node itself. */
  badge: string
  /** One sentence for the inspector: what it is, and why there is nothing to open. */
  detail: string
}

const COPY: Record<CalleeUnboundReason, UnopenableCopy> = {
  "lombok-generated": {
    badge: "generated",
    detail:
      "Lombok generates this accessor at compile time. Analysis reads the original source so line numbers match your repo, which means this method has no source text to show — there is nothing hidden here.",
  },
  "inherited-external": {
    badge: "inherited",
    detail:
      "Declared by a framework supertype (for example Spring Data's CrudRepository), not by the type in your repo. Its behaviour is still recorded — a repository call is tagged as a database sink.",
  },
  "compiler-generated": {
    badge: "generated",
    detail:
      "Synthesized by the Java compiler (an enum's values()/valueOf()). It exists in bytecode only, never in source.",
  },
  "third-party": {
    badge: "external",
    detail:
      "Declared outside every analyzed source root — the JDK or a library. wadi maps your system, so third-party bodies are deliberately out of scope.",
  },
  "ambiguous-overload": {
    badge: "ambiguous",
    detail:
      "Several overloads of this method match and the receiver's type could not be pinned to one. Guessing would risk showing you the wrong body, so the map declines to choose.",
  },
  "unresolved-receiver": {
    badge: "unresolved",
    detail:
      "The receiver's type could not be resolved by the Java frontend, so the callee cannot be named at all. The call is real; its target could not be determined.",
  },
  "declared-not-bound": {
    badge: "unbound",
    detail:
      "This type declares the method, with a body, and the call still could not be connected to it. Unlike every other reason here, that is a gap in the analysis rather than a fact about your code.",
  },
  "not-declared": {
    badge: "elsewhere",
    detail:
      "The named type declares no such method — typically a static import credited to the importing class (ok() from ResponseEntity.ok). The callee is real and defined elsewhere, so this is not a hole in the map.",
  },
  "unparseable-callee": {
    badge: "unnamed",
    detail:
      "The callee's name carries no type qualifier, so there is nothing to look the method up by.",
  },
}

export function unopenableCopy(
  reason: string | null | undefined
): UnopenableCopy | null {
  if (!reason) return null
  // A reason this build does not know about is still worth surfacing: the
  // fallback states the raw code rather than silently dropping to "openable".
  return (
    COPY[reason as CalleeUnboundReason] ?? {
      badge: "no source",
      detail: `No source available to analyse (${reason}).`,
    }
  )
}
