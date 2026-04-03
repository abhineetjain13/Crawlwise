"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { Badge, Button, Card, Input } from "../../components/ui/primitives";
import { EmptyPanel, PageHeader, SectionHeader } from "../../components/ui/patterns";
import { api } from "../../lib/api";
import type { CrawlRun } from "../../lib/api/types";

type StatusFilter = "" | "completed" | "failed" | "cancelled" | "running" | "pending";

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

  const runs = query.data?.items ?? [];
  const visibleRuns = useMemo(() => runs.slice(0, 50), [runs]);

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
        <SectionHeader title="History" />

        <div className="flex flex-col gap-2.5 lg:flex-row lg:items-center">
          <div className="flex-1">
            <Input
              placeholder="Filter by domain or URL"
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
            className="h-10 min-w-44 rounded-lg border border-border bg-transparent px-3 text-sm text-foreground outline-none transition focus:border-brand focus:ring-2 focus:ring-brand/20"
          >
            <option value="">All statuses</option>
            <option value="completed">Completed</option>
            <option value="failed">Failed</option>
            <option value="cancelled">Cancelled</option>
            <option value="running">Running</option>
            <option value="pending">Pending</option>
          </select>
          <Button onClick={applyFilters}>Filter</Button>
          <Button variant="secondary" onClick={resetFilters}>Reset</Button>
        </div>

        {query.isError ? (
          <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-6 text-sm text-red-700 dark:text-red-300">
            Unable to load run history.
          </div>
        ) : query.isLoading ? (
          <div className="rounded-lg border border-border/60 bg-panel-strong/30 px-4 py-6 text-sm text-muted">Loading…</div>
        ) : visibleRuns.length ? (
          <div className="overflow-auto rounded-lg border border-border/70">
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
                {visibleRuns.map((run) => (
                  <RunRow key={run.id} run={run} />
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

function RunRow({ run }: Readonly<{ run: CrawlRun }>) {
  const recordCount = typeof run.result_summary?.record_count === "number" ? run.result_summary.record_count : 0;

  return (
    <tr>
      <td>
        <Link href={`/runs/${run.id}`} className="block font-medium text-foreground">
          {getDomain(run.url)}
        </Link>
      </td>
      <td>
        <a
          href={run.url}
          target="_blank"
          rel="noreferrer"
          className="block max-w-[420px] truncate font-mono text-[11px] text-brand hover:underline"
          title={run.url}
        >
          {run.url}
        </a>
      </td>
      <td>{formatRunType(run.run_type)}</td>
      <td><StatusBadge status={run.status} /></td>
      <td>{recordCount}</td>
      <td>{formatDate(run.created_at)}</td>
    </tr>
  );
}

function StatusBadge({ status }: Readonly<{ status: string }>) {
  const tone = status === "completed" ? "success" : status === "failed" || status === "cancelled" ? "warning" : "neutral";
  return <Badge tone={tone}>{status}</Badge>;
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
