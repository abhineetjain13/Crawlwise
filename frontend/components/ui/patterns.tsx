"use client";

import { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { useLayoutEffect } from "react";

import { useTopBarStore } from "../layout/top-bar-context";
import { cn } from "../../lib/utils";
import { Card, Skeleton } from "./primitives";

/* ─── PageHeader ─────────────────────────────────────────────────────────── */
export function PageHeader({
  title,
  description,
  actions,
}: Readonly<{
  title: string;
  description?: string;
  actions?: ReactNode;
}>) {
  const { setHeader } = useTopBarStore();

  // useLayoutEffect fires before paint — no flash of fallback title
  useLayoutEffect(() => {
    setHeader({ title, description, actions });
    return () => setHeader(null);
  }, [actions, description, setHeader, title]);

  return null;
}

/* ─── SectionHeader ──────────────────────────────────────────────────────── */
export function SectionHeader({
  title,
  description,
  icon: Icon,
  action,
}: Readonly<{
  title: string;
  description?: string;
  icon?: LucideIcon;
  action?: ReactNode;
}>) {
  return (
    <div className="flex items-center justify-between gap-4">
      <div className="min-w-0 space-y-0.5">
        <div className="flex items-center gap-2">
          {Icon && <Icon className="size-3.5 shrink-0 text-[var(--accent)]" />}
          <h2 className="text-[14px] font-semibold tracking-[-0.015em] text-[var(--text-primary)]">
            {title}
          </h2>
        </div>
        {description ? (
          <p className="text-[12px] text-[var(--text-muted)]">{description}</p>
        ) : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}

/* ─── TabBar  — sliding CSS indicator, no flash ──────────────────────────── */
export function TabBar({
  value,
  onChange,
  options,
}: Readonly<{
  value: string;
  onChange: (value: string) => void;
  options: Array<{ value: string; label: string }>;
}>) {
  const activeIndex = options.findIndex((o) => o.value === value);
  const pct = activeIndex >= 0 ? (activeIndex / options.length) * 100 : 0;

  return (
    <div
      className="relative inline-flex h-[30px] items-center rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-elevated)] p-0.5"
    >
      {/* Sliding pill */}
      <span
        aria-hidden="true"
        className="pointer-events-none absolute inset-y-0.5 rounded-[4px] bg-[var(--bg-panel)] shadow-[var(--shadow-xs)] transition-transform duration-150 ease-out border border-[var(--border)]"
        style={{
          width: `calc(100% / ${options.length})`,
          transform: `translateX(${pct * options.length}%)`,
          left: 0,
        }}
      />
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={value === option.value}
          onClick={() => onChange(option.value)}
          className={cn(
            "relative z-10 flex-1 whitespace-nowrap rounded-[4px] px-3 py-1 text-[12px] font-medium transition-colors duration-100",
            value === option.value
              ? "text-[var(--text-primary)]"
              : "text-[var(--text-muted)] hover:text-[var(--text-secondary)]",
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

/* ─── ProgressBar ────────────────────────────────────────────────────────── */
export function ProgressBar({ percent }: Readonly<{ percent: number }>) {
  return (
    <div className="space-y-1">
      <div className="h-1 rounded-full bg-[var(--border)] overflow-hidden">
        <div
          className={cn(
            "h-full rounded-full bg-[var(--accent)] transition-[width] duration-500",
            percent >= 100 && "bg-[var(--success)]",
          )}
          style={{ width: `${Math.min(percent, 100)}%` }}
        />
      </div>
      <div className="text-[11px] text-[var(--text-muted)] tabular-nums">{percent}%</div>
    </div>
  );
}

/* ─── MetricGrid ─────────────────────────────────────────────────────────── */
export function MetricGrid({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <div className="stagger-children grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {children}
    </div>
  );
}

/* ─── EmptyPanel ─────────────────────────────────────────────────────────── */
export function EmptyPanel({
  title,
  description,
}: Readonly<{ title: string; description: string }>) {
  return (
    <div className="grid min-h-32 place-items-center rounded-[var(--radius-lg)] border border-dashed border-[var(--border)] text-center px-6 py-8">
      <div className="space-y-1">
        <p className="text-[13px] font-medium text-[var(--text-primary)]">{title}</p>
        <p className="text-[12px] text-[var(--text-muted)]">{description}</p>
      </div>
    </div>
  );
}

/* ─── JsonPanel ──────────────────────────────────────────────────────────── */
export function JsonPanel({
  title,
  subtitle,
  children,
  className,
}: Readonly<{
  title: string;
  subtitle?: string;
  children: ReactNode;
  className?: string;
}>) {
  return (
    <Card className={cn("space-y-4", className)}>
      <SectionHeader title={title} description={subtitle} />
      {children}
    </Card>
  );
}

/* ─── SkeletonRows ───────────────────────────────────────────────────────── */
export function SkeletonRows({
  count = 5,
  className,
}: Readonly<{ count?: number; className?: string }>) {
  return (
    <div className={cn("space-y-2", className)}>
      {Array.from({ length: count }, (_, i) => (
        <Skeleton key={i} className="h-8 w-full" />
      ))}
    </div>
  );
}

/* ─── MetricSkeleton ─────────────────────────────────────────────────────── */
export function MetricSkeleton() {
  return (
    <div className="stat-card space-y-2">
      <Skeleton className="h-3 w-20" />
      <Skeleton className="h-9 w-28" />
      <Skeleton className="h-3 w-16" />
    </div>
  );
}

/* ─── Divider ────────────────────────────────────────────────────────────── */
export function Divider({ className }: Readonly<{ className?: string }>) {
  return <div className={cn("h-px bg-[var(--border)]", className)} />;
}

/* ─── InlineCode ─────────────────────────────────────────────────────────── */
export function InlineCode({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <code className="rounded-[3px] bg-[var(--bg-elevated)] px-1.5 py-0.5 font-mono text-[11px] text-[var(--text-secondary)]">
      {children}
    </code>
  );
}
