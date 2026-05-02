'use client';

import { useQuery } from '@tanstack/react-query';
import type { Route } from 'next';
import Link from 'next/link';
import { useState } from 'react';
import { Activity, ArrowUpRight, Globe, Hash, LayoutDashboard, RefreshCw } from 'lucide-react';
import { Badge, Button, StatCard } from '../../components/ui/primitives';
import {
  DataRegionEmpty,
  EmptyPanel,
  MetricPulse,
  MetricPulseItem,
  MetricPulseSkeleton,
  PageHeader,
  SkeletonRows,
  StatusDot,
  SurfaceSection,
} from '../../components/ui/patterns';
import { api } from '../../lib/api';
import type { CrawlRun } from '../../lib/api/types';
import { getDomain } from '../../lib/format/domain';
import {
  dashboardStatusBarColor,
  dashboardStatusLabel as statusLabel,
  dashboardStatusTone as statusTone,
  runExecutionLabel,
  runExecutionTone,
} from '../../lib/ui/status';

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
        className="mono-body text-secondary min-w-0 flex-1 truncate text-xs leading-[1.4] font-normal"
        title={domain}
      >
        {domain}
      </span>
      <div className="bg-border h-1.5 w-28 overflow-hidden rounded-full">
        <div
          className="bg-metric-domains h-full rounded-full transition-[width] duration-700"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-muted w-7 text-right text-xs leading-[var(--leading-normal)] font-normal tabular-nums">
        {count}
      </span>
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
      className="group hover:bg-background-elevated flex items-center gap-3 rounded-[var(--radius-md)] px-2 py-2 no-underline transition-colors"
    >
      <StatusDot tone={runExecutionTone(run.status, run.result_summary)} />
      <span className="mono-body text-primary group-hover:text-accent min-w-0 flex-1 truncate text-xs leading-[1.4] font-normal transition-colors">
        {domain || `Run #${run.id}`}
      </span>
      <span className="text-muted text-xs leading-[var(--leading-normal)] font-normal tabular-nums">
        {recordCount.toLocaleString()} rec
      </span>
      <Badge tone={runExecutionTone(run.status, run.result_summary)}>
        {runExecutionLabel(run.status, run.result_summary)}
      </Badge>
      <ArrowUpRight className="text-muted size-3 shrink-0 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100" />
    </Link>
  );
}

/* ─── Page ───────────────────────────────────────────────────────────────── */
export default function DashboardPage() {
  const { data, isLoading, refetch } = useQuery({
    queryKey: ['dashboard'],
    queryFn: api.dashboard,
  });
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
  const sortedStatusEntries = Object.entries(statusCounts).sort(([, a], [, b]) => b - a);

  return (
    <div className="page-stack-lg">
      <PageHeader
        title="Dashboard"
        actions={
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="primary"
              className="h-[var(--control-height)]"
              onClick={() => void handleRefresh()}
              disabled={isRefreshing || isLoading}
            >
              <RefreshCw className={`size-3.5 ${isRefreshing ? 'animate-spin-slow' : ''}`} />
              {isRefreshing ? 'Refreshing…' : 'Refresh'}
            </Button>
          </div>
        }
      />

      {/* ── Metric Pulse (Unified) ── */}
      {isLoading ? (
        <MetricPulse>
          <MetricPulseSkeleton />
          <MetricPulseSkeleton />
          <MetricPulseSkeleton />
          <MetricPulseSkeleton />
        </MetricPulse>
      ) : (
        <MetricPulse>
          <MetricPulseItem
            label="Total Runs"
            value={(data?.total_runs ?? 0).toLocaleString()}
            icon={Hash}
          />
          <MetricPulseItem
            label="Active Runs"
            value={(data?.active_runs ?? 0).toLocaleString()}
            icon={Activity}
            pulse={Boolean(data?.active_runs)}
          />
          <MetricPulseItem
            label="Total Records"
            value={(data?.total_records ?? 0).toLocaleString()}
            icon={LayoutDashboard}
          />
          <MetricPulseItem
            label="Unique Domains"
            value={totalDomains.toLocaleString()}
            icon={Globe}
          />
        </MetricPulse>
      )}

      {/* ── Status distribution bar ── */}
      {!isLoading && totalInDistribution > 0 ? (
        <div className="space-y-2.5">
          <div className="bg-border flex h-2 w-full gap-px overflow-hidden rounded-full">
            {sortedStatusEntries.map(([status, count]) => (
              <StatusSegment
                key={status}
                status={status}
                count={count}
                total={totalInDistribution}
              />
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
            {sortedStatusEntries.map(([status, count]) => (
              <div
                key={status}
                className="text-muted flex items-center gap-1.5 text-sm leading-[var(--leading-normal)] font-normal"
              >
                <Badge tone={statusTone(status)}>{statusLabel(status)}</Badge>
                <span className="text-foreground text-sm leading-[var(--leading-normal)] font-medium tabular-nums">
                  {count}
                </span>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {/* ── Lower grid ── */}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.3fr)_minmax(0,0.7fr)]">
        {/* Recent runs */}
        <SurfaceSection
          title="Recent Runs"
          description="Last 10 jobs"
          action={
            <Link
              href="/runs"
              className="link-accent text-sm leading-[1.4] font-medium no-underline hover:underline"
            >
              View all
            </Link>
          }
          bodyClassName="p-2"
        >
          {isLoading ? (
            <SkeletonRows count={6} className="p-2" />
          ) : data?.recent_runs?.length ? (
            data.recent_runs.slice(0, 10).map((run) => <RunActivityRow key={run.id} run={run} />)
          ) : (
            <div className="py-4">
              <EmptyPanel title="No runs yet" description="Submit a crawl to see activity here." />
            </div>
          )}
        </SurfaceSection>
        {/* Top domains */}
        <SurfaceSection title="Top Domains" description="By run count">
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
            <DataRegionEmpty
              title="No domain data yet"
              description="Run crawls to build domain distribution."
              className="px-0 py-2"
            />
          )}
        </SurfaceSection>
      </div>
    </div>
  );
}
