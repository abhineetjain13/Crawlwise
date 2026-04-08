"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { Route } from "next";
import Link from "next/link";
import { useState } from "react";
import { Activity, ArrowUpRight, Globe, Hash, LayoutDashboard, RefreshCw } from "lucide-react";

import { Badge, Button, StatCard } from "../../components/ui/primitives";
import {
  DataRegionEmpty,
  EmptyPanel,
  MetricGrid,
  MetricSkeleton,
  PageHeader,
  SectionHeader,
  SkeletonRows,
  StatusDot,
  SurfacePanel,
} from "../../components/ui/patterns";
import { api } from "../../lib/api";
import type { CrawlRun } from "../../lib/api/types";
import { getDomain } from "../../lib/format/domain";
import {
  dashboardStatusBarColor,
  dashboardStatusLabel as statusLabel,
  dashboardStatusTone as statusTone,
} from "../../lib/ui/status";

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
  const color = dashboardStatusBarColor(status);
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
      <StatusDot tone={statusTone(run.status)} />
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
  const queryClient = useQueryClient();
  const { data, isLoading, refetch } = useQuery({ queryKey: ["dashboard"], queryFn: api.dashboard });
  const [isRefreshing, setIsRefreshing] = useState(false);

  async function handleRefresh() {
    setIsRefreshing(true);
    try {
      await refetch();
    } finally {
      setIsRefreshing(false);
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
          />
          <StatCard
            label="Active Runs"
            value={(data?.active_runs ?? 0).toLocaleString()}
            icon={<Activity className="size-3.5" />}
            stripeColor="var(--metric-active-color)"
          />
          <StatCard
            label="Total Records"
            value={(data?.total_records ?? 0).toLocaleString()}
            icon={<LayoutDashboard className="size-3.5" />}
            stripeColor="var(--metric-records-color)"
          />
          <StatCard
            label="Unique Domains"
            value={totalDomains.toLocaleString()}
            icon={<Globe className="size-3.5" />}
            stripeColor="var(--metric-domains-color)"
          />
        </MetricGrid>
      )}

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
        <SurfacePanel>
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
        </SurfacePanel>

        {/* Top domains */}
        <SurfacePanel>
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
              <DataRegionEmpty title="No domain data yet" description="Run crawls to build domain distribution." className="px-0 py-2" />
            )}
          </div>
        </SurfacePanel>
      </div>
    </div>
  );
}

