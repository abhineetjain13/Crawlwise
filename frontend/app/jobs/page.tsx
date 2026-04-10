"use client";

import { useQuery } from "@tanstack/react-query";
import { RefreshCw, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import type { ComponentType } from "react";

import { api } from "../../lib/api";
import type { ActiveJob } from "../../lib/api/types";
import { formatJobsTimestamp as formatTimestamp, formatNowHms } from "../../lib/format/date";
import { humanizeStatus, jobsStatusTone as statusTone } from "../../lib/ui/status";
import { cn } from "../../lib/utils";
import { Badge, Button, Card } from "../../components/ui/primitives";
import {
  DataRegionEmpty,
  DataRegionLoading,
  InlineAlert,
  PageHeader,
  ProgressBar,
  SectionHeader,
  TableSurface,
} from "../../components/ui/patterns";

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
      setLastRefreshed(formatNowHms());
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
        description="Live run state for the local dev runner."
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
          description="Auto-refreshes every 5 seconds. Hard kill is the only active-run control in dev mode."
          action={<Badge tone="neutral">{jobs.length} active</Badge>}
        />
        {actionError ? <InlineAlert message={actionError} /> : null}

        {jobsQuery.isLoading ? (
          <DataRegionLoading count={6} />
        ) : jobs.length ? (
          <TableSurface className="border border-border bg-transparent shadow-none">
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
                      <ProgressBar percent={job.progress} />
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
          </TableSurface>
        ) : (
          <DataRegionEmpty title="No active jobs" description="Start a crawl to see live workers here." />
        )}
      </Card>
    </div>
  );
}

function StatusPill({ status }: Readonly<{ status: ActiveJob["status"] }>) {
  const tone = statusTone(status);
  return <Badge tone={tone}>{humanizeStatus(status)}</Badge>;
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

function formatJobType(value: string) {
  return humanizeStatus(value);
}
