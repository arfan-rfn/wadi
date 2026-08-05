"use client"

// Glyph-led wire-shape rendering (§5.2.7 shapes, §5.2.9 UI).
//
// Rows lead with a type glyph so a payload's SHAPE arrives before its names,
// nest by indentation rather than by boxes, and cut off at a threshold with an
// explicit "show N more" — a 17-field body should not decide how much of the
// panel the response gets. The honest terminals (`unresolved` / `cycle` /
// `truncated`) render as stated facts, never as blanks (P10).
import { useState } from "react"

import type { TypeShape } from "@/lib/generated/endpoint.schema"
import { cn } from "@/lib/utils"
import { TypeGlyph } from "@/components/shared/type-glyph"

/** Fields shown before the row list folds. Six is about a screenful in the
 *  peek's width without pushing the next section out of view. */
const FIELD_THRESHOLD = 6
/** Nesting depth rendered inline. Deeper than this and the peek stops being a
 *  peek — the full contract is one click away in the workspace. */
const MAX_DEPTH = 3

function shortType(typeName: string): string {
  const bare = typeName.split("<")[0] ?? typeName
  return bare.substring(bare.lastIndexOf(".") + 1)
}

const TERMINAL_NOTE: Record<string, string> = {
  unresolved: "type is not in the analyzed code — named, never fabricated",
  cycle: "self-referencing type, not expanded again",
  truncated: "depth limit reached",
}

function Row({
  name,
  shape,
  depth,
}: {
  name: string | null
  shape: TypeShape
  depth: number
}) {
  return (
    <div
      className="flex items-center gap-2 py-[3px]"
      style={{ paddingLeft: depth * 14 }}
    >
      <TypeGlyph kind={shape.kind} typeName={shape.type_name} />
      {name ? (
        <span className="min-w-0 truncate font-mono text-[11.5px]">{name}</span>
      ) : null}
      <span className="ml-auto shrink-0 pl-2 font-mono text-2xs text-muted-foreground/75">
        {shortType(shape.type_name)}
      </span>
    </div>
  )
}

export function SchemaTree({
  shape,
  name = null,
  depth = 0,
}: {
  shape: TypeShape
  name?: string | null
  depth?: number
}) {
  const [expanded, setExpanded] = useState(false)
  const note = TERMINAL_NOTE[shape.kind]

  if (note) {
    return (
      <>
        <Row name={name} shape={shape} depth={depth} />
        <p
          className="text-2xs text-muted-foreground"
          style={{ paddingLeft: depth * 14 + 25 }}
        >
          {note}
        </p>
      </>
    )
  }

  // array / map: the container is one row, its element shape continues below.
  if (shape.kind === "array" || shape.kind === "map") {
    return (
      <>
        <Row name={name} shape={shape} depth={depth} />
        {shape.element ? (
          <SchemaTree shape={shape.element} depth={depth + 1} />
        ) : (
          <p
            className="text-2xs text-muted-foreground"
            style={{ paddingLeft: depth * 14 + 25 }}
          >
            element type unknown
          </p>
        )}
      </>
    )
  }

  if (shape.kind !== "object")
    return <Row name={name} shape={shape} depth={depth} />

  const fields = shape.fields ?? []
  if (depth >= MAX_DEPTH && fields.length > 0) {
    return (
      <>
        <Row name={name} shape={shape} depth={depth} />
        <p
          className="text-2xs text-muted-foreground"
          style={{ paddingLeft: depth * 14 + 25 }}
        >
          {fields.length} more field{fields.length === 1 ? "" : "s"} — open the
          full flow to walk them
        </p>
      </>
    )
  }

  const visible = expanded ? fields : fields.slice(0, FIELD_THRESHOLD)
  const hidden = fields.length - visible.length
  return (
    <>
      <Row name={name} shape={shape} depth={depth} />
      {visible.map((field) => (
        <SchemaTree
          key={field.name}
          name={field.name}
          shape={field.shape}
          depth={depth + 1}
        />
      ))}
      {hidden > 0 ? (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          style={{ marginLeft: (depth + 1) * 14 }}
          className={cn(
            "mt-1.5 cursor-pointer rounded-full border px-2.5 py-0.5 text-2xs text-muted-foreground transition-colors",
            "hover:border-muted-foreground/60 hover:text-foreground",
            "focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          )}
        >
          Show {hidden} more field{hidden === 1 ? "" : "s"}
        </button>
      ) : null}
    </>
  )
}
