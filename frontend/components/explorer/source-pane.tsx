"use client"

// The endpoint source map (§11 Phase 2.7 M1): every file this endpoint
// touches, whole-file on demand, executed extents highlighted, untouched code
// dimmed but never hidden, call sites jumping to their callee's section.
// Source is fetched lazily per file while the Flow tab is active (§5.3), and
// a server-truncated window pages honestly ("load more", never silence).
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { useVirtualizer } from "@tanstack/react-virtual"
import {
  ArrowUpRight,
  CornerDownRight,
  Database,
  Globe,
  MailWarning,
} from "lucide-react"
import { useTheme } from "next-themes"

import { QUERY_KEYS } from "@/config/query-keys"
import { cn } from "@/lib/utils"
import type { Icfg, SourceView } from "@/lib/wadi/api"
import { wadiApi } from "@/lib/wadi/api"
import { tokenizeLines, type HighlightToken } from "@/lib/wadi/highlight"
import { useSourceFile } from "@/lib/wadi/hooks"
import { rollupMethods, shortSignature } from "@/lib/wadi/rollup"
import {
  buildSourceMap,
  fileBasename,
  isTouched,
  type LineMark,
  type SourceFileSection,
} from "@/lib/wadi/source-map"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"

const SINK_ICON: Record<string, typeof Database> = {
  db: Database,
  "http-client": Globe,
  "http-client-suspected": Globe,
  mq: MailWarning,
}

/** Highest-signal mark class for the gutter strip, by priority. */
function markClass(marks: LineMark[]): string | null {
  if (marks.some((m) => m.sink)) return "bg-red-500/80"
  if (marks.some((m) => m.kind === "branch")) return "bg-amber-500/80"
  if (marks.some((m) => m.kind === "loop")) return "bg-sky-500/80"
  if (
    marks.some((m) =>
      ["try", "catch", "finally", "throw"].includes(m.construct ?? "")
    )
  )
    return "bg-violet-500/80"
  if (marks.some((m) => m.kind === "call" || m.kind === "return"))
    return "bg-muted-foreground/50"
  return "bg-muted-foreground/30"
}

interface JumpTarget {
  file: string
  line: number
  at: number
}

const VIRTUALIZE_THRESHOLD = 400

function SourceLine({
  index,
  section,
  lines,
  tokens,
  callLinksByLine,
  flashLine,
  onJump,
}: {
  index: number
  section: SourceFileSection
  lines: string[]
  tokens: HighlightToken[][] | null
  callLinksByLine: Map<number, SourceFileSection["callLinks"]>
  flashLine: number | null
  onJump: (file: string, line: number) => void
}) {
  const lineNo = index + 1
  const touched = isTouched(section, lineNo)
  const marks = section.marks.get(lineNo)
  const links = callLinksByLine.get(lineNo)
  const sinkMark = marks?.find((m) => m.sink)
  const SinkIcon = sinkMark ? SINK_ICON[sinkMark.sink ?? ""] : null
  return (
    <div
      className={cn(
        "flex h-[21px] items-center whitespace-pre pr-2",
        touched ? "bg-primary/[0.04]" : "opacity-50",
        flashLine === lineNo && "bg-amber-500/20"
      )}
    >
      <span className="w-12 shrink-0 select-none pr-2 text-right text-muted-foreground/60">
        {lineNo}
      </span>
      <span
        className={cn(
          "mr-2 h-full w-[3px] shrink-0 rounded-full",
          marks ? markClass(marks) : "bg-transparent"
        )}
      />
      <code className="min-w-0 flex-1 overflow-x-hidden text-ellipsis">
        {tokens?.[index]
          ? tokens[index].map((token, i) => (
              <span key={i} style={{ color: token.color }}>
                {token.content}
              </span>
            ))
          : lines[index]}
      </code>
      {SinkIcon ? (
        <SinkIcon className="ml-1 size-3 shrink-0 text-red-500/80" />
      ) : null}
      {links?.map((link) => (
        <button
          key={`${link.nodeId}-${link.targetMethodId}`}
          onClick={() => onJump(link.targetFile, link.targetLine)}
          className="ml-2 inline-flex shrink-0 items-center gap-0.5 rounded border px-1 text-[10px] text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          title={`${link.targetSignature} — ${link.targetFile}:${link.targetLine}`}
        >
          <CornerDownRight className="size-2.5" />
          {shortSignature(link.targetSignature)}
        </button>
      ))}
    </div>
  )
}

export interface SourceFocus {
  file: string
  line: number
  seq: number
}

