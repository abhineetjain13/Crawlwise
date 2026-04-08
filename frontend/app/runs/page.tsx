"use client";

import Link from "next/link";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, Plus, Trash2 } from "lucide-react";

import { Badge, Button, Input } from "../../components/ui/primitives";
import { EmptyPanel, InlineAlert, PageHeader, SkeletonRows } from "../../components/ui/patterns";
import { api } from "../../lib/api";
import type { CrawlRun, RunStatus } from "../../lib/api/types";
import { formatRunsDate as formatDate } from "../../lib/format/date";
import { getDomain } from "../../lib/format/domain";
import { runsStatusDot as statusDot, runsStatusTone as statusTone } from "../../lib/ui/status";
import { cn } from "../../lib/utils";

type StatusFilter = "" | RunStatus;


/* ─── Run row ────────────────────────────────────────────────────────────── */
function RunRow({
  run,
  pendingDelete,
  onDelete,
}: Readonly<{ run: CrawlRun; pendingDelete: boolean; onDelete: () => void }>) {
  const recordCount = typeof run.result_summary?.record_count === "number" ? run.result_summary.record_count : 0;
  const canDelete = !["pending", "running", "paused"].includes(run.status);
  const domain = getDomain(run.url);

  return (
    <tr className="group">
      {/* Domain + URL */}
      <td>
        <div className="flex items-center gap-2.5">
          <span
            className="size-1.5 shrink-0 rounded-full"
            style={{ background: statusDot(run.status) }}
          />
          <div className="min-w-0">
            <Link
              href={`/crawl?run_id=${run.id}`}
              className="no-underline block truncate text-[13px] font-medium text-[var(--text-primary)] hover:text-[var(--accent)] transition-colors max-w-lg"
            >
              {domain || `Run #${run.id}`}
            </Link>
            <a
              href={run.url}
              target="_blank"
              rel="noreferrer"
              className="no-underline block truncate font-mono text-[10px] text-[var(--text-muted)] hover:text-[var(--accent)] transition-colors max-w-lg"
              title={run.url}
            >
              {run.url}
            </a>
          </div>
        </div>
      </td>

      {/* Mode */}
      <td>
        <span className="rounded-[3px] bg-[var(--bg-elevated)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--text-muted)]">
          {formatRunType(run.run_type)}
        </span>
      </td>

      {/* Status */}
      <td>
        <Badge tone={statusTone(run.status)}>{run.status.replace(/_/g, " ")}</Badge>
      </td>

      {/* Records */}
      <td>
        <span className={cn("tabular-nums text-[12px]", recordCount > 0 ? "text-[var(--text-primary)] font-medium" : "text-[var(--text-muted)]")}>
          {recordCount > 0 ? recordCount.toLocaleString() : "—"}
        </span>
      </td>

      {/* Date */}
      <td>
        <span className="text-[11px] text-[var(--text-muted)]">{formatDate(run.created_at)}</span>
      </td>

      {/* Actions */}
      <td className="text-right whitespace-nowrap">
        <div className="flex items-center justify-end gap-1.5 px-0 opacity-0 group-hover:opacity-100 transition-opacity">
          <Link
            href={`/crawl?run_id=${run.id}`}
            className="no-underline focus-ring inline-flex h-7 items-center gap-1 rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-panel)] px-2.5 text-[12px] font-medium text-[var(--text-primary)] transition-colors hover:border-[var(--border-strong)] hover:bg-[var(--bg-elevated)]"
          >
            Open <ArrowUpRight className="size-3" />
          </Link>
          <Button
            type="button"
            variant="danger"
            size="sm"
            onClick={onDelete}
            disabled={!canDelete || pendingDelete}
          >
            <Trash2 className="size-3" />
            {pendingDelete ? "…" : "Delete"}
          </Button>
        </div>
      </td>
    </tr>
  );
}

