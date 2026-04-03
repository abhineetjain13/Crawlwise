"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { Badge, Button, Card, Input } from "../../components/ui/primitives";
import { EmptyPanel, PageHeader } from "../../components/ui/patterns";
import { api } from "../../lib/api";
import type { CrawlRun, RunStatus } from "../../lib/api/types";
import { cn } from "../../lib/utils";

type StatusFilter = "" | RunStatus;

export default function RunsPage() {
  const [domainFilter, setDomainFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("");
  const [appliedDomainFilter, setAppliedDomainFilter] = useState("");
  const [appliedStatusFilter, setAppliedStatusFilter] = useState<StatusFilter>("");

  const query = useQuery({
    queryKey: ["runs", appliedDomainFilter, appliedStatusFilter],
    queryFn: () =>
      api.listCrawls({
        limit: 50,
        status: appliedStatusFilter || undefined,
        url_search: appliedDomainFilter || undefined,
      }),
  });

  const visibleRuns = query.data?.items?.slice(0, 50) ?? [];

  function applyFilters() {
    setAppliedDomainFilter(domainFilter.trim());
    setAppliedStatusFilter(statusFilter);
  }

  function resetFilters() {
    setDomainFilter("");
    setStatusFilter("");
    setAppliedDomainFilter("");
    setAppliedStatusFilter("");
  }

  return (
    <div className="space-y-4">
      <PageHeader title="Run History" description="Review saved runs, outputs, and statuses." />

      <Card className="space-y-4">
        <div className="flex flex-col gap-2 lg:flex-row lg:items-center">
          <div className="flex-1">
            <Input
              placeholder="Filter by domain or URL..."
              value={domainFilter}
              onChange={(event) => setDomainFilter(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  applyFilters();
                }
              }}
            />
          </div>
          <select
            aria-label="Filter by status"
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value as StatusFilter)}
            className="focus-ring h-9 min-w-40 rounded-md border border-border bg-background px-3 text-[13px] text-foreground transition hover:border-border-strong"
          >
            <option value="">All statuses</option>
            <option value="completed">Completed</option>
            <option value="degraded">Degraded</option>
            <option value="failed">Failed</option>
            <option value="cancelled">Cancelled</option>
            <option value="running">Running</option>
            <option value="pending">Pending</option>
          </select>
          <Button onClick={applyFilters}>Filter</Button>
          <Button variant="ghost" onClick={resetFilters}>Reset</Button>
        </div>

        {query.isError ? (
          <div className="rounded-md border border-danger/20 bg-danger/5 px-4 py-4 text-[13px] text-danger">
            Unable to load run history.
          </div>
        ) : query.isLoading ? (
          <div className="animate-shimmer rounded-md border border-border px-4 py-8 text-center text-[13px] text-muted">
            Loading runs...
          </div>
        ) : visibleRuns.length ? (
          <div className="overflow-auto rounded-md border border-border">
            <table className="compact-data-table">
              <thead>
                <tr>
                  <th>Domain</th>
                  <th>URL</th>
                  <th>Mode</th>
                  <th>Status</th>
                  <th>Records</th>
                  <th>Date</th>
                </tr>
              </thead>
              <tbody>
                {visibleRuns.map((run, index) => (
                  <RunRow key={run.id} run={run} index={index} />
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyPanel title="No runs found" description="Submitted crawls will appear here." />
        )}
      </Card>
    </div>
  );
}

function RunRow({ run, index }: Readonly<{ run: CrawlRun; index: number }>) {
  const recordCount = typeof run.result_summary?.record_count === "number" ? run.result_summary.record_count : 0;

  return (
    <tr
      className="animate-fade-in"
      style={{ animationDelay: `${Math.min(index * 30, 300)}ms` }}
    >
      <td>
        <Link href={`/runs/${run.id}`} className="block font-medium text-foreground hover:text-accent transition-colors">
          {getDomain(run.url)}
        </Link>
      </td>
      <td>
        <a
          href={run.url}
          target="_blank"
          rel="noreferrer"
          className="block max-w-[380px] truncate font-mono text-[11px] text-muted hover:text-accent transition-colors"
          title={run.url}
        >
          {run.url}
        </a>
      </td>
      <td className="text-muted">{formatRunType(run.run_type)}</td>
      <td><StatusBadge status={run.status} /></td>
      <td className={cn("tabular-nums", recordCount > 0 ? "text-foreground" : "text-muted")}>{recordCount}</td>
      <td className="text-muted">{formatDate(run.created_at)}</td>
    </tr>
  );
}

function StatusBadge({ status }: Readonly<{ status: string }>) {
  const tone = getStatusTone(status);
  return <Badge tone={tone}>{status}</Badge>;
}

function getStatusTone(status: string) {
  if (status === "completed") return "success" as const;
  if (status === "degraded") return "warning" as const;
  if (status === "failed" || status === "cancelled") return "danger" as const;
  return "neutral" as const;
}

function getDomain(url: string) {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}

function formatRunType(value: string) {
  if (value === "crawl") return "Single";
  if (value === "batch") return "Batch";
  if (value === "csv") return "CSV";
  return value;
}

function formatDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString([], {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}
