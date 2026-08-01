import { IBM_Plex_Mono, IBM_Plex_Sans } from "next/font/google"

// One type family, two voices: IBM Plex — a technical identity that matches
// what wadi shows (code-derived facts), instead of default UI fonts.
export const fontSans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-sans-next",
})

export const fontMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-mono-next",
})
