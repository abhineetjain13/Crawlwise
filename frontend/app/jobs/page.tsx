"use client";

import { useQuery } from "@tanstack/react-query";
import { Activity, RefreshCw, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import type { ComponentType } from "react";

import { api } from "../../lib/api";
import type { ActiveJob } from "../../lib/api/types";
import { formatJobsTimestamp as formatTimestamp } from "../../lib/format/date";
import { jobsStatusTone as statusTone } from "../../lib/ui/status";
import { cn } from "../../lib/utils";
import { Badge, Button, Card } from "../../components/ui/primitives";
import { InlineAlert, PageHeader, SectionHeader } from "../../components/ui/patterns";

export default function JobsPage() {
  const [lastRefreshed, setLastRefreshed] = useState<string>("--");
  const [pendingAction, setPendingAction] = useState<string>("");
  const [actionError, setActionError] = useState("");
  const jobsQuery = useQuery({
    queryKey: ["jobs"],
    queryFn: api.listJobs,
    refetchInterval: 5000,
  });

  useEffect(() => {
    if (jobsQuery.data) {
      setLastRefreshed(new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }));
    }
  }, [jobsQuery.data]);

  const jobs = jobsQuery.data ?? [];

  async function runAction(runId: number) {
    const action = "kill";
    setPendingAction(`${action}:${runId}`);
    try {
      setActionError("");
      await api.killCrawl(runId);
      await jobsQuery.refetch();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : `Unable to ${action} run ${runId}.`);
    } finally {
      setPendingAction("");
    }
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title="Jobs"
        description="Live worker state and job control."
        actions={
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted">Last refreshed {lastRefreshed}</span>
            <Button variant="secondary" type="button" onClick={() => void jobsQuery.refetch()}>
              <RefreshCw className="size-3.5" />
              Refresh
            </Button>
          </div>
        }
      />

      <Card className="space-y-4">
        <SectionHeader
          title="Active Jobs"
          description="Auto-refreshes every 5 seconds. Use hard kill to stop any active run."
          action={<Badge tone="neutral">{jobs.length} active</Badge>}
        />
        {actionError ? <InlineAlert message={actionError} /> : null}

        {jobs.length ? (
          <div className="overflow-auto rounded-[10px] border border-border">
            <table className="compact-data-table min-w-[960px]">
              <thead>
                <tr>
                  <th>Run ID</th>
                  <th>Type</th>
                  <th>Target URL</th>
                  <th>Progress</th>
                  <th>Started</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((job) => (
                  <tr key={job.run_id}>
                    <td className="font-mono text-xs text-foreground">{job.run_id}</td>
                    <td className="text-sm text-muted">{formatJobType(job.type)}</td>
                    <td className="max-w-[320px] truncate text-sm text-foreground" title={job.url}>
                      {job.url}
                    </td>
                    <td>
                      <div className="space-y-1">
                        <ProgressBar value={job.progress} />
                        <div className="text-xs text-muted">{job.progress}%</div>
                      </div>
                    </td>
                    <td className="text-sm text-muted">{formatTimestamp(job.started_at)}</td>
                    <td>
                      <StatusPill status={job.status} />
                    </td>
                    <td>
                      <div className="flex items-center gap-2">
                        <ActionButton
                          icon={XCircle}
                          label="Hard Kill"
                          disabled={!(job.status === "pending" || job.status === "running" || job.status === "paused") || Boolean(pendingAction)}
                          onClick={() => void runAction(job.run_id)}
                          danger
                        />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="grid min-h-40 place-items-center rounded-[10px] border border-dashed border-border bg-panel/60 text-center">
            <div>
              <Activity className="mx-auto size-5 text-muted" />
              <div className="mt-2 text-sm font-medium text-foreground">No active jobs</div>
              <div className="mt-1 text-sm text-muted">Start a crawl to see live workers here.</div>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}

function StatusPill({ status }: Readonly<{ status: ActiveJob["status"] }>) {
  const tone = statusTone(status);
  return <Badge tone={tone}>{status.replace(/_/g, " ")}</Badge>;
}

function ActionButton({
  icon: Icon,
  label,
  disabled,
  danger,
  onClick,
}: Readonly<{
  icon: ComponentType<{ className?: string }>;
  label: string;
  disabled?: boolean;
  danger?: boolean;
  onClick?: () => void;
}>) {
  return (
    <Button
      type="button"
      onClick={onClick}
      variant={danger ? "ghost" : "secondary"}
      disabled={disabled}
      className={cn("h-7 px-2.5 text-xs", danger && "text-danger hover:bg-danger/10 hover:text-danger")}
      title={label}
    >
      <Icon className="size-3.5" />
      {label}
    </Button>
  );
}

function ProgressBar({ value }: Readonly<{ value: number }>) {
  return (
    <div className="h-1.5 w-full rounded-full bg-border">
      <div
        className={cn("h-1.5 rounded-full transition-all", value > 90 ? "bg-brand" : "bg-accent")}
        style={{ width: `${Math.max(0, Math.min(100, value))}%` }}
      />
    </div>
  );
}

function formatJobType(value: string) {
  return value.replace(/_/g, " ");
}
