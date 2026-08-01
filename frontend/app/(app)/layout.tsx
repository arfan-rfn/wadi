import { SiteHeader } from "@/components/site-header"

interface AppLayoutProps {
	children: React.ReactNode
}

// Workbench layout: full-bleed content, no marketing footer — the explorer
// owns the viewport below the header.
export default function AppLayout({ children }: AppLayoutProps) {
	return (
		<>
			<SiteHeader />
			<div className="flex-1">{children}</div>
		</>
	)
}
