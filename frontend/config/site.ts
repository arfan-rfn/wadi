export type SiteConfig = typeof siteConfig

export const siteConfig = {
  name: "wadi",
  description:
    "Ground-truth architecture of your microservice system: services, endpoints, and cross-service flows extracted from code.",
  mainNav: [
    {
      title: "Explorer",
      href: "/",
    },
  ],
  links: {
    github: "https://github.com/trywadi",
  },
  seo: {
    twitterHandle: "",
    ogImage: "/og-image.jpg",
  },
  // Icon must exist in components/icons.tsx
  socials: [
    {
      name: "GitHub",
      url: "https://github.com/trywadi",
      icon: "GitHub",
    },
  ],
  footer: {
    links: {
      Product: [
        { name: "Explorer", url: "/" },
        { name: "API", url: "/api/v1/systems" },
      ],
    },
  },
}
