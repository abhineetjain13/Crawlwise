"use client";

import { LucideIcon } from"lucide-react";
import { Children, isValidElement, useEffectEvent, useLayoutEffect, useMemo } from"react";
import type { ReactNode } from"react";

import { useTopBarStore } from"../layout/top-bar-context";
import { cn } from"../../lib/utils";
import { Card, Skeleton } from"./primitives";

function stableNodeSignature(value: ReactNode): string {
 if (value == null) {
 return"";
 }
 if (typeof value === "boolean") {
 return value ? "true" : "false";
 }
 if (typeof value ==="string"|| typeof value ==="number") {
 return String(value);
 }
 if (Array.isArray(value)) {
 return `[${value.map((entry) => stableNodeSignature(entry)).join("|")}]`;
 }
 if (isValidElement(value)) {
 const props = (value.props ?? {}) as Record<string, unknown>;
 const typeName =
 typeof value.type ==="string"
 ? value.type
 : ("displayName"in value.type && typeof value.type.displayName ==="string"
 ? value.type.displayName
 : value.type.name ??"component");
 const propEntries = Object.entries(props)
 .filter(([key, propValue]) => key !=="children"&& typeof propValue !=="function")
 .map(([key, propValue]) => `${key}:${stableNodeSignature(propValue as ReactNode)}`)
 .sort();
 return `<${typeName}${propEntries.length ? ` ${propEntries.join(",")}` :""}>${stableNodeSignature(props.children as ReactNode)}</${typeName}>`;
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
 () => `${stableNodeSignature(title)}::${description ??""}::${stableNodeSignature(actions)}`,
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
 {Icon && <Icon className="size-3.5 shrink-0 text-[var(--text-muted)]"/>}
 <h2 className="panel-title">{title}</h2>
 </div>
 {description ? (
 <div className="panel-subtitle w-full"style={{ maxWidth:"none"}}>{description}</div>
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
 variant ="pill",
}: Readonly<{
 value: string;
 onChange: (value: string) => void;
 options: Array<{ value: string; label: string }>;
 compact?: boolean;
 className?: string;
 variant?:"pill"|"underline";
}>) {
 const padX = compact ?"px-2.5":"px-3.5";

 if (variant ==="underline") {
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
"relative -mb-[2px] inline-flex shrink-0 items-center justify-center whitespace-nowrap text-sm leading-[1.35] font-semibold transition-all",
 padX,
 value === option.value
 ?"border-b-[3px] border-[var(--accent)] text-accent"
 :"border-b-[3px] border-transparent text-secondary hover:text-primary hover:border-[var(--border)]",
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
"relative z-10 inline-flex shrink-0 items-center justify-center whitespace-nowrap rounded-[4px] py-0 text-sm leading-[1.35] font-semibold tracking-normal transition-all duration-200",
 padX,
 value === option.value
 ?"bg-[var(--accent)] text-[var(--tab-active-fg)] shadow-[0_1px_2px_rgba(15,23,42,0.12)]"
 :"text-secondary hover:text-primary",
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
 percent >= 100 &&"bg-[var(--success)]",
 )}
 style={{ width: `${Math.min(percent, 100)}%` }}
 />
 </div>
 <div className="text-sm leading-[1.45] tabular-nums text-muted">{percent}%</div>
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
 <div className="empty-panel">
 <div className="space-y-1">
 <p className="text-sm font-medium leading-[1.55] text-[var(--text-primary)]">{title}</p>
 <p className="text-sm leading-[1.45] text-[var(--text-muted)]">{description}</p>
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
 return <SurfacePanel className={className}><div className="border-b border-[var(--divider)] px-4 py-3"><SectionHeader title={title} description={description} icon={Icon} action={action} /></div><div className={cn("p-4", bodyClassName)}>{children}</div></SurfacePanel>;
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
 return <div className={cn("surface-muted rounded-lg border-dashed px-4 py-6 text-sm leading-[1.55] text-muted", className)}><p className="m-0 font-medium text-[var(--text-primary)]">{title}</p><p className="m-0 mt-1.5">{description}</p></div>;
}

/* ─── SkeletonRows ───────────────────────────────────────────────────────── */
export function SkeletonRows({
 count = 5,
 className,
}: Readonly<{ count?: number; className?: string }>) {
 return (
 <div className={cn("space-y-2", className)}>
 {Array.from({ length: count }, (_, i) => (
 <Skeleton key={i} className="h-8 w-full"/>
 ))}
 </div>
 );
}

/* ─── MetricSkeleton ─────────────────────────────────────────────────────── */
export function MetricSkeleton() {
 return (
 <div className="metric-card space-y-2">
 <Skeleton className="h-3 w-20"/>
 <Skeleton className="h-9 w-28"/>
 <Skeleton className="h-3 w-16"/>
 </div>
 );
}

/* ─── InlineAlert ────────────────────────────────────────────────────────── */
export function InlineAlert({
 message,
 tone ="danger",
 className,
}: Readonly<{
 message: ReactNode;
 tone?:"danger"|"warning"|"neutral";
 className?: string;
}>) {
 if (!message) return null;
 const toneClass =
 tone ==="danger"
 ?"alert-surface alert-danger"
 : tone ==="warning"
 ?"alert-surface alert-warning"
 :"alert-surface alert-neutral";
 return <div className={cn(toneClass, className)}>{message}</div>;
}

/* ─── StatusDot ──────────────────────────────────────────────────────────── */
export function StatusDot({
 tone ="neutral",
 className,
}: Readonly<{
 tone?:"neutral"|"success"|"warning"|"danger"|"accent"|"info";
 className?: string;
}>) {
 const toneClass =
 tone ==="success"
 ?"bg-success"
 : tone ==="warning"
 ?"bg-warning"
 : tone ==="danger"
 ?"bg-danger"
 : tone ==="accent"
 ?"bg-accent"
 : tone ==="info"
 ?"bg-info"
 :"bg-muted";
 return <span className={cn("inline-block size-1.5 shrink-0 rounded-full", toneClass, className)} aria-hidden="true"/>;
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
 <div className="panel panel-raised flex flex-wrap items-center justify-between gap-3 px-4 py-3">
 <div className="min-w-0 flex-1">{header}</div>
 {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
 </div>
 <div className="page-stack">
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
 { label:"Time", value: duration },
 { label:"Verdict", value: verdict },
 { label:"Quality", value: quality },
 ];
 return (
 <div className="flex flex-wrap items-center justify-end gap-2">
 {chips.map((chip) => (
 <span
 key={chip.label}
 className="inline-flex items-center gap-1.5 rounded-full border border-[var(--subtle-panel-border)] bg-[var(--subtle-panel-bg)] px-2.5 py-1 text-sm leading-[1.45] text-muted"
 >
 <span className="text-sm font-medium leading-[1.45] text-foreground">{chip.label}:</span>
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
 ? "border-[var(--accent)] bg-[var(--subtle-panel-bg)] shadow-card"
 : "border-[var(--divider)] bg-background hover:bg-background-elevated",
 )}
 > <div className="flex items-center justify-between gap-3">
 <div className="min-w-0">
 <div className="truncate text-sm font-semibold text-foreground">{renderLabel(item)}</div>
 {renderMeta ? <div className="mt-2 flex flex-wrap gap-2 text-xs text-muted">{renderMeta(item)}</div> : null}
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
 <div className={cn("rounded-lg border border-[var(--divider)] bg-background px-3 py-3", className)}>
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
 <div className="text-[11px] uppercase tracking-[0.08em] text-muted">{label}</div>
 <div className="pt-1 text-sm font-medium text-foreground">{value}</div>
 </div>
 );
}
