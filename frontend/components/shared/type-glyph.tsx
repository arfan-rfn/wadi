import type { ShapeKind } from "@/lib/generated/endpoint.schema"
import { cn } from "@/lib/utils"

// A field's TYPE, as a glyph you read before you read its name (§5.2.7 shapes).
//
// A 17-field request body rendered as name/type pairs is a wall of text you
// have to parse linearly. The same body with a glyph column has a shape you
// take in at once — a run of strings, three numbers, one nested object. The
// glyph is the scannable channel; the type name beside it stays for precision.

/** Scalar type names that deserve their own glyph, matched on the simple name. */
const NUMERIC = new Set([
  "int",
  "long",
  "short",
  "byte",
  "float",
  "double",
  "Integer",
  "Long",
  "Short",
  "Byte",
  "Float",
  "Double",
  "BigDecimal",
  "BigInteger",
])
const BOOLEAN = new Set(["boolean", "Boolean"])
const TEMPORAL = new Set([
  "Date",
  "Instant",
  "LocalDate",
  "LocalDateTime",
  "LocalTime",
  "OffsetDateTime",
  "ZonedDateTime",
  "Timestamp",
])

type GlyphSpec = { mark: string; tone: string; title: string }

function scalarGlyph(typeName: string): GlyphSpec {
  const simple = typeName.split(/[.<]/).pop() ?? typeName
  if (NUMERIC.has(simple))
    return {
      mark: "#",
      tone: "text-type-number",
      title: "number",
    }
  if (BOOLEAN.has(simple))
    return {
      mark: "01",
      tone: "text-type-boolean",
      title: "boolean",
    }
  if (TEMPORAL.has(simple))
    return {
      mark: "◷",
      tone: "text-type-temporal",
      title: "date / time",
    }
  return {
    mark: "Aa",
    tone: "text-type-string",
    title: "string",
  }
}

function glyphFor(kind: ShapeKind, typeName: string): GlyphSpec {
  switch (kind) {
    case "object":
      return {
        mark: "{}",
        // Shares hue 295 with `boolean` — a collision that predates the token
        // rebuild. Named distinctly so it is visible and separable later; the
        // glyph mark ({} vs 01) is what currently keeps them apart.
        tone: "text-type-object",
        title: "object",
      }
    case "array":
      return {
        mark: "[]",
        tone: "text-type-collection",
        title: "array",
      }
    case "map":
      return {
        mark: "⋮⋮",
        tone: "text-type-collection",
        title: "map",
      }
    // The honest terminals (P10) share the dashed treatment the rest of the UI
    // gives unresolved facts — they must LOOK unresolved, not like a type.
    case "unresolved":
      return {
        mark: "?",
        tone: "text-destructive",
        title: "type not in the CPG",
      }
    case "cycle":
      return { mark: "↻", tone: "text-destructive", title: "self-reference" }
    case "truncated":
      return { mark: "…", tone: "text-destructive", title: "depth cap reached" }
    // Terminal, but NOT an honest-unknown: the code determined this field is
    // always null. It must not wear the destructive dashed treatment (that
    // says "we could not determine this") and it must not fall through to a
    // scalar glyph either, which would render a known-empty field as an
    // ordinary typed one and erase the distinction entirely.
    case "always-null":
      return { mark: "∅", tone: "text-muted-foreground", title: "always null" }
    default:
      return scalarGlyph(typeName)
  }
}

const HONEST_TERMINAL: ReadonlySet<string> = new Set([
  "unresolved",
  "cycle",
  "truncated",
])

export function TypeGlyph({
  kind,
  typeName,
  className,
}: {
  kind: ShapeKind
  typeName: string
  className?: string
}) {
  const { mark, tone, title } = glyphFor(kind, typeName)
  const terminal = HONEST_TERMINAL.has(kind)
  return (
    <span
      title={title}
      aria-label={title}
      role="img"
      className={cn(
        "grid size-[19px] shrink-0 place-items-center rounded-sm font-mono text-2xs leading-none font-semibold",
        terminal ? "border border-dashed border-destructive/50" : "bg-muted",
        tone,
        className
      )}
    >
      {mark}
    </span>
  )
}
