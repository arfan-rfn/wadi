import type { NextConfig } from "next"

// The API proxy lives in app/api/v1/[...path]/route.ts — NOT here as a
// rewrite: rewrite destinations are baked at build time, which would freeze
// WADI_API_URL into the image and break runtime configuration (§13).
const nextConfig: NextConfig = {
  reactStrictMode: true,
  experimental: {
    viewTransition: true,
  },
}

export default nextConfig