/* ─── Page ───────────────────────────────────────────────────────────────── */
export default function RunsPage() {
  const queryClient = useQueryClient();
  const [domainFilter, setDomainFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("");
  const [appliedDomainFilter, setAppliedDomainFilter] = useState("");
  const [appliedStatusFilter, setAppliedStatusFilter] = useState<StatusFilter>("");
  const [pendingDeleteIds, setPendingDeleteIds] = useState<Set<number>>(() => new Set());
  const [actionError, setActionError] = useState("");

  const query = useQuery({
    queryKey: ["runs", appliedDomainFilter, appliedStatusFilter],
    queryFn: () =>
      api.listCrawls({
        limit: 50,
        status: appliedStatusFilter || undefined,
        url_search: appliedDomainFilter || undefined,
      }),
  });

  const deleteMutation = useMutation({
    mutationFn: (runId: number) => api.deleteCrawl(runId),
    onMutate: (runId) => {
      setPendingDeleteIds((c) => { const s = new Set(c); s.add(runId); return s; });
      setActionError("");
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["runs"] });
      await queryClient.invalidateQueries({ queryKey: ["memory-runs"] });
      setActionError("");
    },
    onError: (error) => {
      setActionError(error instanceof Error ? error.message : "Unable to delete run.");
    },
    onSettled: (_d, _e, runId) => {
      setPendingDeleteIds((c) => { const s = new Set(c); s.delete(runId); return s; });
    },
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
      <PageHeader
        title="Run History"
        actions={
          <Link href="/crawl" className="no-underline">
            <Button variant="primary" size="sm">
              <Plus className="size-3.5" />
              New Crawl
            </Button>
          </Link>
        }
      />

      {/* ── Filters ── */}
      <div className="rounded-[var(--radius-xl)] border border-[var(--border)] bg-[var(--surface-card)] p-3 shadow-[var(--shadow-card-value)]">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <div className="flex-1">
          <Input
            placeholder="Filter by domain or URL…"
            value={domainFilter}
            onChange={(e) => setDomainFilter(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") applyFilters(); }}
          />
        </div>
        <select
          aria-label="Filter by status"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
          className="control-select focus-ring min-w-40"
        >
          <option value="">All statuses</option>
          <option value="completed">Completed</option>
          <option value="running">Running</option>
          <option value="pending">Pending</option>
          <option value="paused">Paused</option>
          <option value="failed">Failed</option>
          <option value="killed">Killed</option>
          <option value="proxy_exhausted">Proxy Exhausted</option>
        </select>
        <Button onClick={applyFilters} size="sm">Filter</Button>
        <Button variant="ghost" onClick={resetFilters} size="sm">Reset</Button>
        </div>
      </div>

      {actionError ? <InlineAlert message={actionError} /> : null}

      {/* ── Table ── */}
      <div className="rounded-[var(--radius-xl)] border border-[var(--border)] bg-[var(--bg-panel)] overflow-hidden shadow-[var(--shadow-card-value)]">
        {(() => {
          if (query.isError) {
            return (
              <div className="p-6 text-[13px] text-[var(--danger)]">
                Unable to load run history.
              </div>
            );
          }
          if (query.isLoading) {
            return <div className="p-4"><SkeletonRows count={8} /></div>;
          }
          if (!visibleRuns.length) {
            return <div className="p-4"><EmptyPanel title="No runs found" description="Submitted crawls will appear here." /></div>;
          }
          return (
            <table className="compact-data-table">
              <thead>
                <tr>
                  <th className="min-w-[200px]">Run</th>
                  <th>Type</th>
                  <th>Status</th>
                  <th>Records</th>
                  <th className="whitespace-nowrap">Started</th>
                  <th className="text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {visibleRuns.map((run) => (
                  <RunRow
                    key={run.id}
                    run={run}
                    pendingDelete={pendingDeleteIds.has(run.id)}
                    onDelete={() => {
                      if (!globalThis.confirm(`Delete run ${run.id}? This cannot be undone.`)) return;
                      deleteMutation.mutate(run.id);
                    }}
                  />
                ))}
              </tbody>
            </table>
          );
        })()}
      </div>

      {/* Total count */}
      {visibleRuns.length > 0 && (
        <p className="text-[11px] text-[var(--text-muted)]">
          Showing {visibleRuns.length} of {query.data?.meta?.total ?? visibleRuns.length} runs
        </p>
      )}
    </div>
  );
}

function formatRunType(value: string) {
  if (value === "crawl")  return "Single";
  if (value === "batch")  return "Batch";
  if (value === "csv")    return "CSV";
  return value;
}

