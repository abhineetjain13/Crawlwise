'use client';

import type { ReactNode } from 'react';

import { cn } from '../../lib/utils';

const toneText: Record<string, string> = {
  neutral: 'text-muted',
  success: 'text-success',
  warning: 'text-warning',
  danger: 'text-danger',
  accent: 'text-accent',
  info: 'text-info',
};

const toneBox: Record<string, string> = {
  neutral: 'border-border bg-background-alt',
  success: 'border-success/20 bg-success-bg',
  warning: 'border-warning/25 bg-warning-bg',
  danger: 'border-danger/20 bg-danger-bg',
  accent: 'border-accent/20 bg-accent-subtle',
  info: 'border-info/20 bg-info-bg',
};

export type BadgeProps = {
  children: ReactNode;
  className?: string;
  tone?: keyof typeof toneText;
  flat?: boolean;
} & React.HTMLAttributes<HTMLSpanElement>;

export function Badge({ children, tone = 'neutral', flat, className, ...props }: Readonly<BadgeProps>) {
  return (
    <span
      {...props}
      className={cn(
        'inline-flex min-h-[22px] items-center gap-1.5 text-sm font-medium leading-[var(--leading-snug)] whitespace-nowrap',
        toneText[tone],
        !flat && 'rounded-[var(--radius-md)] border px-2 py-0.5',
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
