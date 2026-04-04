"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { Route } from "next";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Activity, ArrowUpRight, Globe, Hash, LayoutDashboard, RefreshCw, Trash2 } from "lucide-react";

import { Badge, Button, StatCard } from "../../components/ui/primitives";
import { EmptyPanel, MetricGrid, MetricSkeleton, PageHeader, SectionHeader, SkeletonRows } from "../../components/ui/patterns";
import { api } from "../../lib/api";
import { ApiError } from "../../lib/api/client";
import type { CrawlRun } from "../../lib/api/types";

/* ─── Status helpers ─────────────────────────────────────────────────────── */
const STATUS_CONFIG: Record<string, { tone: "success" | "warning" | "danger" | "accent" | "neutral" | "info"; label: string }> = {
  completed:       { tone: "success",  label: "Completed"       },
  running:         { tone: "accent",   label: "Running"         },
  paused:          { tone: "warning",  label: "Paused"          },
  failed:          { tone: "danger",   label: "Failed"          },
  killed:          { tone: "danger",   label: "Killed"          },
  proxy_exhausted: { tone: "danger",   label: "Proxy Exhausted" },
  pending:         { tone: "neutral",  label: "Pending"         },
  degraded:        { tone: "warning",  label: "Degraded"        },
};

function statusTone(status: string) {
  return STATUS_CONFIG[status]?.tone ?? "neutral";
}

function statusLabel(status: string) {
  return STATUS_CONFIG[status]?.label ?? status;
}

/* ─── Domain bar ─────────────────────────────────────────────────────────── */
function DomainBar({
  domain,
  count,
  max,
}: Readonly<{ domain: string; count: number; max: number }>) {
  const pct = max > 0 ? Math.round((count / max) * 100) : 0;
  return (
    <div className="flex items-center gap-3 py-1.5">
      <span
        className="min-w-0 flex-1 truncate text-[12px] font-medium text-[var(--text-secondary)]"
        title={domain}
      >
        {domain}
      </span>
      <div className="flex items-center gap-2">
        <div className="h-1.5 w-28 overflow-hidden rounded-full bg-[var(--border)]">
          <div
            className="h-full rounded-full bg-[var(--metric-domains-color)] transition-[width] duration-700"
            style={{ width: `${pct}%` }}
          />
        </div>
        <span className="w-7 text-right text-[11px] tabular-nums text-[var(--text-muted)]">{count}</span>
      </div>
    </div>
  );
}

/* ─── Status distribution row ────────────────────────────────────────────── */
function StatusSegment({
  status,
  count,
  total,
}: Readonly<{ status: string; count: number; total: number }>) {
  const pct = total > 0 ? (count / total) * 100 : 0;
  if (pct < 0.5) return null;
  const colorMap: Record<string, string> = {
    completed:       "var(--success)",
    running:         "var(--accent)",
    failed:          "var(--danger)",
    killed:          "var(--danger)",
    paused:          "var(--warning)",
    proxy_exhausted: "var(--warning)",
    pending:         "var(--text-muted)",
  };
  const color = colorMap[status] ?? "var(--text-muted)";
  return (
    <div
      className="h-full first:rounded-l-full last:rounded-r-full"
      style={{ width: `${pct}%`, background: color }}
      title={`${statusLabel(status)}: ${count}`}
    />
  );
}

/* ─── Run activity row ───────────────────────────────────────────────────── */
function RunActivityRow({ run }: Readonly<{ run: CrawlRun }>) {
  const domain = getDomain(run.url);
  const recordCount = run.result_summary?.record_count ?? 0;

  return (
    <Link
      href={`/crawl?run_id=${run.id}` as Route}
      className="no-underline group flex items-center gap-3 rounded-[var(--radius-md)] px-2 py-2 transition-colors hover:bg-[var(--bg-elevated)]"
    >
      {/* Status dot */}
      <span
        className="size-1.5 shrink-0 rounded-full"
        style={{ background: `var(--${statusTone(run.status) === "success" ? "success" : statusTone(run.status) === "danger" ? "danger" : statusTone(run.status) === "warning" ? "warning" : "accent"})` }}
      />
      {/* Domain */}
      <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-[var(--text-primary)] group-hover:text-[var(--accent)] transition-colors">
        {domain || `Run #${run.id}`}
      </span>
      {/* Record count */}
      {typeof recordCount === "number" && recordCount > 0 ? (
        <span className="shrink-0 text-[11px] tabular-nums text-[var(--text-muted)]">
          {recordCount.toLocaleString()} rec
        </span>
      ) : null}
      {/* Badge */}
      <Badge tone={statusTone(run.status)}>{statusLabel(run.status)}</Badge>
      {/* Arrow */}
      <ArrowUpRight className="size-3 shrink-0 text-[var(--text-muted)] opacity-0 group-hover:opacity-100 transition-opacity" />
    </Link>
  );
}