export function SourcePane({
  icfg,
  snapshotId,
  serviceId,
  active,
  focus,
}: {
  icfg: Icfg | undefined
  snapshotId: string
  serviceId: string
  active: boolean
  /** External focus request (call tree / canvas selection, §11 Phase 2.7). */
  focus?: SourceFocus | null
}) {
  const sections = useMemo(() => (icfg ? buildSourceMap(icfg) : []), [icfg])
  const sectionRefs = useRef(new Map<string, HTMLDivElement>())
  const jumpSeq = useRef(0)
  const [jump, setJump] = useState<JumpTarget | null>(null)

  const jumpTo = useCallback((file: string, line: number) => {
    // Monotonic sequence so repeating the same jump still retriggers the
    // scroll effect (and keeps this handler pure for the compiler lint).
    jumpSeq.current += 1
    setJump({ file, line, at: jumpSeq.current })
    sectionRefs.current.get(file)?.scrollIntoView({ block: "start" })
  }, [])

  useEffect(() => {
    if (focus) jumpTo(focus.file, focus.line)
  }, [focus, jumpTo])

  if (!icfg) {
    return (
      <div className="space-y-3 p-4">
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-48 w-full" />
      </div>
    )
  }
  if (sections.length === 0) {
    return (
      <p className="p-4 text-sm text-muted-foreground">
        This endpoint&apos;s flow has no source-anchored statements — nothing to
        map.
      </p>
    )
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <nav className="flex shrink-0 flex-wrap items-center gap-1.5 border-b px-3 py-2">
        <span className="mr-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          {sections.length} file{sections.length === 1 ? "" : "s"} touched
        </span>
        {sections.map((section) => (
          <button
            key={section.file}
            onClick={() => jumpTo(section.file, section.touched[0]?.[0] ?? 1)}
            className="rounded-md border px-2 py-0.5 font-mono text-[11px] text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            title={section.file}
          >
            {fileBasename(section.file)}
          </button>
        ))}
      </nav>
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-3">
        {sections.map((section) => (
          <div
            key={section.file}
            ref={(el) => {
              if (el) sectionRefs.current.set(section.file, el)
              else sectionRefs.current.delete(section.file)
            }}
          >
            <SourceFileView
              section={section}
              snapshotId={snapshotId}
              serviceId={serviceId}
              active={active}
              jump={jump?.file === section.file ? jump : null}
              onJump={jumpTo}
            />
          </div>
        ))}
      </div>
    </div>
  )
}

