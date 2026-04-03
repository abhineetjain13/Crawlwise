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
  Database,
  Globe,
  History,
  LayoutDashboard,
  Menu,
  Search,
  Settings2,
  ShieldCheck,
  X,
  Zap,
} from "lucide-react";

import { api } from "../../lib/api";
import { ApiError } from "../../lib/api/client";
import { cn } from "../../lib/utils";
import { Button } from "../ui/primitives";
import type { TopBarState } from "./top-bar-context";
import { TopBarProvider, useTopBarHeader } from "./top-bar-context";
import { ThemeToggle } from "../ui/theme-toggle";

const SIDEBAR_KEY = "crawlerai-sidebar-collapsed";

const navGroups = [
  {
    label: "Workspace",
    items: [
      { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
      { href: "/crawl", label: "Crawlers", icon: Globe },
      { href: "/runs", label: "History", icon: History },
      { href: "/memory", label: "Site Memory", icon: Database },
      { href: "/selectors", label: "Selector Tool", icon: Search },
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
      href: Route;
      label: string;
      icon: ComponentType<{ className?: string }>;
    }>;
  }>;

export function AppShell({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const pathname = usePathname();
  const router = useRouter();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const isAuthRoute = pathname === "/login" || pathname === "/register";
  const authQuery = useQuery({
    queryKey: ["me"],
    queryFn: api.me,
    enabled: !isAuthRoute,
    retry: false,
  });

  useEffect(() => {
    if (!isAuthRoute && authQuery.error instanceof ApiError && authQuery.error.isUnauthorized) {
      router.replace("/login");
    }
  }, [authQuery.error, isAuthRoute, router]);

  if (isAuthRoute) {
    return (
      <div className="min-h-screen bg-background text-foreground">
        <header className="surface-header flex h-[52px] items-center justify-between border-b border-border px-5">
          <div className="flex items-center gap-3">
            <div className="flex size-9 items-center justify-center rounded-[10px] bg-brand text-brand-foreground shadow-[var(--shadow-sm)]">
              <Zap className="size-4" />
            </div>
            <div>
              <div className="text-sm font-semibold tracking-[-0.02em]">CrawlFlow</div>
              <div className="text-[11px] uppercase tracking-[0.06em] text-muted">Secure workspace access</div>
            </div>
          </div>
          <ThemeToggle compact />
        </header>
        <main className="grid min-h-[calc(100vh-52px)] place-items-center px-4 py-8">
          <div className="w-full max-w-md rounded-[var(--radius-xl)] border border-border bg-panel p-7 shadow-[var(--shadow-modal)]">
            {children}
          </div>
        </main>
      </div>
    );
  }

  if (authQuery.isPending) {
    return (
      <div className="grid min-h-screen place-items-center bg-background text-muted">
        <div className="animate-pulse-subtle text-sm">Loading workspace...</div>
      </div>
    );
  }

  if (authQuery.error instanceof ApiError && authQuery.error.isUnauthorized) {
    return (
      <div className="grid min-h-screen place-items-center bg-background px-4 text-center">
        <div className="max-w-md rounded-[var(--radius-xl)] border border-border bg-panel p-6 shadow-[var(--shadow-card)]">
          <div className="text-base font-semibold text-foreground">Session expired</div>
          <p className="mt-2 text-sm text-muted">
            Redirecting to login.
          </p>
        </div>
      </div>
    );
  }

  if (authQuery.error) {
    return (
      <div className="grid min-h-screen place-items-center bg-background px-4 text-center">
        <div className="max-w-md rounded-[var(--radius-xl)] border border-border bg-panel p-6 shadow-[var(--shadow-card)]">
          <div className="text-base font-semibold text-foreground">Unable to load session</div>
          <p className="mt-2 text-sm text-muted">
            The workspace could not verify the current session. Refresh to retry, or sign in again if the session expired.
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
      <div className="min-h-screen bg-background text-foreground">
        <div className="lg:hidden border-b border-border bg-warning/10 px-4 py-2 text-xs text-foreground">
          Best viewed on desktop. Minimum supported viewport is 1024px.
        </div>
        <div className="min-h-screen lg:grid lg:grid-cols-[auto_minmax(0,1fr)]">
          <Sidebar pathname={pathname} />
          <ShellContent pathname={pathname} onOpenMobileNav={() => setMobileNavOpen(true)}>{children}</ShellContent>
        </div>
        <MobileNav pathname={pathname} open={mobileNavOpen} onClose={() => setMobileNavOpen(false)} />
      </div>
    </TopBarProvider>
  );
}

function Sidebar({ pathname }: Readonly<{ pathname: string }>) {
  const [collapsed, setCollapsed] = useState(() => {
    if (typeof window === "undefined") {
      return false;
    }
    const stored = window.localStorage.getItem(SIDEBAR_KEY);
    if (stored === "true" || stored === "false") {
      return stored === "true";
    }
    return window.matchMedia("(max-width: 1279px)").matches;
  });

  useEffect(() => {
    window.localStorage.setItem(SIDEBAR_KEY, String(collapsed));
  }, [collapsed]);

  const widthClass = collapsed ? "lg:w-[56px]" : "lg:w-[220px]";

  return (
    <aside
      className={cn(
        "surface-sidebar sticky top-0 hidden h-screen shrink-0 border-r border-border lg:flex lg:flex-col",
        widthClass,
      )}
    >
      <div className={cn("flex h-[52px] items-center border-b border-border", collapsed ? "justify-center px-2" : "justify-between gap-2 px-3")}>
        {!collapsed ? (
          <div className="flex min-w-0 items-center gap-3">
            <div className="flex size-9 items-center justify-center rounded-[10px] bg-brand text-brand-foreground shadow-[var(--shadow-sm)]">
              <Zap className="size-4" />
            </div>
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold tracking-[-0.02em] text-foreground">CrawlFlow</div>
              <div className="text-[11px] uppercase tracking-[0.06em] text-muted">Operations</div>
            </div>
          </div>
        ) : null}
        <button
          type="button"
          onClick={() => setCollapsed((value) => !value)}
          className="focus-ring inline-flex size-8 shrink-0 items-center justify-center rounded-[var(--radius-md)] border border-border bg-transparent text-muted transition hover:bg-background-elevated hover:text-foreground"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? <ChevronRight className="size-4" /> : <ChevronLeft className="size-4" />}
        </button>
      </div>

      <nav className="flex-1 overflow-y-auto px-2 py-3">
        {navGroups.map((group) => (
          <div key={group.label} className="mb-4">
            {!collapsed ? <div className="label-caps px-2 pb-2">{group.label}</div> : null}
            <div className="space-y-1">
              {group.items.map((item) => {
                const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
                const Icon = item.icon;
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    title={collapsed ? item.label : undefined}
                    className={cn(
                      "no-underline group flex h-9 items-center rounded-[var(--radius-md)] border-l-[3px] px-3 text-[14px] transition-all",
                      collapsed ? "justify-center" : "gap-3",
                      active
                        ? "border-l-accent bg-accent-subtle text-foreground shadow-[inset_0_0_0_1px_color-mix(in_srgb,var(--accent)_18%,transparent)]"
                        : "border-l-transparent text-muted hover:bg-accent-subtle hover:text-foreground",
                    )}
                  >
                    <Icon className="size-5 shrink-0" />
                    {!collapsed ? <span className="truncate">{item.label}</span> : null}
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
      </nav>

      <div className="border-t border-border p-3">
        {!collapsed ? (
          <div className="flex items-center justify-between rounded-[var(--radius-md)] border border-border bg-background-elevated px-3 py-2">
            <div>
              <div className="label-caps">Theme</div>
              <div className="text-sm text-foreground">Light / Dark</div>
            </div>
            <ThemeToggle compact />
          </div>
        ) : null}
      </div>
    </aside>
  );
}

function ShellContent({
  children,
  pathname,
  onOpenMobileNav,
}: Readonly<{ children: React.ReactNode; pathname: string; onOpenMobileNav: () => void }>) {
  const header = useTopBarHeader();
  const fallbackHeader = getFallbackHeader(pathname);
  const topBar = header ?? fallbackHeader;

  return (
    <div className="flex min-w-0 flex-col">
      <header className="surface-header sticky top-0 z-20 h-[52px] border-b border-border backdrop-blur-sm">
        <div className="flex h-full items-center justify-between gap-3 px-4 lg:px-8">
          <div className="flex min-w-0 items-center gap-3">
            <Button type="button" variant="secondary" onClick={onOpenMobileNav} className="h-9 w-9 px-0 lg:hidden" aria-label="Open navigation">
              <Menu className="size-4" />
            </Button>
            <div className="min-w-0">
              <div className="truncate text-[18px] font-semibold tracking-[var(--tracking-tight)] text-foreground">
                {topBar.title}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {topBar.actions ? <div className="flex flex-wrap items-center gap-2">{topBar.actions}</div> : null}
            <ThemeToggle compact />
          </div>
        </div>
      </header>

      <main className="min-w-0 flex-1 px-4 py-4 lg:px-8 lg:py-5">
        <div className="mx-auto w-full max-w-[1440px]">{children}</div>
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
    <div className={cn("fixed inset-0 z-40 lg:hidden", open ? "pointer-events-auto" : "pointer-events-none")}>
      <button
        type="button"
        aria-label="Close navigation"
        onClick={onClose}
        className={cn("absolute inset-0 bg-black/40 transition-opacity", open ? "opacity-100" : "opacity-0")}
      />
      <aside
        className={cn(
          "surface-sidebar absolute inset-y-0 left-0 flex w-[280px] max-w-[85vw] flex-col border-r border-border transition-transform",
          open ? "translate-x-0" : "-translate-x-full",
        )}
        style={{ boxShadow: "var(--surface-drawer-shadow)" }}
      >
        <div className="flex h-[52px] items-center justify-between border-b border-border px-4">
          <div className="flex items-center gap-3">
            <div className="flex size-9 items-center justify-center rounded-[10px] bg-brand text-brand-foreground shadow-[var(--shadow-sm)]">
              <Zap className="size-4" />
            </div>
            <div>
              <div className="text-sm font-semibold tracking-[-0.02em] text-foreground">CrawlFlow</div>
              <div className="text-[11px] uppercase tracking-[0.06em] text-muted">Operations</div>
            </div>
          </div>
          <Button type="button" variant="ghost" onClick={onClose} className="h-8 w-8 px-0" aria-label="Close navigation">
            <X className="size-4" />
          </Button>
        </div>
        <nav className="flex-1 overflow-y-auto px-2 py-3">
          {navGroups.map((group) => (
            <div key={group.label} className="mb-4">
              <div className="label-caps px-2 pb-2">{group.label}</div>
              <div className="space-y-1">
                {group.items.map((item) => {
                  const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
                  const Icon = item.icon;
                  return (
                    <Link
                      key={item.href}
                      href={item.href}
                      onClick={onClose}
                      className={cn(
                        "no-underline flex h-9 items-center gap-3 rounded-[var(--radius-md)] border-l-[3px] px-3 text-sm transition-all",
                        active
                          ? "border-l-accent bg-accent-subtle text-foreground shadow-[inset_0_0_0_1px_color-mix(in_srgb,var(--accent)_18%,transparent)]"
                          : "border-l-transparent text-muted hover:bg-accent-subtle hover:text-foreground",
                      )}
                    >
                      <Icon className="size-5 shrink-0" />
                      <span className="truncate">{item.label}</span>
                    </Link>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>
        <div className="border-t border-border p-3">
          <div className="flex items-center justify-between rounded-[var(--radius-md)] border border-border bg-background-elevated px-3 py-2">
            <div>
              <div className="label-caps">Theme</div>
              <div className="text-sm text-foreground">Light / Dark</div>
            </div>
            <ThemeToggle compact />
          </div>
        </div>
      </aside>
    </div>
  );
}

function getFallbackHeader(pathname: string): TopBarState {
  if (pathname.startsWith("/dashboard")) {
    return { title: "Dashboard", description: "Runs, records, and live activity." };
  }
  if (pathname.startsWith("/crawl")) {
    return { title: "Crawlers", description: "Configure, run, and review crawl jobs." };
  }
  if (pathname.startsWith("/runs/")) {
    return { title: "Run Details", description: "Review records, exports, and logs." };
  }
  if (pathname.startsWith("/runs")) {
    return { title: "Run History", description: "Review saved runs, outputs, and statuses." };
  }
  if (pathname.startsWith("/memory")) {
    return { title: "Site Memory", description: "Saved domain-level selectors and crawl memory." };
  }
  if (pathname.startsWith("/selectors")) {
    return { title: "CSS / XPath Selector", description: "LLM-assisted selector suggestion and validation." };
  }
  if (pathname.startsWith("/admin/users")) {
    return { title: "Users", description: "Accounts and roles." };
  }
  if (pathname.startsWith("/admin/llm")) {
    return { title: "LLM Config", description: "Providers, models, and budgets." };
  }
  if (pathname.startsWith("/jobs")) {
    return { title: "Jobs", description: "Live worker state." };
  }
  return { title: "CrawlFlow", description: "Internal crawling operations." };
}