/* ─── Page ───────────────────────────────────────────────────────────────── */
export default function DashboardPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { data, isLoading, refetch } = useQuery({ queryKey: ["dashboard"], queryFn: api.dashboard });
  const meQuery = useQuery({ queryKey: ["me"], queryFn: api.me, retry: false });
  const [isResetting, setIsResetting] = useState(false);
  const [resetError, setResetError] = useState("");
  const [isRefreshing, setIsRefreshing] = useState(false);

  async function handleRefresh() {
    setIsRefreshing(true);
    try {
      await refetch();
    } finally {
      setIsRefreshing(false);
    }
  }

  async function handleResetData() {
    const confirmed = globalThis.confirm(
      "Delete and reset all app data? This clears runs, records, logs, artifacts, cookies, selectors, and domain mappings.",
    );
    if (!confirmed) return;
    setIsResetting(true);
    setResetError("");
    try {
      await api.resetApplicationData();
      await queryClient.invalidateQueries();
      await refetch();
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        const detail =
          typeof error.body === "string"
            ? error.body.trim()
            : error.body
              ? JSON.stringify(error.body)
              : "";
        const message =
          detail === "Not authenticated"
            ? "You are signed out. Sign in as an admin to reset data."
            : detail === "Invalid token" || detail === "Session expired"
              ? "Your session expired. Sign in again to continue."
              : detail
                ? `Reset failed: ${detail}`
                : "Your session expired. Sign in again to continue.";
        setResetError(message);
        globalThis.alert(message);
        router.replace("/login");
        return;
      }

      const message =
        error instanceof ApiError && error.status === 403
            ? "Reset Demo is admin-only."
            : error instanceof Error
              ? error.message
              : "Failed to reset application data.";
      setResetError(message);
      globalThis.alert(message);
    } finally {
      setIsResetting(false);
    }
  }

  /* Derived stats */
  const totalDomains = data?.top_domains?.length ?? 0;
  const maxDomainCount = data?.top_domains?.[0]?.count ?? 1;

  /* Status distribution */
  const statusCounts = (data?.recent_runs ?? []).reduce<Record<string, number>>((acc, run) => {
    acc[run.status] = (acc[run.status] ?? 0) + 1;
    return acc;
  }, {});
  const totalInDistribution = Object.values(statusCounts).reduce((a, b) => a + b, 0);

  return (
    <div className="space-y-5">
      <PageHeader
        title="Dashboard"
        actions={
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => void handleRefresh()}
              disabled={isRefreshing || isLoading}
            >
              <RefreshCw className={`size-3.5 ${isRefreshing ? "animate-spin-slow" : ""}`} />
              {isRefreshing ? "Refreshing…" : "Refresh"}
            </Button>
            {meQuery.data?.role === "admin" ? (
              <Button
                type="button"
                onClick={() => void handleResetData()}
                disabled={isResetting || meQuery.isLoading}
                variant="danger"
                size="sm"
              >
                <Trash2 className="size-3.5" />
                {isResetting ? "Resetting…" : "Reset Demo"}
              </Button>
            ) : null}
          </div>
        }
      />

      {/* ── KPI tiles ── */}
      {isLoading ? (
        <MetricGrid>
          <MetricSkeleton />
          <MetricSkeleton />
          <MetricSkeleton />
          <MetricSkeleton />
        </MetricGrid>
      ) : (
        <MetricGrid>
          <StatCard
            label="Total Runs"
            value={(data?.total_runs ?? 0).toLocaleString()}
            icon={<Hash className="size-3.5" />}
            stripeColor="var(--metric-runs-color)"
            sub="All crawl jobs"
          />
          <StatCard
            label="Active Runs"
            value={(data?.active_runs ?? 0).toLocaleString()}
            icon={<Activity className="size-3.5" />}
            stripeColor="var(--metric-active-color)"
            sub={data?.active_runs ? "Running now" : "None in progress"}
          />
          <StatCard
            label="Total Records"
            value={(data?.total_records ?? 0).toLocaleString()}
            icon={<LayoutDashboard className="size-3.5" />}
            stripeColor="var(--metric-records-color)"
            sub="Extracted rows"
          />
          <StatCard
            label="Unique Domains"
            value={totalDomains.toLocaleString()}
            icon={<Globe className="size-3.5" />}
            stripeColor="var(--metric-domains-color)"
            sub="Crawled sites"
          />
        </MetricGrid>
      )}

      {resetError ? (
        <div className="rounded-[var(--radius-lg)] border border-[var(--danger-bg)] bg-[var(--danger-bg)] px-4 py-3 text-[13px] text-[var(--danger)]">
          {resetError}
        </div>
      ) : null}

      {/* ── Status distribution bar ── */}
      {!isLoading && totalInDistribution > 0 ? (
        <div className="space-y-2.5">
          <div className="flex h-2 w-full overflow-hidden rounded-full bg-[var(--border)] gap-px">
            {Object.entries(statusCounts)
              .sort(([, a], [, b]) => b - a)
              .map(([status, count]) => (
                <StatusSegment key={status} status={status} count={count} total={totalInDistribution} />
              ))}
          </div>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
            {Object.entries(statusCounts)
              .sort(([, a], [, b]) => b - a)
              .map(([status, count]) => (
                <div key={status} className="flex items-center gap-1.5 text-[11px] text-[var(--text-muted)]">
                  <Badge tone={statusTone(status)}>{statusLabel(status)}</Badge>
                  <span className="tabular-nums font-medium">{count}</span>
                </div>
              ))}
          </div>
        </div>
      ) : null}

      {/* ── Lower grid ── */}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.3fr)_minmax(0,0.7fr)]">
        {/* Recent runs */}
        <div className="rounded-[var(--radius-xl)] border border-[var(--border)] bg-[var(--bg-panel)] shadow-[var(--shadow-card-value)]">
          <div className="flex items-center justify-between border-b border-[var(--border)] px-4 py-3">
            <SectionHeader title="Recent Runs" description="Last 10 jobs" />
            <Link href="/runs" className="no-underline text-[12px] font-medium text-[var(--accent)] hover:underline">
              View all
            </Link>
          </div>
          <div className="p-2">
            {isLoading ? (
              <SkeletonRows count={6} className="p-2" />
            ) : data?.recent_runs?.length ? (
              data.recent_runs.slice(0, 10).map((run) => (
                <RunActivityRow key={run.id} run={run} />
              ))
            ) : (
              <div className="py-4">
                <EmptyPanel title="No runs yet" description="Submit a crawl to see activity here." />
              </div>
            )}
          </div>
        </div>

        {/* Top domains */}
        <div className="rounded-[var(--radius-xl)] border border-[var(--border)] bg-[var(--bg-panel)] shadow-[var(--shadow-card-value)]">
          <div className="border-b border-[var(--border)] px-4 py-3">
            <SectionHeader title="Top Domains" description="By run count" />
          </div>
          <div className="p-4">
            {isLoading ? (
              <SkeletonRows count={5} />
            ) : data?.top_domains?.length ? (
              <div>
                {data.top_domains.map((item) => (
                  <DomainBar
                    key={item.domain}
                    domain={item.domain}
                    count={item.count}
                    max={maxDomainCount}
                  />
                ))}
              </div>
            ) : (
              <p className="py-2 text-[12px] text-[var(--text-muted)]">No domain data yet.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function getDomain(url: string) {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}
