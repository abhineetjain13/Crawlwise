"use client";

import * as React from "react";
import { useId } from "react";
import { createPortal } from "react-dom";
import type { ComponentPropsWithoutRef, ReactNode } from "react";
import { cn } from "../../lib/utils";

function colorWithAlpha(color: string | undefined, alphaPercent: number) {
 const normalized = String(color ??"").trim();
 if (!normalized) {
 return"var(--accent-subtle)";
 }
 return `color-mix(in srgb, ${normalized} ${alphaPercent}%, transparent)`;
}

function sanitizeIdSegment(value: string) {
 const normalized = String(value).trim().toLowerCase().replace(/[^a-z0-9_-]+/g,"-");
 return normalized.replace(/^-+|-+$/g,"") ||"option";
}

/* ─── Card ───────────────────────────────────────────────────────────────── */
export function Card({
 children,
 className,
 animate = false,
 ...props
}: Readonly<ComponentPropsWithoutRef<"section"> & { children: ReactNode; animate?: boolean }>) {
 return (
 <section
 {...props}
 className={cn(
"panel panel-raised relative p-5",
 animate &&"animate-fade-in",
 className,
 )}
 >
 {children}
 </section>
 );
}

/* ─── Title / Subtitle ───────────────────────────────────────────────────── */
export function Title({
 children,
 kicker,
 className,
}: Readonly<{ children: ReactNode; kicker?: string; className?: string }>) {
 return (
 <div className={cn("space-y-1", className)}>
 {kicker ? (
 <p className="page-kicker">
 {kicker}
 </p>
 ) : null}
 <h1 className="page-title">
 {children}
 </h1>
 </div>
 );
}

export function Subtitle({ children }: Readonly<{ children: ReactNode }>) {
 return <p className="page-subtitle max-w-2xl">{children}</p>;
}

/* ─── Field ──────────────────────────────────────────────────────────────── */
export function Field({
 label,
 hint,
 children,
}: Readonly<{ label: string; hint?: string; children: ReactNode }>) {
 return (
 <label className="grid gap-1.5">
 <span className="field-label">{label}</span>
 {children}
 {hint ? <span className="field-hint">{hint}</span> : null}
 </label>
 );
}

/* ─── Input ──────────────────────────────────────────────────────────────── */
export function Input(props: ComponentPropsWithoutRef<"input">) {
 const normalizedProps =
 props.type ==="file"
 ? props
 :"value"in props
 ? { ...props, value: props.value ??""}
 : props;

 return (
 <input
 {...normalizedProps}
 className={cn(
"input focus-ring",
 normalizedProps.className,
 )}
 />
 );
}

/* ─── Textarea ───────────────────────────────────────────────────────────── */
export function Textarea(props: ComponentPropsWithoutRef<"textarea">) {
 const normalizedProps =
"value"in props
 ? { ...props, value: props.value ??""}
 : props;

 return (
 <textarea
 {...normalizedProps}
 className={cn(
"textarea focus-ring",
 normalizedProps.className,
 )}
 />
 );
}

