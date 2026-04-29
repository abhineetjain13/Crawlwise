"use client";

import type { ReactNode } from "react";

import { cn } from "../../lib/utils";

export function Table({ children, className }: Readonly<{ children: ReactNode; className?: string }>) {
  return (
    <div className="relative w-full overflow-auto">
      <table className={cn("w-full caption-bottom leading-[var(--leading-relaxed)]", className)}>{children}</table>
    </div>
  );
}

export function TableHeader({ children, className }: Readonly<{ children: ReactNode; className?: string }>) {
  return <thead className={cn("[&_tr]:border-b", className)}>{children}</thead>;
}

export function TableBody({ children, className }: Readonly<{ children: ReactNode; className?: string }>) {
  return <tbody className={cn("[&_tr:last-child]:border-0", className)}>{children}</tbody>;
}

export function TableRow({
  children,
  className,
  ...props
}: Readonly<{ children: ReactNode; className?: string } & React.HTMLAttributes<HTMLTableRowElement>>) {
  return (
    <tr {...props} className={cn("border-b border-divider transition-colors hover:bg-background-alt", className)}>
      {children}
    </tr>
  );
}

export function TableHead({ children, className }: Readonly<{ children: ReactNode; className?: string }>) {
  return <th className={cn("h-9 px-4 text-left align-middle font-[family:var(--table-header-font-family)] text-[var(--table-header-font-size)] font-[var(--table-header-weight)] uppercase tracking-[var(--table-header-tracking)] text-muted", className)}>{children}</th>;
}

export function TableCell({
  children,
  className,
  colSpan,
}: Readonly<{ children: ReactNode; className?: string; colSpan?: number }>) {
  return (
    <td className={cn("p-4 align-middle text-[var(--table-font-size)] font-normal leading-[1.5] text-secondary", className)} colSpan={colSpan}>
      {children}
    </td>
  );
}
