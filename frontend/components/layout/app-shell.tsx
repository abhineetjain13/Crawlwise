"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import type { Route } from "next";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import type { ComponentType, ReactNode } from "react";
import {
    Activity,
    Brain,
    ChevronLeft,
    ChevronRight,
    Database,
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
} from "lucide-react";

import { api } from "../../lib/api";
import { httpErrorStatus } from "../../lib/api/client";
import { STORAGE_KEYS } from "../../lib/constants/storage-keys";
import { cn } from "../../lib/utils";
import { getAuthSessionQueryOptions, isAuthRoute } from "./auth-session-query";
import { Button, Dropdown } from "../ui/primitives";
import { ConfirmDialog } from "../ui/dialog";
import type { TopBarState } from "./top-bar-context";
import { TopBarProvider, useTopBarHeader } from "./top-bar-context";
import { ThemeToggle } from "../ui/theme-toggle";
import "./app-shell.module.css";
import "./auth-shell.module.css";

const navGroups = [
    {
        label: "Workspace",
        items: [
            { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
            { href: "/crawl", label: "Crawl Studio", icon: Globe },
            { href: "/runs", label: "History", icon: History },
            { href: "/product-intelligence", label: "Product Intelligence", icon: Brain },
            { href: "/selectors", label: "Selector Tool", icon: Search, exactMatch: true },
            { href: "/selectors/manage", label: "Domain Memory", icon: Database },
            { href: "/jobs", label: "Jobs", icon: Activity },
        ],
    },
    {
        label: "Admin",
        items: [
            { href: "/admin/users", label: "Users", icon: ShieldCheck },
            { href: "/admin/llm", label: "LLM Config", icon: Settings2 },
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
    if ("exactMatch" in item && item.exactMatch) {
        return pathname === item.href;
    }
    return pathname === item.href || pathname.startsWith(`${item.href}/`);
}

const navItemCount = navGroups.reduce((total, group) => total + group.items.length, 0);

type ResetMode = "crawl" | "memory" | "intelligence";

const resetDialogCopy: Record<ResetMode, { title: string; description: string; confirmLabel: string }> = {
    crawl: {
        title: "Reset crawl data",
        description: "Delete crawl runs, records, logs, artifacts, and runtime cookie files? Learned domain memory will be preserved.",
        confirmLabel: "Reset Crawl Data",
    },
    memory: {
        title: "Reset domain memory",
        description: "Delete learned domain memory only? This clears saved selectors, saved run profiles, cookie memory, and field feedback without deleting crawl history.",
        confirmLabel: "Reset Domain Memory",
    },
    intelligence: {
        title: "Reset Product Intelligence",
        description: "Delete Product Intelligence sessions, sources, discovered URLs, matches, and intelligence results? Crawl history and domain memory will be preserved.",
        confirmLabel: "Reset Intelligence",
    },
};

const resetForbiddenMessage =
    "The API refused reset (admin-only on an older backend build, or a stale session). Stop and restart the FastAPI server so it loads the latest code, then try again, or sign out and sign back in.";

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
                                <div key={index} className="skeleton h-8 w-full rounded-[7px]" />
                            ))}
                        </div>
                    </aside>
                    <div className="app-main-col">
                        <div className="app-topbar">
                            <div className="skeleton h-4 w-36" />
                        </div>
                        <main className="app-page-frame">
                            <div className="app-page-inner page-stack-lg">
                                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                                    {Array.from({ length: 4 }, (_, index) => (
                                        <div key={index} className="space-y-3 rounded-[var(--radius-xl)] border border-border bg-panel p-4 shadow-card">
                                            <div className="skeleton h-3 w-20" />
                                            <div className="skeleton h-8 w-28" />
                                        </div>
                                    ))}
                                </div>
                                <div className="skeleton h-72 w-full rounded-[10px]" />
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
                <div className="max-w-sm rounded-[var(--radius-xl)] border border-border bg-panel p-6 text-center shadow-card">
                    <p className="text-base font-semibold leading-snug text-foreground type-heading">Session expired</p>
                    <p className="mt-1.5 text-sm leading-[var(--leading-relaxed)] text-secondary">Redirecting to login…</p>
                </div>
            </div>
        );
    }

    if (authQuery.error) {
        return (
            <div className="app-shell-feedback">
                <div className="max-w-sm rounded-[var(--radius-xl)] border border-border bg-panel p-6 text-center shadow-card">
                    <p className="text-base font-semibold leading-snug text-foreground type-heading">Unable to load session</p>
                    <p className="mt-1.5 text-sm leading-[var(--leading-relaxed)] text-secondary">
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
                    className="ui-on-accent-surface sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-accent focus:px-3 focus:py-2 focus:text-sm"
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
            <div className="auth-shell-card">
                <div className="auth-shell-header">
                    <div className="auth-shell-brand">
                        <LogoMark auth />
                        <span>CrawlerAI</span>
                    </div>
                    <ThemeToggle compact />
                </div>
                {children}
            </div>
        </div>
    );
}

