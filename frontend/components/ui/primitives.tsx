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
        "panel panel-raised relative p-5",
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
    props.type === "file"
      ? props
      : "value" in props
        ? { ...props, value: props.value ?? "" }
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
    "value" in props
      ? { ...props, value: props.value ?? "" }
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

export function Select(props: ComponentPropsWithoutRef<"select">) {
  return (
    <select
      {...props}
      className={cn(
        "control-select focus-ring",
        props.className,
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
    primary: "btn-primary",
    secondary: "btn-secondary",
    ghost: "btn-ghost",
    accent: "btn-primary",
    danger: "btn-danger",
  };
  const sizes: Record<string, string> = {
    sm: "btn-sm",
    md: "",
    lg: "btn-lg",
    icon: "btn-icon",
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
  tone = "neutral",
  className,
}: Readonly<{
  children: ReactNode;
  tone?: "neutral" | "success" | "warning" | "danger" | "accent" | "info";
  className?: string;
}>) {
  const tones: Record<string, string> = {
    neutral: "badge-neutral",
    success: "badge-success",
    warning: "badge-warning",
    danger: "badge-danger",
    accent: "badge-accent",
    info: "badge-info",
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
          checked ? "translate-x-[14px]" : "translate-x-0.5"
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
        <div className="skeleton h-7 w-20" aria-hidden />
      ) : (
        <div className="metric-value">
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
      className="metric-card"
      style={{ "--stat-accent": stripeColor } as React.CSSProperties}
    >
      <div className="metric-head">
        <p className="metric-label">{label}</p>
        {icon && (
          <div
            className="metric-icon"
            style={{ background: colorWithAlpha(stripeColor, 10), color: iconColor ?? stripeColor ?? "var(--accent)" }}
          >
            {icon}
          </div>
        )}
      </div>
      {loading ? (
        <div className="mt-2.5 skeleton h-9 w-28" aria-hidden />
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
        "h-9 px-4 text-left align-middle text-[11px] font-semibold uppercase tracking-[0.07em] text-[var(--text-muted)]",
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
  return <div className={cn("skeleton", className)} aria-hidden="true" />;
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
          "text-[11px] font-medium leading-normal text-[var(--text-primary)] opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100",
          "z-50 break-words",
        )}
      >
        {content}
        <div className="absolute -bottom-[6px] left-1/2 size-2.5 -translate-x-1/2 rotate-45 border-b border-r border-[var(--border-strong)] bg-[var(--bg-panel)]" />
      </div>
    </div>
  );
}
