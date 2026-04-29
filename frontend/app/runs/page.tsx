"use client";

import Link from "next/link";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, Copy, ExternalLink, Plus, Trash2 } from "lucide-react";

import { Badge, Button, Dropdown, Input, Tooltip } from "../../components/ui/primitives";
import { ConfirmDialog } from "../../components/ui/dialog";
import {
    DataRegionEmpty,
    DataRegionError,
    DataRegionLoading,
    InlineAlert,
    PageHeader,
    StatusDot,
    SurfacePanel,
    TableSurface,
} from "../../components/ui/patterns";
import { api } from "../../lib/api";
import type { CrawlRun, RunStatus } from "../../lib/api/types";
import { formatRunsDate as formatDate } from "../../lib/format/date";
import { getDomain } from "../../lib/format/domain";
import { runExecutionLabel, runExecutionTone } from "../../lib/ui/status";
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
        <tr className="group relative hover:z-50">
            {/* Domain + URL */}
            <td className="overflow-visible">
                <div className="flex items-center gap-2.5">
                    <StatusDot tone={runExecutionTone(run.status, run.result_summary)} />
                    <div className="flex min-w-0 items-center gap-2">
                        <Tooltip content={run.url} align="start">
                            <Link
                                href={`/crawl?run_id=${run.id}`}
                                className="type-mono-standard link-accent no-underline block max-w-[280px] truncate font-normal leading-[1.4] text-primary transition-colors"
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
                                <Copy className="size-3" />
                            </button>
                            <a
                                href={run.url}
                                target="_blank"
                                rel="noreferrer"
                                className="text-muted transition-colors hover:text-accent"
                                title="Open original URL"
                            >
                                <ExternalLink className="size-3" />
                            </a>
                        </div>
                    </div>
                </div>
            </td>

            {/* Mode */}
            <td>
                <span className="mono-body rounded-[3px] bg-background-elevated px-1.5 py-0.5 text-sm leading-[var(--leading-normal)] text-muted">
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
                <span className={cn("mono-body text-sm font-normal leading-[var(--leading-normal)] text-foreground tabular-nums", recordCount > 0 ? "text-primary" : "text-muted")}>
                    {recordCount > 0 ? recordCount.toLocaleString() : "—"}
                </span>
            </td>

            {/* Date */}
            <td className="text-right">
                <span className="mono-body text-sm leading-[var(--leading-normal)] text-muted tabular-nums">{formatDate(run.created_at)}</span>
            </td>

            {/* Actions */}
            <td className="text-right whitespace-nowrap">
                <div className="flex items-center justify-end gap-1.5 px-0 opacity-0 group-hover:opacity-100 transition-opacity">
                    <Link
                        href={`/crawl?run_id=${run.id}`}
                        className="ui-on-accent-surface focus-ring inline-flex min-h-[26px] items-center justify-center gap-1.5 rounded-[var(--radius-md)] border border-accent bg-accent px-[9px] text-sm font-medium leading-none no-underline shadow-xs transition-[background-color,color,border-color,box-shadow,opacity,transform] hover:-translate-y-px hover:border-accent-hover hover:bg-accent-hover"
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
    const [deleteTarget, setDeleteTarget] = useState<CrawlRun | null>(null);

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
            setDeleteTarget(null);
        },
        onError: (error) => {
            setActionError(error instanceof Error ? error.message : "Unable to delete run.");
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
                    <Link href="/crawl" className="no-underline">
                        <Button variant="primary" className="h-[var(--control-height)]"><Plus className="size-3.5" />
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
                            onKeyDown={(e) => { if (e.key === "Enter") applyFilters(); }}
                            className="text-mono-body"
                        />
                    </div>
                    <Dropdown<StatusFilter>
                        ariaLabel="Filter by status"
                        value={statusFilter}
                        onChange={setStatusFilter}
                        options={[
                            { value: "", label: "All statuses" },
                            { value: "completed", label: "Completed" },
                            { value: "running", label: "Running" },
                            { value: "pending", label: "Pending" },
                            { value: "paused", label: "Paused" },
                            { value: "failed", label: "Failed" },
                            { value: "killed", label: "Killed" },
                            { value: "proxy_exhausted", label: "Proxy Exhausted" },
                        ]}
                        className="w-full md:w-[180px]"
                    />
                    <Button onClick={applyFilters} className="h-[var(--control-height)]">Filter</Button>
                    <Button variant="ghost" onClick={resetFilters} className="h-[var(--control-height)]">Reset</Button>
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
                        return <DataRegionEmpty title="No runs found" description="Submitted crawls will appear here." />;
                    }
                    return (
                        <table className="compact-data-table">
                            <colgroup>
                                <col style={{ width: "30%" }} />
                                <col style={{ width: "15%" }} />
                                <col style={{ width: "15%" }} />
                                <col style={{ width: "10%" }} />
                                <col style={{ width: "15%" }} />
                                <col style={{ width: "15%" }} />
                            </colgroup>
                            <thead>
                                <tr>
                                    <th>Run</th>
                                    <th>Type</th>
                                    <th>Status</th>
                                    <th className="text-right">Records</th>
                                    <th className="text-right">Started</th>
                                    <th className="text-right">Actions</th>
                                </tr>
                            </thead>
                            <tbody>
                                {visibleRuns.map((run) => (
                                    <RunRow
                                        key={run.id}
                                        run={run}
                                        pendingDelete={pendingDeleteIds.has(run.id)}
                                        onDelete={() => setDeleteTarget(run)}
                                    />
                                ))}
                            </tbody>
                        </table>
                    );
                })()}
            </TableSurface>

            {/* Total count */}
            {visibleRuns.length > 0 && (
                <p className="text-sm leading-[var(--leading-normal)] text-muted">
                    Showing {visibleRuns.length} of {query.data?.meta?.total ?? visibleRuns.length} runs
                </p>
            )}
            <ConfirmDialog
                open={deleteTarget !== null}
                onOpenChange={(open) => {
                    if (!open) setDeleteTarget(null);
                }}
                title="Delete run"
                description={deleteTarget ? `Delete run ${deleteTarget.id}? This cannot be undone.` : ""}
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
    if (value === "crawl") return "Single";
    if (value === "batch") return "Batch";
    if (value === "csv") return "CSV";
    return value;
}

