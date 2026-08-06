import { Geist, Geist_Mono } from "next/font/google"

// One type family, two voices — Geist (2026-08-06, replacing IBM Plex).
//
// Chosen on measurement, not taste. At 12px, against the strings this UI
// actually renders:
//
//                       advance    x-height   "144 nodes · 178 edges"
//   IBM Plex Mono       0.600em    6.19       —
//   Geist Mono          0.600em    6.36       —
//   IBM Plex Sans       —          6.19       190.8px
//   Geist               —          6.36       184.9px
//
// The finding that decided it: EVERY mainstream monospace is exactly 0.600em
// advance, so changing mono buys no density at all — same characters per line
// either way. What differs is x-height, which is precisely what governs
// legibility at this app's 11px floor. Geist Mono is 2.7% taller than Plex
// Mono at identical width, and Geist Sans is both 3.1% NARROWER and 2.7%
// taller than Plex Sans — better on both axes a dense UI cares about.
//
// The clincher is that Geist Sans and Geist Mono share an x-height exactly
// (6.36 / 6.36). This UI mixes the two inline constantly — "144 nodes · 178
// edges" sits beside "CancelController.calculate" in one line of the identity
// header — and matched x-heights keep those on a single visual line instead
// of the mono reading a size larger.
//
// Rejected: JetBrains Mono has the tallest x-height measured (6.60) and is
// the better pure code face, but it is 3.8% off any sans here, which shows up
// in exactly that inline mixing. Inter has the tallest sans x-height (6.55)
// and is 3.1% WIDER than Plex — it buys legibility by spending the density
// this app does not have to spare.
//
// Both are variable (wght 100-900), so one file per family covers every
// weight; Plex Mono was static and shipped three.
export const fontSans = Geist({
  subsets: ["latin"],
  variable: "--font-sans-next",
})

export const fontMono = Geist_Mono({
  subsets: ["latin"],
  variable: "--font-mono-next",
})
