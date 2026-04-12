"use client";

import * as React from "react";
import { useId } from "react";
import type { ComponentPropsWithoutRef, ReactNode } from "react";
import { cn } from "../../lib/utils";

function colorWithAlpha(color: string | undefined, alphaPercent: number) {
  const normalized = String(color ?? "").trim();
  if (!normalized) {
    return "var(--accent-subtle)";
  }
  return `color-mix(in srgb, ${normalized} ${alphaPercent}%, transparent)`;
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
        "surface-panel",
        "relative",
        "p-5",
        animate && "animate-fade-in",
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
        <p className="text-kicker text-accent">
          {kicker}
        </p>
      ) : null}
      <h1 className="text-page-title text-primary">
        {children}
      </h1>
    </div>
  );
}

export function Subtitle({ children }: Readonly<{ children: ReactNode }>) {
  return <p className="max-w-2xl text-page-subtitle">{children}</p>;
}

/* ─── Field ──────────────────────────────────────────────────────────────── */
export function Field({
  label,
  hint,
  children,
}: Readonly<{ label: string; hint?: string; children: ReactNode }>) {
  return (
    <label className="grid gap-1.5">
      <span className="label-caps">{label}</span>
      {children}
      {hint ? <span className="text-meta text-muted">{hint}</span> : null}
    </label>
  );
}

/* ─── Input ──────────────────────────────────────────────────────────────── */
export function Input(props: ComponentPropsWithoutRef<"input">) {
  const normalizedProps =
    props.type === "file"
      ? props
      : "value" in props
        ? { ...props, value: props.value ?? "" }
        : props;

  return (
    <input
      {...normalizedProps}
      className={cn(
        "control-field focus-ring h-[var(--control-height)] w-full rounded-[var(--radius-md)]",
        "bg-[var(--control-input-bg)] px-3 text-body-sm text-[var(--text-primary)] shadow-[var(--control-input-shadow)]",
        "hover:bg-[var(--control-input-hover-bg)] hover:shadow-[var(--control-input-hover-shadow)]",
        "focus:shadow-[var(--control-input-focus-shadow)]",
        "placeholder:text-[var(--text-muted)]",
        "hover:border-[var(--border-strong)]",
        "transition-all",
        normalizedProps.className,
      )}
    />
  );
}

/* ─── Textarea ───────────────────────────────────────────────────────────── */
export function Textarea(props: ComponentPropsWithoutRef<"textarea">) {
  const normalizedProps =
    "value" in props
      ? { ...props, value: props.value ?? "" }
      : props;

  return (
    <textarea
      {...normalizedProps}
      className={cn(
        "control-field focus-ring min-h-20 w-full rounded-[var(--radius-md)]",
        "bg-[var(--control-input-bg)] px-3 py-2 text-body-sm text-[var(--text-primary)] shadow-[var(--control-input-shadow)]",
        "hover:bg-[var(--control-input-hover-bg)] hover:shadow-[var(--control-input-hover-shadow)]",
        "focus:shadow-[var(--control-input-focus-shadow)]",
        "placeholder:text-[var(--text-muted)]",
        "hover:border-[var(--border-strong)]",
        "transition-all",
        normalizedProps.className,
      )}
    />
  );
}

/* ─── Button ─────────────────────────────────────────────────────────────── */
export function Button({
  className,
  variant = "primary",
  size = "md",
  ...props
}: Readonly<
  ComponentPropsWithoutRef<"button"> & {
    variant?: "primary" | "secondary" | "ghost" | "accent" | "danger";
    size?: "sm" | "md" | "lg" | "icon";
  }
>) {
  const variants: Record<string, string> = {
    primary:
      "bg-[var(--accent)] !text-[var(--button-filled-fg)] hover:bg-[var(--accent-hover)] shadow-[0_14px_30px_color-mix(in_srgb,var(--accent)_24%,transparent)]",
    secondary:
      "button-secondary-surface text-[var(--text-primary)] hover:bg-[var(--button-secondary-hover-bg)] hover:border-[var(--border-focus)]",
    ghost:
      "button-ghost-surface text-[var(--text-primary)] hover:bg-[var(--button-ghost-hover-bg)] hover:text-[var(--text-primary)]",
    accent: "accent-fill",
    danger: "border-[length:var(--interactive-border-width)] border-[var(--danger)] danger-fill",
  };
  const sizes: Record<string, string> = {
    sm:   "h-8 px-2.5 text-caption",
    md:   "h-[var(--control-height)] px-3.5 text-body-sm",
    lg:   "h-10 px-4 text-body",
    icon: "h-[var(--control-height)] w-[var(--control-height)] p-0",
  };
  const onAccent = variant === "primary" || variant === "danger" || variant === "accent";
  return (
    <button
      {...props}
      className={cn(
        "focus-ring inline-flex items-center justify-center gap-1.5 rounded-[var(--radius-md)] font-medium",
        "transition-all disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 disabled:grayscale",
        onAccent && "ui-on-accent-surface",
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
  tone = "neutral",
  className,
}: Readonly<{
  children: ReactNode;
  tone?: "neutral" | "success" | "warning" | "danger" | "accent" | "info";
  className?: string;
}>) {
  const tones: Record<string, string> = {
    neutral: "bg-[var(--status-neutral-bg)] text-[var(--text-secondary)]",
    success: "bg-[var(--success-bg)] text-[var(--success)]",
    warning: "bg-[var(--warning-bg)] text-[var(--warning)]",
    danger:  "bg-[var(--danger-bg)]  text-[var(--danger)]",
    accent:  "bg-[var(--accent-subtle)] text-[var(--accent)]",
    info:    "bg-[var(--info-bg)] text-[var(--info)]",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-[var(--radius-sm)] px-1.5 py-0.5",
        "text-kicker leading-none",
        tones[tone] ?? tones.neutral,
        className,
      )}
    >
      <span
        className={cn("size-1 rounded-full bg-current", tone === "accent" && "animate-pulse")}
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
        "focus-ring relative inline-flex h-[18px] w-8 shrink-0 cursor-pointer items-center rounded-full transition-colors",
        checked ? "bg-[var(--accent)] shadow-[0_8px_18px_color-mix(in_srgb,var(--accent)_26%,transparent)]" : "bg-[var(--border-strong)]",
      )}
    >
      <span
        className={cn(
          "inline-block h-3.5 w-3.5 rounded-full bg-[var(--accent-fg)] shadow-[0_3px_10px_rgba(0,0,0,0.18)] transition-transform",
          checked ? "translate-x-[14px]" : "translate-x-0.5",
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
    <div className="surface-panel space-y-1.5 p-4">
      <p className="label-caps">{label}</p>
      {loading ? (
        <div className="skeleton h-7 w-20" aria-hidden />
      ) : (
        <div className="text-title-md text-primary">
          {value}
        </div>
      )}
    </div>
  );
}

