"use client";

import type { ComponentPropsWithoutRef } from "react";
import { cva } from "class-variance-authority";

import { cn } from "../../lib/utils";

export const inputVariants = cva(
  "focus-ring h-[var(--control-height)] w-full rounded-[var(--radius-md)] border border-border-strong bg-background-elevated px-3 text-sm leading-normal text-foreground shadow-xs transition-[border-color,box-shadow] placeholder:text-muted hover:border-border-strong focus:border-accent",
);

export const textareaVariants = cva(
  "focus-ring min-h-[84px] w-full resize-y rounded-[var(--radius-md)] border border-border-strong bg-background-elevated px-3 py-2 text-sm leading-[1.5] text-foreground shadow-xs transition-[border-color,box-shadow] placeholder:text-muted hover:border-border-strong focus:border-accent",
);

export function Input(props: ComponentPropsWithoutRef<"input">) {
  const normalizedProps =
    props.type === "file"
      ? props
      : "value" in props
        ? { ...props, value: props.value ?? "" }
        : props;

  return <input {...normalizedProps} className={cn(inputVariants(), normalizedProps.className)} />;
}

export function Textarea(props: ComponentPropsWithoutRef<"textarea">) {
  const normalizedProps = "value" in props ? { ...props, value: props.value ?? "" } : props;

  return <textarea {...normalizedProps} className={cn(textareaVariants(), normalizedProps.className)} />;
}
