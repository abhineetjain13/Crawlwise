'use client';

import type { ReactNode } from 'react';

import { cn } from '../../lib/utils';

export function Table({
  children,
  className,
  wrapperClassName,
}: Readonly<{ children: ReactNode; className?: string; wrapperClassName?: string }>) {
  return (
    <div className={cn('relative w-full overflow-auto', wrapperClassName)}>
      <table className={cn('w-full caption-bottom', className)}>{children}</table>
    </div>
  );
}

export function TableHeader({
  children,
  className,
}: Readonly<{ children: ReactNode; className?: string }>) {
  return <thead className={cn('[&_tr]:border-b', className)}>{children}</thead>;
}

export function TableBody({
  children,
  className,
}: Readonly<{ children: ReactNode; className?: string }>) {
  return <tbody className={cn('[&_tr:last-child]:border-0', className)}>{children}</tbody>;
}

export function TableRow({
  children,
  className,
  ...props
}: Readonly<
  { children: ReactNode; className?: string } & React.HTMLAttributes<HTMLTableRowElement>
>) {
  return (
    <tr
      {...props}
      className={cn(
        // Hairline bottom border; fades on last row via TableBody selector
        'border-border border-b transition-colors',
        // Hover: subtle accent-tinted bg works in both themes
        'hover:bg-[color-mix(in_srgb,var(--accent)_5%,var(--bg-panel))]',
        className,
      )}
    >
      {children}
    </tr>
  );
}

export function TableHead({
  children,
  className,
}: Readonly<{ children: ReactNode; className?: string }>) {
  // Header: primary sans family with text-xs sizing, semibold, uppercase, wide tracking
  return (
    <th
      className={cn(
        'text-secondary h-8 px-4 text-left align-middle text-xs font-semibold tracking-wide uppercase [font-family:var(--font-primary-family)]',
        className,
      )}
    >
      {children}
    </th>
  );
}

export function TableCell({
  children,
  className,
  colSpan,
}: Readonly<{ children: ReactNode; className?: string; colSpan?: number }>) {
  return (
    <td
      className={cn(
        'text-primary px-4 py-2 align-middle leading-normal font-normal [font-family:var(--font-primary-family)] text-[length:var(--text-sm)]',
        className,
      )}
      colSpan={colSpan}
    >
      {children}
    </td>
  );
}
