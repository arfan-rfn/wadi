"use client"

// The one source renderer (§11 Phase 2.8): `SourceViewer` is the full-width
// Source lens (one scroller, sticky file headers, a filterable file index) and
// `SourceSnippet` is the anchor peek used by drill-ins — both share the same
// shiki pipeline and line rendering, so code looks identical everywhere.
// Source is fetched lazily on demand (§5.3); server-truncated windows page
// honestly ("load more", never silence); generated variants are flagged.
// The unit of disclosure is the METHOD (§11 M8): whole methods render,
// everything between them folds into a strip that states its own line count
// and opens on click — code is hidden, never silently (the file header counts
// what is folded, and any selection landing inside a fold opens it).
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
  ChevronsUpDown,
  CornerDownRight,
  Database,
  Globe,
  MailWarning,
  WrapText,
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
import {
  buildSourceRows,
  foldContaining,
  readWrapPreference,
  rowIndexForLine,
  writeWrapPreference,
  type SourceRow,
} from "@/lib/wadi/source-rows"
import { Skeleton } from "@/components/ui/skeleton"

const LINE_HEIGHT = 21
/** Fold strips and method headers are one line tall plus their border. */
const FOLD_HEIGHT = 22
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
  wrap = false,
}: {
  tokens: HighlightToken[] | undefined
  fallback: string
  /** Wrapped code must be allowed to shrink; unwrapped code must not. */
  wrap?: boolean
}) {
  return (
    // Unwrapped: `shrink-0`, so the element sizes to its content and the row
    // genuinely becomes wider than the column — that is what gives the code
    // body something to scroll. `flex-1` would squeeze it back to the panel
    // width and silently clip every long line instead.
    // Wrapped: the opposite is required — it must shrink to the column so the
    // text can break, and `min-w-0` is what lets a flex child do that at all.
    <code className={wrap ? "min-w-0 flex-1" : "shrink-0"}>
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
  // View preferences: remembered per user, not per URL — how you like to READ
  // code is not part of what a shared link is about.
  const [wrap, setWrap] = useState(() => readWrapPreference())
  useEffect(() => writeWrapPreference(wrap), [wrap])
  const [onlyFile, setOnlyFile] = useState<string | null>(null)

  const jumpTo = useCallback((file: string, line: number) => {
    jumpSeq.current += 1
    setJump({ file, line, at: jumpSeq.current })
  }, [])

  useEffect(() => {
    if (focus) jumpTo(focus.file, focus.line)
  }, [focus, jumpTo])

  // A filter must never swallow a selection: if the graph sends the reader to
  // a file the filter is hiding, the filter yields. Anything else reproduces
  // the dead-click class this workspace has spent its life removing.
  const targetFile = jump?.file ?? selection?.file ?? null
  useEffect(() => {
    if (targetFile && onlyFile && targetFile !== onlyFile) setOnlyFile(null)
  }, [targetFile, onlyFile])

  const visibleSections = useMemo(
    () => (onlyFile ? sections.filter((s) => s.file === onlyFile) : sections),
    [sections, onlyFile]
  )

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
        {/* The chips FILTER rather than scroll. Four files concatenated into
            one column is what made this panel feel like a document dump; being
            able to say "just this file" is the cheapest way out of it. */}
        <button
          onClick={() => setOnlyFile(null)}
          className={cn(
            "rounded-md border px-2 py-0.5 text-2xs transition-colors",
            onlyFile === null
              ? "border-primary/40 bg-primary/10 text-foreground"
              : "text-muted-foreground hover:bg-muted hover:text-foreground"
          )}
        >
          all {sections.length} file{sections.length === 1 ? "" : "s"}
        </button>
        {sections.map((section) => (
          <button
            key={section.file}
            onClick={() => {
              setOnlyFile(section.file)
              jumpTo(section.file, section.shown[0]?.[0] ?? 1)
            }}
            className={cn(
              "rounded-md border px-2 py-0.5 font-mono text-2xs transition-colors",
              onlyFile === section.file
                ? "border-primary/40 bg-primary/10 text-foreground"
                : "text-muted-foreground hover:bg-muted hover:text-foreground"
            )}
            title={section.file}
          >
            {fileBasename(section.file)}
          </button>
        ))}
        <button
          onClick={() => setWrap((v) => !v)}
          aria-pressed={wrap}
          className={cn(
            "ml-auto inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-2xs transition-colors",
            wrap
              ? "border-primary/40 bg-primary/10 text-foreground"
              : "text-muted-foreground hover:bg-muted hover:text-foreground"
          )}
          title="Wrap long lines instead of scrolling sideways"
        >
          <WrapText className="size-3" aria-hidden />
          wrap
        </button>
      </nav>
      {/* ONE scroller for every file — sticky headers live in normal flow, so
          there is no nested scrolling anywhere in the lens. */}
      <div
        ref={scrollRef}
        className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden"
      >
        {visibleSections.map((section) => (
          <SourceFileView
            key={section.file}
            section={section}
            snapshotId={snapshotId}
            serviceId={serviceId}
            active={active}
            jump={jump?.file === section.file ? jump : null}
            selection={selection?.file === section.file ? selection : null}
            wrap={wrap}
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
  wrap,
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
  wrap: boolean
  onJump: (file: string, line: number) => void
  onJumpNode?: (methodId: string) => void
  onSelectNode?: (icfgNodeId: string) => void
  scrollRef: React.RefObject<HTMLDivElement | null>
  layoutRevision: number
  onLayoutShift: () => void
}) {
  const queryClient = useQueryClient()
  const sectionRef = useRef<HTMLElement>(null)
  const headerRef = useRef<HTMLElement>(null)
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

  const [scrollMargin, setScrollMargin] = useState(0)

  // --- folding ---------------------------------------------------------------------
  const [expandedFolds, setExpandedFolds] = useState<ReadonlySet<string>>(
    () => new Set()
  )
  const rowModel = useMemo(
    () =>
      buildSourceRows(
        lines.length,
        section.shown,
        expandedFolds,
        section.methods
      ),
    [lines.length, section.shown, expandedFolds, section.methods]
  )
  const expandFold = useCallback((id: string) => {
    setExpandedFolds((prev) => {
      if (prev.has(id)) return prev
      const next = new Set(prev)
      next.add(id)
      return next
    })
  }, [])

  // Offset of this section's body within the shared scroller — the
  // virtualizer's scrollMargin. Re-measured whenever this section or any
  // sibling changes height, which now includes OPENING A FOLD: a fold is worth
  // dozens of lines, and a stale margin puts every virtualized row in the
  // sections below it at the wrong offset.
  useLayoutEffect(() => {
    const body = bodyRef.current
    const scroller = scrollRef.current
    if (!body || !scroller) return
    setScrollMargin(
      body.getBoundingClientRect().top -
        scroller.getBoundingClientRect().top +
        scroller.scrollTop
    )
  }, [layoutRevision, rowModel.rows.length, scrollRef])

  // Growing (source loaded, window appended, fold opened) shifts every later
  // section.
  useEffect(() => {
    onLayoutShift()
  }, [rowModel.rows.length, onLayoutShift])

  // A folded line is not an unreachable one: whatever the graph selects, or a
  // jump asks for, opens its fold. Same rule the canvas follows for a
  // selection inside a collapsed method (§11 Phase 2.8).
  const wantedLine = jump?.line ?? selection?.focusLine ?? null
  useEffect(() => {
    if (wantedLine === null) return
    const fold = foldContaining(rowModel.rows, wantedLine)
    if (fold) expandFold(fold.id)
  }, [wantedLine, rowModel, expandFold])

  // Wrapping makes row heights variable, which a fixed-size virtualizer cannot
  // model — and folding already cuts most files below the threshold, so the
  // two rarely meet. Correctness over cleverness: wrap turns virtualization off.
  const virtualize = !wrap && rowModel.rows.length > VIRTUALIZE_THRESHOLD
  const virtualizer = useVirtualizer({
    count: virtualize ? rowModel.rows.length : 0,
    getScrollElement: () => scrollRef.current,
    estimateSize: (index) =>
      rowModel.rows[index]?.kind === "line" ? LINE_HEIGHT : FOLD_HEIGHT,
    overscan: 30,
    scrollMargin,
    initialRect: { width: 800, height: 600 },
  })

  useEffect(() => {
    if (jump && lines.length > 0) {
      // Rows stopped being lines when folding landed: never index by line.
      const row = rowIndexForLine(rowModel, jump.line)
      if (row !== null) {
        if (virtualize) {
          virtualizer.scrollToIndex(row, { align: "center" })
        } else {
          // Optional CALL, not just optional access: jsdom implements no
          // `scrollIntoView`, and an exception here would abort the render
          // pass that opens the fold this jump is aiming at.
          bodyRef.current?.children[row]?.scrollIntoView?.({
            block: "center",
            // Never sideways: a line wider than the panel would otherwise drag
            // the whole column — tab bar, gutter and all — out of view.
            inline: "nearest",
          })
        }
      }
      setFlashLine(jump.line)
      const timer = setTimeout(() => setFlashLine(null), 1600)
      return () => clearTimeout(timer)
    }
  }, [jump, lines.length, virtualize, virtualizer, rowModel])

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

  // Which method is under the panel's top edge — the pinned label in the file
  // header. Read from the DOM rather than from scroll arithmetic: rows can be
  // virtualized, folded, or wrapped, and only the DOM knows their real heights.
  const [currentMethod, setCurrentMethod] = useState<string | null>(null)
  useEffect(() => {
    const scroller = scrollRef.current
    const body = bodyRef.current
    if (!scroller || !body) return
    let frame = 0
    const update = () => {
      frame = 0
      // Measured, not assumed: the header wraps at narrow widths, and a stale
      // constant would name the wrong method near every boundary.
      const top =
        scroller.getBoundingClientRect().top +
        (headerRef.current?.offsetHeight ?? 0)
      let seen: string | null = null
      for (const header of body.querySelectorAll<HTMLElement>(
        "[data-method-start]"
      )) {
        if (header.getBoundingClientRect().top > top) break
        seen = header.dataset.methodStart ?? null
      }
      const line = seen === null ? null : Number(seen)
      setCurrentMethod(
        section.methods.find((m) => m.startLine === line)?.signature ?? null
      )
    }
    const onScroll = () => {
      if (frame === 0) frame = requestAnimationFrame(update)
    }
    update()
    scroller.addEventListener("scroll", onScroll, { passive: true })
    return () => {
      scroller.removeEventListener("scroll", onScroll)
      if (frame !== 0) cancelAnimationFrame(frame)
    }
  }, [scrollRef, section.methods, rowModel])

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
      <header
        ref={headerRef}
        className="sticky top-0 z-10 flex items-center justify-between gap-2 border-b bg-background/95 px-3 py-1.5 backdrop-blur"
      >
        <span className="flex min-w-0 items-baseline gap-2">
          <span className="truncate font-mono text-xs">{section.file}</span>
          {currentMethod ? (
            // The enclosing method, pinned: scrolling into the middle of a file
            // must never leave the reader asking which method they are in.
            <span className="shrink-0 truncate font-mono text-2xs text-muted-foreground">
              › {shortSignature(currentMethod)}
            </span>
          ) : null}
        </span>
        <span className="shrink-0 font-mono text-2xs text-muted-foreground">
          {section.methods.length} method
          {section.methods.length === 1 ? "" : "s"} · {section.touched.length}{" "}
          executed region
          {section.touched.length === 1 ? "" : "s"}
          {totalLines ? ` · ${totalLines} lines` : ""}
          {/* Say what is NOT on screen. The panel shows whole methods, so a
              header reporting only the file's length reads as a claim to be
              showing all of it (P10). */}
          {rowModel.foldedCount > 0 ? ` · ${rowModel.foldedCount} folded` : ""}
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
            ? virtualizer.getVirtualItems().map((item) => (
                <div
                  key={item.key}
                  className="absolute left-0 w-full"
                  style={{
                    top: 0,
                    transform: `translateY(${item.start - scrollMargin}px)`,
                    height: item.size,
                  }}
                >
                  <SourceRowView
                    row={rowModel.rows[item.index]}
                    section={section}
                    lines={lines}
                    tokens={tokens}
                    callLinksByLine={callLinksByLine}
                    flashLine={flashLine}
                    selection={selection}
                    wrap={wrap}
                    onExpandFold={expandFold}
                    onJump={onJump}
                    onJumpNode={onJumpNode}
                    onSelectNode={onSelectNode}
                  />
                </div>
              ))
            : rowModel.rows.map((row) => (
                <SourceRowView
                  key={
                    row.kind === "line"
                      ? `l${row.line}`
                      : `${row.kind}${row.id}`
                  }
                  row={row}
                  section={section}
                  lines={lines}
                  tokens={tokens}
                  callLinksByLine={callLinksByLine}
                  flashLine={flashLine}
                  selection={selection}
                  wrap={wrap}
                  onExpandFold={expandFold}
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

/** One rendered row: a line, a collapsed fold, or a method header. */
function SourceRowView({
  row,
  section,
  lines,
  tokens,
  callLinksByLine,
  flashLine,
  selection,
  wrap,
  onExpandFold,
  onJump,
  onJumpNode,
  onSelectNode,
}: {
  row: SourceRow | undefined
  section: SourceFileSection
  lines: string[]
  tokens: HighlightToken[][] | null
  callLinksByLine: Map<number, CallLink[]>
  flashLine: number | null
  selection: SourceSelection | null
  wrap: boolean
  onExpandFold: (id: string) => void
  onJump: (file: string, line: number) => void
  onJumpNode?: (methodId: string) => void
  onSelectNode?: (icfgNodeId: string) => void
}) {
  if (!row) return null

  if (row.kind === "fold") {
    const count = row.endLine - row.startLine + 1
    return (
      <button
        onClick={() => onExpandFold(row.id)}
        className="flex h-[22px] w-full items-center gap-2 border-y border-dashed border-border/60 bg-muted/20 px-2 text-2xs text-muted-foreground transition-colors hover:bg-muted/50 hover:text-foreground"
        title={`Show lines ${row.startLine}–${row.endLine}`}
      >
        <ChevronsUpDown className="size-3 shrink-0" aria-hidden />
        <span className="font-mono">
          {count} line{count === 1 ? "" : "s"} · {row.startLine}–{row.endLine}
        </span>
      </button>
    )
  }

  if (row.kind === "method") {
    return (
      // NOT sticky: the code body sets `overflow-x`, which makes it its own
      // scroll container, so a sticky child pins to the body rather than to the
      // panel and ends up overlapping its own first line. The pinned copy lives
      // in the file header instead, which sits outside that container.
      <div
        data-method-start={row.startLine}
        className="flex h-[22px] items-center gap-1.5 border-t bg-muted/30 px-2"
      >
        <span className="truncate font-mono text-2xs font-medium text-foreground/80">
          {shortSignature(row.signature)}
        </span>
      </div>
    )
  }

  return (
    <SourceLine
      lineNo={row.line}
      section={section}
      lines={lines}
      tokens={tokens}
      callLinksByLine={callLinksByLine}
      flashLine={flashLine}
      selection={selection}
      wrap={wrap}
      onJump={onJump}
      onJumpNode={onJumpNode}
      onSelectNode={onSelectNode}
    />
  )
}

function SourceLine({
  lineNo,
  section,
  lines,
  tokens,
  callLinksByLine,
  flashLine,
  selection,
  wrap,
  onJump,
  onJumpNode,
  onSelectNode,
}: {
  lineNo: number
  section: SourceFileSection
  lines: string[]
  tokens: HighlightToken[][] | null
  callLinksByLine: Map<number, CallLink[]>
  flashLine: number | null
  selection: SourceSelection | null
  wrap: boolean
  onJump: (file: string, line: number) => void
  onJumpNode?: (methodId: string) => void
  onSelectNode?: (icfgNodeId: string) => void
}) {
  const index = lineNo - 1
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
        "group flex w-max min-w-full pr-2 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-ring",
        // Wrapping trades the fixed row height for readability: no line is cut
        // off at the right edge, and nothing has to be scrolled sideways.
        wrap
          ? "w-full whitespace-pre-wrap break-words"
          : "h-[21px] items-center whitespace-pre",
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
      {/* The mark strip doubles as the "this line is on the graph" tell: only
          ~7% of a file carries an ICFG node, and without a visible difference a
          click on any other line reads as broken rather than as inert. */}
      <span
        className={cn(
          "mr-2 w-[3px] shrink-0 rounded-full",
          wrap ? "h-[21px] self-start" : "h-full",
          marks ? markClass(marks) : "bg-transparent",
          selectable && "ring-1 ring-inset ring-foreground/20"
        )}
      />
      <TokenLine
        tokens={tokens?.[index] ?? undefined}
        fallback={lines[index]}
        wrap={wrap}
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
