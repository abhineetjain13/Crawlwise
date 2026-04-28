"use client";

import type { ComponentPropsWithoutRef } from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "../../lib/utils";

export const buttonVariants = cva(
  "focus-ring inline-flex items-center justify-center gap-1.5 rounded-[var(--radius-md)] border text-sm font-medium leading-none whitespace-nowrap no-underline transition-[background-color,color,border-color,box-shadow,opacity,transform] disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 disabled:grayscale",
  {
    variants: {
      variant: {
        primary: "ui-on-accent-surface border-accent bg-accent shadow-xs hover:border-accent-hover hover:bg-accent-hover active:opacity-90 transition-[background-color,border-color,box-shadow,opacity]",
        secondary: "border-border-strong bg-background-elevated text-foreground shadow-sm hover:bg-background-alt hover:border-border-strong active:shadow-none transition-[background-color,border-color,box-shadow]",
        ghost: "border-transparent bg-transparent text-muted hover:bg-status-neutral-bg hover:text-foreground transition-[background-color,color]",
        accent: "ui-on-accent-surface border-accent bg-accent shadow-sm hover:border-accent-hover hover:bg-accent-hover active:opacity-90 active:scale-[0.98] transition-[background-color,border-color,box-shadow,opacity,transform]",
        danger: "border-danger/30 bg-danger/10 text-danger hover:border-danger/40 hover:bg-danger/15 transition-[background-color,border-color]",
      },
      size: {
        sm: "min-h-[26px] px-[9px]",
        md: "min-h-[var(--control-height)] px-3",
        lg: "min-h-9 px-3.5",
        icon: "size-[var(--control-height)] p-0",
      },
    },
    defaultVariants: {
      variant: "primary",
      size: "md",
    },
  },
);

export type ButtonProps = ComponentPropsWithoutRef<"button"> & VariantProps<typeof buttonVariants>;

export function Button({ className, variant, size, ...props }: Readonly<ButtonProps>) {
  return <button {...props} className={cn(buttonVariants({ variant, size }), className)} />;
}
