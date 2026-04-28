"use client";

import { Award, CheckCircle2, Clock, LucideIcon } from "lucide-react";
import { Children, isValidElement, useEffectEvent, useLayoutEffect, useMemo } from "react";
import type { ReactNode } from "react";

import { useTopBarStore } from "../layout/top-bar-context";
import { cn } from "../../lib/utils";
import { InlineAlert } from "./alert";
import { Card } from "./card";
import { Skeleton } from "./primitives";

export { InlineAlert } from "./alert";

function stableNodeSignature(value: ReactNode): string {
  if (value == null) {
    return "";
  }
  if (typeof value === "boolean") {
    return value ? "true" : "false";
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
  const signature = useMemo(
    () => `${stableNodeSignature(title)}::${description ?? ""}::${stableNodeSignature(actions)}`,
    [title, description, actions],
  );
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
          <h2 className="m-0 text-[var(--text-md)] font-medium leading-[var(--leading-tight)] text-foreground">{title}</h2>
        </div>
        {description ? (
          <div className="w-full text-sm leading-[var(--leading-relaxed)] text-secondary">{description}</div>
        ) : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}

/* ─── TabBar — sliding CSS indicator, no flash ──────────────────────────── */
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
  const padX = compact ? "px-2.5" : "px-3.5";

  if (variant === "underline") {
    return (
      <div
        className={cn(
          "flex h-[var(--control-height)] items-stretch bg-transparent p-0 -mb-px",
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
              "relative -mb-px inline-flex shrink-0 items-center justify-center whitespace-nowrap text-sm leading-[var(--leading-snug)] font-medium transition-all",
              padX,
              value === option.value
                ? "border-b-2 border-accent text-accent"
                : "border-b-2 border-transparent text-secondary hover:text-foreground hover:border-border",
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
        "segmented-root inline-flex h-[var(--control-height)] items-stretch rounded-[var(--radius-md)] p-0.5",
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
            "relative z-10 inline-flex shrink-0 items-center justify-center whitespace-nowrap rounded-[4px] py-0 text-sm leading-[var(--leading-snug)] font-medium transition-all duration-200",
            padX,
            value === option.value
              ? "ui-on-accent-surface bg-accent shadow-[0_1px_2px_rgba(15,23,42,0.12)]"
              : "text-secondary hover:text-foreground",
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
      <div className="h-1 rounded-full bg-border overflow-hidden">
        <div
          className={cn(
            "h-full rounded-full bg-accent transition-[width] duration-500",
            percent >= 100 && "bg-success",
          )}
          style={{ width: `${Math.min(percent, 100)}%` }}
        />
      </div>
      <div className="text-sm leading-[var(--leading-normal)] tabular-nums text-muted">{percent}%</div>
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
    <div className="grid min-h-32 place-items-center rounded-[var(--radius-xl)] border border-dashed border-border-strong bg-subtle-panel px-6 py-8 text-center">
      <div className="space-y-1">
        <p className="text-sm font-medium leading-[var(--leading-relaxed)] text-foreground">{title}</p>
        <p className="text-sm leading-[var(--leading-normal)] text-muted">{description}</p>
      </div>
    </div>
  );
}

/* ─── SectionCard ────────────────────────────────────────────────────────── */
export function SectionCard({
  title,
  description,
  action,
  children,
  className,
}: Readonly<{
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}>) {
  return <Card className={cn("section-card", className)}><SectionHeader title={title} description={description} action={action} />{children}</Card>;
}
export function SurfaceSection({
  title,
  description,
  icon: Icon,
  action,
  children,
  className,
  bodyClassName,
}: Readonly<{
  title: string;
  description?: ReactNode;
  icon?: LucideIcon;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}>) {
  return <SurfacePanel className={className}><div className="border-b border-divider px-4 py-3"><SectionHeader title={title} description={description} icon={Icon} action={action} /></div><div className={cn("p-4", bodyClassName)}>{children}</div></SurfacePanel>;
}

/* ─── MutedPanelMessage ──────────────────────────────────────────────────── */
export function MutedPanelMessage({
  title,
  description,
  className,
}: Readonly<{
  title: string;
  description: string;
  className?: string;
}>) {
  return <div className={cn("surface-muted rounded-lg border-dashed px-4 py-6 text-sm leading-[var(--leading-relaxed)] text-muted", className)}><p className="m-0 font-medium text-foreground">{title}</p><p className="m-0 mt-1.5">{description}</p></div>;
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
    <div className="relative space-y-2 overflow-hidden rounded-[var(--radius-xl)] border border-border bg-panel p-4 shadow-card">
      <Skeleton className="h-3 w-20" />
      <Skeleton className="h-9 w-28" />
      <Skeleton className="h-3 w-16" />
    </div>
  );
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
    <div className="page-stack">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius-xl)] border border-border bg-panel px-4 py-3 shadow-card">
        <div className="min-w-0 flex-1">{header}</div>
        {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
      </div>
      <div className="page-stack">
        <div className="flex flex-wrap items-stretch justify-between gap-3 border-b border-divider">
          <div className="flex items-end">{tabs}</div>
          {summary ? <div className="py-2 self-center">{summary}</div> : null}
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
  const normalizedVerdict = verdict.toLowerCase();
  const normalizedQuality = quality.toLowerCase();

  // Themed tones and backgrounds matching the requested high-density aesthetic
  const verdictTone = normalizedVerdict === "success" ? "text-[#107c41]" : normalizedVerdict === "partial" ? "text-[#9a6b00]" : "text-[#d93025]";
  const verdictBg = normalizedVerdict === "success" ? "bg-[#e6f4ea]" : normalizedVerdict === "partial" ? "bg-[#fff4e5]" : "bg-[#fce8e6]";
  const verdictBar = normalizedVerdict === "success" ? "bg-[#107c41]" : normalizedVerdict === "partial" ? "bg-[#f9ab00]" : "bg-[#d93025]";

  const qualityTone = normalizedQuality === "high" ? "text-[#107c41]" : normalizedQuality === "medium" ? "text-[#9a6b00]" : normalizedQuality === "low" ? "text-[#d93025]" : "text-[#5f6368]";
  const qualityBg = normalizedQuality === "high" ? "bg-[#e6f4ea]" : normalizedQuality === "medium" ? "bg-[#fff4e5]" : normalizedQuality === "low" ? "bg-[#fce8e6]" : "bg-[#f1f3f4]";
  const qualityBar = normalizedQuality === "high" ? "bg-[#107c41]" : normalizedQuality === "medium" ? "bg-[#f9ab00]" : normalizedQuality === "low" ? "bg-[#d93025]" : "bg-[#9aa0a6]";

  const chips = [
    { label: "TIME", value: duration, icon: Clock, tone: "text-[#005a9e]", bg: "bg-[#eff6fc]", bar: "bg-[#005a9e]" },
    { label: "VERDICT", value: verdict, icon: CheckCircle2, tone: verdictTone, bg: verdictBg, bar: verdictBar },
    { label: "QUALITY", value: quality, icon: Award, tone: qualityTone, bg: qualityBg, bar: qualityBar },
  ];

  return (
    <div className="flex flex-wrap items-center justify-end gap-2.5">
      {chips.map((chip) => {
        const Icon = chip.icon;
        return (
          <div
            key={chip.label}
            className={cn(
              "inline-flex items-center gap-2.5 rounded-xl px-3 py-1.5 transition-all hover:brightness-[0.98]",
              chip.bg,
            )}
          >
            <div className={cn("h-4 w-[3.5px] shrink-0 rounded-full", chip.bar)} />
            <div className="flex items-center gap-1.5">
              <Icon className={cn("size-3.5 shrink-0 opacity-90", chip.tone)} aria-hidden="true" />
              <div className="flex items-baseline gap-2">
                <span className="text-[10px] font-bold uppercase tracking-[0.05em] text-[#5f6368]">{chip.label}</span>
                <span className={cn("text-sm font-semibold tabular-nums tracking-tight", chip.tone)}>
                  {chip.value}
                </span>
              </div>
            </div>
          </div>
        );
      })}
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

/* ─── NavList — selectable sidebar list ─────────────────────────────────── */
export function NavList<T>({
  items,
  selectedKey,
  onSelect,
  getKey,
  renderLabel,
  renderMeta,
  renderBadge,
  className,
}: Readonly<{
  items: ReadonlyArray<T>;
  selectedKey: string;
  onSelect: (key: string) => void;
  getKey: (item: T) => string;
  renderLabel: (item: T) => ReactNode;
  renderMeta?: (item: T) => ReactNode;
  renderBadge?: (item: T) => ReactNode;
  className?: string;
}>) {
  return (
    <div className={cn("space-y-2", className)}>
      {items.map((item) => {
        const key = getKey(item);
        const isActive = key === selectedKey;
        return (
          <button
            key={key}
            type="button"
            aria-pressed={isActive}
            onClick={() => onSelect(key)}
            className={cn(
              "w-full rounded-[var(--radius-xl)] border px-3 py-3 text-left transition-colors",
              isActive
                ? "border-accent bg-subtle-panel shadow-card"
                : "border-divider bg-background hover:bg-background-elevated",
            )}
          >
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <div className="truncate text-[var(--text-sm)] font-medium leading-[var(--leading-snug)] text-foreground">{renderLabel(item)}</div>
                {renderMeta ? <div className="mt-2 flex flex-wrap gap-2 text-[var(--text-xs)] leading-[var(--leading-snug)] text-muted">{renderMeta(item)}</div> : null}
              </div>
              {renderBadge ? renderBadge(item) : null}
            </div>
          </button>
        );
      })}
    </div>
  );
}

/* ─── DetailRow — bordered content row for lists ────────────────────────── */
export function DetailRow({
  children,
  className,
}: Readonly<{ children: ReactNode; className?: string }>) {
  return (
    <div className={cn("rounded-lg border border-divider bg-background px-3 py-3", className)}>
      {children}
    </div>
  );
}

/* ─── KVTile — compact key-value mini-stat ──────────────────────────────── */
export function KVTile({
  label,
  value,
  className,
}: Readonly<{ label: string; value: ReactNode; className?: string }>) {
  return (
    <div className={cn("rounded-[var(--radius-md)] bg-background-elevated px-2.5 py-2", className)}>
      <div className="type-label">{label}</div>
      <div className="pt-1 text-sm font-medium text-foreground">{value}</div>
    </div>
  );
}
