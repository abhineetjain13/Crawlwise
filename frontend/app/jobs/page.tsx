'use client';

import { useQuery } from '@tanstack/react-query';
import { RefreshCw, XCircle } from 'lucide-react';
import type { ComponentType } from 'react';
import { useState } from 'react';

import { api } from '../../lib/api';
import type { ActiveJob } from '../../lib/api/types';
import { formatJobsTimestamp as formatTimestamp, formatTimeHms } from '../../lib/format/date';
import { humanizeStatus, jobsStatusTone as statusTone } from '../../lib/ui/status';
import { cn } from '../../lib/utils';
import {
  DataRegionEmpty,
  DataRegionError,
  DataRegionLoading,
  InlineAlert,
  PageHeader,
  ProgressBar,
  SectionCard,
  TableSurface,
} from '../../components/ui/patterns';
import { Badge, Button } from '../../components/ui/primitives';

export default function JobsPage() {
  const [pendingAction, setPendingAction] = useState('');
  const [actionError, setActionError] = useState('');
  const jobsQuery = useQuery({
    queryKey: ['jobs'],
    queryFn: api.listJobs,
    refetchInterval: 5000,
  });

  const jobs = jobsQuery.data ?? [];
  const lastRefreshed = jobsQuery.dataUpdatedAt
    ? formatTimeHms(new Date(jobsQuery.dataUpdatedAt).toISOString())
    : '--';

  async function runAction(runId: number) {
    const action = 'kill';
    setPendingAction(`${action}:${runId}`);
    try {
      setActionError('');
      await api.killCrawl(runId);
      await jobsQuery.refetch();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : `Unable to ${action} run ${runId}.`);
    } finally {
      setPendingAction('');
    }
  }

  return (
    <div className="page-stack">
      <PageHeader
        title="Jobs"
        description="Live run state for the local dev runner."
        actions={
          <div className="flex items-center gap-2">
            <span className="text-muted text-sm leading-[var(--leading-normal)]">
              Last refreshed {lastRefreshed}
            </span>
            <Button
              variant="secondary"
              type="button"
              className="h-[var(--control-height)]"
              onClick={() => void jobsQuery.refetch()}
            >
              <RefreshCw className="size-3.5" />
              Refresh
            </Button>
          </div>
        }
      />

      <SectionCard
        title="Active Jobs"
        description="Auto-refreshes every 5 seconds. Hard kill is the only active-run control in dev mode."
        action={<Badge tone="neutral">{jobs.length} active</Badge>}
      >
        {actionError ? <InlineAlert message={actionError} /> : null}

        {jobsQuery.isLoading ? (
          <DataRegionLoading count={6} />
        ) : jobsQuery.isError ? (
          <DataRegionError message="Failed to load jobs." />
        ) : jobs.length ? (
          <TableSurface className="table-surface-flat">
            <table className="compact-data-table min-w-[960px]">
              <colgroup>
                <col style={{ width: '10%' }} />
                <col style={{ width: '10%' }} />
                <col style={{ width: '30%' }} />
                <col style={{ width: '15%' }} />
                <col style={{ width: '15%' }} />
                <col style={{ width: '10%' }} />
                <col style={{ width: '10%' }} />
              </colgroup>
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
                    <td className="mono-body text-foreground text-sm leading-[1.5]">
                      {job.run_id}
                    </td>
                    <td className="text-muted text-sm leading-[var(--leading-relaxed)]">
                      {formatJobType(job.type)}
                    </td>
                    <td
                      className="mono-body text-foreground max-w-[320px] truncate text-sm font-medium leading-[var(--leading-relaxed)]"
                      title={job.url}
                    >
                      {job.url}
                    </td>
                    <td>
                      <ProgressBar percent={job.progress} />
                    </td>
                    <td className="text-muted text-sm leading-[var(--leading-relaxed)]">
                      {formatTimestamp(job.started_at)}
                    </td>
                    <td>
                      <StatusPill status={job.status} />
                    </td>
                    <td>
                      <div className="flex items-center gap-2">
                        <ActionButton
                          icon={XCircle}
                          label="Hard Kill"
                          disabled={
                            !(
                              job.status === 'pending' ||
                              job.status === 'running' ||
                              job.status === 'paused'
                            ) || Boolean(pendingAction)
                          }
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
          <DataRegionEmpty
            title="No active jobs"
            description="Start a crawl to see live workers here."
          />
        )}
      </SectionCard>
    </div>
  );
}

function StatusPill({ status }: Readonly<{ status: ActiveJob['status'] }>) {
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
      variant={danger ? 'ghost' : 'secondary'}
      disabled={disabled}
      className={cn(
        'h-7 px-2.5 text-sm leading-[var(--leading-normal)]',
        danger && 'text-danger hover:bg-danger/10 hover:text-danger',
      )}
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
