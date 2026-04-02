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
    <div className="flex flex-col gap-3 rounded-[1.75rem] border border-border/70 bg-panel/80 px-5 py-4 shadow-card backdrop-blur sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0 space-y-1.5">
        <h1 className="text-2xl font-semibold tracking-tight text-foreground sm:text-[2rem]">{title}</h1>
        {description ? <p className="max-w-2xl text-sm leading-6 text-muted">{description}</p> : null}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
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
      <div className="space-y-1">
        <h2 className="text-lg font-semibold tracking-tight text-foreground">{title}</h2>
        {description ? <p className="text-sm text-muted">{description}</p> : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}

export function MetricGrid({ children }: Readonly<{ children: ReactNode }>) {
  return <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">{children}</div>;
}

export function EmptyPanel({
  title,
  description,
}: Readonly<{
  title: string;
  description: string;
}>) {
  return (
    <Card className="grid min-h-40 place-items-center border-dashed text-center">
      <div className="space-y-1.5">
        <p className="text-sm font-medium text-foreground">{title}</p>
        <p className="text-sm text-muted">{description}</p>
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
    <Card className={cn("space-y-4", className)}>
      <SectionHeader title={title} description={subtitle} />
      {children}
    </Card>
  );
}
