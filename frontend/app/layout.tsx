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
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "white" },
    { media: "(prefers-color-scheme: dark)", color: "black" },
  ],
}

export const metadata: Metadata = getSEOTags({
  title: siteConfig.name,
  relativeUrl: "/",
  description: siteConfig.description,
  icons: {
    icon: "/favicon.ico",
    shortcut: "/favicon-16x16.png",
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