/* ─── Dropdown (Clerk-style custom select) ───────────────────────────────── */
export function Dropdown<T extends string>({
 value,
 onChange,
 options,
 ariaLabel,
 className,
 disabled = false,
}: Readonly<{
 value: T;
 onChange: (value: T) => void;
 options: Array<{ value: T; label: string }>;
 ariaLabel?: string;
 className?: string;
 disabled?: boolean;
}>) {
 const [open, setOpen] = React.useState(false);
 const containerRef = React.useRef<HTMLDivElement>(null);
 const closeTimerRef = React.useRef<number | undefined>(undefined);
 const dropdownId = useId().replace(/[^a-zA-Z0-9_-]+/g,"") ||"dropdown";
 const activeIndex = options.findIndex((o) => o.value === value);
 const listboxId = `${dropdownId}-listbox`;
 const activeDescendant =
 activeIndex >= 0
 ? `${dropdownId}-option-${activeIndex}-${sanitizeIdSegment(options[activeIndex].value)}`
 : undefined;
 if (process.env.NODE_ENV ==="development"&& activeIndex === -1 && options.length > 0) {
      console.warn(`Dropdown: value "${value}" not found in options`);
 }
 function scheduleClose() {
 closeTimerRef.current = window.setTimeout(() => setOpen(false), 120) as unknown as number;
 }

 function cancelClose() {
 if (closeTimerRef.current) {
 clearTimeout(closeTimerRef.current);
 closeTimerRef.current = undefined;
 }
 }

 React.useEffect(() => {
 return () => {
 if (closeTimerRef.current) clearTimeout(closeTimerRef.current);
 };
 }, []);

 React.useEffect(() => {
 if (!open) return;
 function handleClickOutside(e: MouseEvent) {
 if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
 setOpen(false);
 }
 }
 function handleEscape(e: KeyboardEvent) {
 if (e.key ==="Escape") setOpen(false);
 }
 document.addEventListener("mousedown", handleClickOutside);
 document.addEventListener("keydown", handleEscape);
 return () => {
 document.removeEventListener("mousedown", handleClickOutside);
 document.removeEventListener("keydown", handleEscape);
 };
 }, [open]);

 function handleKeyDown(e: React.KeyboardEvent) {
 if (!open && (e.key === "Enter" || e.key === " " || e.key === "ArrowDown")) {
 e.preventDefault();
 setOpen(true);
 return;
 }
 if (!open) return;
 if (e.key ==="ArrowDown") {
 e.preventDefault();
 const next = (activeIndex + 1) % options.length;
 onChange(options[next].value);
 } else if (e.key ==="ArrowUp") {
 e.preventDefault();
 const prev = (activeIndex - 1 + options.length) % options.length;
 onChange(options[prev].value);
 } else if (e.key === "Enter" || e.key === " ") {
 e.preventDefault();
 setOpen(false);
 } }

 const selectedLabel = options[activeIndex]?.label ?? value;

 return (
 <div
 ref={containerRef}
 className={cn("relative", className)}
 onMouseEnter={() => { if (!disabled) { cancelClose(); setOpen(true); } }}
 onMouseLeave={() => { if (open) scheduleClose(); }}
 >
 <button
 type="button"
 role="combobox"
 aria-expanded={open}
 aria-label={ariaLabel}
 aria-haspopup="listbox"
 aria-controls={listboxId}
 onClick={() => setOpen((v) => !v)}
 disabled={disabled}
 onKeyDown={handleKeyDown}
 className="focus-ring flex h-[var(--control-height)] w-full items-center justify-between gap-2 rounded-[var(--radius-md)] border border-[var(--border-strong)] bg-[var(--bg-elevated)] px-3 text-left text-sm font-medium leading-[1.4] text-[var(--text-primary)] transition-[border-color,box-shadow] hover:border-[var(--border-strong)] focus:border-[var(--border-focus)] focus:shadow-[0_0_0_3px_var(--accent-subtle)]"
 >
 <span className="truncate">{selectedLabel}</span>
 <svg
 className={cn("size-3.5 shrink-0 text-muted transition-transform duration-150", open &&"rotate-180")}
 viewBox="0 0 16 16"
 fill="none"
 stroke="currentColor"
 strokeWidth={2}
 strokeLinecap="round"
 strokeLinejoin="round"
 >
 <path d="M4 6l4 4 4-4"/>
 </svg>
 </button>
 {open ? (
 <div
 id={listboxId}
 role="listbox"
 aria-activedescendant={activeDescendant}
 className="absolute left-0 z-50 mt-1 min-w-full rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-elevated)] py-1 shadow-[var(--shadow-lg)] animate-[dropdown-in_150ms_cubic-bezier(0.16,1,0.3,1)]"
 >
 {options.map((option, index) => {
 const optionId = `${dropdownId}-option-${index}-${sanitizeIdSegment(option.value)}`;
 return (
 <button
 key={option.value}
 id={optionId}
 role="option"
 aria-selected={option.value === value}
 onClick={() => {
 onChange(option.value);
 setOpen(false);
 }}
 onMouseDown={(e) => e.preventDefault()}
 className={cn(
"flex w-full items-center px-3 py-2 text-sm leading-[1.35] transition-colors",
 option.value === value
 ?"bg-[var(--accent-subtle)] text-[var(--accent)] font-medium"
 :"text-[var(--text-primary)] hover:bg-[var(--bg-alt)]",
 )}
 >
 {option.label}
 </button>
 );
 })}
 </div>
 ) : null}
 </div>
 );
}

/* ─── Button ─────────────────────────────────────────────────────────────── */
export function Button({
 className,
 variant ="primary",
 size ="md",
 ...props
}: Readonly<
 ComponentPropsWithoutRef<"button"> & {
 variant?:"primary"|"secondary"|"ghost"|"accent"|"danger";
 size?:"sm"|"md"|"lg"|"icon";
 }
>) {
 const variants: Record<string, string> = {
 primary:"btn-primary",
 secondary:"btn-secondary",
 ghost:"btn-ghost",
 accent:"btn-primary",
 danger:"btn-danger",
 };
 const sizes: Record<string, string> = {
 sm:"btn-sm",
 md:"",
 lg:"btn-lg",
 icon:"btn-icon",
 };
 return (
 <button
 {...props}
 className={cn(
"btn focus-ring disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 disabled:grayscale",
 variants[variant],
 sizes[size],
 className,
 )}
 />
 );
}

