'use client';

import Link from 'next/link';
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowRightCircle, ArrowUpRight, Copy, ExternalLink, Plus, Trash2 } from 'lucide-react';

import { Badge, Button, Dropdown, Input, Tooltip } from '../../components/ui/primitives';
import { ConfirmDialog } from '../../components/ui/dialog';
import {
  DataRegionEmpty,
  DataRegionError,
  DataRegionLoading,
  InlineAlert,
  PageHeader,
  StatusDot,
  SurfacePanel,
  TableSurface,
} from '../../components/ui/patterns';
import { api } from '../../lib/api';
import type { CrawlRun, RunStatus } from '../../lib/api/types';
import { formatRunsDate as formatDate } from '../../lib/format/date';
import { getDomain } from '../../lib/format/domain';
import { runExecutionLabel, runExecutionTone } from '../../lib/ui/status';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../../components/ui/table';
import { cn } from '../../lib/utils';

type StatusFilter = '' | RunStatus;

/* ─── Run row ────────────────────────────────────────────────────────────── */
function RunRow({
  run,
  pendingDelete,
  onDelete,
}: Readonly<{ run: CrawlRun; pendingDelete: boolean; onDelete: () => void }>) {
  const recordCount =
    typeof run.result_summary?.record_count === 'number' ? run.result_summary.record_count : 0;
  const canDelete = !['pending', 'running', 'paused'].includes(run.status);
  const domain = getDomain(run.url);

  return (
    <TableRow className="group">
      {/* Domain + URL */}
      <TableCell className="overflow-visible">
        <div className="flex items-center gap-2.5">
          <StatusDot tone={runExecutionTone(run.status, run.result_summary)} />
          <div className="flex min-w-0 items-center gap-2">
            <Tooltip content={run.url} align="start">
              <Link
                href={`/crawl?run_id=${run.id}`}
                className="link-accent text-primary type-body block max-w-[280px] truncate font-medium no-underline transition-colors"
              >
                {domain || `Run #${run.id}`}
              </Link>
            </Tooltip>

            <div className="flex items-center gap-1 opacity-10 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100">
              <button
                type="button"
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  void navigator.clipboard.writeText(run.url);
                }}
                className="text-muted hover:text-accent inline-flex min-h-6 min-w-6 items-center justify-center transition-colors"
                title="Copy URL"
                aria-label="Copy URL"
              >
                <Copy className="size-3" />
              </button>
              <a
                href={run.url}
                target="_blank"
                rel="noreferrer"
                className="text-muted hover:text-accent inline-flex min-h-6 min-w-6 items-center justify-center transition-colors"
                title="Open original URL"
                aria-label="Open original URL"
              >
                <ExternalLink className="size-3" />
              </a>
            </div>
          </div>
        </div>
      </TableCell>

      {/* Mode */}
      <TableCell>
        <span className="type-caption-mono bg-background-elevated text-muted rounded-[var(--radius-sm)] px-1.5 py-0.5">
          {formatRunType(run.run_type)}
        </span>
      </TableCell>

      {/* Status */}
      <TableCell>
        <Badge tone={runExecutionTone(run.status, run.result_summary)}>
          {runExecutionLabel(run.status, run.result_summary)}
        </Badge>
      </TableCell>

      {/* Records */}
      <TableCell className="text-right">
        <span
          className={cn(
            'type-caption-mono tabular-nums',
            recordCount > 0 ? 'text-primary' : 'text-muted',
          )}
        >
          {recordCount > 0 ? recordCount.toLocaleString() : '—'}
        </span>
      </TableCell>

      {/* Date */}
      <TableCell className="text-right">
        <span className="type-caption-mono text-muted tabular-nums">
          {formatDate(run.created_at)}
        </span>
      </TableCell>

      {/* Actions */}
      <TableCell className="text-right whitespace-nowrap">
        <div className="flex items-center justify-end gap-1.5 px-0 opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100">
          <Button variant="accent" size="sm" asChild className="h-7 px-3">
            <Link href={`/crawl/${run.id}`}>
              Open
              <ArrowRightCircle className="ml-1 size-3" />
            </Link>
          </Button>
          <Button
            type="button"
            variant="danger"
            size="sm"
            onClick={onDelete}
            disabled={!canDelete || pendingDelete}
          >
            <Trash2 className="size-3" />
            {pendingDelete ? '…' : 'Delete'}
          </Button>
        </div>
      </TableCell>
    </TableRow>
  );
}

