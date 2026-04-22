"use client";

import { useQuery } from"@tanstack/react-query";
import Link from"next/link";
import type { Route } from"next";
import { usePathname, useRouter } from"next/navigation";
import { useEffect, useState } from"react";
import type { ComponentType, ReactNode } from"react";
import {
 Activity,
 ChevronLeft,
 ChevronRight,
 Globe,
 History,
 LayoutDashboard,
 Menu,
 Search,
 Settings2,
 ShieldCheck,
 Trash2,
 X,
 Zap,
} from"lucide-react";

import { api } from"../../lib/api";
import { httpErrorStatus } from"../../lib/api/client";
import { STORAGE_KEYS } from"../../lib/constants/storage-keys";
import { cn } from"../../lib/utils";
import { getAuthSessionQueryOptions, isAuthRoute } from"./auth-session-query";
import { Button } from"../ui/primitives";
import type { TopBarState } from"./top-bar-context";
import { TopBarProvider, useTopBarHeader } from"./top-bar-context";
import { ThemeToggle } from"../ui/theme-toggle";

const navGroups = [
 {
 label:"Workspace",
 items: [
 { href:"/dashboard", label:"Dashboard", icon: LayoutDashboard },
 { href:"/crawl", label:"Crawl Studio", icon: Globe },
 { href:"/runs", label:"History", icon: History },
 { href:"/selectors", label:"Selector Tool", icon: Search, exactMatch: true },
 { href:"/selectors/manage", label:"Domain Memory", icon: Search },
 { href:"/jobs", label:"Jobs", icon: Activity },
 ],
 },
 {
 label:"Admin",
 items: [
 { href:"/admin/users", label:"Users", icon: ShieldCheck },
 { href:"/admin/llm", label:"LLM Config", icon: Settings2 },
 ],
 },
] as const satisfies ReadonlyArray<{
 label: string;
 items: ReadonlyArray<{
 href: string;
 label: string;
 icon: ComponentType<{ className?: string }>;
 exactMatch?: boolean;
 }>;
}>;

function isNavItemActive(
 pathname: string,
 item: (typeof navGroups)[number]["items"][number],
): boolean {
 if ("exactMatch"in item && item.exactMatch) {
 return pathname === item.href;
 }
 return pathname === item.href || pathname.startsWith(`${item.href}/`);
}

const authTickerRows = [
 { domain:"shop.nike.com", records:"2,847 records", time:"just now"},
 { domain:"target.com", records:"4,120 records", time:"2m ago"},
 { domain:"wayfair.com", records:"920 records", time:"6m ago"},
 { domain:"bestbuy.com", records:"1,412 records", time:"11m ago"},
];

const navItemCount = navGroups.reduce((total, group) => total + group.items.length, 0);

