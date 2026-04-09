"use client";

import { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { useCallback, useLayoutEffect, useRef, useState } from "react";

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
          <h2 className="text-body font-semibold tracking-[-0.015em] text-[var(--text-primary)]">
            {title}
          </h2>
        </div>
        {description ? (
          <p className="text-caption text-[var(--text-muted)]">{description}</p>
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
  compact = false,
}: Readonly<{
  value: string;
  onChange: (value: string) => void;
  options: Array<{ value: string; label: string }>;
  compact?: boolean;
}>) {
  const containerRef = useRef<HTMLDivElement>(null);
  const buttonRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const [pill, setPill] = useState({ left: 0, width: 0 });

  const activeIndex = options.findIndex((o) => o.value === value);
  const padX = compact ? "px-2.5" : "px-3";

  const syncPill = useCallback(() => {
    const container = containerRef.current;
    if (activeIndex < 0 || !container) {
      setPill({ left: 0, width: 0 });
      return;
    }
    const btn = buttonRefs.current[activeIndex];
    if (!btn) {
      return;
    }
    const cRect = container.getBoundingClientRect();
    const bRect = btn.getBoundingClientRect();
    setPill({
      left: bRect.left - cRect.left,
      width: bRect.width,
    });
  }, [activeIndex]);

  useLayoutEffect(() => {
    syncPill();
  }, [syncPill, value, options]);

  useLayoutEffect(() => {
    const container = containerRef.current;
    if (!container || typeof ResizeObserver === "undefined") {
      return;
    }
    const ro = new ResizeObserver(() => syncPill());
    ro.observe(container);
    window.addEventListener("resize", syncPill);
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", syncPill);
    };
  }, [syncPill]);

  return (
    <div
      ref={containerRef}
      className="relative inline-flex h-8 items-stretch rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-elevated)] p-0.5"
    >
      <span
        aria-hidden="true"
        className="pointer-events-none absolute inset-y-0.5 rounded-[4px] border border-[var(--accent)] bg-[var(--accent)] shadow-[var(--shadow-xs)] transition-[left,width] duration-150 ease-out motion-reduce:transition-none"
        style={{
          width: pill.width > 0 ? pill.width : 0,
          left: pill.left,
          opacity: activeIndex >= 0 && pill.width > 0 ? 1 : 0,
        }}
      />
      {options.map((option, index) => (
        <button
          key={option.value}
          ref={(el) => {
            buttonRefs.current[index] = el;
          }}
          type="button"
          aria-pressed={value === option.value}
          onClick={() => onChange(option.value)}
          className={cn(
            "relative z-10 inline-flex shrink-0 items-center justify-center self-stretch whitespace-nowrap rounded-[4px] py-0 text-caption font-medium leading-none transition-colors duration-100 motion-reduce:transition-none",
            padX,
            value === option.value
              ? "text-[var(--accent-foreground)]"
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
      <div className="text-meta text-[var(--text-muted)] tabular-nums">{percent}%</div>
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
        <p className="text-body-sm font-medium text-[var(--text-primary)]">{title}</p>
        <p className="text-caption text-[var(--text-muted)]">{description}</p>
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
    <code className="rounded-[3px] bg-[var(--bg-elevated)] px-1.5 py-0.5 font-mono text-meta text-[var(--text-secondary)]">
      {children}
    </code>
  );
}

/* ─── InlineAlert ────────────────────────────────────────────────────────── */
export function InlineAlert({
  message,
  tone = "danger",
}: Readonly<{
  message: ReactNode;
  tone?: "danger" | "warning" | "neutral";
}>) {
  if (!message) return null;
  const toneClass =
    tone === "danger"
      ? "border-danger/20 bg-danger/10 text-danger"
      : tone === "warning"
        ? "border-warning/30 bg-warning/10 text-warning"
        : "border-border bg-panel text-muted";
  return <div className={cn("rounded-md border px-3 py-2 text-sm", toneClass)}>{message}</div>;
}

/* ─── StatusDot ──────────────────────────────────────────────────────────── */
export function StatusDot({
  tone = "neutral",
  className,
}: Readonly<{
  tone?: "neutral" | "success" | "warning" | "danger" | "accent" | "info";
  className?: string;
}>) {
  const toneClass =
    tone === "success"
      ? "bg-success"
      : tone === "warning"
        ? "bg-warning"
        : tone === "danger"
          ? "bg-danger"
          : tone === "accent"
            ? "bg-accent"
            : tone === "info"
              ? "bg-info"
              : "bg-muted";
  return <span className={cn("inline-block size-1.5 shrink-0 rounded-full", toneClass, className)} aria-hidden="true" />;
}

/* ─── SurfacePanel ───────────────────────────────────────────────────────── */
export function SurfacePanel({
  children,
  className,
}: Readonly<{
  children: ReactNode;
  className?: string;
}>) {
  return <Card className={cn("p-0", className)}>{children}</Card>;
}

/* ─── RunWorkspaceShell ──────────────────────────────────────────────────── */
export function RunWorkspaceShell({
  header,
  actions,
  tabs,
  summary,
  content,
}: Readonly<{
  header: ReactNode;
  actions?: ReactNode;
  tabs: ReactNode;
  summary?: ReactNode;
  content: ReactNode;
}>) {
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius-lg)] border border-border bg-[var(--bg-elevated)] px-4 py-3">
        <div className="min-w-0 flex-1">{header}</div>
        {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
      </div>
      <div className="space-y-4">
        <div className="flex flex-wrap items-end justify-between gap-3 border-b border-border">
          {tabs}
          {summary ? <div className="pb-2">{summary}</div> : null}
        </div>
        {content}
      </div>
    </div>
  );
}

/* ─── RunSummaryChips ────────────────────────────────────────────────────── */
export function RunSummaryChips({
  duration,
  verdict,
  quality,
}: Readonly<{
  duration: string;
  verdict: string;
  quality: string;
}>) {
  const chips = [
    { label: "Time", value: duration },
    { label: "Verdict", value: verdict },
    { label: "Quality", value: quality },
  ];
  return (
    <div className="flex flex-wrap items-center justify-end gap-2 text-xs">
      {chips.map((chip) => (
        <span
          key={chip.label}
          className="inline-flex items-center gap-1.5 rounded-full border border-border bg-panel px-2.5 py-1 text-muted"
        >
          <span className="font-semibold text-foreground">{chip.label}:</span>
          <span>{chip.value}</span>
        </span>
      ))}
    </div>
  );
}

/* ─── TableSurface ───────────────────────────────────────────────────────── */
export function TableSurface({
  children,
  className,
  contentClassName,
}: Readonly<{
  children: ReactNode;
  className?: string;
  contentClassName?: string;
}>) {
  return (
    <SurfacePanel className={cn("overflow-hidden", className)}>
      <div className={cn("overflow-auto", contentClassName)}>{children}</div>
    </SurfacePanel>
  );
}

/* ─── DataRegion states ──────────────────────────────────────────────────── */
export function DataRegionLoading({
  count = 6,
  className,
}: Readonly<{ count?: number; className?: string }>) {
  return (
    <div className={cn("p-4", className)}>
      <SkeletonRows count={count} />
    </div>
  );
}

export function DataRegionEmpty({
  title,
  description,
  className,
}: Readonly<{ title: string; description: string; className?: string }>) {
  return (
    <div className={cn("p-4", className)}>
      <EmptyPanel title={title} description={description} />
    </div>
  );
}

export function DataRegionError({
  message,
  className,
}: Readonly<{ message: string; className?: string }>) {
  return (
    <div className={cn("p-4", className)}>
      <InlineAlert message={message} />
    </div>
  );
}
