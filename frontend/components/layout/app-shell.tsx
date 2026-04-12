"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import type { Route } from "next";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import type { ComponentType } from "react";
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
} from "lucide-react";

import { api } from "../../lib/api";
import { ApiError, httpErrorStatus } from "../../lib/api/client";
import { STORAGE_KEYS } from "../../lib/constants/storage-keys";
import { cn } from "../../lib/utils";
import { getAuthSessionQueryOptions, isAuthRoute } from "./auth-session-query";
import { Button } from "../ui/primitives";
import type { TopBarState } from "./top-bar-context";
import { TopBarProvider, useTopBarHeader } from "./top-bar-context";
import { ThemeToggle } from "../ui/theme-toggle";

const navGroups = [
  {
    label: "Workspace",
    items: [
      { href: "/dashboard",  label: "Dashboard",     icon: LayoutDashboard },
      { href: "/crawl",      label: "Crawl Studio",   icon: Globe           },
      { href: "/runs",       label: "History",        icon: History         },
      { href: "/selectors",  label: "Selector Tool",  icon: Search          },
      { href: "/jobs",       label: "Jobs",           icon: Activity        },
    ],
  },
  {
    label: "Admin",
    items: [
      { href: "/admin/users", label: "Users",      icon: ShieldCheck },
      { href: "/admin/llm",   label: "LLM Config", icon: Settings2   },
    ],
  },
] as const satisfies ReadonlyArray<{
  label: string;
  items: ReadonlyArray<{
    href: Route;
    label: string;
    icon: ComponentType<{ className?: string }>;
  }>;
}>;

const navItemCount = navGroups.reduce((total, group) => total + group.items.length, 0);

