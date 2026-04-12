"use client";

import { LucideIcon } from "lucide-react";
import { Children, isValidElement, useEffectEvent, useLayoutEffect } from "react";
import type { ReactNode } from "react";

import { useTopBarStore } from "../layout/top-bar-context";
import { cn } from "../../lib/utils";
import { Card, Skeleton } from "./primitives";

function stableNodeSignature(value: ReactNode): string {
  if (value == null || typeof value === "boolean") {
    return "";
  }
  if (typeof value === "string" || typeof value === "number") {
    return String(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((entry) => stableNodeSignature(entry)).join("|")}]`;
  }
  if (isValidElement(value)) {
    const props = (value.props ?? {}) as Record<string, unknown>;
    const typeName =
      typeof value.type === "string"
        ? value.type
        : ("displayName" in value.type && typeof value.type.displayName === "string"
            ? value.type.displayName
            : value.type.name ?? "component");
    const propEntries = Object.entries(props)
      .filter(([key, propValue]) => key !== "children" && typeof propValue !== "function")
      .map(([key, propValue]) => `${key}:${stableNodeSignature(propValue as ReactNode)}`)
      .sort();
    return `<${typeName}${propEntries.length ? ` ${propEntries.join(",")}` : ""}>${stableNodeSignature(props.children as ReactNode)}</${typeName}>`;
  }
  return Children.toArray(value).map((entry) => stableNodeSignature(entry)).join("|");
}

/* ─── PageHeader ─────────────────────────────────────────────────────────── */
export function PageHeader({
  title,
  description,
  actions,
}: Readonly<{
  title: ReactNode;
  description?: string;
  actions?: ReactNode;
}>) {
  const { setHeader } = useTopBarStore();
  const signature = `${stableNodeSignature(title)}::${description ?? ""}::${stableNodeSignature(actions)}`;
  const syncHeader = useEffectEvent(() => {
    setHeader({ title, description, actions });
  });

  useLayoutEffect(() => {
    syncHeader();
  }, [signature]);
  useLayoutEffect(() => () => setHeader(null), [setHeader]);

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
  description?: ReactNode;
  icon?: LucideIcon;
  action?: ReactNode;
}>) {
  return (
    <div className="flex items-center justify-between gap-4">
      <div className="min-w-0 flex-1 space-y-2">
        <div className="flex items-center gap-2">
          {Icon && <Icon className="size-3.5 shrink-0 text-muted" />}
          <h2 className="text-section-title text-primary">
            {title}
          </h2>
        </div>
        {description ? (
          <div className="w-full text-caption text-muted">{description}</div>
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
  className,
  variant = "pill",
}: Readonly<{
  value: string;
  onChange: (value: string) => void;
  options: Array<{ value: string; label: string }>;
  compact?: boolean;
  className?: string;
  variant?: "pill" | "underline";
}>) {
  const activeIndex = options.findIndex((o) => o.value === value);
  const padX = compact ? "px-2.5" : "px-3.5";
  const pillStyle =
    variant === "pill" && options.length > 0 && activeIndex >= 0
      ? {
          width: `calc((100% - 4px) / ${options.length})`,
          left: `calc(2px + ((100% - 4px) / ${options.length}) * ${activeIndex})`,
          opacity: 1,
        }
      : {
          width: 0,
          left: 0,
          opacity: 0,
        };

  if (variant === "underline") {
    return (
      <div
        className={cn(
          "flex h-[var(--control-height)] items-stretch border-b border-[var(--divider)] bg-transparent p-0",
          className,
        )}
      >
        {options.map((option) => (
          <button
            key={option.value}
            type="button"
            aria-pressed={value === option.value}
            onClick={() => onChange(option.value)}
            className={cn(
              "relative -mb-[2px] inline-flex shrink-0 items-center justify-center whitespace-nowrap text-link-ui font-bold transition-all",
              padX,
              value === option.value
                ? "border-b-[3px] border-[var(--accent)] text-accent"
                : "border-b-[3px] border-transparent text-muted hover:text-primary hover:border-[var(--border)]",
            )}
          >
            {option.label}
          </button>
        ))}
      </div>
    );
  }

  return (
    <div
      className={cn(
        "segmented-root relative grid h-[var(--control-height)] items-stretch rounded-[var(--radius-md)] p-0.5",
        className,
      )}
      style={{ gridTemplateColumns: `repeat(${Math.max(options.length, 1)}, minmax(0, 1fr))` }}
    >
      <span
        aria-hidden="true"
        className="tab-indicator-active pointer-events-none absolute inset-y-0.5 rounded-[4px] bg-[var(--segmented-item-active-bg)] transition-[left,width] duration-200 ease-out"
        style={pillStyle}
      />      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={value === option.value}
          onClick={() => onChange(option.value)}
          className={cn(
            "relative z-10 inline-flex min-w-0 items-center justify-center self-stretch whitespace-nowrap rounded-[4px] py-0 text-meta font-bold transition-all duration-200",
            padX,
            value === option.value
              ? "text-primary"
              : "text-muted hover:text-primary",
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
      <div className="text-meta tabular-nums text-muted">{percent}%</div>
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
    <div className="grid min-h-32 place-items-center rounded-[var(--radius-lg)] border border-dashed border-[var(--divider)] bg-[var(--subtle-panel-bg)] text-center px-6 py-8">
      <div className="space-y-1">
        <p className="text-body-sm font-medium text-primary">{title}</p>
        <p className="text-caption text-muted">{description}</p>
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
    <div className="surface-panel stat-card space-y-2 p-4">
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
    <code className="rounded-[3px] bg-[var(--bg-elevated)] px-1.5 py-0.5 text-meta font-mono text-secondary">
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
      ? "alert-surface alert-danger"
      : tone === "warning"
        ? "alert-surface alert-warning"
        : "alert-surface bg-panel text-muted";
  return <div className={cn(toneClass)}>{message}</div>;
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
      <div className="surface-elevated flex flex-wrap items-center justify-between gap-3 px-4 py-3">
        <div className="min-w-0 flex-1">{header}</div>
        {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
      </div>
      <div className="space-y-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
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
    <div className="flex flex-wrap items-center justify-end gap-2">
      {chips.map((chip) => (
        <span
          key={chip.label}
          className="inline-flex items-center gap-1.5 rounded-full border border-[var(--subtle-panel-border)] bg-[var(--subtle-panel-bg)] px-2.5 py-1 text-caption text-muted"
        >
          <span className="text-data-strong text-foreground">{chip.label}:</span>
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
    <SurfacePanel className={cn("overflow-visible", className)}>
      <div className={cn("min-h-0 min-w-0 w-full", contentClassName)}>{children}</div>
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