/* ─── StatCard  — Dashboard KPI tile with colored top stripe ─────────────── */
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
      className="stat-card"
      style={{ "--stat-accent": stripeColor } as React.CSSProperties}
    >
      <div className="flex items-start justify-between gap-3">
        <p className="label-caps">{label}</p>
        {icon && (
          <div
            className="flex size-7 items-center justify-center rounded-[var(--radius-md)]"
            style={{ background: colorWithAlpha(stripeColor, 10), color: iconColor ?? stripeColor ?? "var(--accent)" }}
          >
            {icon}
          </div>
        )}
      </div>
      {loading ? (
        <div className="mt-2.5 skeleton h-9 w-28" aria-hidden />
      ) : (
        <div className="mt-2 text-stat-value text-primary">
          {value}
        </div>
      )}
      {sub && !loading && (
        <div className="mt-1.5 text-meta text-muted">
          {sub}
        </div>
      )}
    </div>
  );
}

/* ─── DataList ───────────────────────────────────────────────────────────── */
export function DataList({
  title,
  items,
  empty,
}: Readonly<{ title: string; items: ReactNode[]; empty: string }>) {
  return (
    <Card className="space-y-3">
      <h2 className="text-section-title text-primary">
        {title}
      </h2>
      {items.length ? (
        <div className="grid gap-2">{items}</div>
      ) : (
        <p className="text-body-sm text-muted">{empty}</p>
      )}
    </Card>
  );
}

/* ─── CodeBlock ──────────────────────────────────────────────────────────── */
export function CodeBlock({
  children,
  className,
}: Readonly<{ children: ReactNode; className?: string }>) {
  return (
    <pre
      className={cn(
        "max-h-[28rem] overflow-auto rounded-[var(--radius-lg)] border border-[var(--border)]",
        "bg-[var(--subtle-panel-bg)] p-4 font-mono text-caption leading-[1.6] text-primary",
        className,
      )}
    >
      {children}
    </pre>
  );
}

/* ─── Table primitives ───────────────────────────────────────────────────── */
export function Table({ children, className }: Readonly<{ children: ReactNode; className?: string }>) {
  return (
    <div className="relative w-full overflow-auto">
      <table className={cn("w-full caption-bottom text-body-sm", className)}>{children}</table>
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
          "border-b border-[var(--divider)] transition-colors hover:bg-[var(--bg-elevated)]",
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
        "h-9 px-4 text-left align-middle label-caps tone-muted",
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
    <td className={cn("text-data p-4 align-middle", className)} colSpan={colSpan}>
      {children}
    </td>
  );
}

/* ─── Skeleton ───────────────────────────────────────────────────────────── */
export function Skeleton({ className }: Readonly<{ className?: string }>) {
  return <div className={cn("skeleton", className)} aria-hidden="true" />;
}

/* ─── Spinner ────────────────────────────────────────────────────────────── */
export function Spinner({ className }: Readonly<{ className?: string }>) {
  return (
    <svg
      className={cn("animate-spin-slow", className)}
      xmlns="http://www.w3.org/2000/svg"
      fill="none"
      viewBox="0 0 24 24"
      aria-hidden="true"
    >
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
      />
    </svg>
  );
}

/* ─── Tooltip ────────────────────────────────────────────────────────────── */
export function Tooltip({
  children,
  content,
  className,
}: Readonly<{ children: ReactNode; content: string; className?: string }>) {
  const tooltipId = useId();
  const child = React.Children.only(children);
  const enhancedChild = React.isValidElement(child)
    ? React.cloneElement(child, { "aria-describedby": tooltipId } as React.HTMLAttributes<HTMLElement>)
    : child;

  return (
    <div className={cn("group relative flex items-center", className)}>
      {enhancedChild}
      <div
        id={tooltipId}
        role="tooltip"
        className={cn(
          "pointer-events-none absolute bottom-full left-1/2 mb-2 w-max max-w-[320px] -translate-x-1/2",
          "tooltip-surface rounded-[var(--radius-md)] bg-[var(--bg-panel)] px-2 py-1.5 shadow-[var(--shadow-lg)]",
          "text-meta font-medium leading-normal text-primary opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100",
          "z-50 break-words",
        )}
      >
        {content}
        <div className="absolute -bottom-[6px] left-1/2 size-2.5 -translate-x-1/2 rotate-45 border-b border-r border-[var(--border-strong)] bg-[var(--bg-panel)]" />
      </div>
    </div>
  );
}