export function AppShell({ children }: Readonly<{ children: React.ReactNode }>) {
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
    return (
      <div className="min-h-screen bg-[var(--bg-base)] text-[var(--text-primary)]">
        <header
          className="surface-header header-blur flex h-[52px] items-center justify-between border-b border-[var(--divider)] px-6"
        >
          <LogoMark />
          <ThemeToggle compact />
        </header>
        <main className="grid min-h-[calc(100vh-52px)] place-items-center px-4 py-10">
          <div className="surface-panel w-full max-w-[400px] p-8 shadow-[var(--shadow-modal)]">
            {children}
          </div>
        </main>
      </div>
    );
  }

  /* Skeleton shell — pixel-identical layout to real shell */
  if (authQuery.isPending) {
    return (
      <div className="min-h-screen lg:grid lg:grid-cols-[220px_minmax(0,1fr)]">
        <aside className="surface-sidebar sticky top-0 hidden h-screen shrink-0 border-r border-[var(--divider)] lg:flex lg:flex-col lg:w-[220px]">
          <div className="flex h-[52px] items-center gap-3 border-b border-[var(--divider)] px-4">
            <div className="size-7 rounded-lg bg-[var(--border)]" />
            <div className="skeleton h-3 w-24" />
          </div>
          <div className="flex-1 px-3 py-3 space-y-1">
            {Array.from({ length: navItemCount }, (_, i) => (
              <div key={i} className="skeleton h-8 w-full rounded-[var(--radius-md)]" />
            ))}
          </div>
        </aside>
        <div className="flex min-w-0 flex-col">
          <div className="surface-header sticky top-0 z-20 h-[52px] border-b border-[var(--divider)]">
            <div className="flex h-full items-center gap-4 px-6">
              <div className="skeleton h-4 w-36" />
            </div>
          </div>
          <main className="p-6 space-y-5">
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              {Array.from({ length: 4 }, (_, i) => (
                <div key={i} className="stat-card space-y-3">
                  <div className="skeleton h-3 w-20" />
                  <div className="skeleton h-8 w-28" />
                </div>
              ))}
            </div>
            <div className="skeleton h-72 w-full rounded-[var(--radius-xl)]" />
          </main>
        </div>
      </div>
    );
  }

  if (authQuery.error && httpErrorStatus(authQuery.error) === 401) {
    return (
      <div className="grid min-h-screen place-items-center bg-[var(--bg-base)] px-4 text-center">
        <div className="surface-panel max-w-sm p-6">
          <p className="text-section-title text-primary">Session expired</p>
          <p className="mt-1.5 text-body-sm text-muted">Redirecting to login…</p>
        </div>
      </div>
    );
  }

  if (authQuery.error) {
    return (
      <div className="grid min-h-screen place-items-center bg-[var(--bg-base)] px-4 text-center">
        <div className="surface-panel max-w-sm p-6">
          <p className="text-section-title text-primary">Unable to load session</p>
          <p className="mt-1.5 text-body-sm text-muted">
            Refresh to retry, or sign in again if the session expired.
          </p>
          <div className="mt-4 flex justify-center"><ThemeToggle compact /></div>
        </div>
      </div>
    );
  }

  return (
    <TopBarProvider>
      <div className="min-h-screen bg-[var(--bg-base)] text-[var(--text-primary)]">
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-[var(--accent)] focus:px-3 focus:py-2 focus:text-body-sm focus:text-[var(--button-filled-fg)]"
        >
          Skip to main content
        </a>
        <div className="lg:hidden border-b border-[var(--divider)] bg-[var(--warning-bg)] px-4 py-2 text-caption text-secondary">
          Best viewed on desktop (1024px+).
        </div>
        <div className="min-h-screen lg:grid lg:grid-cols-[auto_minmax(0,1fr)]">
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

/* ─── Logo mark ──────────────────────────────────────────────────────────── */
function LogoMark({ collapsed = false }: Readonly<{ collapsed?: boolean }>) {
  return (
    <div className="flex items-center gap-2.5 min-w-0">
      <div className="logo-badge flex size-7 shrink-0 items-center justify-center rounded-[8px] bg-[var(--accent)] text-[var(--button-filled-fg)]">
        <Zap className="size-3.5" strokeWidth={2.5} />
      </div>
      {!collapsed && (
        <span className="truncate text-link-ui font-semibold tracking-[var(--tracking-tight)] text-primary">
          CrawlFlow
        </span>
      )}
    </div>
  );
}

/* ─── Sidebar ────────────────────────────────────────────────────────────── */
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
    <aside
      className={cn(
        "surface-sidebar sticky top-0 hidden h-screen shrink-0 border-r border-[var(--divider)] backdrop-blur-xl lg:flex lg:flex-col sidebar-animated",
        collapsed ? "lg:w-[52px]" : "lg:w-[220px]",
      )}
    >
      {/* Header row */}
      <div
        className={cn(
          "flex h-[52px] shrink-0 items-center border-b border-[var(--divider)]",
          collapsed ? "justify-center px-0" : "justify-between px-4",
        )}
      >
        {!collapsed && <LogoMark />}
        <button
          type="button"
          onClick={() => setCollapsed((v) => !v)}
          className="focus-ring inline-flex size-7 shrink-0 items-center justify-center rounded-[var(--radius-md)] text-[var(--text-muted)] transition hover:bg-[var(--bg-elevated)] hover:text-[var(--text-primary)]"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? <ChevronRight className="size-3.5" /> : <ChevronLeft className="size-3.5" />}
        </button>
      </div>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto overflow-x-hidden px-2 py-3" aria-label="Main navigation">
        {navGroups.map((group) => (
          <div key={group.label} className="mb-4">
            {!collapsed && (
              <p className="label-caps mb-1 px-2 text-muted">
                {group.label}
              </p>
            )}
            <div className="space-y-0.5">
              {group.items.map((item) => {
                const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
                const Icon = item.icon;
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    title={collapsed ? item.label : undefined}
                    className={cn(
                      "no-underline group relative flex h-[var(--control-height)] items-center rounded-[12px] px-2.5 text-link-ui transition-all",
                      collapsed ? "justify-center" : "gap-2.5",
                      active
                        ? "nav-item-active text-accent"
                        : "text-secondary hover:bg-[var(--nav-item-hover-bg)] hover:text-primary",
                    )}
                  >
                    {active ? <span className="absolute left-0 top-1/2 h-5 w-1 -translate-y-1/2 rounded-r-full bg-[var(--nav-item-active-marker)]" /> : null}
                    <Icon
                      className={cn(
                        "size-4 shrink-0 transition-colors",
                        active ? "text-accent" : "text-muted group-hover:text-secondary",
                      )}
                    />
                    {!collapsed && <span className="truncate">{item.label}</span>}
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
      </nav>

      {/* Footer */}
      {!collapsed && (
        <div className="shrink-0 border-t border-[var(--divider)] px-3 py-3">
          <div className="flex items-center justify-between">
            <span className="text-meta text-muted">Theme</span>
            <ThemeToggle compact />
          </div>
        </div>
      )}
    </aside>
  );
}

/* ─── Shell content ──────────────────────────────────────────────────────── */
function ShellContent({
  children,
  pathname,
  onOpenMobileNav,
}: Readonly<{ children: React.ReactNode; pathname: string; onOpenMobileNav: () => void }>) {
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
          "The API refused reset (admin-only on an older backend build, or a stale session). Stop and restart the FastAPI server so it loads the latest code, then try again — or sign out and sign back in.",
        );
        return;
      }
      const message = error instanceof Error ? error.message : "Failed to reset application data.";
      globalThis.alert(message);
    } finally {
      setIsResetting(false);
    }
  }

  const resetDisabled = isResetting;

  return (
    <div className="flex min-w-0 flex-col">
      <header
        className="surface-header header-blur sticky top-0 z-20 h-[52px] border-b border-[var(--divider)]"
      >
        <div className="flex h-full items-center justify-between gap-3 px-4 lg:px-6">
          <div className="flex min-w-0 items-center gap-3">
            <Button
              type="button"
              variant="ghost"
              onClick={onOpenMobileNav}
              className="h-8 w-8 px-0 lg:hidden"
              aria-label="Open navigation"
            >
              <Menu className="size-4" />
            </Button>
            <h1 className="truncate text-section-title text-primary">
              {topBar.title}
            </h1>
          </div>
          <div className="flex items-center gap-2">
            {topBar.actions && (
              <div className="flex flex-wrap items-center gap-2">{topBar.actions}</div>
            )}
            <Button
              type="button"
              onClick={() => {
                void handleResetData();
              }}
              disabled={resetDisabled}
              aria-disabled={resetDisabled}
              variant="secondary"
              size="sm"
              className="h-8"
            >
              <Trash2 className="size-3.5" />
              {isResetting ? "Resetting..." : "Reset"}
            </Button>
            <ThemeToggle compact />
          </div>
        </div>
      </header>

      <main id="main-content" className="min-w-0 flex-1 px-4 py-5 lg:px-6">
        <div className="mx-auto w-full max-w-[1440px]">{children}</div>
      </main>
    </div>
  );
}

