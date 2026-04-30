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
  return (
    <th
      className={cn("h-9 px-4 text-left align-middle uppercase text-muted", className)}
      style={{
        fontFamily: "var(--table-header-font-family)",
        fontSize: "var(--table-header-font-size)",
        fontWeight: "var(--table-header-weight)",
        letterSpacing: "var(--table-header-tracking)",
      }}
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
    <td className={cn("p-4 align-middle font-normal leading-[1.5] text-secondary", className)} style={{ fontSize: "var(--table-font-size)" }} colSpan={colSpan}>
      {children}
    </td>
  );
}
