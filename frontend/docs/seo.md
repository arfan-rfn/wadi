# SEO Configuration

This document explains the SEO setup for this Next.js template and how to customize it for your project.

## Overview

The template includes comprehensive SEO support with:
- Open Graph tags for rich link previews on social media
- Twitter Card tags for Twitter-specific previews
- Canonical URLs for proper indexing
- JSON-LD structured data
- Sitemap generation via `next-sitemap`
- robots.txt configuration

## Configuration

### Site Configuration

SEO settings are managed in `config/site.ts`:

```typescript
seo: {
  twitterHandle: "@yourtwitterhandle", // Your Twitter/X handle
  ogImage: "/og-image.jpg",            // Default OG image path
}
```

**Update these values for your project:**
1. Replace `@yourtwitterhandle` with your actual Twitter handle
2. The `ogImage` path points to your default social sharing image

### OG Image Requirements

Add your OG image to `public/og-image.jpg` with these specifications:

| Property | Requirement |
|----------|-------------|
| **Dimensions** | 1200 x 630 pixels |
| **Format** | JPG or PNG |
| **File Size** | Keep under 1MB for fast loading |
| **Content** | Include your brand logo, site name, and key visual |

The OG image appears when your links are shared on:
- Facebook
- Twitter/X
- LinkedIn
- Discord
- Slack
- iMessage
- And other platforms that support Open Graph

## Using getSEOTags()

The `getSEOTags()` function in `lib/seo.ts` generates all necessary metadata for a page.

### Basic Usage

```typescript
import { getSEOTags } from "@/lib/seo";

export const metadata = getSEOTags({
  title: "Page Title",
  description: "Page description for search engines and social previews",
  relativeUrl: "/page-path",
});
```

### With Custom OG Image

```typescript
export const metadata = getSEOTags({
  title: "Blog Post Title",
  description: "Blog post description",
  relativeUrl: "/blog/post-slug",
  imageUrl: "https://example.com/custom-image.jpg", // Full URL
});
```

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `title` | string | Yes | Page title for SEO and social previews |
| `description` | string | Yes | Page description (aim for 150-160 characters) |
| `relativeUrl` | string | Yes | Path relative to base URL (e.g., `/blog/post`) |
| `imageUrl` | string | No | Custom OG image URL (defaults to `/og-image.jpg`) |

## Generated Meta Tags

The `getSEOTags()` function generates these tags:

### Open Graph Tags
- `og:type` - Content type (website)
- `og:locale` - Language locale (en_US)
- `og:url` - Canonical page URL
- `og:site_name` - Site name from config
- `og:title` - Page title
- `og:description` - Page description
- `og:image` - Social sharing image (1200x630)

### Twitter Card Tags
- `twitter:card` - Card type (summary_large_image)
- `twitter:site` - Site's Twitter handle
- `twitter:title` - Page title
- `twitter:description` - Page description
- `twitter:image` - Image for Twitter cards

### Other Tags
- `canonical` - Canonical URL for SEO
- `robots` - Indexing instructions
- Various `apple-web-app` tags

## Testing Social Previews

Validate your SEO implementation using these tools:

| Platform | Validation Tool |
|----------|----------------|
| Twitter/X | [Card Validator](https://cards-dev.twitter.com/validator) |
| Facebook | [Sharing Debugger](https://developers.facebook.com/tools/debug/) |
| LinkedIn | [Post Inspector](https://www.linkedin.com/post-inspector/) |
| General | [OpenGraph.xyz](https://www.opengraph.xyz/) |

## Sitemap

The sitemap is automatically generated during build via `next-sitemap`. Configuration is in `next-sitemap.config.js`.

To exclude pages from the sitemap, update the config:

```javascript
exclude: ['/admin/*', '/private/*'],
```

## Structured Data (JSON-LD)

The template includes JSON-LD structured data for:
- WebSite schema (homepage)
- Organization schema
- Article schema (blog posts)

These help search engines understand your content and can enable rich results in search.

## Best Practices

1. **Unique Titles**: Each page should have a unique, descriptive title
2. **Meta Descriptions**: Write compelling descriptions under 160 characters
3. **Consistent Branding**: Use consistent imagery across your OG images
4. **Test Before Launch**: Always validate social previews before launching
5. **Monitor Performance**: Use Google Search Console to track indexing
