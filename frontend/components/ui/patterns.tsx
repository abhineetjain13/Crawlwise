"use client";

import type { ReactNode } from "react";
import { useEffect } from "react";

import { useTopBarStore } from "../layout/top-bar-context";
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
  const { setHeader } = useTopBarStore();

  useEffect(() => {
    setHeader({ title, description, actions });
    return () => setHeader(null);
  }, [actions, description, setHeader, title]);

  return null;
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
        <h2 className="text-[16px] font-semibold tracking-[var(--tracking-tight)] text-foreground">
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
    <div className="stagger-children grid gap-4 md:grid-cols-2 xl:grid-cols-4">
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
    <Card className="grid min-h-36 place-items-center border-dashed text-center">
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
    <Card className={cn("space-y-4", className)}>
      <SectionHeader title={title} description={subtitle} />
      {children}
    </Card>
  );
}
