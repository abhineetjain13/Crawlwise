"use client";

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
        "rounded-[var(--radius-xl)] border border-[var(--border)] bg-[var(--surface-card)] shadow-[var(--shadow-card-value)] backdrop-blur-xl",
        "before:pointer-events-none before:absolute before:inset-[1px] before:rounded-[calc(var(--radius-xl)-1px)] before:border before:border-[var(--surface-card-edge)] before:content-['']",
        "relative overflow-hidden",
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
        <p className="text-kicker text-[var(--accent)]">
          {kicker}
        </p>
      ) : null}
      <h1 className="text-title-sm text-[var(--text-primary)] sm:text-[20px]">
        {children}
      </h1>
    </div>
  );
}

export function Subtitle({ children }: Readonly<{ children: ReactNode }>) {
  return <p className="max-w-2xl text-body-sm leading-5 text-[var(--text-muted)]">{children}</p>;
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
      {hint ? <span className="text-meta text-[var(--text-muted)]">{hint}</span> : null}
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
        "focus-ring h-8 w-full rounded-[var(--radius-md)] border border-[var(--border)]",
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
        "focus-ring min-h-20 w-full rounded-[var(--radius-md)] border border-[var(--border)]",
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
    primary:   "bg-[var(--accent)] text-[var(--accent-fg)] hover:bg-[var(--accent-hover)] shadow-[var(--shadow-xs)]",
    secondary: "border border-[var(--border)] bg-[var(--button-secondary-bg)] text-[var(--text-primary)] hover:bg-[var(--button-secondary-hover-bg)] hover:border-[var(--border-strong)]",
    ghost:     "border border-transparent bg-transparent text-[var(--text-muted)] hover:bg-[var(--button-ghost-hover-bg)] hover:text-[var(--text-primary)]",
    accent:    "accent-fill",
    danger:    "border border-[var(--danger-bg)] bg-transparent text-[var(--danger)] hover:bg-[var(--danger-bg)]",
  };
  const sizes: Record<string, string> = {
    sm:   "h-7 px-2.5 text-caption",
    md:   "h-8 px-3.5 text-body-sm",
    lg:   "h-9 px-4 text-body",
    icon: "h-8 w-8 p-0",
  };
  return (
    <button
      {...props}
      className={cn(
        "focus-ring inline-flex items-center justify-center gap-1.5 rounded-[var(--radius-md)] font-medium",
        "transition-all disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-40",
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
        "text-meta font-semibold uppercase tracking-[0.05em]",
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
        checked ? "bg-[var(--accent)]" : "bg-[var(--border-strong)]",
      )}
    >
      <span
        className={cn(
          "inline-block h-3.5 w-3.5 rounded-full bg-[var(--accent-fg)] shadow-[var(--shadow-xs)] transition-transform",
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
    <div className="rounded-[var(--radius-xl)] border border-[var(--border)] bg-[var(--bg-panel)] p-4 space-y-1.5 shadow-[var(--shadow-card-value)]">
      <p className="label-caps">{label}</p>
      {loading ? (
        <div className="skeleton h-7 w-20" aria-hidden />
      ) : (
        <div className="text-title-md text-[var(--text-primary)]">
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
        <div className="mt-2 text-[var(--text-2xl)] font-bold tracking-[var(--tracking-tighter)] text-[var(--text-primary)]">
          {value}
        </div>
      )}
      {sub && !loading && (
        <div className="mt-1.5 text-meta font-medium text-[var(--text-muted)]">
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
      <h2 className="text-[var(--text-md)] font-semibold tracking-[var(--tracking-tight)] text-[var(--text-primary)]">
        {title}
      </h2>
      {items.length ? (
        <div className="grid gap-2">{items}</div>
      ) : (
        <p className="text-body-sm text-[var(--text-muted)]">{empty}</p>
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
        "bg-[var(--bg-elevated)] p-4 font-mono text-caption leading-[1.6] text-[var(--text-primary)]",
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
      <table className={cn("w-full caption-bottom text-sm", className)}>{children}</table>
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
        "border-b border-[var(--border)] transition-colors hover:bg-[var(--bg-elevated)]",
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
        "h-9 px-4 text-left align-middle text-meta font-semibold uppercase tracking-[0.05em] text-[var(--text-muted)]",
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
    <td className={cn("p-4 align-middle text-[var(--text-secondary)]", className)} colSpan={colSpan}>
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
