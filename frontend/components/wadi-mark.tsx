// The wadi mark: a wadi in cross-section — uneven banks, flat dry bed, a
// channel cut through.
//
// Inlined rather than served as an <img> because the path is filled with
// `currentColor`: one asset follows the surrounding text token in both themes,
// with no second file, no flash on theme change, and no network request at the
// size it is actually drawn (16px in the header).
//
// It is achromatic on purpose, and must stay that way. Every hue in this
// product is a data channel — five HTTP verbs, seven flow constructs, an
// eight-step role wheel — so a coloured mark would either collide with a hue
// that already means something specific or introduce an eighteenth the system
// has no room for. Never recolour it into a data hue, and never place it in a
// circle: full-round is reserved for state (chips, status dots).
export function WadiMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 64 64"
      className={className}
      role="img"
      aria-label="wadi"
      fill="currentColor"
    >
      <g transform="translate(0,-5)">
        <path d="M4 60V22h12l12 28h8l12-36h12v46z" />
      </g>
    </svg>
  )
}
