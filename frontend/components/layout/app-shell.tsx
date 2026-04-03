"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import type { Route } from "next";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import {
  LayoutDashboard,
  Zap,
  History,
  SlidersHorizontal,
  Users,
  Cpu,
  Activity,
} from "lucide-react";

import { api } from "../../lib/api";
import { cn } from "../../lib/utils";
import { ThemeToggle } from "../ui/theme-toggle";

const navItems = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/crawl", label: "Crawl Studio", icon: Zap },
  { href: "/runs", label: "Runs", icon: History },
  { href: "/selectors", label: "Selectors", icon: SlidersHorizontal },
  { href: "/admin/users", label: "Users", icon: Users },
  { href: "/admin/llm", label: "LLM", icon: Cpu },
  { href: "/jobs", label: "Jobs", icon: Activity },
] as const satisfies ReadonlyArray<{
  href: Route;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
}>;

export function AppShell({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const pathname = usePathname();
  const router = useRouter();
  const isAuthRoute = pathname === "/login" || pathname === "/register";
  const authQuery = useQuery({
    queryKey: ["me"],
    queryFn: api.me,
    enabled: !isAuthRoute,
    retry: false,
  });

  useEffect(() => {
    if (!isAuthRoute && authQuery.isError) {
      router.replace("/login");
    }
  }, [authQuery.isError, isAuthRoute, router]);

  if (isAuthRoute) {
    return (
      <div className="flex min-h-screen flex-col">
        <header className="flex h-12 shrink-0 items-center justify-between border-b border-border px-4">
          <div className="flex items-center gap-2.5">
            <div className="flex size-6 items-center justify-center rounded bg-brand shadow-sm">
              <Zap className="size-3.5 text-brand-foreground" />
            </div>
            <span className="text-[13px] font-semibold text-foreground">
              CrawlerAI
            </span>
          </div>
          <ThemeToggle compact />
        </header>
        <main className="flex flex-1 items-center justify-center p-4">
          <div className="w-full max-w-sm animate-scale-in">{children}</div>
        </main>
      </div>
    );
  }

  if (authQuery.isPending) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="animate-pulse-subtle text-[13px] text-muted">
          Loading...
        </div>
      </div>
    );
  }

  if (authQuery.isError) {
    return null;
  }

  return (
    <div className="flex min-h-screen">
      {/* Sidebar */}
      <aside className="hidden w-[248px] shrink-0 border-r border-border bg-[linear-gradient(180deg,#eef4ff,#e8f0fb)] lg:flex lg:flex-col">
        <div className="flex h-[52px] shrink-0 items-center gap-2.5 border-b border-border px-5">
          <div className="flex size-7 items-center justify-center rounded-md bg-brand shadow-sm">
            <Zap className="size-3.5 text-brand-foreground" />
          </div>
          <span className="text-[15px] font-semibold tracking-[-0.02em] text-foreground">
            CrawlerAI
          </span>
        </div>

        <nav className="flex-1 space-y-1 px-3 py-4">
          {navItems.map((item) => {
            const active = pathname.startsWith(item.href);
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "flex items-center gap-3 rounded-xl px-3.5 py-2.5 text-[13px] transition-all",
                  active
                    ? "bg-[linear-gradient(180deg,#dbeafe,#cfe0ff)] font-semibold text-foreground shadow-sm ring-1 ring-accent/15"
                    : "text-muted hover:bg-white/70 hover:text-foreground",
                )}
              >
                <Icon className="size-4 shrink-0" />
                {item.label}
              </Link>
            );
          })}
        </nav>

        <div className="border-t border-border px-4 py-3">
          <div className="flex items-center justify-between">
            <span className="text-[11px] text-muted">Theme</span>
            <ThemeToggle compact />
          </div>
        </div>
      </aside>

      {/* Mobile header */}
      <div className="flex flex-1 flex-col">
        <header className="flex h-12 shrink-0 items-center justify-between border-b border-border px-4 lg:hidden">
          <div className="flex items-center gap-2.5">
            <div className="flex size-6 items-center justify-center rounded bg-foreground">
              <Zap className="size-3.5 text-background" />
            </div>
            <span className="text-[13px] font-semibold text-foreground">
              CrawlerAI
            </span>
          </div>
          <div className="flex items-center gap-1">
            {navItems.map((item) => {
              const active = pathname.startsWith(item.href);
              const Icon = item.icon;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-label={item.label}
                  className={cn(
                    "inline-flex size-8 items-center justify-center rounded-md transition-all",
                    active
                      ? "bg-accent/10 text-foreground ring-1 ring-accent/15"
                      : "text-muted hover:text-foreground",
                  )}
                  title={item.label}
                >
                  <Icon className="size-4" />
                </Link>
              );
            })}
            <ThemeToggle compact />
          </div>
        </header>

        <main className="min-w-0 flex-1 p-4 lg:p-6">
          <div className="mx-auto max-w-[1200px] space-y-4">{children}</div>
        </main>
      </div>
    </div>
  );
}
