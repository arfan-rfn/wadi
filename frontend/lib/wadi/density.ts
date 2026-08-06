// Reading density (§11 Phase 2.10).
//
// The answer to "we need to fit a lot of information together" is not a
// smaller font. Below ~11px legibility falls off a cliff while the space
// recovered is marginal — and the app had already spent that budget, with 61
// arbitrary sizes down to 8px and 34 opacity-diluted foregrounds sitting near
// 2.4:1. Both are gone; the type scale has a floor now.
//
// So density buys its space from SPACING instead: row height, padding and gap.
// Compact fits roughly 20% more rows per screen with every glyph unchanged.
// That makes it a reader's preference rather than a decision baked into each
// component, which is the point — a 27" desktop and a laptop want different
// answers and neither is wrong.
//
// The tokens themselves live in styles/globals.css, keyed off the
// `data-density` attribute on <html>. Nothing here knows their values.

export type Density = "comfortable" | "compact"

const STORAGE_KEY = "wadi.density"
const ATTRIBUTE = "data-density"

export const DENSITIES: readonly Density[] = ["comfortable", "compact"]

function isDensity(value: string | null): value is Density {
  return value === "comfortable" || value === "compact"
}

export function readDensity(): Density {
  if (typeof window === "undefined") return "comfortable"
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY)
    return isDensity(stored) ? stored : "comfortable"
  } catch {
    return "comfortable"
  }
}

export function writeDensity(density: Density): void {
  if (typeof window === "undefined") return
  try {
    window.localStorage.setItem(STORAGE_KEY, density)
  } catch {
    // A blocked or full storage is not a reason to break the preference.
  }
}

/** Stamp the attribute the CSS keys off. Comfortable is the default and is
 * expressed as the ABSENCE of the attribute, so the tokens in `:root` are the
 * baseline and compact is the single override — one place to read, not two. */
export function applyDensity(density: Density): void {
  if (typeof document === "undefined") return
  const root = document.documentElement
  if (density === "compact") root.setAttribute(ATTRIBUTE, "compact")
  else root.removeAttribute(ATTRIBUTE)
}

/**
 * The script inlined into <head> to stamp density before first paint.
 *
 * Same reasoning as next-themes' anti-flash script: reading localStorage in an
 * effect means the first painted frame is always comfortable, so a compact
 * reader watches every row snap shorter on load. Running before paint costs a
 * few synchronous bytes and removes the flash entirely.
 */
export const DENSITY_INIT_SCRIPT = `(function(){try{var d=localStorage.getItem("${STORAGE_KEY}");if(d==="compact")document.documentElement.setAttribute("${ATTRIBUTE}","compact")}catch(e){}})()`