function LogoMark({
    collapsed = false,
    auth = false,
}: Readonly<{ collapsed?: boolean; auth?: boolean }>) {
    const iconSize = auth ? "size-5" : "size-4";
    const mark = (
        <svg
            viewBox="0 0 24 24"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            className={cn(iconSize, "text-inherit")}
            aria-hidden="true"
        >
            <path
                d="M17 5H7C5.89543 5 5 5.89543 5 7V17C5 18.1046 5.89543 19 7 19H17"
                stroke="currentColor"
                strokeWidth="3"
                strokeLinecap="square"
            />
            <rect x="14" y="10" width="4" height="4" fill="currentColor" />
        </svg>
    );

    if (collapsed) {
        return (
            <div className="app-logo app-logo-collapsed">
                <div className="app-logo-mark">
                    {mark}
                </div>
            </div>
        );
    }

    return (
        <div className="app-logo">
            <div className={cn("app-logo-mark", auth && "app-logo-mark-large")}>
                {mark}
            </div>
            <div className="app-logo-copy">
                <span className="app-logo-title">CrawlerAI</span>
            </div>
        </div>
    );
}

function Sidebar({ pathname }: Readonly<{ pathname: string }>) {
    const [collapsed, setCollapsed] = useState(() => {
        if (typeof window === "undefined") return false;
        const stored = window.localStorage.getItem(STORAGE_KEYS.SIDEBAR_COLLAPSED);
        if (stored === "true" || stored === "false") return stored === "true";
        return window.matchMedia("(max-width: 1279px)").matches;
    });

    useEffect(() => {
        window.localStorage.setItem(STORAGE_KEYS.SIDEBAR_COLLAPSED, String(collapsed));
    }, [collapsed]);

    return (
        <aside className={cn("app-sidebar", collapsed && "is-collapsed")}>
            <div className="app-sidebar-header">
                <LogoMark collapsed={collapsed} />
                <button
                    type="button"
                    onClick={() => setCollapsed((value) => !value)}
                    className="app-icon-button"
                    aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
                >
                    {collapsed ? <ChevronRight className="size-3.5" /> : <ChevronLeft className="size-3.5" />}
                </button>
            </div>

            <nav className="app-sidebar-nav" aria-label="Main navigation">
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
                                        className={cn("app-nav-item", active && "is-active", collapsed && "is-collapsed")}
                                    >
                                        <Icon className="app-nav-icon" />
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
    const [resetPending, setResetPending] = useState<ResetMode | null>(null);
    const [resetMode, setResetMode] = useState<ResetMode>("crawl");
    const [resetDialogOpen, setResetDialogOpen] = useState(false);
    const [resetError, setResetError] = useState("");

    async function executeReset() {
        setResetPending(resetMode);
        setResetError("");
        try {
            if (resetMode === "memory") {
                await api.resetDomainMemory();
            } else if (resetMode === "intelligence") {
                await api.resetProductIntelligence();
            } else {
                await api.resetCrawlData();
            }
            globalThis.location.reload();
        } catch (error) {
            const status = httpErrorStatus(error);
            if (status === 401) {
                router.replace("/login");
                return;
            }
            if (status === 403) {
                setResetError(resetForbiddenMessage);
                return;
            }
            setResetError(error instanceof Error ? error.message : "Failed to reset selected data.");
        } finally {
            setResetPending(null);
        }
    }

    function handleSelectedReset() {
        setResetError("");
        setResetDialogOpen(true);
    }

    const resetCopy = resetDialogCopy[resetMode];
    const resetLabel =
        resetPending === "crawl"
            ? "Resetting Crawl Data..."
            : resetPending === "memory"
                ? "Resetting Domain Memory..."
                : resetPending === "intelligence"
                    ? "Resetting Intelligence..."
                    : "Reset";

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
                        <Menu className="size-4" />
                    </Button>
                    <h1 className="app-topbar-title">{topBar.title}</h1>
                </div>
                <div className="app-topbar-actions">
                    {topBar.actions ? <div className="flex flex-wrap items-center gap-2">{topBar.actions}</div> : null}
                    <div className="flex items-center gap-2">
                        <Button
                            type="button"
                            onClick={handleSelectedReset}
                            disabled={resetPending !== null}
                            variant="secondary"
                            className="h-[var(--control-height)]"
                        >
                            <Trash2 className="size-3.5" />
                            {resetLabel}
                        </Button>
                        <Dropdown
                            ariaLabel="Reset action"
                            value={resetMode}
                            onChange={setResetMode}
                            disabled={resetPending !== null}
                            align="center"
                            className="w-max"
                            options={[
                                { value: "crawl", label: "Crawl Data" },
                                { value: "memory", label: "Domain Memory" },
                                { value: "intelligence", label: "Intelligence" },
                            ]}
                        />                    </div>
                    <ThemeToggle compact />
                </div>
            </header>

            <main id="main-content" className="app-page-frame">
                <div className="app-page-inner">{children}</div>
            </main>
            <ConfirmDialog
                open={resetDialogOpen}
                onOpenChange={setResetDialogOpen}
                title={resetCopy.title}
                description={resetCopy.description}
                confirmLabel={resetCopy.confirmLabel}
                pending={resetPending !== null}
                danger
                error={resetError}
                onConfirm={() => void executeReset()}
            />
        </div>
    );
}

