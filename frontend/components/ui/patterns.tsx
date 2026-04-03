"use client";

import type { ReactNode } from "react";

import { cn } from "../../lib/utils";
import { Card } from "./primitives";

export function PageHeader({
  title,
  description,
  actions,
}: Readonly<{
  title: string;
  description?: string;
  actions?: ReactNode;
}>) {
  return (
    <div className="animate-fade-in flex flex-col gap-2 border-b border-border pb-4 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0 space-y-1">
        <h1 className="text-lg font-semibold tracking-[-0.02em] text-foreground">
          {title}
        </h1>
        {description ? (
          <p className="max-w-xl text-[13px] text-muted">{description}</p>
        ) : null}
      </div>
      {actions ? (
        <div className="flex shrink-0 items-center gap-2">{actions}</div>
      ) : null}
    </div>
  );
}

export function SectionHeader({
  title,
  description,
  action,
}: Readonly<{
  title: string;
  description?: string;
  action?: ReactNode;
}>) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div className="space-y-0.5">
        <h2 className="text-[15px] font-semibold tracking-[-0.01em] text-foreground">
          {title}
        </h2>
        {description ? (
          <p className="text-[13px] text-muted">{description}</p>
        ) : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}

export function MetricGrid({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <div className="stagger-children grid gap-3 md:grid-cols-2 xl:grid-cols-4">
      {children}
    </div>
  );
}

export function EmptyPanel({
  title,
  description,
}: Readonly<{
  title: string;
  description: string;
}>) {
  return (
    <Card className="grid min-h-32 place-items-center border-dashed text-center">
      <div className="space-y-1">
        <p className="text-[13px] font-medium text-foreground">{title}</p>
        <p className="text-[13px] text-muted">{description}</p>
      </div>
    </Card>
  );
}

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
    <Card className={cn("space-y-3", className)}>
      <SectionHeader title={title} description={subtitle} />
      {children}
    </Card>
  );
}
