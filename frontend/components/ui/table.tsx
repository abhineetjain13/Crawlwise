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
  ...props
}: Readonly<
  { children: ReactNode; className?: string } & React.HTMLAttributes<HTMLTableSectionElement>
>) {
  return (
    <thead {...props} className={cn('[&_tr]:border-b', className)}>
      {children}
    </thead>
  );
}

export function TableBody({
  children,
  className,
  ...props
}: Readonly<
  { children: ReactNode; className?: string } & React.HTMLAttributes<HTMLTableSectionElement>
>) {
  return (
    <tbody {...props} className={cn('[&_tr:last-child]:border-0', className)}>
      {children}
    </tbody>
  );
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
  ...props
}: Readonly<
  { children: ReactNode; className?: string } & React.ThHTMLAttributes<HTMLTableCellElement>
>) {
  // Header: primary sans family with text-xs sizing, semibold, uppercase, wide tracking
  return (
    <th
      {...props}
      className={cn(
        'text-secondary h-8 px-4 text-left align-middle [font-family:var(--font-primary-family)] text-xs font-semibold tracking-wide uppercase',
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
  ...props
}: Readonly<
  { children: ReactNode; className?: string; colSpan?: number } & React.TdHTMLAttributes<HTMLTableCellElement>
>) {
  return (
    <td
      {...props}
      className={cn(
        'text-primary px-4 py-2 align-middle [font-family:var(--font-primary-family)] text-[length:var(--text-sm)] leading-normal font-normal',
        className,
      )}
      colSpan={colSpan}
    >
      {children}
    </td>
  );
}
