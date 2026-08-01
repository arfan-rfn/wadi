/**
 * Custom Image Component with Redirect URL Support
 *
 * This component wraps Next.js Image to handle URLs that return 302 redirects,
 * which the default Next.js image optimizer doesn't support well.
 *
 * ## The Problem
 * Next.js Image optimization fetches images server-side to optimize them.
 * When a URL returns a 302 redirect (like our backend file API does),
 * the optimizer fails to follow the redirect properly, causing images to not load.
 *
 * ## When to Use This Component
 * Use `<CustomImage>` instead of `<Image>` when:
 * - Loading images from our backend file API (`/api/v1/files/...`)
 * - Loading images from any URL that returns a redirect
 * - Loading user-uploaded content (avatars, attachments, etc.)
 *
 * ## When to Use Regular Next.js Image
 * Use the standard `<Image>` from 'next/image' when:
 * - Loading static images from `/public` folder
 * - Loading images from CDNs that return direct responses (not redirects)
 * - Loading images where you need optimization benefits (resizing, WebP conversion)
 *
 * ## How It Works
 * - Detects URLs that match our backend file API pattern
 * - For redirect URLs: renders with `unoptimized={true}` so the browser handles the redirect
 * - For other URLs: uses standard Next.js optimization
 *
 * ## Example Usage
 * ```tsx
 * import { CustomImage } from '@/components/ui/image'
 *
 * // For user avatars or uploaded files
 * <CustomImage
 *   src={user.avatarUrl}
 *   alt="User avatar"
 *   width={100}
 *   height={100}
 * />
 *
 * // For static images, prefer regular Next.js Image
 * import Image from 'next/image'
 * <Image src="/logo.png" alt="Logo" width={100} height={100} />
 * ```
 */

"use client"

import NextImage, { ImageProps } from "next/image"

/**
 * Patterns that indicate a URL will redirect and should skip optimization.
 * Add new patterns here as needed.
 */
const REDIRECT_URL_PATTERNS = [
  /\/api\/v1\/files\//,           // Backend file API
  /localhost:\d+\/api\/.*files/,  // Local dev file API
] as const

/**
 * Checks if a URL is expected to return a redirect response.
 * These URLs should bypass Next.js image optimization.
 */
function isRedirectUrl(src: string | undefined): boolean {
  if (!src || typeof src !== "string") return false

  return REDIRECT_URL_PATTERNS.some((pattern) => pattern.test(src))
}

export interface CustomImageProps extends ImageProps {
  /**
   * Force skip optimization regardless of URL pattern detection.
   * Useful for one-off cases where you know the URL redirects.
   */
  forceUnoptimized?: boolean
}

/**
 * Custom Image component that handles redirect URLs.
 *
 * Automatically detects backend file API URLs and skips Next.js optimization
 * for them, allowing the browser to handle 302 redirects properly.
 */
export function CustomImage({
  src,
  forceUnoptimized,
  unoptimized,
  ...props
}: CustomImageProps) {
  // Determine if we should skip optimization
  const shouldSkipOptimization =
    forceUnoptimized ||
    unoptimized ||
    isRedirectUrl(typeof src === "string" ? src : undefined)

  return (
    <NextImage
      src={src}
      unoptimized={shouldSkipOptimization}
      {...props}
    />
  )
}

/**
 * Re-export for convenience when you explicitly want the optimized version.
 * Use this when you're certain the URL doesn't redirect.
 */
export { default as OptimizedImage } from "next/image"
