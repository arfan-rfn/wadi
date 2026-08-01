import { createEnv } from "@t3-oss/env-nextjs"
import { z } from "zod"

// Wadi's UI talks to the orchestrator through the same-origin /api/v1 proxy
// (see app/api/v1/[...path]/route.ts), so no NEXT_PUBLIC_* config is required.
// WADI_API_URL is read server-side by the proxy at request time (§13).
export const env = createEnv({
  server: {
    NODE_ENV: z.enum(["development", "test", "production"]).optional(),
  },
  client: {
    NEXT_PUBLIC_BASE_URL: z.string().min(1).optional(),
  },
  experimental__runtimeEnv: {
    NEXT_PUBLIC_BASE_URL: process.env.NEXT_PUBLIC_BASE_URL,
  },
})
