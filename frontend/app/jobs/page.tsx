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
} from '../../components/ui/patterns';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../../components/ui/table';
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
            <span className="text-muted type-caption">Last refreshed {lastRefreshed}</span>
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
          <div className="surface-muted overflow-x-auto rounded-[var(--radius-md)] border">
            <Table
              wrapperClassName="max-h-[calc(100vh-260px)]"
              className="compact-data-table min-w-[960px] table-fixed"
            >
              <colgroup>
                <col style={{ width: '10%' }} />
                <col style={{ width: '10%' }} />
                <col style={{ width: '30%' }} />
                <col style={{ width: '15%' }} />
                <col style={{ width: '15%' }} />
                <col style={{ width: '10%' }} />
                <col style={{ width: '10%' }} />
              </colgroup>
              <TableHeader>
                <TableRow>
                  <TableHead>Run ID</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Target URL</TableHead>
                  <TableHead>Progress</TableHead>
                  <TableHead>Started</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {jobs.map((job) => (
                  <TableRow key={job.run_id}>
                    <TableCell className="type-caption-mono font-medium">{job.run_id}</TableCell>
                    <TableCell className="type-body">{formatJobType(job.type)}</TableCell>
                    <TableCell className="type-caption-mono max-w-[320px] truncate" title={job.url}>
                      {job.url}
                    </TableCell>
                    <TableCell>
                      <ProgressBar percent={job.progress} />
                    </TableCell>
                    <TableCell className="type-caption-mono text-muted">
                      {formatTimestamp(job.started_at)}
                    </TableCell>
                    <TableCell>
                      <StatusPill status={job.status} />
                    </TableCell>
                    <TableCell>
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
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
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
  return <Badge tone={tone} flat={status === 'killed'}>{humanizeStatus(status)}</Badge>;
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
        'type-control h-7 px-2.5',
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
