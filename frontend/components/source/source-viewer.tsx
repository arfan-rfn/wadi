"use client"

// The one source renderer (§11 Phase 2.8): `SourceViewer` is the full-width
// Source lens (every touched file, one scroller, sticky file headers) and
// `SourceSnippet` is the anchor peek used by drill-ins — both share the same
// shiki pipeline and line rendering, so code looks identical everywhere.
// Source is fetched lazily on demand (§5.3); server-truncated windows page
// honestly ("load more", never silence); untouched code is dimmed, never
// hidden; generated variants are flagged.
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react"
import { useQueryClient } from "@tanstack/react-query"
import { useVirtualizer } from "@tanstack/react-virtual"
import {
  ArrowUpRight,
  ChevronDown,
  ChevronRight,
  CornerDownRight,
  Database,
  Globe,
  MailWarning,
} from "lucide-react"
import { useTheme } from "next-themes"

import { QUERY_KEYS } from "@/config/query-keys"
import type { SourceAnchor } from "@/lib/generated/icfg.schema"
import { cn } from "@/lib/utils"
import type { Icfg, SourceView } from "@/lib/wadi/api"
import { wadiApi } from "@/lib/wadi/api"
import { tokenizeLines, type HighlightToken } from "@/lib/wadi/highlight"
import { useSource, useSourceFile } from "@/lib/wadi/hooks"
import { shortSignature } from "@/lib/wadi/rollup"
import {
  buildSourceMap,
  fileBasename,
  isTouched,
  type CallLink,
  type LineMark,
  type SourceFileSection,
  type SourceSelection,
} from "@/lib/wadi/source-map"
import { Skeleton } from "@/components/ui/skeleton"

const LINE_HEIGHT = 21
// Small files render every line in flow (cheap DOM, sticky headers for free);
// only long files pay for virtualization.
const VIRTUALIZE_THRESHOLD = 400

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

/** Shared shiki tokenization keyed on content + theme; null = plain text. */
function useLineTokens(content: string, file: string) {
  const { resolvedTheme } = useTheme()
  const [tokens, setTokens] = useState<HighlightToken[][] | null>(null)
  useEffect(() => {
    let cancelled = false
    if (content === "") {
      setTokens(null)
      return
    }
    void tokenizeLines(content, file, resolvedTheme === "dark").then(
      (result) => {
        if (!cancelled) setTokens(result)
      }
    )
    return () => {
      cancelled = true
    }
  }, [content, file, resolvedTheme])
  return tokens
}

function TokenLine({
  tokens,
  fallback,
}: {
  tokens: HighlightToken[] | undefined
  fallback: string
}) {
  return (
    // `shrink-0`, so the element sizes to its content and the row genuinely
    // becomes wider than the column — that is what gives the code body
    // something to scroll. `flex-1` would squeeze it back to the panel width
    // and silently clip every long line instead.
    <code className="shrink-0">
      {tokens
        ? tokens.map((token, i) => (
            <span key={i} style={{ color: token.color }}>
              {token.content}
            </span>
          ))
        : fallback}
    </code>
  )
}

// --- snippet mode (drill-ins: auth evidence, call sites, anomaly samples) ---

export function SourceSnippet({
  snapshotId,
  serviceId,
  anchor,
  context = 3,
}: {
  snapshotId: string
  serviceId: string
  anchor: SourceAnchor
  context?: number
}) {
  const [open, setOpen] = useState(false)
  const startLine = Math.max(1, anchor.start_line - context)
  const endLine = anchor.end_line + context
  const source = useSource(
    open,
    snapshotId,
    serviceId,
    anchor.file,
    startLine,
    endLine
  )
  const tokens = useLineTokens(source.data?.content ?? "", anchor.file)

  return (
    <div className="min-w-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex max-w-full items-center gap-1 text-left font-mono text-2xs break-all text-muted-foreground hover:text-foreground"
        aria-expanded={open}
      >
        {open ? (
          <ChevronDown className="size-3" aria-hidden />
        ) : (
          <ChevronRight className="size-3" aria-hidden />
        )}
        {anchor.file}:{anchor.start_line}
      </button>
      {open && (
        <div className="mt-1.5 overflow-x-auto rounded-md border bg-muted/40">
          {source.isLoading && (
            <div className="space-y-1 p-2">
              <Skeleton className="h-3 w-3/4" />
              <Skeleton className="h-3 w-2/3" />
            </div>
          )}
          {source.isError && (
            <p className="p-2 text-2xs text-muted-foreground">
              Source unavailable: {(source.error as Error).message}
            </p>
          )}
          {source.data && (
            <>
              {source.data.variant !== "original" && (
                <div className="border-b px-2 py-1 text-2xs text-muted-foreground">
                  {source.data.variant} variant — the text analysis actually saw
                  (anchors align with this, not the raw file)
                </div>
              )}
              <pre className="p-0 text-2xs leading-5">
                {source.data.content.split("\n").map((line, index) => {
                  const lineNo = source.data.start_line + index
                  const inAnchor =
                    lineNo >= anchor.start_line && lineNo <= anchor.end_line
                  return (
                    <div
                      key={lineNo}
                      className={cn(
                        "flex gap-3 px-2",
                        inAnchor && "bg-amber-500/10"
                      )}
                    >
                      <span className="w-8 shrink-0 select-none text-right text-muted-foreground/60">
                        {lineNo}
                      </span>
                      <TokenLine
                        tokens={tokens?.[index]}
                        fallback={line || " "}
                      />
                    </div>
                  )
                })}
              </pre>
            </>
          )}
        </div>
      )}
    </div>
  )
}

