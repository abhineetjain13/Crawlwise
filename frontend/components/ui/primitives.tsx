"use client";

import type { ComponentPropsWithoutRef, ReactNode } from "react";

import { cn } from "../../lib/utils";

export function Card({
  children,
  className,
}: Readonly<{ children: ReactNode; className?: string }>) {
  return <section className={cn("rounded-xl border border-border/70 bg-panel/92 p-4 shadow-card backdrop-blur sm:p-5", className)}>{children}</section>;
}

export function Title({
  children,
  kicker,
  className,
}: Readonly<{ children: ReactNode; kicker?: string; className?: string }>) {
  return (
    <div className={cn("space-y-2", className)}>
      {kicker ? <p className="text-xs font-semibold uppercase tracking-[0.24em] text-brand">{kicker}</p> : null}
      <h1 className="text-balance text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">{children}</h1>
    </div>
  );
}

export function Subtitle({ children }: Readonly<{ children: ReactNode }>) {
  return <p className="max-w-2xl text-sm leading-6 text-muted">{children}</p>;
}

export function Field({
  label,
  hint,
  children,
}: Readonly<{ label: string; hint?: string; children: ReactNode }>) {
  return (
    <label className="grid gap-2">
      <span className="text-sm font-medium text-foreground">{label}</span>
      {children}
      {hint ? <span className="text-xs text-muted">{hint}</span> : null}
    </label>
  );
}

export function Input(props: ComponentPropsWithoutRef<"input">) {
  return (
    <input
      {...props}
      className={cn(
        "h-10 w-full rounded-lg border border-border bg-transparent px-3 text-sm text-foreground outline-none transition placeholder:text-muted focus:border-brand focus:ring-2 focus:ring-brand/20",
        props.className,
      )}
    />
  );
}

export function Textarea(props: ComponentPropsWithoutRef<"textarea">) {
  return (
    <textarea
      {...props}
      className={cn(
        "min-h-24 w-full rounded-lg border border-border bg-transparent px-3 py-2.5 text-sm text-foreground outline-none transition placeholder:text-muted focus:border-brand focus:ring-2 focus:ring-brand/20",
        props.className,
      )}
    />
  );
}

export function Button({
  className,
  variant = "primary",
  ...props
}: Readonly<ComponentPropsWithoutRef<"button"> & { variant?: "primary" | "secondary" | "ghost" }>) {
  const variants = {
    primary: "bg-brand text-brand-foreground shadow-sm hover:bg-brand/90",
    secondary: "border border-border bg-panel text-foreground hover:bg-panel-strong",
    ghost: "text-foreground hover:bg-panel-strong",
  };
  return (
    <button
      {...props}
      className={cn(
        "inline-flex h-9 items-center justify-center rounded-lg px-3.5 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-60",
        variants[variant],
        className,
      )}
    />
  );
}

export function Badge({
  children,
  tone = "neutral",
}: Readonly<{ children: ReactNode; tone?: "neutral" | "success" | "warning" }>) {
  const tones = {
    neutral: "bg-panel-strong text-foreground",
    success: "bg-emerald-500/12 text-emerald-600 dark:text-emerald-300",
    warning: "bg-amber-500/14 text-amber-700 dark:text-amber-300",
  };
  return <span className={cn("inline-flex rounded-lg px-3 py-1 text-xs font-semibold", tones[tone])}>{children}</span>;
}

export function Metric({
  label,
  value,
  hint,
}: Readonly<{ label: string; value: ReactNode; hint?: ReactNode }>) {
  return (
    <Card className="space-y-2 p-4">
      <p className="text-xs font-medium uppercase tracking-[0.18em] text-muted">{label}</p>
      <div className="text-3xl font-semibold tracking-tight text-foreground">{value}</div>
      {hint ? <div className="text-xs text-muted">{hint}</div> : null}
    </Card>
  );
}

export function DataList({
  title,
  items,
  empty,
}: Readonly<{ title: string; items: ReactNode[]; empty: string }>) {
  return (
    <Card className="space-y-4">
      <h2 className="text-lg font-semibold text-foreground">{title}</h2>
      {items.length ? <div className="grid gap-3">{items}</div> : <p className="text-sm text-muted">{empty}</p>}
    </Card>
  );
}

export function CodeBlock({
  children,
  className,
}: Readonly<{ children: ReactNode; className?: string }>) {
  return (
    <pre className={cn("max-h-[28rem] overflow-auto rounded-xl border border-border bg-panel-strong/70 p-4 font-mono text-[11px] leading-6 text-foreground", className)}>
      {children}
    </pre>
  );
}
