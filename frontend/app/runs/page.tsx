"use client";

import Link from"next/link";
import { useState } from"react";
import { useMutation, useQuery, useQueryClient } from"@tanstack/react-query";
import { ArrowUpRight, Copy, ExternalLink, Plus, Trash2 } from"lucide-react";

import { Badge, Button, Dropdown, Input, Tooltip } from"../../components/ui/primitives";
import {
 DataRegionEmpty,
 DataRegionError,
 DataRegionLoading,
 InlineAlert,
 PageHeader,
 StatusDot,
 SurfacePanel,
 TableSurface,
} from"../../components/ui/patterns";
import { api } from"../../lib/api";
import type { CrawlRun, RunStatus } from"../../lib/api/types";
import { formatRunsDate as formatDate } from"../../lib/format/date";
import { getDomain } from"../../lib/format/domain";
import { runExecutionLabel, runExecutionTone } from"../../lib/ui/status";
import { cn } from"../../lib/utils";

type StatusFilter =""| RunStatus;


/* ─── Run row ────────────────────────────────────────────────────────────── */
function RunRow({
 run,
 pendingDelete,
 onDelete,
}: Readonly<{ run: CrawlRun; pendingDelete: boolean; onDelete: () => void }>) {
 const recordCount = typeof run.result_summary?.record_count ==="number"? run.result_summary.record_count : 0;
 const canDelete = !["pending","running","paused"].includes(run.status);
 const domain = getDomain(run.url);

 return (
 <tr className="group relative hover:z-50">
 {/* Domain + URL */}
 <td className="overflow-visible">
 <div className="flex items-center gap-2.5">
 <StatusDot tone={runExecutionTone(run.status, run.result_summary)} />
 <div className="flex min-w-0 items-center gap-2">
 <Tooltip content={run.url} align="start">
 <Link
 href={`/crawl?run_id=${run.id}`}
 className="link-accent no-underline block max-w-[280px] truncate font-mono text-sm font-medium leading-[1.4] text-primary transition-colors"
 >
 {domain || `Run #${run.id}`}
 </Link>
 </Tooltip>
 
 <div className="flex items-center gap-1 opacity-10 group-hover:opacity-100 transition-opacity">
 <button
 type="button"
 onClick={(e) => {
 e.preventDefault();
 e.stopPropagation();
 void navigator.clipboard.writeText(run.url);
 }}
 className="text-muted transition-colors hover:text-accent"
 title="Copy URL"
 >
 <Copy className="size-3"/>
 </button>
 <a
 href={run.url}
 target="_blank"
 rel="noreferrer"
 className="text-muted transition-colors hover:text-accent"
 title="Open original URL"
 >
 <ExternalLink className="size-3"/>
 </a>
 </div>
 </div>
 </div>
 </td>

 {/* Mode */}
 <td>
 <span className="rounded-[3px] bg-[var(--bg-elevated)] px-1.5 py-0.5 text-sm leading-[1.45] font-mono text-muted">
 {formatRunType(run.run_type)}
 </span>
 </td>

 {/* Status */}
 <td>
 <Badge tone={runExecutionTone(run.status, run.result_summary)}>
 {runExecutionLabel(run.status, run.result_summary)}
 </Badge>
 </td>

 {/* Records */}
 <td className="text-right">
 <span className={cn("font-mono text-sm font-medium leading-[1.45] text-foreground tabular-nums", recordCount > 0 ?"text-primary":"text-muted")}>
 {recordCount > 0 ? recordCount.toLocaleString() :"—"}
 </span>
 </td>

 {/* Date */}
 <td className="text-right">
 <span className="font-mono text-sm leading-[1.45] text-muted tabular-nums">{formatDate(run.created_at)}</span>
 </td>

 {/* Actions */}
 <td className="text-right whitespace-nowrap">
 <div className="flex items-center justify-end gap-1.5 px-0 opacity-0 group-hover:opacity-100 transition-opacity">
 <Link
 href={`/crawl?run_id=${run.id}`}
 className="btn-link btn-link-primary btn-link-sm focus-ring"
 >
 Open <ArrowUpRight className="size-3"/>
 </Link>
 <Button
 type="button"
 variant="danger"
 size="sm"
 onClick={onDelete}
 disabled={!canDelete || pendingDelete}
 >
 <Trash2 className="size-3"/>
 {pendingDelete ?"…":"Delete"}
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
 setActionError(error instanceof Error ? error.message :"Unable to delete run.");
 },
 onSettled: (_d, _e, runId) => {
 setPendingDeleteIds((c) => { const s = new Set(c); s.delete(runId); return s; });
 },
 });

 const visibleRuns = query.data?.items ?? [];

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
 <div className="page-stack">
 <PageHeader
 title="Run History"
 actions={
 <Link href="/crawl"className="no-underline">
 <Button variant="primary"size="sm">
 <Plus className="size-3.5"/>
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
 onKeyDown={(e) => { if (e.key ==="Enter") applyFilters(); }}
 className="text-mono-body"
 />
 </div>
 <Dropdown<StatusFilter>
 ariaLabel="Filter by status"
 value={statusFilter}
 onChange={setStatusFilter}
 options={[
 { value:"", label:"All statuses"},
 { value:"completed", label:"Completed"},
 { value:"running", label:"Running"},
 { value:"pending", label:"Pending"},
 { value:"paused", label:"Paused"},
 { value:"failed", label:"Failed"},
 { value:"killed", label:"Killed"},
 { value:"proxy_exhausted", label:"Proxy Exhausted"},
 ]}
 className="w-full md:w-[180px]"
 />
 <Button onClick={applyFilters} size="sm">Filter</Button>
 <Button variant="ghost"onClick={resetFilters} size="sm">Reset</Button>
 </div>
 </SurfacePanel>

 {actionError ? <InlineAlert message={actionError} /> : null}

 {/* ── Table ── */}
 <TableSurface>
 {(() => {
 if (query.isError) {
 return <DataRegionError message="Unable to load run history."/>;
 }
 if (query.isLoading) {
 return <DataRegionLoading count={8} />;
 }
 if (!visibleRuns.length) {
 return <DataRegionEmpty title="No runs found"description="Submitted crawls will appear here."/>;
 }
 return (
 <table className="compact-data-table">
 <thead>
 <tr>
 <th className="min-w-[200px] text-left font-semibold text-[var(--text-secondary)]">Run</th>
 <th className="text-left font-semibold text-[var(--text-secondary)]">Type</th>
 <th className="text-left font-semibold text-[var(--text-secondary)]">Status</th>
 <th className="w-[110px] text-right font-semibold text-[var(--text-secondary)]">Records</th>
 <th className="w-[180px] whitespace-nowrap text-right font-semibold text-[var(--text-secondary)]">Started</th>
 <th className="w-[170px] text-right font-semibold text-[var(--text-secondary)]">Actions</th>
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
 </TableSurface>

 {/* Total count */}
 {visibleRuns.length > 0 && (
 <p className="text-sm leading-[1.45] text-muted">
 Showing {visibleRuns.length} of {query.data?.meta?.total ?? visibleRuns.length} runs
 </p>
 )}
 </div>
 );
}

function formatRunType(value: string) {
 if (value ==="crawl") return"Single";
 if (value ==="batch") return"Batch";
 if (value ==="csv") return"CSV";
 return value;
}