function SourceFileView({
  section,
  snapshotId,
  serviceId,
  active,
  jump,
  onJump,
}: {
  section: SourceFileSection
  snapshotId: string
  serviceId: string
  active: boolean
  jump: JumpTarget | null
  onJump: (file: string, line: number) => void
}) {
  const { resolvedTheme } = useTheme()
  const queryClient = useQueryClient()
  const first = useSourceFile(active, snapshotId, serviceId, section.file)
  const [extra, setExtra] = useState<SourceView[]>([])
  const [loadingMore, setLoadingMore] = useState(false)
  const [tokens, setTokens] = useState<HighlightToken[][] | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const [flashLine, setFlashLine] = useState<number | null>(null)

  const windows = useMemo(
    () => (first.data ? [first.data, ...extra] : []),
    [first.data, extra]
  )
  const content = useMemo(
    () => windows.map((w) => w.content).join(""),
    [windows]
  )
  const lines = useMemo(() => {
    const split = content.split("\n")
    if (split.length > 0 && split[split.length - 1] === "") split.pop()
    return split
  }, [content])
  const lastWindow = windows[windows.length - 1]
  const totalLines = lastWindow?.total_lines ?? lines.length
  const hasMore = lastWindow?.truncated === true

  useEffect(() => {
    let cancelled = false
    if (content === "") {
      setTokens(null)
      return
    }
    void tokenizeLines(content, section.file, resolvedTheme === "dark").then(
      (result) => {
        if (!cancelled) setTokens(result)
      }
    )
    return () => {
      cancelled = true
    }
  }, [content, section.file, resolvedTheme])

  // Small files render every line directly (page scroll, no inner scrollbox);
  // only long files pay for virtualization.
  const virtualize = lines.length > VIRTUALIZE_THRESHOLD
  const virtualizer = useVirtualizer({
    count: virtualize ? lines.length : 0,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 21,
    overscan: 25,
    initialRect: { width: 800, height: 600 },
  })

  useEffect(() => {
    if (jump) {
      if (virtualize) {
        virtualizer.scrollToIndex(Math.max(jump.line - 1, 0), {
          align: "center",
        })
      } else {
        scrollRef.current?.children[Math.max(jump.line - 1, 0)]?.scrollIntoView(
          { block: "center" }
        )
      }
      setFlashLine(jump.line)
      const timer = setTimeout(() => setFlashLine(null), 1600)
      return () => clearTimeout(timer)
    }
  }, [jump, virtualize, virtualizer])

  const loadMore = async () => {
    if (!lastWindow) return
    setLoadingMore(true)
    try {
      const nextStart = lastWindow.end_line + 1
      const next = await queryClient.fetchQuery({
        queryKey: QUERY_KEYS.sourceFile(
          snapshotId,
          serviceId,
          section.file,
          nextStart
        ),
        queryFn: () =>
          wadiApi.sourceFile(snapshotId, serviceId, section.file, nextStart),
        staleTime: Infinity,
      })
      setExtra((prev) => [...prev, next])
    } finally {
      setLoadingMore(false)
    }
  }

  const callLinksByLine = useMemo(() => {
    const map = new Map<number, typeof section.callLinks>()
    for (const link of section.callLinks) {
      const existing = map.get(link.line) ?? []
      existing.push(link)
      map.set(link.line, existing)
    }
    return map
  }, [section.callLinks])

  return (
    <section className="rounded-lg border">
      <header className="flex items-center justify-between gap-2 border-b bg-muted/30 px-3 py-1.5">
        <span className="truncate font-mono text-xs">{section.file}</span>
        <span className="shrink-0 font-mono text-[10px] text-muted-foreground">
          {section.methods.length} method
          {section.methods.length === 1 ? "" : "s"} · {section.touched.length}{" "}
          executed region
          {section.touched.length === 1 ? "" : "s"}
          {totalLines ? ` · ${totalLines} lines` : ""}
        </span>
      </header>

      {first.data?.variant && first.data.variant !== "original" ? (
        <p className="border-b bg-amber-500/10 px-3 py-1 text-[11px] text-amber-700 dark:text-amber-400">
          Generated variant — the text as analysis saw it, not the committed
          file.
        </p>
      ) : null}

      {first.isPending && active ? (
        <div className="space-y-1.5 p-3">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-5/6" />
          <Skeleton className="h-4 w-2/3" />
        </div>
      ) : null}
      {first.isError ? (
        <p className="p-3 text-xs text-muted-foreground">
          Source unavailable: {(first.error as Error).message}
        </p>
      ) : null}

      {lines.length > 0 ? (
        <div
          ref={scrollRef}
          className="max-h-[70vh] overflow-auto font-mono text-xs leading-[21px]"
        >
          {virtualize ? (
            <div
              style={{
                height: virtualizer.getTotalSize(),
                position: "relative",
              }}
            >
              {virtualizer.getVirtualItems().map((row) => (
                <div
                  key={row.key}
                  className="absolute left-0 w-full"
                  style={{
                    top: 0,
                    transform: `translateY(${row.start}px)`,
                    height: row.size,
                  }}
                >
                  <SourceLine
                    index={row.index}
                    section={section}
                    lines={lines}
                    tokens={tokens}
                    callLinksByLine={callLinksByLine}
                    flashLine={flashLine}
                    onJump={onJump}
                  />
                </div>
              ))}
            </div>
          ) : (
            lines.map((_, index) => (
              <SourceLine
                key={index}
                index={index}
                section={section}
                lines={lines}
                tokens={tokens}
                callLinksByLine={callLinksByLine}
                flashLine={flashLine}
                onJump={onJump}
              />
            ))
          )}
        </div>
      ) : null}

      {hasMore ? (
        <div className="border-t px-3 py-1.5">
          <button
            onClick={() => void loadMore()}
            disabled={loadingMore}
            className="inline-flex items-center gap-1 text-[11px] text-muted-foreground transition-colors hover:text-foreground disabled:opacity-50"
          >
            <ArrowUpRight className="size-3" />
            {loadingMore
              ? "Loading…"
              : `Load lines ${(lastWindow?.end_line ?? 0) + 1}–${Math.min(
                  (lastWindow?.end_line ?? 0) + 2000,
                  totalLines ?? Infinity
                )} of ${totalLines}`}
          </button>
        </div>
      ) : null}
    </section>
  )
}

/** Summary chips used by the Flow tab header (M1: file + method counts). */
export function SourceSummary({ icfg }: { icfg: Icfg }) {
  const sections = useMemo(() => buildSourceMap(icfg), [icfg])
  const methods = useMemo(() => rollupMethods(icfg), [icfg])
  return (
    <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
      <Badge variant="outline" className="px-1.5 py-0 text-[10px]">
        {sections.length} files
      </Badge>
      <Badge variant="outline" className="px-1.5 py-0 text-[10px]">
        {methods.length} methods
      </Badge>
    </div>
  )
}