/* ─── Badge ──────────────────────────────────────────────────────────────── */
export function Badge({
 children,
 tone ="neutral",
 className,
}: Readonly<{
 children: ReactNode;
 tone?:"neutral"|"success"|"warning"|"danger"|"accent"|"info";
 className?: string;
}>) {
 const tones: Record<string, string> = {
 neutral:"badge-neutral",
 success:"badge-success",
 warning:"badge-warning",
 danger:"badge-danger",
 accent:"badge-accent",
 info:"badge-info",
 };
 return (
 <span
 className={cn(
"badge",
 tones[tone] ?? tones.neutral,
 className,
 )}
 >
 <span
 className={cn("size-1 rounded-full bg-current", tone ==="accent"&&"animate-pulse")}
 aria-hidden
 />
 {children}
 </span>
 );
}

/* ─── Toggle ─────────────────────────────────────────────────────────────── */
export function Toggle({
 checked,
 onChange,
 ariaLabel,
}: Readonly<{ checked: boolean; onChange: (v: boolean) => void; ariaLabel?: string }>) {
 return (
 <button
 type="button"
 role="switch"
 aria-label={ariaLabel}
 aria-checked={checked}
 onClick={() => onChange(!checked)}
 className={cn(
"focus-ring relative inline-flex h-[20px] w-[36px] shrink-0 cursor-pointer items-center rounded-full transition-colors",
 checked ?"bg-[var(--accent)]":"bg-[var(--border-strong)]",
 )}
 >
 <span
 className={cn(
"inline-block h-4 w-4 rounded-full bg-white shadow-sm transition-transform",
 checked ?"translate-x-[16px]":"translate-x-[2px]"
 )}
 />
 </button>
 );
}

/* ─── Metric (simple inline, used in crawl page) ─────────────────────────── */
export function Metric({
 label,
 value,
 loading = false,
}: Readonly<{ label: string; value: ReactNode; loading?: boolean }>) {
 return (
 <div className="metric-card space-y-1.5">
 <p className="metric-label">{label}</p>
 {loading ? (
 <div className="skeleton h-7 w-20"aria-hidden />
 ) : (
 <div className="metric-value">
 {value}
 </div>
 )}
 </div>
 );
}

/* ─── StatCard — Dashboard KPI tile with colored top stripe ─────────────── */
export function StatCard({
 label,
 value,
 icon,
 iconColor,
 stripeColor,
 sub,
 loading = false,
}: Readonly<{
 label: string;
 value: ReactNode;
 icon?: ReactNode;
 iconColor?: string;
 stripeColor?: string;
 sub?: ReactNode;
 loading?: boolean;
}>) {
 return (
 <div
 className="metric-card"
 style={{"--stat-accent": stripeColor } as React.CSSProperties}
 >
 <div className="metric-head">
 <p className="metric-label">{label}</p>
 {icon && (
 <div
 className="metric-icon"
 style={{ background: colorWithAlpha(stripeColor, 10), color: iconColor ?? stripeColor ??"var(--accent)"}}
 >
 {icon}
 </div>
 )}
 </div>
 {loading ? (
 <div className="mt-2.5 skeleton h-9 w-28"aria-hidden />
 ) : (
 <div className="metric-value mt-2">
 {value}
 </div>
 )}
 {sub && !loading && (
 <div className="metric-sub mt-1.5">
 {sub}
 </div>
 )}
 </div>
 );
}

/* ─── Table primitives ───────────────────────────────────────────────────── */
export function Table({ children, className }: Readonly<{ children: ReactNode; className?: string }>) {
 return (
 <div className="relative w-full overflow-auto">
 <table className={cn("w-full caption-bottom text-sm leading-[1.55]", className)}>{children}</table>
 </div>
 );
}

export function TableHeader({ children, className }: Readonly<{ children: ReactNode; className?: string }>) {
 return <thead className={cn("[&_tr]:border-b", className)}>{children}</thead>;
}

export function TableBody({ children, className }: Readonly<{ children: ReactNode; className?: string }>) {
 return <tbody className={cn("[&_tr:last-child]:border-0", className)}>{children}</tbody>;
}

