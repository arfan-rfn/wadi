/**
 * Avatar Component with Redirect URL Support
 *
 * This component uses Radix UI Avatar primitives and includes special handling
 * for image URLs that return 302 redirects (like our backend file API).
 *
 * ## AvatarImage Behavior
 * - External URLs (http/https): Skips Next.js optimization, uses native img
 *   This allows the browser to handle 302 redirects from our file API
 * - Internal/relative URLs: Uses Next.js image optimization via getImageProps
 *
 * ## Usage
 * ```tsx
 * <Avatar>
 *   <AvatarImage src={user.avatarUrl} alt={user.name} />
 *   <AvatarFallback>JD</AvatarFallback>
 * </Avatar>
 * ```
 *
 * For non-avatar images, use `<CustomImage>` from '@/components/ui/image'
 */

"use client"

import * as React from "react"
import * as AvatarPrimitive from "@radix-ui/react-avatar"

import { cn } from "@/lib/utils"
import { getImageProps } from "next/image"

function Avatar({
  className,
  ...props
}: React.ComponentProps<typeof AvatarPrimitive.Root>) {
  return (
    <AvatarPrimitive.Root
      data-slot="avatar"
      className={cn(
        "relative flex size-8 shrink-0 overflow-hidden rounded-full",
        className
      )}
      {...props}
    />
  )
}

interface AvatarImageProps extends React.ComponentProps<typeof AvatarPrimitive.Image> {
  /** Force skip Next.js optimization. Auto-detected for external URLs. */
  unoptimized?: boolean;
}

function AvatarImage({
  className,
  unoptimized,
  ...props
}: AvatarImageProps) {
  const { src, alt, width, height, ...rest } = props;

  if (!src) {
    return <AvatarPrimitive.Image {...props} />;
  }

  // External URLs (http/https) skip Next.js optimization because:
  // 1. They may return 302 redirects (like our backend file API)
  // 2. Next.js image optimizer doesn't handle redirects well
  // 3. The browser's native img tag handles redirects properly
  const isExternalUrl = typeof src === 'string' && (src.startsWith('http://') || src.startsWith('https://'));
  const shouldSkipOptimization = unoptimized || isExternalUrl;

  if (shouldSkipOptimization) {
    return (
      <AvatarPrimitive.Image
        data-slot="avatar-image"
        className={cn("aspect-square size-full rounded-full object-cover", className)}
        src={src}
        alt={alt}
        {...rest}
      />
    );
  }

  const size =
    width && height
      ? { width: Number(width), height: Number(height) }
      : { fill: true };

  // This is the key line that makes Next.js image optimization take effect
  const { props: nextOptimizedProps } = getImageProps({
    src: src as string,
    alt: alt as string,
    ...size,
    ...rest,
  });

  return (
    <AvatarPrimitive.Image
      data-slot="avatar-image"
      className={cn("aspect-square size-full rounded-full object-cover", className)}
      {...nextOptimizedProps}
    />
  )
}

function AvatarFallback({
  className,
  ...props
}: React.ComponentProps<typeof AvatarPrimitive.Fallback>) {
  return (
    <AvatarPrimitive.Fallback
      data-slot="avatar-fallback"
      className={cn(
        "bg-muted flex size-full items-center justify-center rounded-full",
        className
      )}
      {...props}
    />
  )
}

export { Avatar, AvatarImage, AvatarFallback }