/* ─── Page ───────────────────────────────────────────────────────────────── */
export default function RunsPage() {
  const queryClient = useQueryClient();
  const [domainFilter, setDomainFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('');
  const [appliedDomainFilter, setAppliedDomainFilter] = useState('');
  const [appliedStatusFilter, setAppliedStatusFilter] = useState<StatusFilter>('');
  const [pendingDeleteIds, setPendingDeleteIds] = useState<Set<number>>(() => new Set());
  const [actionError, setActionError] = useState('');
  const [deleteTarget, setDeleteTarget] = useState<CrawlRun | null>(null);

  const query = useQuery({
    queryKey: ['runs', appliedDomainFilter, appliedStatusFilter],
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
      setPendingDeleteIds((c) => {
        const s = new Set(c);
        s.add(runId);
        return s;
      });
      setActionError('');
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['runs'] });
      await queryClient.invalidateQueries({ queryKey: ['memory-runs'] });
      setActionError('');
      setDeleteTarget(null);
    },
    onError: (error) => {
      setActionError(error instanceof Error ? error.message : 'Unable to delete run.');
    },
    onSettled: (_d, _e, runId) => {
      setPendingDeleteIds((c) => {
        const s = new Set(c);
        s.delete(runId);
        return s;
      });
    },
  });

  const visibleRuns = query.data?.items ?? [];

  function applyFilters() {
    setAppliedDomainFilter(domainFilter.trim());
    setAppliedStatusFilter(statusFilter);
  }

  function resetFilters() {
    setDomainFilter('');
    setStatusFilter('');
    setAppliedDomainFilter('');
    setAppliedStatusFilter('');
  }

  return (
    <div className="page-stack h-full">
      <PageHeader
        title="Run History"
        actions={
          <Link href="/crawl" className="no-underline">
            <Button variant="primary" className="h-[var(--control-height)]">
              <Plus className="size-3.5" />
              New Crawl
            </Button>
          </Link>
        }
      />

      {/* ── Filters ── */}
      <SurfacePanel className="p-3">
        <div className="grid gap-2 md:grid-cols-[minmax(320px,1fr)_180px_auto_auto] md:items-center">
          <div className="min-w-0">
            <Input
              placeholder="Filter by domain or URL…"
              value={domainFilter}
              onChange={(e) => setDomainFilter(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') applyFilters();
              }}
              className="text-mono-body"
            />
          </div>
          <Dropdown<StatusFilter>
            ariaLabel="Filter by status"
            value={statusFilter}
            onChange={setStatusFilter}
            options={[
              { value: '', label: 'All statuses' },
              { value: 'completed', label: 'Completed' },
              { value: 'running', label: 'Running' },
              { value: 'pending', label: 'Pending' },
              { value: 'paused', label: 'Paused' },
              { value: 'failed', label: 'Failed' },
              { value: 'killed', label: 'Killed' },
              { value: 'proxy_exhausted', label: 'Proxy Exhausted' },
            ]}
            className="w-full md:w-[180px]"
          />
          <Button onClick={applyFilters} className="h-[var(--control-height)]">
            Filter
          </Button>
          <Button variant="ghost" onClick={resetFilters} className="h-[var(--control-height)]">
            Reset
          </Button>
        </div>
      </SurfacePanel>

      {actionError ? <InlineAlert message={actionError} /> : null}

      {/* ── Table ── */}
      <TableSurface>
        {(() => {
          if (query.isError) {
            return <DataRegionError message="Unable to load run history." />;
          }
          if (query.isLoading) {
            return <DataRegionLoading count={8} />;
          }
          if (!visibleRuns.length) {
            return (
              <DataRegionEmpty
                title="No runs found"
                description="Submitted crawls will appear here."
              />
            );
          }
          return (
            <Table
              wrapperClassName="max-h-[calc(100vh-320px)]"
              className="compact-data-table table-fixed"
            >
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[30%]">Run</TableHead>
                  <TableHead className="w-[15%]">Type</TableHead>
                  <TableHead className="w-[15%]">Status</TableHead>
                  <TableHead className="w-[10%] text-right">Records</TableHead>
                  <TableHead className="w-[15%] text-right">Started</TableHead>
                  <TableHead className="w-[15%] text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {visibleRuns.map((run) => (
                  <RunRow
                    key={run.id}
                    run={run}
                    pendingDelete={pendingDeleteIds.has(run.id)}
                    onDelete={() => setDeleteTarget(run)}
                  />
                ))}
              </TableBody>
            </Table>
          );
        })()}
      </TableSurface>

      {/* Total count */}
      {visibleRuns.length > 0 && (
        <p className="type-caption">
          Showing {visibleRuns.length} of {query.data?.meta?.total ?? visibleRuns.length} runs
        </p>
      )}
      <ConfirmDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open) setDeleteTarget(null);
        }}
        title="Delete run"
        description={deleteTarget ? `Delete run ${deleteTarget.id}? This cannot be undone.` : ''}
        confirmLabel="Delete Run"
        pending={deleteTarget ? pendingDeleteIds.has(deleteTarget.id) : false}
        danger
        onConfirm={() => {
          if (!deleteTarget) return;
          deleteMutation.mutate(deleteTarget.id);
        }}
      />
    </div>
  );
}

function formatRunType(value: string) {
  if (value === 'crawl') return 'Single';
  if (value === 'batch') return 'Batch';
  if (value === 'csv') return 'CSV';
  return value;
}