export function TableRow({
 children,
 className,
 ...props
}: Readonly<{ children: ReactNode; className?: string } & React.HTMLAttributes<HTMLTableRowElement>>) {
 return (
 <tr
 {...props}
 className={cn(
"border-b border-[var(--divider)] transition-colors hover:bg-[var(--bg-alt)]",
 className,
 )}
 >
 {children}
 </tr>
 );
}

export function TableHead({ children, className }: Readonly<{ children: ReactNode; className?: string }>) {
 return (
 <th
 className={cn(
"h-9 px-4 text-left align-middle text-sm font-semibold uppercase tracking-[0.07em] text-[var(--text-muted)]",
 className,
 )}
 >
 {children}
 </th>
 );
}

export function TableCell({
 children,
 className,
 colSpan,
}: Readonly<{ children: ReactNode; className?: string; colSpan?: number }>) {
 return (
 <td className={cn("p-4 align-middle text-sm leading-[1.5] text-[var(--text-secondary)]", className)} colSpan={colSpan}>
 {children}
 </td>
 );
}

/* ─── Skeleton ───────────────────────────────────────────────────────────── */
export function Skeleton({ className }: Readonly<{ className?: string }>) {
 return <div className={cn("skeleton", className)} aria-hidden="true"/>;
}

/* ─── Tooltip ────────────────────────────────────────────────────────────── */
export function Tooltip({
 children,
 content,
 className,
 align ="center",
}: Readonly<{ children: ReactNode; content: string; className?: string; align?:"center"|"start"}>) {
 const tooltipId = useId();
 const child = React.Children.only(children);
 const anchorRef = React.useRef<HTMLDivElement>(null);
 const tooltipRef = React.useRef<HTMLDivElement>(null);
 const [open, setOpen] = React.useState(false);
 const [position, setPosition] = React.useState<{ left: number; top: number }>({ left: 0, top: 0 });
 const enhancedChild = React.isValidElement(child)
 ? React.cloneElement(child, {"aria-describedby": tooltipId } as React.HTMLAttributes<HTMLElement>)
 : child;

 const updatePosition = React.useCallback(() => {
 if (!anchorRef.current || !tooltipRef.current) {
 return;
 }
 const anchorRect = anchorRef.current.getBoundingClientRect();
 const tooltipRect = tooltipRef.current.getBoundingClientRect();
 const margin = 12;
 const idealLeft =
 align === "start"
 ? anchorRect.left
 : anchorRect.left + anchorRect.width / 2 - tooltipRect.width / 2;
 const maxLeft = window.innerWidth - tooltipRect.width - margin;
 const nextLeft = Math.min(Math.max(idealLeft, margin), Math.max(margin, maxLeft));
 const nextTop = Math.max(margin, anchorRect.top - tooltipRect.height - 8);
 setPosition({ left: nextLeft, top: nextTop });
 }, [align, setPosition]);

 React.useLayoutEffect(() => {
 if (!open) {
 return;
 }
 updatePosition();
 }, [open, content, updatePosition]);

 React.useEffect(() => {
 if (!open) {
 return;
 }
 const handleLayout = () => updatePosition();
 window.addEventListener("resize", handleLayout);
 window.addEventListener("scroll", handleLayout, true);
 return () => {
 window.removeEventListener("resize", handleLayout);
 window.removeEventListener("scroll", handleLayout, true);
 };
 }, [open, updatePosition]);

 return (
 <div
 ref={anchorRef}
 className={cn("relative flex items-center", className)}
 onMouseEnter={() => setOpen(true)}
 onMouseLeave={() => setOpen(false)}
 onFocus={() => setOpen(true)}
 onBlur={(event) => {
 if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
 setOpen(false);
 }
 }}
 >
 {enhancedChild}
 {open && typeof document !== "undefined"
 ? createPortal(
 <div
 ref={tooltipRef}
 id={tooltipId}
 role="tooltip"
 className={cn(
 "pointer-events-none fixed w-max max-w-[min(420px,calc(100vw-24px))]",
 "tooltip-surface rounded-[var(--radius-md)] bg-[var(--bg-panel)] px-2 py-1.5 shadow-[var(--shadow-lg)]",
 "text-sm font-medium leading-normal text-[var(--text-primary)] z-[200] break-words",
 )}
 style={{ left: `${position.left}px`, top: `${position.top}px` }}
 >
 {content}
 <div
 className="absolute -bottom-[6px] size-2.5 rotate-45 border-b border-r border-[var(--border-strong)] bg-[var(--bg-panel)]"
 style={{
 left:
 align === "start"
 ? "12px"
 : "50%",
 transform: align === "start" ? undefined : "translateX(-50%)",
 }}
 />
 </div>,
 document.body,
 )
 : null}
 </div>
 );
}
