// Shiki wrapper (§11 Phase 2.7): VS Code TextMate grammars, lazily loaded per
// file extension — polyglot-ready (Phase 8 languages need only an entry in
// LANG_BY_EXT). The highlighter and each grammar load on first use; unknown
// extensions fall back to plaintext. Tokenized results are cached by the
// callers (pinned-SHA content never changes).

import type { BundledLanguage, Highlighter } from "shiki"

const LANG_BY_EXT: Record<string, BundledLanguage> = {
  java: "java",
  kt: "kotlin",
  kts: "kotlin",
  py: "python",
  ts: "typescript",
  tsx: "tsx",
  js: "javascript",
  jsx: "jsx",
  go: "go",
  rb: "ruby",
  rs: "rust",
  scala: "scala",
  sql: "sql",
  xml: "xml",
  yml: "yaml",
  yaml: "yaml",
  json: "json",
  properties: "properties",
  sh: "shellscript",
  md: "markdown",
}

export const LIGHT_THEME = "github-light-default"
export const DARK_THEME = "github-dark-default"

export function langForFile(file: string): string {
  const ext = file.split(".").pop()?.toLowerCase() ?? ""
  return LANG_BY_EXT[ext] ?? "plaintext"
}

let highlighterPromise: Promise<Highlighter> | null = null

async function getHighlighter(): Promise<Highlighter> {
  if (!highlighterPromise) {
    highlighterPromise = import("shiki").then((shiki) =>
      shiki.createHighlighter({ themes: [LIGHT_THEME, DARK_THEME], langs: [] })
    )
  }
  return highlighterPromise
}

export interface HighlightToken {
  content: string
  color: string | undefined
}

/** Tokenize whole-file content into per-line token runs. Returns null tokens
 * (plain rendering) when the grammar cannot load — never throws. */
export async function tokenizeLines(
  content: string,
  file: string,
  dark: boolean
): Promise<HighlightToken[][] | null> {
  try {
    const highlighter = await getHighlighter()
    let lang = langForFile(file)
    if (
      lang !== "plaintext" &&
      !highlighter.getLoadedLanguages().includes(lang)
    ) {
      try {
        await highlighter.loadLanguage(lang as BundledLanguage)
      } catch {
        lang = "plaintext"
      }
    }
    const { tokens } = highlighter.codeToTokens(content, {
      lang: lang as BundledLanguage,
      theme: dark ? DARK_THEME : LIGHT_THEME,
    })
    return tokens.map((line) =>
      line.map((token) => ({ content: token.content, color: token.color }))
    )
  } catch {
    return null
  }
}
