import "@/styles/globals.css"

import { Metadata, Viewport } from "next"

import { siteConfig } from "@/config/site"
import { fontMono, fontSans } from "@/lib/fonts"
import { getSEOTags } from "@/lib/seo"
import { cn } from "@/lib/utils"
import { DENSITY_INIT_SCRIPT } from "@/lib/wadi/density"
import { Toaster } from "@/components/ui/sonner"
import { JsonLd } from "@/components/json-ld"
import Providers from "@/components/providers"
import { TailwindIndicator } from "@/components/tailwind-indicator"

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  // The real ground colours, not `white`/`black`. This paints the browser
  // chrome around the page (mobile address bar, PWA title bar), so a generic
  // pair leaves a visible seam where the app's own ground begins.
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#F7F7F9" },
    { media: "(prefers-color-scheme: dark)", color: "#0A0A0C" },
  ],
}

export const metadata: Metadata = getSEOTags({
  title: siteConfig.name,
  relativeUrl: "/",
  description: siteConfig.description,
  // SVG first: browsers that support it get a mark that stays sharp at any
  // density and follows the tab's own light/dark scheme, with the .ico as the
  // fallback for those that don't. Ordering matters — the ico is listed with
  // an explicit size so it is not treated as a candidate for every slot.
  icons: {
    icon: [
      { url: "/favicon.svg", type: "image/svg+xml" },
      { url: "/favicon.ico", sizes: "32x32" },
      { url: "/favicon-16x16.png", type: "image/png", sizes: "16x16" },
      { url: "/favicon-32x32.png", type: "image/png", sizes: "32x32" },
      { url: "/favicon-48x48.png", type: "image/png", sizes: "48x48" },
    ],
    shortcut: "/favicon.ico",
    apple: "/apple-touch-icon.png",
  },
  manifest: `/manifest.json`,
})

interface RootLayoutProps {
  children: React.ReactNode
}

export default function RootLayout({ children }: RootLayoutProps) {
  return (
    <>
      <html lang="en" suppressHydrationWarning>
        <head>
          {/* Stamps the density attribute before first paint. Without it the
              first frame is always comfortable and a compact reader watches
              every row snap shorter on load — the same flash next-themes
              solves the same way. */}
          <script dangerouslySetInnerHTML={{ __html: DENSITY_INIT_SCRIPT }} />
        </head>
        <body
          className={`min-h-screen bg-background font-sans antialiased ${fontSans.variable} ${fontMono.variable}`}
          suppressHydrationWarning
        >
          <Providers>
            <JsonLd />
            <div className="relative flex min-h-screen flex-col bg-background">
              {children}
            </div>
            <Toaster />
            <TailwindIndicator />
          </Providers>
        </body>
      </html>
    </>
  )
}
