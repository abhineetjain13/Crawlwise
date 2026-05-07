'use client';

import type { ComponentPropsWithoutRef, ReactNode } from 'react';
import { cva, type VariantProps } from 'class-variance-authority';

import { cn } from '../../lib/utils';

export const cardVariants = cva(
  'relative overflow-hidden rounded-[var(--radius-xl)] border border-border card-gradient p-5 transition-[border-color] hover:border-border-strong',
  {
    variants: {
      animate: {
        true: 'animate-fade-in',
        false: '',
      },
    },
    defaultVariants: {
      animate: false,
    },
  },
);

export type CardProps = ComponentPropsWithoutRef<'section'> &
  VariantProps<typeof cardVariants> & {
    children: ReactNode;
  };

export function Card({ children, className, animate, ...props }: Readonly<CardProps>) {
  return (
    <section {...props} className={cn(cardVariants({ animate }), className)}>
      {children}
    </section>
  );
}
