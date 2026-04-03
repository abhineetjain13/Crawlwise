"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import type { Route } from "next";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";

import { api } from "../../lib/api";
import { cn } from "../../lib/utils";
import { ThemeToggle } from "../ui/theme-toggle";

const navItems = [
  { href: "/dashboard", label: "Dashboard", short: "Home" },
  { href: "/crawl", label: "Crawl Studio", short: "Crawl" },
  { href: "/runs", label: "Runs", short: "Runs" },
  { href: "/selectors", label: "Selectors", short: "Selectors" },
  { href: "/admin/users", label: "Users", short: "Users" },
  { href: "/admin/llm", label: "LLM", short: "LLM" },
  { href: "/jobs", label: "Jobs", short: "Jobs" },
] as const satisfies ReadonlyArray<{ href: Route; label: string; short: string }>;

export function AppShell({ children }: Readonly<{ children: React.ReactNode }>) {
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
      <div className="min-h-screen px-3 py-3 sm:px-4">
        <div className="mx-auto flex min-h-[calc(100vh-1.5rem)] max-w-5xl flex-col gap-4">
          <div className="flex items-center justify-between rounded-xl border border-border/70 bg-background-elevated px-4 py-3 shadow-card backdrop-blur">
            <div className="flex items-center gap-3">
              <div className="rounded-full bg-brand/12 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.24em] text-brand">
                CrawlerAI
              </div>
              <span className="text-sm text-muted">Sign in</span>
            </div>
            <ThemeToggle />
          </div>
          <div className="grid flex-1 items-center gap-4 lg:grid-cols-[1fr_minmax(0,28rem)]">
            <div className="space-y-3">
              <h2 className="max-w-lg text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">
                Review, map, and promote fields.
              </h2>
            </div>
            <div>{children}</div>
          </div>
        </div>
      </div>
    );
  }

  if (authQuery.isPending) {
    return (
      <div className="min-h-screen px-2.5 py-2.5 sm:px-3 sm:py-3 lg:px-4">
        <div className="mx-auto grid max-w-[1500px] gap-3 xl:grid-cols-[200px_minmax(0,1fr)]">
          <aside className="rounded-xl border border-border/70 bg-background-elevated p-3 shadow-card backdrop-blur xl:sticky xl:top-3 xl:h-[calc(100vh-1.5rem)]" />
          <main className="rounded-xl border border-border/70 bg-panel/80 p-5 text-sm text-muted shadow-card backdrop-blur">
            Checking session...
          </main>
        </div>
      </div>
    );
  }

  if (authQuery.isError) {
    return null;
  }

  return (
    <div className="min-h-screen px-2.5 py-2.5 sm:px-3 sm:py-3 lg:px-4">
      <div className="mx-auto grid max-w-[1500px] gap-3 xl:grid-cols-[200px_minmax(0,1fr)]">
        <aside className="rounded-xl border border-border/70 bg-background-elevated p-3 shadow-card backdrop-blur xl:sticky xl:top-3 xl:h-[calc(100vh-1.5rem)]">
          <div className="flex h-full flex-col gap-4">
            <div className="space-y-2">
              <div className="inline-flex rounded-full bg-brand/12 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.24em] text-brand">
                CrawlerAI
              </div>
            </div>

            <nav className="grid gap-1">
              {navItems.map((item) => {
                const active = pathname.startsWith(item.href);
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={cn(
                      "rounded-lg px-3 py-2 text-sm font-medium transition",
                      active
                        ? "bg-brand text-white shadow-sm"
                        : "text-foreground hover:bg-panel-strong",
                    )}
                  >
                    <span className="xl:hidden">{item.short}</span>
                    <span className="hidden xl:inline">{item.label}</span>
                  </Link>
                );
              })}
            </nav>

            <div className="mt-auto flex items-center justify-between rounded-lg border border-border bg-panel/80 px-3 py-2">
              <div>
                <p className="text-xs font-medium text-foreground">Theme</p>
                <p className="text-[11px] text-muted">Light / Dark</p>
              </div>
              <ThemeToggle />
            </div>
          </div>
        </aside>

        <main className="min-w-0 space-y-3">{children}</main>
      </div>
    </div>
  );
}
