"use client";

import type { CSSProperties, ReactNode } from "react";

function colorWithAlpha(color: string | undefined, alphaPercent: number) {
  const normalized = String(color ?? "").trim();
  if (!normalized) {
    return "var(--accent-subtle)";
  }
  return `color-mix(in srgb, ${normalized} ${alphaPercent}%, transparent)`;
}

export function Metric({
  label,
  value,
  loading = false,
}: Readonly<{ label: string; value: ReactNode; loading?: boolean }>) {
  return (
    <div className="relative space-y-1.5 overflow-hidden rounded-[var(--radius-xl)] border border-border bg-panel p-4 shadow-card transition-[border-color,box-shadow,transform] hover:-translate-y-0.5 hover:border-border-strong hover:shadow-elevated">
      <p className="text-sm font-medium text-secondary">{label}</p>
      {loading ? (
        <div className="skeleton h-7 w-20" aria-hidden />
      ) : (
        <div className="mono-body font-semibold leading-none text-foreground tabular-nums" style={{ fontSize: "var(--text-3xl)" }}>{value}</div>
      )}
    </div>
  );
}

export function StatCard({
  label,
  value,
  icon,
  iconColor,
  stripeColor,
  sub,
  loading = false,
}: Readonly<{
  label: string;
  value: ReactNode;
  icon?: ReactNode;
  iconColor?: string;
  stripeColor?: string;
  sub?: ReactNode;
  loading?: boolean;
}>) {
  return (
    <div className="relative overflow-hidden rounded-[var(--radius-xl)] border border-border bg-panel p-4 shadow-card transition-[border-color,box-shadow,transform] hover:-translate-y-0.5 hover:border-border-strong hover:shadow-elevated">
      <div className="absolute inset-x-0 top-0 h-0.5" style={{ background: stripeColor ?? "var(--accent)" }} aria-hidden />
      <div className="mb-2.5 flex items-center justify-between gap-2">
        <p className="text-sm font-medium text-secondary">{label}</p>
        {icon ? (
          <div
            className="grid size-[22px] place-items-center rounded-md"
            style={{ background: colorWithAlpha(stripeColor, 10), color: iconColor ?? stripeColor ?? "var(--accent)" } as CSSProperties}
          >
            {icon}
          </div>
        ) : null}
      </div>
      {loading ? (
        <div className="mt-2.5 skeleton h-9 w-28" aria-hidden />
      ) : (
        <div className="mono-body mt-2 font-semibold leading-none text-foreground tabular-nums" style={{ fontSize: "var(--text-3xl)" }}>{value}</div>
      )}
      {sub && !loading ? <div className="mt-1.5 text-sm leading-[var(--leading-normal)] text-muted">{sub}</div> : null}
    </div>
  );
}
