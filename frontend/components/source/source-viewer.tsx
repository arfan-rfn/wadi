"use client"

// The one source renderer (§11 Phase 2.8): `SourceViewer` is the full-width
// Source lens (one scroller, sticky file headers, a filterable file index) and
// `SourceSnippet` is the anchor peek used by drill-ins — both share the same
// shiki pipeline and line rendering, so code looks identical everywhere.
// A flow touches several files, and they used to be concatenated into one
// unbroken column of rules and gutters where no boundary said "a new file
// starts here". Each file is now a CARD — its own edges, its own header, its
// own collapsed state — numbered by the order the flow first reaches it. The
// handler's file opens by itself; the rest open on click, or on their own when
// a selection or a jump lands inside them (a closed file is never a dead end).
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
  ChevronsDownUp,
  ChevronsUpDown,
  CornerDownRight,
  Database,
  FileCode2,
  Globe,
  MailWarning,
  WrapText,
} from "lucide-react"
import { useTheme } from "next-themes"

import { QUERY_KEYS } from "@/config/query-keys"
import type { SourceAnchor } from "@/lib/generated/icfg.schema"
import { cn } from "@/lib/utils"
import { ScrollArea } from "@/components/ui/scroll-area"
import type { Icfg, SourceView } from "@/lib/wadi/api"
import { wadiApi } from "@/lib/wadi/api"
import { tokenizeLines, type HighlightToken } from "@/lib/wadi/highlight"
import { useSource, useSourceFile } from "@/lib/wadi/hooks"
import { shortSignature } from "@/lib/wadi/rollup"
import {
  buildSourceMap,
  fileBasename,
  fileDirname,
  isTouched,
  shortDirectory,
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

/**
 * Which edges of a horizontal scroller have content past them. The tab strip
 * hides its native scrollbar (chrome under chrome — it read as a second rule
 * competing with the tabs' own bottom edge), so the fact that there is more to
 * see has to be carried by the strip itself, the way an editor does it.
 */
function useOverflowEdges<T extends HTMLElement>(): [
  React.RefObject<T | null>,
  boolean,
  boolean,
] {
  const ref = useRef<T>(null)
  const [edges, setEdges] = useState({ start: false, end: false })
  useEffect(() => {
    const node = ref.current
    if (!node) return
    const update = () => {
      const max = node.scrollWidth - node.clientWidth
      setEdges({ start: node.scrollLeft > 1, end: node.scrollLeft < max - 1 })
    }
    update()
    node.addEventListener("scroll", update, { passive: true })
    // Tabs appear and the panel resizes; neither fires `scroll`.
    const observer =
      typeof ResizeObserver === "undefined" ? null : new ResizeObserver(update)
    observer?.observe(node)
    for (const child of node.children) observer?.observe(child)
    return () => {
      node.removeEventListener("scroll", update)
      observer?.disconnect()
    }
  }, [])
  // A tuple, not an object: bundling the ref with plain booleans reads to the
  // linter as reaching into a ref during render every time the flags are used.
  return [ref, edges.start, edges.end]
}

// Written out rather than composed: Tailwind reads class names out of the
// SOURCE TEXT, so a template-built arbitrary value compiles to nothing.
const FADE_BOTH =
  "[mask-image:linear-gradient(to_right,transparent,black_1.5rem,black_calc(100%_-_1.5rem),transparent)]"
const FADE_START =
  "[mask-image:linear-gradient(to_right,transparent,black_1.5rem)]"
const FADE_END =
  "[mask-image:linear-gradient(to_right,black_calc(100%_-_1.5rem),transparent)]"

function fadeMask(start: boolean, end: boolean): string | undefined {
  if (start && end) return FADE_BOTH
  if (start) return FADE_START
  if (end) return FADE_END
  return undefined
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
        <div className="mt-1.5 overflow-x-auto rounded-md border bg-muted/40 [scrollbar-color:var(--color-muted-foreground)_transparent] [scrollbar-width:thin]">
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
  const [tabsRef, tabsAtStart, tabsAtEnd] = useOverflowEdges<HTMLDivElement>()

  // Which file cards are open. Closed is a real state, not a lazy one: a
  // closed card fetches nothing and renders no code, so a ten-file endpoint
  // opens as ten readable headers instead of ten screens of concatenated text.
  const [openFiles, setOpenFiles] = useState<ReadonlySet<string>>(
    () => new Set()
  )
  const openFile = useCallback((file: string) => {
    setOpenFiles((prev) =>
      prev.has(file) ? prev : new Set(prev).add(file)
    )
  }, [])
  const toggleFile = useCallback((file: string) => {
    setOpenFiles((prev) => {
      const next = new Set(prev)
      if (!next.delete(file)) next.add(file)
      return next
    })
  }, [])

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
  // …and neither must a closed card. Same rule the folds follow: whatever the
  // graph selects is opened, never merely pointed at.
  useEffect(() => {
    if (targetFile) openFile(targetFile)
  }, [targetFile, openFile])

  // The handler's file — flow order 0 — is what the reader came for, so it is
  // open on arrival. Keyed on the file itself: re-running the effect for a new
  // endpoint must not re-open a card this reader has since closed.
  const entryFile = sections[0]?.file
  useEffect(() => {
    if (entryFile) openFile(entryFile)
  }, [entryFile, openFile])

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

  const allOpen = sections.every((section) => openFiles.has(section.file))

  return (
    // `min-w-0`: without it a flex column is sized by its widest child, so a
    // long line of code would stretch the whole panel past its slot and take
    // the tab bar and file index off-screen with it.
    <div className="flex h-full min-h-0 min-w-0 flex-col">
      {/* Editor-style file tabs: the shape every IDE uses, so the affordance
          needs no learning. They FILTER rather than scroll — four files
          concatenated into one column is what made this panel read as a
          document dump, and "just this file" is the cheapest way out. The
          active tab is joined to the content below by a flush bottom edge,
          which is what makes a tab read as a tab rather than a chip. */}
      <div className="flex shrink-0 items-end gap-2 border-b bg-muted/30 pr-1.5 pl-1.5">
        <div
          ref={tabsRef}
          role="tablist"
          aria-label="Source files"
          className={cn(
            "flex min-w-0 flex-1 items-end gap-px overflow-x-auto pt-1.5",
            // The strip's own scrollbar was chrome under chrome — a second
            // horizontal rule right beneath the tabs' bottom edge, for a row
            // that scrolls fine by wheel and drag. Editors hide it and let the
            // fading edge say "there is more"; so does this.
            "[scrollbar-width:none] [&::-webkit-scrollbar]:hidden",
            fadeMask(tabsAtStart, tabsAtEnd)
          )}
        >
          <button
            role="tab"
            type="button"
            aria-selected={onlyFile === null}
            onClick={() => setOnlyFile(null)}
            className={cn(
              "-mb-px shrink-0 cursor-pointer rounded-t-md border border-b-0 px-2.5 py-1 text-2xs transition-colors",
              "focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
              onlyFile === null
                ? "border-border bg-background text-foreground"
                : "border-transparent text-muted-foreground hover:bg-muted hover:text-foreground"
            )}
          >
            All {sections.length}
          </button>
          {sections.map((section) => (
            <button
              key={section.file}
              role="tab"
              type="button"
              aria-selected={onlyFile === section.file}
              onClick={() => {
                setOnlyFile(section.file)
                openFile(section.file)
                jumpTo(section.file, section.shown[0]?.[0] ?? 1)
              }}
              className={cn(
                "-mb-px flex shrink-0 cursor-pointer items-center gap-1.5 rounded-t-md border border-b-0 px-2.5 py-1 font-mono text-2xs transition-colors",
                "focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
                onlyFile === section.file
                  ? "border-border bg-background text-foreground"
                  : "border-transparent text-muted-foreground hover:bg-muted hover:text-foreground"
              )}
              title={section.file}
            >
              <FileCode2 aria-hidden className="size-3 shrink-0 opacity-70" />
              {fileBasename(section.file)}
            </button>
          ))}
        </div>
        {/* Outside the scroller: view controls that scroll away with the tabs
            are controls you cannot find. */}
        <div className="flex shrink-0 items-center gap-1 pb-1">
          {onlyFile === null && sections.length > 1 ? (
            <button
              type="button"
              onClick={() =>
                setOpenFiles(
                  allOpen ? new Set() : new Set(sections.map((s) => s.file))
                )
              }
              className={cn(
                "inline-flex cursor-pointer items-center gap-1 rounded-md border px-2 py-0.5 text-2xs text-muted-foreground transition-colors",
                "hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
              )}
              title={
                allOpen
                  ? "Collapse every file to its header"
                  : "Open every file in the flow"
              }
            >
              {allOpen ? (
                <ChevronsDownUp className="size-3" aria-hidden />
              ) : (
                <ChevronsUpDown className="size-3" aria-hidden />
              )}
              {allOpen ? "collapse" : "expand"}
            </button>
          ) : null}
          <button
            type="button"
            onClick={() => setWrap((v) => !v)}
            aria-pressed={wrap}
            className={cn(
              "inline-flex cursor-pointer items-center gap-1 rounded-md border px-2 py-0.5 text-2xs transition-colors",
              "focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
              wrap
                ? "border-primary/40 bg-primary/10 text-foreground"
                : "text-muted-foreground hover:bg-muted hover:text-foreground"
            )}
            title="Wrap long lines instead of scrolling sideways"
          >
            <WrapText className="size-3" aria-hidden />
            wrap
          </button>
        </div>
      </div>
      {/* ONE scroller for every file — sticky headers live in normal flow, so
          there is no nested scrolling anywhere in the lens. `viewportRef` hands
          the real scrolling element to the IntersectionObserver that lazy-loads
          each file: Radix nests it below Root, so a ref on the Root would watch
          the wrong box and every section would report itself visible. */}
      <ScrollArea
        viewportRef={scrollRef}
        // The muted ground is what makes each file card read as a raised
        // object rather than as another band in a continuous column.
        className="min-h-0 flex-1 bg-muted/25"
        viewportClassName="[&>div]:!block"
      >
        {visibleSections.map((section) => (
          <SourceFileView
            key={section.file}
            section={section}
            fileCount={sections.length}
            expanded={openFiles.has(section.file)}
            onToggleExpanded={() => toggleFile(section.file)}
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
      </ScrollArea>
    </div>
  )
}

function SourceFileView({
  section,
  fileCount,
  expanded,
  onToggleExpanded,
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
  /** How many files the whole flow touches — the badge's denominator. */
  fileCount: number
  expanded: boolean
  onToggleExpanded: () => void
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
    if (seen || !active || !expanded) return
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
  }, [seen, active, expanded, scrollRef])
  // A jump or a selection targets THIS file, so it is wanted whether or not it
  // has been scrolled near — that is the click that asked for it. A closed card
  // is wanted by nobody: it fetches nothing until it is opened.
  const wanted =
    active && expanded && (seen || jump !== null || selection !== null)
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

  const directory = fileDirname(section.file)

  return (
    // One card per file: its own edges on a muted ground, so "a different file
    // starts here" is carried by the shape and not left to the reader to infer
    // from a change of path text. `overflow-clip` rather than `overflow-hidden`
    // — hidden would make this box the sticky header's scrollport and the
    // header would never stick at all.
    <section
      ref={sectionRef}
      data-source-card={section.file}
      className={cn(
        "mx-2 mb-2 min-w-0 overflow-clip rounded-lg border bg-background shadow-xs first:mt-2",
        !expanded && "bg-background/60"
      )}
    >
      {/* Sticky within the ONE scroller, and bounded by this card — the current
          file stays named while its code scrolls, then hands over to the next
          file's header instead of stacking on top of it. */}
      <header
        ref={headerRef}
        className={cn(
          // A CONTAINER, not a media query: this panel is user-resizable, so
          // what fits is a fact about the panel's width and nothing to do with
          // the viewport's.
          "@container sticky top-0 z-10 bg-muted/60 backdrop-blur",
          expanded && "border-b"
        )}
      >
        <button
          type="button"
          onClick={onToggleExpanded}
          aria-expanded={expanded}
          className={cn(
            "flex w-full cursor-pointer items-center gap-2 px-2 py-1.5 text-left transition-colors",
            "hover:bg-muted focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring focus-visible:outline-none"
          )}
        >
          <ChevronDown
            aria-hidden
            className={cn(
              "size-3.5 shrink-0 text-muted-foreground transition-transform",
              !expanded && "-rotate-90"
            )}
          />
          {/* Files are listed in the order the flow first reaches them, so the
              position is a fact about the flow, not a row number. */}
          <span
            className="shrink-0 rounded border border-border/70 bg-background px-1 font-mono text-[10px] text-muted-foreground tabular-nums"
            title={`File ${section.order + 1} of ${fileCount}, in the order this endpoint's flow first reaches them`}
          >
            {section.order + 1}
          </span>
          <FileCode2
            aria-hidden
            className="size-3.5 shrink-0 text-muted-foreground"
          />
          <span
            className="truncate font-mono text-xs font-medium"
            title={section.file}
          >
            {fileBasename(section.file)}
          </span>
          {expanded && currentMethod ? (
            // The enclosing method, pinned: scrolling into the middle of a file
            // must never leave the reader asking which method they are in.
            <span className="min-w-0 flex-1 truncate font-mono text-2xs text-muted-foreground">
              › {shortSignature(currentMethod)}
            </span>
          ) : (
            <span className="flex-1" />
          )}
        </button>
        <div className="flex items-baseline gap-2 px-2 pb-1.5 pl-[1.6rem] font-mono text-[10px] text-muted-foreground/70">
          {directory ? (
            <span className="min-w-0 flex-1 truncate" title={directory}>
              {shortDirectory(directory)}
            </span>
          ) : (
            <span className="flex-1" />
          )}
          <span className="shrink-0">
            {section.methods.length} method
            {section.methods.length === 1 ? "" : "s"}
            {/* Dropped first when the panel is narrow AND there is a fuller
                set to fall back on — a squeezed row that truncates mid-word
                tells the reader nothing. On a closed card, where nothing has
                been fetched yet, this is the only stat besides the method
                count, so it stays at every width. */}
            <span className={totalLines ? "hidden @[26rem]:inline" : undefined}>
              {" · "}
              {section.touched.length} executed
            </span>
            {/* Only known once the file is fetched — a closed card says what
                the graph knows, not what it has not looked at. */}
            {totalLines ? (
              <span className="hidden @[20rem]:inline">
                {" · "}
                {totalLines} lines
              </span>
            ) : null}
            {/* Say what is NOT on screen, at every width. The panel shows whole
                methods, so a header reporting only the file's length reads as a
                claim to be showing all of it (P10). */}
            {rowModel.foldedCount > 0 ? ` · ${rowModel.foldedCount} folded` : ""}
          </span>
        </div>
      </header>

      {!expanded ? null : (
        <>

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
            // Thin themed bar rather than the OS default: a full-width native
            // gutter under every code block was the loudest chrome on screen.
            "[scrollbar-color:var(--color-muted-foreground)_transparent] [scrollbar-width:thin]",
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
        </>
      )}
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
      {/* Selection groups through the GUTTER — a tinted number column with the
          numbers themselves in the accent — not through a coloured rule down
          the left edge. A stripe was one more vertical line in a panel already
          full of them, and it is not how this UI marks selection anywhere else. */}
      <span
        className={cn(
          // Pinned: scrolling a long line sideways must not cost you the
          // line numbers, which are how the gutter marks stay readable. The
          // opaque base is what occludes the code sliding under it, so the
          // selection tint has to ride on top of it rather than replace it.
          "sticky left-0 z-[1] w-11 shrink-0 select-none bg-background pr-2 text-right",
          inSelection
            ? "font-medium text-primary"
            : "text-muted-foreground/60 group-hover:text-muted-foreground"
        )}
      >
        {inSelection ? (
          <span aria-hidden className="absolute inset-0 bg-primary/15" />
        ) : null}
        <span className="relative">{lineNo}</span>
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