export function AppShell({ children }: Readonly<{ children: ReactNode }>) {
 const pathname = usePathname();
 const router = useRouter();
 const [mobileNavOpen, setMobileNavOpen] = useState(false);
 const authRoute = isAuthRoute(pathname);

 const authQuery = useQuery(getAuthSessionQueryOptions(pathname));

 useEffect(() => {
 if (!authRoute && authQuery.error && httpErrorStatus(authQuery.error) === 401) {
 router.replace("/login");
 }
 }, [authQuery.error, authRoute, router]);

 if (authRoute) {
 return <AuthShell>{children}</AuthShell>;
 }

 if (authQuery.isPending) {
 return (
 <div className="app-shell-root">
 <div className="app-shell-grid">
 <aside className="app-sidebar">
 <div className="app-sidebar-header">
 <LogoMark />
 </div>
 <div className="app-sidebar-nav">
 {Array.from({ length: navItemCount }, (_, index) => (
 <div key={index} className="skeleton h-8 w-full rounded-[7px]"/>
 ))}
 </div>
 </aside>
 <div className="app-main-col">
 <div className="app-topbar">
 <div className="skeleton h-4 w-36"/>
 </div>
 <main className="app-page-frame">
 <div className="app-page-inner page-stack-lg">
 <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
 {Array.from({ length: 4 }, (_, index) => (
 <div key={index} className="metric-card space-y-3">
 <div className="skeleton h-3 w-20"/>
 <div className="skeleton h-8 w-28"/>
 </div>
 ))}
 </div>
 <div className="skeleton h-72 w-full rounded-[10px]"/>
 </div>
 </main>
 </div>
 </div>
 </div>
 );
 }

 if (authQuery.error && httpErrorStatus(authQuery.error) === 401) {
 return (
 <div className="app-shell-feedback">
 <div className="panel panel-raised max-w-sm p-6 text-center">
 <p className="text-base font-semibold leading-snug text-[var(--text-primary)]">Session expired</p>
 <p className="panel-subtitle mt-1.5">Redirecting to login…</p>
 </div>
 </div>
 );
 }

 if (authQuery.error) {
 return (
 <div className="app-shell-feedback">
 <div className="panel panel-raised max-w-sm p-6 text-center">
 <p className="text-base font-semibold leading-snug text-[var(--text-primary)]">Unable to load session</p>
 <p className="panel-subtitle mt-1.5">
 Refresh to retry, or sign in again if the session expired.
 </p>
 <div className="mt-4 flex justify-center">
 <ThemeToggle compact />
 </div>
 </div>
 </div>
 );
 }

 return (
 <TopBarProvider>
 <div className="app-shell-root">
 <a
 href="#main-content"
 className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-[var(--accent)] focus:px-3 focus:py-2 focus:text-sm focus:text-[var(--accent-fg)]"
 >
 Skip to main content
 </a>
 <div className="app-shell-grid">
 <Sidebar pathname={pathname} />
 <ShellContent pathname={pathname} onOpenMobileNav={() => setMobileNavOpen(true)}>
 {children}
 </ShellContent>
 </div>
 <MobileNav pathname={pathname} open={mobileNavOpen} onClose={() => setMobileNavOpen(false)} />
 </div>
 </TopBarProvider>
 );
}

function AuthShell({ children }: Readonly<{ children: ReactNode }>) {
 return (
 <div className="auth-shell">
 <section className="auth-shell-main">
 <div className="auth-shell-inner">
 <div className="auth-shell-header">
 <LogoMark auth />
 <ThemeToggle compact />
 </div>
 <div className="auth-shell-card">{children}</div>
 </div>
 </section>
 <aside className="auth-shell-aside">
 <div className="auth-shell-orb"aria-hidden="true"/>
 <div className="auth-shell-side-inner">
 <div className="auth-shell-ticker">
 <div className="auth-shell-ticker-head">
 <span className="auth-shell-pulse"aria-hidden="true"/>
 <span>Live across your workspace</span>
 </div>
 {authTickerRows.map((row) => (
 <div key={row.domain} className="auth-shell-ticker-row">
 <div>
 <div className="auth-shell-ticker-domain">{row.domain}</div>
 <div className="auth-shell-ticker-meta">extracted {row.records}</div>
 </div>
 <span className="auth-shell-ticker-time">{row.time}</span>
 </div>
 ))}
 </div>
 <blockquote className="auth-shell-quote">
 <p>
 “Our merch team stood up 40 new source crawls in a week without writing a single scraper.”
 </p>
 <footer>Dan K., Director of Data Ops</footer>
 </blockquote>
 </div>
 </aside>
 </div>
 );
}

