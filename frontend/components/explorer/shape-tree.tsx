"use client"

// Wire-contract renderer (§5.2.7): field rows in the API-reference idiom
// (name · type chip · nesting), with the honest terminals styled as facts —
// `unresolved` and `cycle` are information, not blanks.
import type { TypeShape } from "@/lib/generated/endpoint.schema"
import { cn } from "@/lib/utils"

function shortType(typeName: string): string {
  const bare = typeName.split("<")[0]
  return bare.substring(bare.lastIndexOf(".") + 1)
}

function TerminalChip({ shape }: { shape: TypeShape }) {
  const label =
    shape.kind === "unresolved"
      ? `${shortType(shape.type_name)} — unresolved (outside the analyzed code)`
      : shape.kind === "cycle"
        ? `${shortType(shape.type_name)} — recursive reference`
        : `${shortType(shape.type_name)} — truncated at depth limit`
  return (
    <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground">
      {label}
    </span>
  )
}

export function ShapeTree({
  shape,
  depth = 0,
}: {
  shape: TypeShape
  depth?: number
}) {
  if (
    shape.kind === "unresolved" ||
    shape.kind === "cycle" ||
    shape.kind === "truncated"
  ) {
    return <TerminalChip shape={shape} />
  }
  if (shape.kind === "scalar") {
    return (
      <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px]">
        {shortType(shape.type_name)}
      </span>
    )
  }
  if (shape.kind === "array" || shape.kind === "map") {
    return (
      <span className="inline-flex flex-wrap items-center gap-1">
        <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px]">
          {shape.kind === "array" ? "[ ]" : "map"}
        </span>
        {shape.element ? (
          <ShapeTree shape={shape.element} depth={depth} />
        ) : (
          <span className="text-[11px] text-muted-foreground">
            of unknown elements
          </span>
        )}
      </span>
    )
  }
  // object
  return (
    <div className={cn("min-w-0", depth > 0 && "mt-1")}>
      <span className="font-mono text-[11px] text-muted-foreground">
        {shortType(shape.type_name)}
      </span>
      <ul
        className={cn(
          "mt-1 space-y-1 border-l pl-3",
          depth >= 3 && "border-dashed"
        )}
      >
        {(shape.fields ?? []).map((field) => (
          <li
            key={field.name}
            className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5"
          >
            <span className="font-mono text-xs">{field.name}</span>
            {field.java_name && (
              <span className="text-[10px] text-muted-foreground">
                (java: {field.java_name})
              </span>
            )}
            <ShapeTree shape={field.shape} depth={depth + 1} />
          </li>
        ))}
        {(shape.fields ?? []).length === 0 && (
          <li className="text-[11px] text-muted-foreground">no fields</li>
        )}
      </ul>
    </div>
  )
}
