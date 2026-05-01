'use client';

import type { ReactNode } from 'react';
import { cva, type VariantProps } from 'class-variance-authority';

import { cn } from '../../lib/utils';

export const alertVariants = cva('alert-surface', {
  variants: {
    tone: {
      danger: 'alert-danger',
      warning: 'alert-warning',
      neutral: 'alert-neutral',
    },
  },
  defaultVariants: {
    tone: 'danger',
  },
});

export type InlineAlertProps = {
  message: ReactNode;
  className?: string;
} & VariantProps<typeof alertVariants>;

export function InlineAlert({ message, tone, className }: Readonly<InlineAlertProps>) {
  if (!message) return null;
  return (
    <div role="alert" className={cn(alertVariants({ tone }), className)}>
      {message}
    </div>
  );
}