// --- full mode (the Source lens) --------------------------------------------

export interface SourceFocus {
  file: string
  line: number
  seq: number
}

interface JumpTarget {
  file: string
  line: number
  at: number
}

export function SourceViewer({
  icfg,
  snapshotId,
  serviceId,
  active,
  focus,
  selection,
  onJumpNode,
  onSelectNode,
}: {
  icfg: Icfg | undefined
  snapshotId: string
  serviceId: string
  active: boolean
  /** External focus request (file index / inspector "open in source"). */
  focus?: SourceFocus | null
  /** The region the current graph selection maps onto — highlighted for as
   * long as it stays selected, and scrolled to when it changes. */
  selection?: SourceSelection | null
  /** Optional: notify when a call link is followed (sync selection). */
  onJumpNode?: (methodId: string) => void
  /** Clicking a line selects the ICFG node it carries — the reverse of
   * `selection`, so the mapping runs both ways. */
  onSelectNode?: (icfgNodeId: string) => void
}) {
  const sections = useMemo(() => (icfg ? buildSourceMap(icfg) : []), [icfg])
  const scrollRef = useRef<HTMLDivElement>(null)
  // Bumped whenever any section's rendered height changes, so every section
  // re-measures its offset within the one shared scroller.
  const [layoutRevision, setLayoutRevision] = useState(0)
  const onLayoutShift = useCallback(() => setLayoutRevision((r) => r + 1), [])
  const jumpSeq = useRef(0)
  const [jump, setJump] = useState<JumpTarget | null>(null)

  const jumpTo = useCallback((file: string, line: number) => {
    jumpSeq.current += 1
    setJump({ file, line, at: jumpSeq.current })
  }, [])

  useEffect(() => {
    if (focus) jumpTo(focus.file, focus.line)
  }, [focus, jumpTo])

  // A new selection scrolls its code into view. Keyed on the region itself,
  // so re-selecting the same node does not yank the scroll position back.
  const selectionKey = selection
    ? `${selection.file}:${selection.startLine}-${selection.endLine}`
    : null
  useEffect(() => {
    if (selection) jumpTo(selection.file, selection.focusLine)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectionKey, jumpTo])

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
    // `min-w-0`: without it a flex column is sized by its widest child, so a
    // long line of code would stretch the whole panel past its slot and take
    // the tab bar and file index off-screen with it.
    <div className="flex h-full min-h-0 min-w-0 flex-col">
      <nav className="flex shrink-0 flex-wrap items-center gap-1.5 border-b px-3 py-2">
        <span className="mr-1 text-2xs font-semibold uppercase tracking-wider text-muted-foreground">
          {sections.length} file{sections.length === 1 ? "" : "s"} touched
        </span>
        {sections.map((section) => (
          <button
            key={section.file}
            onClick={() => jumpTo(section.file, section.touched[0]?.[0] ?? 1)}
            className="rounded-md border px-2 py-0.5 font-mono text-2xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            title={section.file}
          >
            {fileBasename(section.file)}
          </button>
        ))}
      </nav>
      {/* ONE scroller for every file — sticky headers live in normal flow, so
          there is no nested scrolling anywhere in the lens. */}
      <div
        ref={scrollRef}
        className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden"
      >
        {sections.map((section) => (
          <SourceFileView
            key={section.file}
            section={section}
            snapshotId={snapshotId}
            serviceId={serviceId}
            active={active}
            jump={jump?.file === section.file ? jump : null}
            selection={selection?.file === section.file ? selection : null}
            onJump={jumpTo}
            onJumpNode={onJumpNode}
            onSelectNode={onSelectNode}
            scrollRef={scrollRef}
            layoutRevision={layoutRevision}
            onLayoutShift={onLayoutShift}
          />
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
  selection,
  onJump,
  onJumpNode,
  onSelectNode,
  scrollRef,
  layoutRevision,
  onLayoutShift,
}: {
  section: SourceFileSection
  snapshotId: string
  serviceId: string
  active: boolean
  jump: JumpTarget | null
  selection: SourceSelection | null
  onJump: (file: string, line: number) => void
  onJumpNode?: (methodId: string) => void
  onSelectNode?: (icfgNodeId: string) => void
  scrollRef: React.RefObject<HTMLDivElement | null>
  layoutRevision: number
  onLayoutShift: () => void
}) {
  const queryClient = useQueryClient()
  const sectionRef = useRef<HTMLElement>(null)
  // Every touched file used to fetch AND shiki-tokenize on mount, so opening a
  // 20-file endpoint paid 20 whole-file requests and 20 synchronous
  // tokenizations before the reader looked at one of them — against §5.3,
  // which says source is fetched on demand. Sticky once seen: scrolling back
  // must not re-fetch.
  const [seen, setSeen] = useState(false)
  useEffect(() => {
    if (seen || !active) return
    const node = sectionRef.current
    if (!node) return
    // No IntersectionObserver (jsdom, very old browsers): load eagerly. The
    // laziness is an optimisation; never showing the code is not an option.
    if (typeof IntersectionObserver === "undefined") {
      setSeen(true)
      return
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) setSeen(true)
      },
      // A screen of lead time, so the code is there before it is scrolled to.
      { root: scrollRef.current ?? null, rootMargin: "600px 0px" }
    )
    observer.observe(node)
    return () => observer.disconnect()
  }, [seen, active, scrollRef])
  // A jump or a selection targets THIS file, so it is wanted whether or not it
  // has been scrolled near — that is the click that asked for it.
  const wanted = active && (seen || jump !== null || selection !== null)
  const first = useSourceFile(wanted, snapshotId, serviceId, section.file)
  const [extra, setExtra] = useState<SourceView[]>([])
  const [loadingMore, setLoadingMore] = useState(false)
  const bodyRef = useRef<HTMLDivElement>(null)
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
  // The server's own window size, read back off the window it sent.
  const windowSize = lastWindow
    ? lastWindow.end_line - lastWindow.start_line + 1
    : 0
  const tokens = useLineTokens(content, section.file)

  // Offset of this section's body within the shared scroller — the
  // virtualizer's scrollMargin. Re-measured whenever any sibling grows.
  const [scrollMargin, setScrollMargin] = useState(0)
  useLayoutEffect(() => {
    const body = bodyRef.current
    const scroller = scrollRef.current
    if (!body || !scroller) return
    setScrollMargin(
      body.getBoundingClientRect().top -
        scroller.getBoundingClientRect().top +
        scroller.scrollTop
    )
  }, [layoutRevision, lines.length, scrollRef])

  // Growing (source loaded, window appended) shifts every later section.
  useEffect(() => {
    onLayoutShift()
  }, [lines.length, onLayoutShift])

  const virtualize = lines.length > VIRTUALIZE_THRESHOLD
  const virtualizer = useVirtualizer({
    count: virtualize ? lines.length : 0,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => LINE_HEIGHT,
    overscan: 30,
    scrollMargin,
    initialRect: { width: 800, height: 600 },
  })

  useEffect(() => {
    if (jump && lines.length > 0) {
      if (virtualize) {
        virtualizer.scrollToIndex(Math.max(jump.line - 1, 0), {
          align: "center",
        })
      } else {
        bodyRef.current?.children[Math.max(jump.line - 1, 0)]?.scrollIntoView({
          block: "center",
          // Never sideways: a line wider than the panel would otherwise drag
          // the whole column — tab bar, gutter and all — out of view.
          inline: "nearest",
        })
      }
      setFlashLine(jump.line)
      const timer = setTimeout(() => setFlashLine(null), 1600)
      return () => clearTimeout(timer)
    }
  }, [jump, lines.length, virtualize, virtualizer])

  const [loadMoreError, setLoadMoreError] = useState<Error | null>(null)
  const loadMore = async () => {
    if (!lastWindow) return
    setLoadingMore(true)
    setLoadMoreError(null)
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
    } catch (cause) {
      // Swallowed, this just resets the spinner and shows nothing — and the
      // reader concludes the file ends there. Every other fetch in this file
      // reports its failure; so does this one.
      setLoadMoreError(cause as Error)
    } finally {
      setLoadingMore(false)
    }
  }

  const callLinksByLine = useMemo(() => {
    const map = new Map<number, CallLink[]>()
    for (const link of section.callLinks) {
      const existing = map.get(link.line) ?? []
      existing.push(link)
      map.set(link.line, existing)
    }
    return map
  }, [section.callLinks])

  return (
    <section ref={sectionRef} className="min-w-0 border-b last:border-b-0">
      {/* Sticky within the ONE scroller — the current file stays named while
          its code scrolls (context is never lost). */}
      <header className="sticky top-0 z-10 flex items-center justify-between gap-2 border-b bg-background/95 px-3 py-1.5 backdrop-blur">
        <span className="truncate font-mono text-xs">{section.file}</span>
        <span className="shrink-0 font-mono text-2xs text-muted-foreground">
          {section.methods.length} method
          {section.methods.length === 1 ? "" : "s"} · {section.touched.length}{" "}
          executed region
          {section.touched.length === 1 ? "" : "s"}
          {totalLines ? ` · ${totalLines} lines` : ""}
        </span>
      </header>

      {first.data?.variant && first.data.variant !== "original" ? (
        <p className="border-b bg-amber-500/10 px-3 py-1 text-2xs text-amber-700 dark:text-amber-400">
          Generated variant — the text as analysis saw it, not the committed
          file.
        </p>
      ) : null}

      {/* Reserves height for a file not yet fetched, so the sections below it
          do not all pile into the viewport at once and defeat the laziness. */}
      {(first.isPending && wanted) || (active && !wanted) ? (
        <div className="min-h-60 space-y-1.5 p-3">
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
          ref={bodyRef}
          className={cn(
            // Long lines scroll here, inside the code column — code is wide,
            // and truncating it with an ellipsis is what made this panel feel
            // like a preview instead of a source view.
            "overflow-x-auto font-mono text-xs leading-[21px]",
            virtualize && "relative"
          )}
          style={
            virtualize ? { height: virtualizer.getTotalSize() } : undefined
          }
        >
          {virtualize
            ? virtualizer.getVirtualItems().map((row) => (
                <div
                  key={row.key}
                  className="absolute left-0 w-full"
                  style={{
                    top: 0,
                    transform: `translateY(${row.start - scrollMargin}px)`,
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
                    selection={selection}
                    onJump={onJump}
                    onJumpNode={onJumpNode}
                    onSelectNode={onSelectNode}
                  />
                </div>
              ))
            : lines.map((_, index) => (
                <SourceLine
                  key={index}
                  index={index}
                  section={section}
                  lines={lines}
                  tokens={tokens}
                  callLinksByLine={callLinksByLine}
                  flashLine={flashLine}
                  selection={selection}
                  onJump={onJump}
                  onJumpNode={onJumpNode}
                  onSelectNode={onSelectNode}
                />
              ))}
        </div>
      ) : null}

      {hasMore ? (
        <div className="border-t px-3 py-1.5">
          <button
            onClick={() => void loadMore()}
            disabled={loadingMore}
            className="inline-flex items-center gap-1 text-2xs text-muted-foreground transition-colors hover:text-foreground disabled:opacity-50"
          >
            <ArrowUpRight className="size-3" />
            {loadingMore
              ? "Loading…"
              : // Window size comes from the window the server actually sent,
                // not a client-side copy of its cap — a copy would make this
                // label lie the moment the cap moved.
                `Load lines ${(lastWindow?.end_line ?? 0) + 1}–${Math.min(
                  (lastWindow?.end_line ?? 0) + windowSize,
                  totalLines ?? Infinity
                )} of ${totalLines}`}
          </button>
          {loadMoreError ? (
            <p className="text-2xs text-destructive">
              Could not load more — {loadMoreError.message}
            </p>
          ) : null}
        </div>
      ) : null}
    </section>
  )
}

function SourceLine({
  index,
  section,
  lines,
  tokens,
  callLinksByLine,
  flashLine,
  selection,
  onJump,
  onJumpNode,
  onSelectNode,
}: {
  index: number
  section: SourceFileSection
  lines: string[]
  tokens: HighlightToken[][] | null
  callLinksByLine: Map<number, CallLink[]>
  flashLine: number | null
  selection: SourceSelection | null
  onJump: (file: string, line: number) => void
  onJumpNode?: (methodId: string) => void
  onSelectNode?: (icfgNodeId: string) => void
}) {
  const lineNo = index + 1
  const touched = isTouched(section, lineNo)
  const marks = section.marks.get(lineNo)
  const links = callLinksByLine.get(lineNo)
  const sinkMark = marks?.find((m) => m.sink)
  const SinkIcon = sinkMark ? SINK_ICON[sinkMark.sink ?? ""] : null
  // The selected region stays lit for as long as it stays selected — a
  // highlight that fades after a second leaves the reader with no answer to
  // "which code am I looking at". The anchor line reads stronger than the
  // rest of the region so a whole-method selection still says where it starts.
  const inSelection =
    selection !== null &&
    lineNo >= selection.startLine &&
    lineNo <= selection.endLine
  const isAnchor = inSelection && selection.focusLine === lineNo
  const selectable = onSelectNode != null && marks != null && marks.length > 0
  return (
    // Clicking a line selects its node — the reverse half of the 1:1 mapping.
    // The graph→source direction is keyboard-reachable through the canvas
    // keymap, so this direction needs a keyboard path too, and the selected
    // region needs to be announced rather than conveyed only by a tint.
    <div
      role={selectable ? "button" : undefined}
      tabIndex={selectable ? 0 : undefined}
      aria-pressed={selectable ? inSelection : undefined}
      onClick={selectable ? () => onSelectNode(marks[0].nodeId) : undefined}
      onKeyDown={
        selectable
          ? (event) => {
              if (event.key !== "Enter" && event.key !== " ") return
              event.preventDefault()
              onSelectNode(marks[0].nodeId)
            }
          : undefined
      }
      className={cn(
        "group flex h-[21px] w-max min-w-full items-center whitespace-pre pr-2 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-ring",
        touched ? "bg-primary/[0.04]" : "opacity-50",
        inSelection && "bg-primary/10",
        isAnchor && "bg-primary/20",
        flashLine === lineNo && !inSelection && "bg-amber-500/20",
        selectable && "cursor-pointer hover:bg-muted/60"
      )}
    >
      {/* Selection accent: a solid rule down the left edge of the region, so
          a multi-line method body reads as one block rather than as a wash. */}
      <span
        className={cn(
          "sticky left-0 z-[1] h-full w-[2px] shrink-0",
          inSelection ? "bg-primary" : "bg-transparent"
        )}
      />
      <span
        className={cn(
          // Pinned: scrolling a long line sideways must not cost you the
          // line numbers, which are how the gutter marks stay readable.
          "sticky left-[2px] z-[1] w-11 shrink-0 select-none bg-background pr-2 text-right",
          inSelection
            ? "text-primary/80"
            : "text-muted-foreground/60 group-hover:text-muted-foreground"
        )}
      >
        {lineNo}
      </span>
      <span
        className={cn(
          "mr-2 h-full w-[3px] shrink-0 rounded-full",
          marks ? markClass(marks) : "bg-transparent"
        )}
      />
      <TokenLine
        tokens={tokens?.[index] ?? undefined}
        fallback={lines[index]}
      />
      {SinkIcon ? (
        <SinkIcon className="ml-1 size-3 shrink-0 text-red-500/80" />
      ) : null}
      {links?.map((link) => (
        <button
          key={`${link.nodeId}-${link.targetMethodId}`}
          onClick={(event) => {
            // The row itself selects this line's node; the link jumps to the
            // callee. Both firing would select one thing and scroll to another.
            event.stopPropagation()
            onJump(link.targetFile, link.targetLine)
            onJumpNode?.(link.targetMethodId)
          }}
          className="ml-2 inline-flex shrink-0 items-center gap-0.5 rounded border px-1 text-2xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          title={`${link.targetSignature} — ${link.targetFile}:${link.targetLine}`}
        >
          <CornerDownRight className="size-2.5" />
          {shortSignature(link.targetSignature)}
        </button>
      ))}
    </div>
  )
}
