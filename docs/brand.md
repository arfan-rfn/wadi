# wadi — brand assets

Source of truth for the mark. Assets live in `frontend/public/` (icons, served
at the web root) and `frontend/public/brand/` (lockups and 1024px marks). The
header renders the mark from `frontend/components/wadi-mark.tsx`, which inlines
the `currentColor` path rather than loading a file.

Mark: a wadi in cross-section. Uneven banks, flat dry bed, channel cut through.
Achromatic in every context — the mark never takes a hue, because every hue in
the product is already a data channel.

## Colour

| context      | mark      | ground    |
|--------------|-----------|-----------|
| light        | `#1E1E20` | `#F7F7F9` |
| dark         | `#F2F2F4` | `#0A0A0C` |
| print/stencil| `#000000` | paper     |

The only defensible accent, if one is ever needed, is the focus ring
(`#53568B` light / `#8A8DB2` dark). Recommendation is to ship achromatic.

## Rules

- Clear space: 1/4 of the mark's 64x64 square artboard on all sides. Measure the
  artboard, not the visible ink — against the ink it works out at roughly 1/3.
- Minimum size: 16px. Below that, do not use the mark.
- Wordmark: Geist 600, lowercase, tracking -0.04em. Never caps or title case.
- Lockup: artboard height = 1.08x the wordmark font size; gap = 1/3 of the artboard.
- Never recolour into a data hue, stretch, rotate, outline, add effects,
  or place inside a circle (full-round is reserved for state in the UI).

## Files

    brand/
      favicon.ico                     16 / 32 / 48, PNG payloads
      site.webmanifest
      svg/
        wadi-mark.svg                 currentColor — inline this one in the app
        wadi-mark-light.svg           #1E1E20
        wadi-mark-dark.svg            #F2F2F4
        wadi-tile-dark-bg.svg         radius 8, for square slots
        wadi-tile-light-bg.svg        radius 8
        wadi-lockup-light.svg         live <text>, requires Geist
        wadi-lockup-dark.svg          live <text>, requires Geist
        favicon.svg                   switches on prefers-color-scheme
      png/
        favicon-16x16.png             transparent, dark ink
        favicon-32x32.png
        favicon-48x48.png
        apple-touch-icon.png          180, opaque
        android-chrome-192x192.png    opaque
        android-chrome-512x512.png    opaque
        maskable-512x512.png          extra safe zone for Android masking
        wadi-tile-512.png             radius 8
        wadi-mark-1024-light.png      transparent
        wadi-mark-1024-dark.png       transparent
        wadi-lockup-light.png         transparent, #1E1E20 ink, type rasterised
        wadi-lockup-dark.png          transparent, #F2F2F4 ink, type rasterised

## Install

Copy `favicon.ico`, `favicon.svg`, `apple-touch-icon.png`,
`android-chrome-*.png`, `maskable-512x512.png` and `site.webmanifest`
to your web root, then:

```html
<link rel="icon" href="/favicon.ico" sizes="32x32">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="manifest" href="/site.webmanifest">
```

For the app header, inline `svg/wadi-mark.svg` — it uses `currentColor`, so it
follows your text colour token in both themes with no second asset.

## Path data

    M4 60V22h12l12 28h8l12-36h12v46z

On a 64x64 viewBox, wrapped in `<g transform="translate(0,-5)">` to centre it
in the square artboard.
