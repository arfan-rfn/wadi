# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this directory.

The wadi frontend: a Next.js App Router UI over the orchestrator's `/api/v1`.
Based on [arfan-rfn/next-template](https://github.com/arfan-rfn/next-template)
(Tailwind v4, shadcn/Radix in `components/ui/`, TanStack Query, next-themes),
with the template's auth (Better Auth), analytics (PostHog/GA — wadi telemetry
is opt-in only, §16), blog/MDX, and dashboard surfaces removed.

## Commands

```bash
npm run dev            # dev server on port 9235 (the WADI keypad block)
npm run build          # production build
npm run typecheck      # tsc --noEmit
npm run lint           # eslint
npm run generate-types # regenerate lib/generated from ../schemas (run `make schema` at repo root first)
```

## Wadi-specific rules

- **Types are generated, never hand-written** (§7): `lib/generated/*.d.ts` comes
  from the contract JSON Schemas. After any `wadi-contracts` change: repo-root
  `make schema` → `npm run generate-types`. CI fails on staleness.
- **All orchestrator calls go through `lib/wadi/api.ts`** and the TanStack Query
  hooks in `lib/wadi/hooks.ts` (query keys in `config/query-keys.ts`).
- **The API proxy is a runtime route handler** (`app/api/v1/[...path]/route.ts`)
  reading `WADI_API_URL` per request. Never move it into next.config
  `rewrites()` — those are resolved at build time and would bake the URL into
  the image (§13 requires runtime config).
- The UI requires no `NEXT_PUBLIC_*` variables (same-origin proxy);
  `NEXT_PUBLIC_BASE_URL` is optional and only affects SEO metadata.
- Server Components by default; client components only where interactivity
  demands it (the explorer page is client-side by nature).
