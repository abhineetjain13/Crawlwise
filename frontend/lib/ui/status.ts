type Tone = 'success' | 'warning' | 'danger' | 'accent' | 'neutral' | 'info';
type RunSummaryLike =
  | {
      extraction_verdict?: unknown;
      record_count?: unknown;
    }
  | null
  | undefined;

const DASHBOARD_STATUS_CONFIG: Record<string, { tone: Tone; label: string }> = {
  completed: { tone: 'success', label: 'Completed' },
  running: { tone: 'accent', label: 'Running' },
  paused: { tone: 'warning', label: 'Paused' },
  failed: { tone: 'danger', label: 'Failed' },
  killed: { tone: 'warning', label: 'Killed' },
  proxy_exhausted: { tone: 'danger', label: 'Proxy Exhausted' },
  pending: { tone: 'neutral', label: 'Pending' },
  degraded: { tone: 'warning', label: 'Degraded' },
};

const RUNS_STATUS_CONFIG: Record<string, { tone: Exclude<Tone, 'info'>; dot: string }> = {
  completed: { tone: 'success', dot: 'var(--success)' },
  running: { tone: 'accent', dot: 'var(--accent)' },
  paused: { tone: 'warning', dot: 'var(--warning)' },
  failed: { tone: 'danger', dot: 'var(--danger)' },
  killed: { tone: 'warning', dot: 'var(--warning)' },
  proxy_exhausted: { tone: 'danger', dot: 'var(--danger)' },
  pending: { tone: 'neutral', dot: 'var(--text-muted)' },
};

export function dashboardStatusTone(status: string): Tone {
  return DASHBOARD_STATUS_CONFIG[status]?.tone ?? 'neutral';
}

export function dashboardStatusLabel(status: string): string {
  return DASHBOARD_STATUS_CONFIG[status]?.label ?? status;
}

export function runsStatusTone(status: string): Exclude<Tone, 'info'> {
  return RUNS_STATUS_CONFIG[status]?.tone ?? 'neutral';
}

export function runsStatusDot(status: string): string {
  return RUNS_STATUS_CONFIG[status]?.dot ?? 'var(--text-muted)';
}

export function jobsStatusTone(status: string): Exclude<Tone, 'info'> {
  if (status === 'running') return 'success';
  if (status === 'paused') return 'warning';
  if (status === 'killed') return 'warning';
  if (status === 'failed' || status === 'proxy_exhausted') return 'danger';
  return 'neutral';
}

export function dashboardStatusBarColor(status: string): string {
  if (status === 'completed') return 'var(--success)';
  if (status === 'running') return 'var(--accent)';
  if (status === 'failed' || status === 'proxy_exhausted') return 'var(--danger)';
  if (status === 'killed' || status === 'paused' || status === 'degraded') return 'var(--warning)';
  return 'var(--text-muted)';
}

export function dashboardStatusDotColor(status: string): string {
  const tone = dashboardStatusTone(status);
  if (tone === 'success') return 'var(--success)';
  if (tone === 'danger') return 'var(--danger)';
  if (tone === 'warning') return 'var(--warning)';
  if (tone === 'neutral') return 'var(--text-muted)';
  return 'var(--accent)';
}

export function isSubduedStatus(status: string): boolean {
  return status === 'completed' || status === 'killed';
}

/** Completed / killed / partial verdicts use flat (text-only) badges. */
export function isFlatStatus(status: string, summary?: RunSummaryLike): boolean {
  if (status === 'killed') return true;
  if (status !== 'completed') return false;
  const verdict = String(summary?.extraction_verdict ?? '')
    .trim()
    .toLowerCase();
  return verdict === 'partial' || verdict === '';
}

export function humanizeStatus(status: string): string {
  return String(status || '')
    .replace(/_/g, ' ')
    .trim();
}

export function runExecutionTone(status: string, summary?: RunSummaryLike): Exclude<Tone, 'info'> {
  if (status !== 'completed') {
    return runsStatusTone(status);
  }
  const verdict = String(summary?.extraction_verdict ?? '')
    .trim()
    .toLowerCase();
  const recordCount = typeof summary?.record_count === 'number' ? summary.record_count : 0;
  if (verdict === 'blocked' || verdict === 'error') return 'danger';
  if (
    verdict === 'partial' ||
    verdict === 'schema_miss' ||
    verdict === 'listing_detection_failed' ||
    verdict === 'empty' ||
    recordCount === 0
  ) {
    return 'warning';
  }
  return 'success';
}

export function runExecutionDot(status: string, summary?: RunSummaryLike): string {
  const tone = runExecutionTone(status, summary);
  if (tone === 'success') return 'var(--success)';
  if (tone === 'danger') return 'var(--danger)';
  if (tone === 'warning') return 'var(--warning)';
  if (tone === 'accent') return 'var(--accent)';
  return 'var(--text-muted)';
}

export function runExecutionLabel(status: string, summary?: RunSummaryLike): string {
  if (status !== 'completed') {
    return dashboardStatusLabel(status);
  }
  const verdict = String(summary?.extraction_verdict ?? '')
    .trim()
    .toLowerCase();
  const recordCount = typeof summary?.record_count === 'number' ? summary.record_count : 0;
  if (verdict === 'blocked') return 'Blocked';
  if (verdict === 'error') return 'Error';
  if (verdict === 'partial') return 'Partial';
  if (verdict === 'listing_detection_failed') return 'Listing Failed';
  if (verdict === 'schema_miss') return 'Schema Miss';
  if (verdict === 'empty' || recordCount === 0) return 'No Results';
  return dashboardStatusLabel(status);
}
