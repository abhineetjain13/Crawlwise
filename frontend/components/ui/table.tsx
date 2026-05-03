'use client';

import type { ReactNode } from 'react';

import { cn } from '../../lib/utils';

export function Table({
  children,
  className,
}: Readonly<{ children: ReactNode; className?: string }>) {
  return (
    <div className="relative w-full overflow-auto">
      <table className={cn('w-full caption-bottom', className)}>
        {children}
      </table>
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
      className={cn('border-divider hover:bg-accent/[0.04] border-b transition-colors', className)}
    >
      {children}
    </tr>
  );
}

export function TableHead({
  children,
  className,
}: Readonly<{ children: ReactNode; className?: string }>) {
  return (
    <th
      className={cn('type-label-mono syntax-key h-9 px-4 text-left align-middle', className)}
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
      className={cn('type-body py-1.5 px-4 align-middle', className)}
      colSpan={colSpan}
    >
      {children}
    </td>
  );
}
