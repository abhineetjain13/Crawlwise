'use client';

import type { ReactNode } from 'react';
import { cva } from 'class-variance-authority';

import { cn } from '../../lib/utils';

const toneText = {
  neutral: 'text-muted',
  success: 'text-success',
  warning: 'text-warning',
  danger: 'text-danger',
  accent: 'text-accent',
  info: 'text-info',
} as const;

const toneBox = {
  neutral: 'border-border bg-background-alt',
  success: 'border-success/20 bg-success-bg',
  warning: 'border-warning/25 bg-warning-bg',
  danger: 'border-danger/20 bg-danger-bg',
  accent: 'border-accent/20 bg-accent-subtle',
  info: 'border-info/20 bg-info-bg',
} as const;

export type BadgeProps = {
  children: ReactNode;
  className?: string;
  tone?: keyof typeof toneText;
  flat?: boolean;
} & React.HTMLAttributes<HTMLSpanElement>;

export const badgeVariants = cva(
  'inline-flex min-h-[22px] items-center gap-1.5 text-sm leading-[var(--leading-snug)] font-medium whitespace-nowrap',
);

export function Badge({
  children,
  tone = 'neutral',
  flat,
  className,
  ...props
}: Readonly<BadgeProps>) {
  return (
    <span
      {...props}
      className={cn(
        badgeVariants(),
        toneText[tone],
        !flat && 'rounded-full border px-2.5 py-0.5 shadow-[inset_0_1px_0_color-mix(in_srgb,white_38%,transparent)]',
        !flat && toneBox[tone],
        className,
      )}
    >
      <span
        className={cn('size-1 rounded-full bg-current', tone === 'accent' && 'animate-pulse')}
        aria-hidden
      />
      {children}
    </span>
  );
}