/* ─── Mobile nav ─────────────────────────────────────────────────────────── */
function MobileNav({
  pathname,
  open,
  onClose,
}: Readonly<{ pathname: string; open: boolean; onClose: () => void }>) {
  return (
    <div className={cn("fixed inset-0 z-40 lg:hidden", open ? "pointer-events-auto" : "pointer-events-none")}>
      <button
        type="button"
        aria-label="Close navigation"
        onClick={onClose}
        className={cn("overlay-scrim absolute inset-0 backdrop-blur-sm transition-opacity", open ? "opacity-100" : "opacity-0")}
      />
      <aside
        className={cn(
          "surface-sidebar surface-drawer absolute inset-y-0 left-0 flex w-[260px] max-w-[85vw] flex-col border-r border-[var(--divider)] transition-transform duration-200 ease-out",
          open ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="flex h-[52px] items-center justify-between border-b border-[var(--divider)] px-4">
          <LogoMark />
          <Button type="button" variant="ghost" onClick={onClose} className="h-7 w-7 px-0" aria-label="Close">
            <X className="size-4" />
          </Button>
        </div>
        <nav className="flex-1 overflow-y-auto px-2 py-3">
          {navGroups.map((group) => (
            <div key={group.label} className="mb-4">
              <p className="label-caps mb-1 px-2 text-muted">
                {group.label}
              </p>
              <div className="space-y-0.5">
                {group.items.map((item) => {
                  const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
                  const Icon = item.icon;
                  return (
                    <Link
                      key={item.href}
                      href={item.href}
                      onClick={onClose}
                      className={cn(
                        "no-underline flex h-[var(--control-height)] items-center gap-2.5 rounded-[var(--radius-md)] px-2 text-link-ui transition-all",
                        active
                          ? "bg-[var(--accent-subtle)] text-accent"
                          : "text-secondary hover:bg-[var(--bg-elevated)] hover:text-primary",
                      )}
                    >
                      <Icon className={cn("size-4 shrink-0", active ? "text-accent" : "text-muted")} />
                      <span className="truncate">{item.label}</span>
                    </Link>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>
        <div className="shrink-0 border-t border-[var(--divider)] px-3 py-3">
          <div className="flex items-center justify-between">
            <span className="text-meta text-muted">Theme</span>
            <ThemeToggle compact />
          </div>
        </div>
      </aside>
    </div>
  );
}

function getFallbackHeader(pathname: string): TopBarState {
  if (pathname.startsWith("/dashboard"))    return { title: "Dashboard" };
  if (pathname.startsWith("/crawl"))        return { title: "Crawl Studio" };
  if (pathname.startsWith("/runs/"))        return { title: "Run Details" };
  if (pathname.startsWith("/runs"))         return { title: "Run History" };
  if (pathname.startsWith("/selectors"))    return { title: "Selector Tool" };
  if (pathname.startsWith("/admin/users"))  return { title: "Users" };
  if (pathname.startsWith("/admin/llm"))    return { title: "LLM Config" };
  if (pathname.startsWith("/jobs"))         return { title: "Jobs" };
  return { title: "CrawlFlow" };
}