function LogoMark({
 collapsed = false,
 auth = false,
}: Readonly<{ collapsed?: boolean; auth?: boolean }>) {
 if (collapsed) {
 return (
 <div className="app-logo app-logo-collapsed">
 <div className="app-logo-mark">
 <Zap className="size-3.5"strokeWidth={2.4} />
 </div>
 </div>
 );
 }

 return (
 <div className="app-logo">
 <div className={cn("app-logo-mark", auth &&"app-logo-mark-large")}>
 <Zap className={cn(auth ?"size-[18px]":"size-3.5")} strokeWidth={2.4} />
 </div>
 <div className="app-logo-copy">
 <span className="app-logo-title">CrawlerAI</span>
 <span className="app-logo-subtitle">Feedonomics</span>
 </div>
 </div>
 );
}

function Sidebar({ pathname }: Readonly<{ pathname: string }>) {
 const [collapsed, setCollapsed] = useState(() => {
 if (typeof window ==="undefined") return false;
 const stored = window.localStorage.getItem(STORAGE_KEYS.SIDEBAR_COLLAPSED);
 if (stored ==="true"|| stored ==="false") return stored ==="true";
 return window.matchMedia("(max-width: 1279px)").matches;
 });

 useEffect(() => {
 window.localStorage.setItem(STORAGE_KEYS.SIDEBAR_COLLAPSED, String(collapsed));
 }, [collapsed]);

 return (
 <aside className={cn("app-sidebar", collapsed &&"is-collapsed")}>
 <div className="app-sidebar-header">
 <LogoMark collapsed={collapsed} />
 <button
 type="button"
 onClick={() => setCollapsed((value) => !value)}
 className="app-icon-button"
 aria-label={collapsed ?"Expand sidebar":"Collapse sidebar"}
 >
 {collapsed ? <ChevronRight className="size-3.5"/> : <ChevronLeft className="size-3.5"/>}
 </button>
 </div>

 <nav className="app-sidebar-nav"aria-label="Main navigation">
 {navGroups.map((group) => (
 <div key={group.label} className="app-sidebar-group">
 {!collapsed && <p className="app-sidebar-group-label">{group.label}</p>}
 <div className="space-y-1">
 {group.items.map((item) => {
 const active = isNavItemActive(pathname, item);
 const Icon = item.icon;
 return (
 <Link
 key={item.href}
 href={item.href as Route}
 title={collapsed ? item.label : undefined}
 className={cn("app-nav-item", active &&"is-active", collapsed &&"is-collapsed")}
 >
 <Icon className="app-nav-icon"/>
 {!collapsed && <span className="truncate">{item.label}</span>}
 </Link>
 );
 })}
 </div>
 </div>
 ))}
 </nav>

 {!collapsed && (
 <div className="app-sidebar-footer">
 <div className="app-sidebar-footer-row">
 <div>
 <div className="app-sidebar-footer-title">Display</div>
 <div className="app-sidebar-footer-subtitle">Theme preference</div>
 </div>
 <ThemeToggle compact />
 </div>
 </div>
 )}
 </aside>
 );
}

function ShellContent({
 children,
 pathname,
 onOpenMobileNav,
}: Readonly<{ children: ReactNode; pathname: string; onOpenMobileNav: () => void }>) {
 const header = useTopBarHeader();
 const topBar = header ?? getFallbackHeader(pathname);
 const router = useRouter();
 const [isResetting, setIsResetting] = useState(false);

 async function handleResetData() {
 if (!confirm("Delete crawl data and generated artifacts? This clears runs, records, logs, review promotions, artifacts, cookies, and learned selector/domain mappings. User accounts and LLM config remain.")) {
 return;
 }
 setIsResetting(true);
 try {
 await api.resetApplicationData();
 globalThis.location.reload();
 } catch (error) {
 const status = httpErrorStatus(error);
 if (status === 401) {
 router.replace("/login");
 return;
 }
 if (status === 403) {
 globalThis.alert(
"The API refused reset (admin-only on an older backend build, or a stale session). Stop and restart the FastAPI server so it loads the latest code, then try again, or sign out and sign back in.",
 );
 return;
 }
 const message = error instanceof Error ? error.message :"Failed to reset application data.";
 globalThis.alert(message);
 } finally {
 setIsResetting(false);
 }
 }

 return (
 <div className="app-main-col">
 <header className="app-topbar">
 <div className="app-topbar-main">
 <Button
 type="button"
 variant="ghost"
 onClick={onOpenMobileNav}
 className="app-mobile-toggle lg:hidden"
 aria-label="Open navigation"
 >
 <Menu className="size-4"/>
 </Button>
 <h1 className="app-topbar-title">{topBar.title}</h1>
 </div>
 <div className="app-topbar-actions">
 {topBar.actions ? <div className="flex flex-wrap items-center gap-2">{topBar.actions}</div> : null}
 <Button
 type="button"
 onClick={() => {
 void handleResetData();
 }}
 disabled={isResetting}
 variant="secondary"
 size="sm"
 >
 <Trash2 className="size-3.5"/>
 {isResetting ?"Resetting...":"Reset"}
 </Button>
 <ThemeToggle compact />
 </div>
 </header>

 <main id="main-content"className="app-page-frame">
 <div className="app-page-inner">{children}</div>
 </main>
 </div>
 );
}

