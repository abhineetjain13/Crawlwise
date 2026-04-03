"use client";

import type { ComponentPropsWithoutRef, ReactNode } from "react";

import { cn } from "../../lib/utils";

export function Card({
  children,
  className,
}: Readonly<{ children: ReactNode; className?: string }>) {
  return (
    <section
      className={cn(
        "animate-fade-in rounded-[var(--radius-lg)] border border-border bg-panel p-5 shadow-card",
        className,
      )}
    >
      {children}
    </section>
  );
}

export function Title({
  children,
  kicker,
  className,
}: Readonly<{ children: ReactNode; kicker?: string; className?: string }>) {
  return (
    <div className={cn("space-y-1.5", className)}>
      {kicker ? (
        <p className="label-caps text-accent">
          {kicker}
        </p>
      ) : null}
      <h1 className="text-[18px] font-semibold tracking-[var(--tracking-tight)] text-foreground sm:text-[20px]">
        {children}
      </h1>
    </div>
  );
}

export function Subtitle({ children }: Readonly<{ children: ReactNode }>) {
  return <p className="max-w-2xl text-[13px] leading-5 text-muted">{children}</p>;
}

export function Field({
  label,
  hint,
  children,
}: Readonly<{ label: string; hint?: string; children: ReactNode }>) {
  return (
    <label className="grid gap-1.5">
      <span className="label-caps">{label}</span>
      {children}
      {hint ? <span className="text-[12px] text-muted">{hint}</span> : null}
    </label>
  );
}

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
        "focus-ring h-8 w-full rounded-[var(--radius-md)] border border-border bg-panel px-[10px] text-[13px] text-foreground transition placeholder:text-[var(--text-muted)]",
        "hover:border-border-strong focus:border-[var(--border-focus)]",
        normalizedProps.className,
      )}
    />
  );
}

export function Textarea(props: ComponentPropsWithoutRef<"textarea">) {
  const normalizedProps =
    "value" in props
      ? { ...props, value: props.value ?? "" }
      : props;

  return (
    <textarea
      {...normalizedProps}
      className={cn(
        "focus-ring min-h-20 w-full rounded-[var(--radius-md)] border border-border bg-panel px-[10px] py-2 text-[13px] text-foreground transition placeholder:text-[var(--text-muted)]",
        "hover:border-border-strong focus:border-[var(--border-focus)]",
        normalizedProps.className,
      )}
    />
  );
}

export function Button({
  className,
  variant = "primary",
  ...props
}: Readonly<
  ComponentPropsWithoutRef<"button"> & {
    variant?: "primary" | "secondary" | "ghost" | "accent" | "danger";
  }
>) {
  const variants = {
    primary: "bg-brand text-brand-foreground shadow-sm hover:bg-accent-hover",
    secondary:
      "border border-border bg-transparent text-foreground hover:bg-background-elevated",
    ghost: "border border-transparent bg-transparent text-muted hover:bg-accent-subtle hover:text-accent",
    accent: "bg-accent text-white shadow-sm hover:bg-accent-hover",
    danger: "border border-danger/30 bg-transparent text-danger hover:bg-danger/10",
  };
  return (
    <button
      {...props}
      className={cn(
        "focus-ring inline-flex h-8 items-center justify-center gap-2 rounded-[var(--radius-md)] px-[14px] text-[13px] font-medium transition-all disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-40",
        variants[variant],
        className,
      )}
    />
  );
}

export function Badge({
  children,
  tone = "neutral",
}: Readonly<{
  children: ReactNode;
  tone?: "neutral" | "success" | "warning" | "danger";
}>) {
  const tones = {
    neutral: "bg-[var(--status-inactive-bg)] text-[var(--text-secondary)]",
    success: "bg-[var(--status-active-bg)] text-success",
    warning: "bg-[var(--status-paused-bg)] text-warning",
    danger: "bg-[var(--status-killed-bg)] text-danger",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-[var(--radius-sm)] px-2 py-1 text-[10px] font-semibold uppercase tracking-[var(--tracking-wide)]",
        tones[tone],
      )}
    >
      <span className="size-1.5 rounded-full bg-current" aria-hidden />
      {children}
    </span>
  );
}

export function Metric({
  label,
  value,
  hint,
}: Readonly<{ label: string; value: ReactNode; hint?: ReactNode }>) {
  return (
    <Card className="space-y-2 p-5">
      <p className="label-caps">
        {label}
      </p>
      <div className="text-[24px] font-bold tracking-[var(--tracking-tight)] text-foreground">
        {value}
      </div>
      {hint ? <div className="text-[12px] text-muted">{hint}</div> : null}
    </Card>
  );
}

export function DataList({
  title,
  items,
  empty,
}: Readonly<{ title: string; items: ReactNode[]; empty: string }>) {
  return (
    <Card className="space-y-3">
      <h2 className="text-[16px] font-semibold tracking-[var(--tracking-tight)] text-foreground">
        {title}
      </h2>
      {items.length ? (
        <div className="grid gap-2">{items}</div>
      ) : (
        <p className="text-[13px] text-muted">{empty}</p>
      )}
    </Card>
  );
}

export function CodeBlock({
  children,
  className,
}: Readonly<{ children: ReactNode; className?: string }>) {
  return (
    <pre
      className={cn(
        "max-h-[28rem] overflow-auto rounded-[var(--radius-lg)] border border-border bg-background-elevated p-4 font-mono text-[12px] leading-[1.6] text-foreground",
        className,
      )}
    >
      {children}
    </pre>
  );
}