function MobileNav({
    pathname,
    open,
    onClose,
}: Readonly<{ pathname: string; open: boolean; onClose: () => void }>) {
    return (
        <div className={cn("app-mobile-nav", open ? "is-open" : "")}>
            <button
                type="button"
                aria-label="Close navigation"
                onClick={onClose}
                className="app-mobile-nav-scrim"
            />
            <aside className="app-mobile-nav-sheet">
                <div className="app-sidebar-header">
                    <LogoMark auth />
                    <Button type="button" variant="ghost" onClick={onClose} size="icon" aria-label="Close">
                        <X className="size-4" />
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
                                            className={cn("app-nav-item", active && "is-active")}
                                        >
                                            <Icon className="app-nav-icon" />
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
    if (pathname.startsWith("/dashboard")) return { title: "Dashboard", description: "Overview of crawler activity across your workspace." };
    if (pathname.startsWith("/crawl")) return { title: "Crawl Studio", description: "Configure sources, run jobs, and monitor execution." };
    if (pathname.startsWith("/product-intelligence")) return { title: "Product Intelligence", description: "Find matching product pages and compare prices." };
    if (pathname.startsWith("/runs/")) return { title: "Run Details", description: "Inspect a crawl run, logs, and extracted output." };
    if (pathname.startsWith("/runs")) return { title: "Run History", description: "Review and manage previously submitted crawls." };
    if (pathname.startsWith("/selectors/manage")) return { title: "Domain Memory", description: "Inspect learned selectors and saved run profiles by domain and surface." };
    if (pathname.startsWith("/selectors")) return { title: "Selector Tool", description: "Suggest, test, and validate field selectors." };
    if (pathname.startsWith("/admin/users")) return { title: "Users", description: "Manage workspace access and roles." };
    if (pathname.startsWith("/admin/llm")) return { title: "LLM Config", description: "Control provider settings and prompts." };
    if (pathname.startsWith("/jobs")) return { title: "Jobs", description: "Review worker activity and queued work." };
    return { title: "CrawlerAI" };
}
