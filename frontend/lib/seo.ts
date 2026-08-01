import { env } from "@/env";
import { siteConfig } from "@/config/site";
import { Metadata } from "next"


interface SEOTagsParams extends Metadata {
	title: string;
	description: string;
	relativeUrl: string;
	imageUrl?: string;
	[key: string]: any;
}

export function getSEOTags(seoTags: SEOTagsParams): Metadata {
	const { title, description, relativeUrl, imageUrl } = seoTags;
	// Wadi is a local-first product: SEO base is optional and defaults to the
	// local UI address (§13 keypad block). Set NEXT_PUBLIC_BASE_URL for shared
	// deployments.
	const baseUrl = env.NEXT_PUBLIC_BASE_URL ?? "http://127.0.0.1:9235";

	// Ensure the canonical URL is absolute
	const fullUrl = `${baseUrl}${relativeUrl}`;

	// Get the OG image URL - use provided imageUrl or fall back to default
	const ogImageUrl = imageUrl || `${baseUrl}${siteConfig.seo.ogImage}`;

	return {
		metadataBase: fullUrl ? new URL(fullUrl) : null,
		alternates: {
			canonical: fullUrl,
		},
		openGraph: {
			type: 'website',
			locale: 'en_US',
			url: fullUrl,
			siteName: siteConfig.name,
			title: title,
			description: description,
			images: [
				{
					url: ogImageUrl,
					width: 1200,
					height: 630,
					alt: title,
				},
			],
		},
		robots: {
			index: true,
			follow: true,
			nocache: false,
			"max-video-preview": -1,
			"max-image-preview": "large",
			"max-snippet": -1,
			googleBot: {
				index: true,
				follow: true,
				noimageindex: false,
				"max-video-preview": -1,
				"max-image-preview": "large",
				"max-snippet": -1,
			},
		},
		twitter: {
			card: "summary_large_image",
			site: siteConfig.seo.twitterHandle,
			title: title,
			description: description,
			images: [ogImageUrl],
		},
		appleWebApp: {
			title: title,
		},
		...seoTags,
	};
}