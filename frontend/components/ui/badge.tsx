"use client";

import type { ReactNode } from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "../../lib/utils";

export const badgeVariants = cva(
  "inline-flex min-h-[22px] items-center gap-1.5 rounded-[var(--radius-md)] border px-2 py-0.5 text-sm font-medium leading-[var(--leading-snug)] whitespace-nowrap",
  {
    variants: {
      tone: {
        neutral: "border-border bg-background-alt text-muted",
        success: "border-success/20 bg-success-bg text-success",
        warning: "border-warning/25 bg-warning-bg text-warning",
        danger: "border-danger/20 bg-danger-bg text-danger",
        accent: "border-accent/20 bg-accent-subtle text-accent",
        info: "border-info/20 bg-info-bg text-info",
      },
    },
    defaultVariants: {
      tone: "neutral",
    },
  },
);

export type BadgeProps = {
  children: ReactNode;
  className?: string;
} & VariantProps<typeof badgeVariants>;

export function Badge({ children, tone, className }: Readonly<BadgeProps>) {
  return (
    <span className={cn(badgeVariants({ tone }), className)}>
      <span className={cn("size-1 rounded-full bg-current", tone === "accent" && "animate-pulse")} aria-hidden />
      {children}
    </span>
  );
}