function MobileNav({
 pathname,
 open,
 onClose,
}: Readonly<{ pathname: string; open: boolean; onClose: () => void }>) {
 return (
 <div className={cn("app-mobile-nav", open ?"is-open":"")}>
 <button
 type="button"
 aria-label="Close navigation"
 onClick={onClose}
 className="app-mobile-nav-scrim"
 />
 <aside className="app-mobile-nav-sheet">
 <div className="app-sidebar-header">
 <LogoMark auth />
 <Button type="button"variant="ghost"onClick={onClose} size="icon"aria-label="Close">
 <X className="size-4"/>
 </Button>
 </div>
 <nav className="app-sidebar-nav">
 {navGroups.map((group) => (
 <div key={group.label} className="app-sidebar-group">
 <p className="app-sidebar-group-label">{group.label}</p>
 <div className="space-y-1">
 {group.items.map((item) => {
 const active = isNavItemActive(pathname, item);
 const Icon = item.icon;
 return (
 <Link
 key={item.href}
 href={item.href as Route}
 onClick={onClose}
 className={cn("app-nav-item", active &&"is-active")}
 >
 <Icon className="app-nav-icon"/>
 <span className="truncate">{item.label}</span>
 </Link>
 );
 })}
 </div>
 </div>
 ))}
 </nav>
 <div className="app-sidebar-footer">
 <div className="app-sidebar-footer-row">
 <div>
 <div className="app-sidebar-footer-title">Display</div>
 <div className="app-sidebar-footer-subtitle">Theme preference</div>
 </div>
 <ThemeToggle compact />
 </div>
 </div>
 </aside>
 </div>
 );
}

function getFallbackHeader(pathname: string): TopBarState {
 if (pathname.startsWith("/dashboard")) return { title:"Dashboard", description:"Overview of crawler activity across your workspace."};
 if (pathname.startsWith("/crawl")) return { title:"Crawl Studio", description:"Configure sources, run jobs, and monitor execution."};
 if (pathname.startsWith("/runs/")) return { title:"Run Details", description:"Inspect a crawl run, logs, and extracted output."};
 if (pathname.startsWith("/runs")) return { title:"Run History", description:"Review and manage previously submitted crawls."};
 if (pathname.startsWith("/selectors/manage")) return { title:"Domain Memory", description:"Manage saved selector memory by domain and surface."};
 if (pathname.startsWith("/selectors")) return { title:"Selector Tool", description:"Suggest, test, and validate field selectors."};
 if (pathname.startsWith("/admin/users")) return { title:"Users", description:"Manage workspace access and roles."};
 if (pathname.startsWith("/admin/llm")) return { title:"LLM Config", description:"Control provider settings and prompts."};
 if (pathname.startsWith("/jobs")) return { title:"Jobs", description:"Review worker activity and queued work."};
 return { title:"CrawlerAI"};
}
