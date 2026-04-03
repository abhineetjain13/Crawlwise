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
        "animate-fade-in rounded-lg border border-border bg-panel p-4 shadow-card sm:p-5",
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
        <p className="text-[11px] font-medium uppercase tracking-[0.08em] text-accent">
          {kicker}
        </p>
      ) : null}
      <h1 className="text-xl font-semibold tracking-[-0.02em] text-foreground sm:text-2xl">
        {children}
      </h1>
    </div>
  );
}

export function Subtitle({ children }: Readonly<{ children: ReactNode }>) {
  return <p className="max-w-xl text-[13px] leading-relaxed text-muted">{children}</p>;
}

export function Field({
  label,
  hint,
  children,
}: Readonly<{ label: string; hint?: string; children: ReactNode }>) {
  return (
    <label className="grid gap-1.5">
      <span className="text-[13px] font-medium text-foreground">{label}</span>
      {children}
      {hint ? <span className="text-[11px] text-muted">{hint}</span> : null}
    </label>
  );
}

export function Input(props: ComponentPropsWithoutRef<"input">) {
  return (
    <input
      {...props}
      className={cn(
        "focus-ring h-9 w-full rounded-md border border-border bg-background px-3 text-[13px] text-foreground transition placeholder:text-muted/60",
        "hover:border-border-strong focus:border-accent",
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
        "focus-ring min-h-24 w-full rounded-md border border-border bg-background px-3 py-2 text-[13px] text-foreground transition placeholder:text-muted/60",
        "hover:border-border-strong focus:border-accent",
        props.className,
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
    variant?: "primary" | "secondary" | "ghost" | "accent";
  }
>) {
  const variants = {
    primary:
      "bg-brand text-brand-foreground shadow-sm hover:opacity-90 active:opacity-80",
    secondary:
      "border border-border bg-background text-foreground hover:bg-panel-strong active:bg-panel-strong/80",
    ghost: "text-foreground hover:bg-panel-strong active:bg-panel-strong/80",
    accent:
      "bg-accent text-white shadow-sm hover:opacity-90 active:opacity-80",
  };
  return (
    <button
      {...props}
      className={cn(
        "focus-ring inline-flex h-8 items-center justify-center gap-1.5 rounded-md px-3 text-[13px] font-medium transition-all disabled:pointer-events-none disabled:opacity-50",
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
    neutral: "bg-panel-strong text-muted",
    success: "bg-success/10 text-success",
    warning: "bg-warning/10 text-warning",
    danger: "bg-danger/10 text-danger",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md px-2 py-0.5 text-[11px] font-medium",
        tones[tone],
      )}
    >
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
    <Card className="space-y-1 p-4">
      <p className="text-[11px] font-medium uppercase tracking-[0.04em] text-muted">
        {label}
      </p>
      <div className="text-2xl font-semibold tracking-[-0.02em] text-foreground">
        {value}
      </div>
      {hint ? <div className="text-[11px] text-muted">{hint}</div> : null}
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
      <h2 className="text-[15px] font-semibold tracking-[-0.01em] text-foreground">
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
        "max-h-[28rem] overflow-auto rounded-md border border-border bg-panel-strong p-4 font-mono text-[12px] leading-[1.6] text-foreground",
        className,
      )}
    >
      {children}
    </pre>
  );
}
