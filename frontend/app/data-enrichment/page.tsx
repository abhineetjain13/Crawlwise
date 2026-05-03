'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ExternalLink, History, Loader2, Play, RefreshCcw } from 'lucide-react';
import { useMemo, useState } from 'react';

import { HistoryDrawer, type HistoryItem } from '../../components/ui/history-drawer';

import {
  DataRegionEmpty,
  DataRegionLoading,
  InlineAlert,
  PageHeader,
} from '../../components/ui/patterns';
import { Badge, Button } from '../../components/ui/primitives';
import { api } from '../../lib/api';
import { EnrichmentStatus, EnrichmentTableLoading } from './enrichment-components';
import type {
  DataEnrichmentJob,
  DataEnrichmentSourceRecordInput,
  EnrichedProduct,
} from '../../lib/api/types';
import { STORAGE_KEYS } from '../../lib/constants/storage-keys';
import { cn } from '../../lib/utils';

type PrefillPayload = {
  source_run_id?: number | null;
  records?: DataEnrichmentSourceRecordInput[];
};

const ENRICHED_FIELD_LABELS: Array<[keyof EnrichedProduct, string]> = [
  ['price_normalized', 'Price'],
  ['color_family', 'Color'],
  ['size_normalized', 'Size'],
  ['size_system', 'Size system'],
  ['gender_normalized', 'Gender'],
  ['materials_normalized', 'Materials'],
  ['availability_normalized', 'Availability'],
  ['seo_keywords', 'SEO keywords'],
  ['category_path', 'Category'],
  ['intent_attributes', 'Intent'],
  ['audience', 'Audience'],
  ['style_tags', 'Style'],
  ['ai_discovery_tags', 'Discovery tags'],
  ['suggested_bundles', 'Bundles'],
];

function loadPrefill(): PrefillPayload {
  if (typeof window === 'undefined') return {};
  const stored = window.sessionStorage.getItem(STORAGE_KEYS.DATA_ENRICHMENT_PREFILL);
  if (!stored) return {};
  try {
    const parsed = JSON.parse(stored) as PrefillPayload;
    return {
      source_run_id: typeof parsed.source_run_id === 'number' ? parsed.source_run_id : null,
      records: Array.isArray(parsed.records) ? parsed.records : [],
    };
  } catch {
    return {};
  } finally {
    window.sessionStorage.removeItem(STORAGE_KEYS.DATA_ENRICHMENT_PREFILL);
  }
}

export default function DataEnrichmentPage() {
  const queryClient = useQueryClient();
  const [initialPrefill] = useState(loadPrefill);
  const [llmEnabled, setLlmEnabled] = useState(false);
  const [activeJobId, setActiveJobId] = useState<number | null>(null);
  const [error, setError] = useState('');
  const [historyOpen, setHistoryOpen] = useState(false);

  const sourceRecords = initialPrefill.records ?? [];
  const sourceRecordIds = sourceRecords
    .map((record) => record.id)
    .filter((id): id is number => typeof id === 'number');

  const jobsQuery = useQuery({
    queryKey: ['data-enrichment-jobs'],
    queryFn: () => api.listDataEnrichmentJobs({ limit: 20 }),
    refetchInterval: 4000,
  });

  const historyItems: HistoryItem[] = useMemo(() => {
    return (jobsQuery.data ?? []).map((job) => ({
      id: job.id,
      status: job.status,
      created_at: job.created_at,
      label: job.source_run_id ? `From Run #${job.source_run_id}` : 'Direct Input',
      meta: `${Number(job.summary?.accepted_count ?? 0)} records enriched`,
    }));
  }, [jobsQuery.data]);

  const defaultJobId = sourceRecords.length ? null : (jobsQuery.data?.[0]?.id ?? null);
  const resolvedJobId = activeJobId ?? defaultJobId;
  const detailQuery = useQuery({
    queryKey: ['data-enrichment-job', resolvedJobId],
    queryFn: () => api.getDataEnrichmentJob(resolvedJobId ?? 0),
    enabled: resolvedJobId !== null,
    refetchInterval: (query) => {
      const status = String(query.state.data?.job?.status ?? '');
      return status === 'pending' || status === 'running' ? 2500 : false;
    },
  });
  const activeJob =
    detailQuery.data?.job ?? jobsQuery.data?.find((job) => job.id === resolvedJobId) ?? null;
  const isRunning = activeJob?.status === 'pending' || activeJob?.status === 'running';

  const products = detailQuery.data?.enriched_products ?? [];
  const completedCount = products.filter((product) => product.status === 'enriched').length;
  const semanticCount = products.filter((product) =>
    Boolean(product.intent_attributes?.length),
  ).length;

  const createMutation = useMutation({
    mutationFn: () =>
      api.createDataEnrichmentJob({
        source_run_id: initialPrefill.source_run_id ?? null,
        source_record_ids: sourceRecordIds,
        source_records: sourceRecords,
        options: {
          max_source_records: 500,
          llm_enabled: llmEnabled,
        },
      }),
    onSuccess: async (job) => {
      setError('');
      setActiveJobId(job.id);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['data-enrichment-jobs'] }),
        queryClient.invalidateQueries({ queryKey: ['data-enrichment-job', job.id] }),
      ]);
    },
    onError: (mutationError) => {
      setError(
        mutationError instanceof Error ? mutationError.message : 'Unable to start enrichment.',
      );
    },
  });

  const descriptionText =
    [
      sourceRecords.length > 0 ? `${sourceRecords.length} selected` : null,
      completedCount > 0 ? `${completedCount} enriched` : null,
      semanticCount > 0 ? `${semanticCount} semantic` : null,
      activeJob ? `Mode: ${activeJob.options?.llm_enabled ? 'LLM' : 'Rules'}` : null,
    ]
      .filter(Boolean)
      .join(' · ') ||
    'Normalize ecommerce detail records into category, price, attribute, and discovery fields.';

  return (
    <div className="page-stack gap-4">
      <PageHeader
        title="Data Enrichment"
        description={descriptionText}
        actions={
          <div className="flex w-full flex-wrap items-center justify-end gap-2">
            <label className="border-border bg-background-elevated text-foreground hover:bg-background-alt inline-flex h-[var(--control-height)] cursor-pointer items-center gap-2 rounded-[var(--radius-md)] border px-3 text-sm transition-colors">
              <input
                type="checkbox"
                checked={llmEnabled}
                onChange={(event) => setLlmEnabled(event.target.checked)}
                className="border-divider text-accent focus:ring-accent h-3.5 w-3.5 cursor-pointer rounded"
              />
              LLM Enrichment
            </label>
            <Button
              type="button"
              variant="accent"
              className="h-[var(--control-height)] px-4"
              disabled={!sourceRecordIds.length || createMutation.isPending || isRunning}
              onClick={() => createMutation.mutate()}
            >
              <Play className="size-3.5" />
              {createMutation.isPending
                ? 'Starting...'
                : isRunning
                  ? activeJob?.status === 'pending'
                    ? 'Starting...'
                    : 'Enriching...'
                  : 'Enrich Selected'}
            </Button>
          </div>
        }
      />

      {error ? <InlineAlert tone="danger" message={error} /> : null}

      {isRunning ? (
        <EnrichmentStatus
          sourceCount={activeJob?.summary?.accepted_count ?? sourceRecords.length}
          llmEnabled={Boolean(activeJob?.options?.llm_enabled)}
        />
      ) : null}

      {/* ── Main Results ── */}
      <div className="mb-8">
        <section className="border-border bg-panel shadow-card overflow-hidden rounded-[var(--radius-xl)] border">
          <header className="border-divider flex flex-wrap items-center justify-between gap-4 border-b px-4 py-3">
            <div className="flex items-center gap-3">
              <h2 className="type-label text-muted text-xs font-normal tracking-widest uppercase">
                {products.length > 0 ? 'ENRICHED OUTPUT' : 'SELECTED RECORDS'}
              </h2>
            </div>
            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => void detailQuery.refetch()}
                disabled={!resolvedJobId || detailQuery.isFetching}
                className="text-muted hover:text-foreground h-8 px-2 text-xs font-bold tracking-tight uppercase"
              >
                <RefreshCcw className="mr-1.5 size-3" />
                Refresh
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                onClick={() => setHistoryOpen(true)}
                aria-label="Enrichment History"
                className="text-muted hover:text-foreground h-8 w-8"
              >
                <History className="size-4" />
              </Button>
            </div>
          </header>

          {isRunning && completedCount === 0 ? (
            <EnrichmentTableLoading llmEnabled={Boolean(activeJob?.options?.llm_enabled)} />
          ) : detailQuery.isLoading && !isRunning ? (
            <DataRegionLoading count={8} className="px-0" />
          ) : products.length ? (
            <div className="commerce-table surface-muted max-h-[70vh] overflow-auto">
              <table className="compact-data-table min-w-[1200px] border-separate border-spacing-0">
                <thead style={{ position: 'sticky', top: 0, zIndex: 20 }}>
                  <tr className="bg-subtle-panel shadow-sm">
                    <th className="bg-subtle-panel sticky left-0 z-30 w-[180px] border-r border-border/50">Record</th>
                    {ENRICHED_FIELD_LABELS.map(([key, label]) => (
                      <th key={String(key)} className="bg-subtle-panel">
                        <div className="flex min-w-0 items-center gap-1">
                          <span className="flex-1 truncate">{label.toUpperCase()}</span>
                        </div>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-divider divide-y">
                  {products.map((product) => (
                    <EnrichedProductRow key={product.id} product={product} />
                  ))}
                </tbody>
              </table>
            </div>
          ) : sourceRecords.length ? (
            <div className="divide-divider divide-y">
              {sourceRecords.map((record, index) => {
                const badgeValue = record.id ?? record.source_url;
                return (
                  <div
                    key={record.id ?? record.source_url ?? index}
                    className="hover:bg-background-alt/50 flex items-center gap-3 px-4 py-2.5 transition-colors"
                  >
                    <span className="text-muted w-6 shrink-0 font-mono text-xs">
                      {index + 1}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="text-foreground truncate text-xs font-medium tracking-tight">
                        {recordTitle(record)}
                      </div>
                      <div className="text-muted flex items-center gap-2 text-xs">
                        {record.source_url ? (
                          <a
                            href={record.source_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-accent truncate opacity-80 hover:underline"
                            title={record.source_url}
                          >
                            {record.source_url}
                          </a>
                        ) : null}
                      </div>
                    </div>
                    {badgeValue ? (
                      <Badge
                        tone="neutral"
                        className="h-5 shrink-0 px-1.5 font-mono text-xs opacity-60"
                      >
                        #{badgeValue}
                      </Badge>
                    ) : null}
                  </div>
                );
              })}
            </div>
          ) : (
            <DataRegionEmpty
              title="No records selected"
              description="Open an ecommerce detail run and send selected records here to begin enrichment."
            />
          )}
        </section>
      </div>

      <HistoryDrawer
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        items={historyItems}
        activeId={resolvedJobId}
        onSelect={(id) => setActiveJobId(id)}
        title="Enrichment History"
      />
    </div>
  );
}

function EnrichedProductRow({ product }: Readonly<{ product: EnrichedProduct }>) {
  return (
    <tr key={product.id} className="group/row hover:bg-subtle-panel transition-colors">
      <td className="bg-background group-hover/row:bg-subtle-panel sticky left-0 z-10 border-r border-border/50 transition-colors">
        <div className="flex items-center gap-2 py-1.5">
          <Badge tone="neutral" className="h-5 shrink-0 px-1.5 font-mono text-xs opacity-60">
            #{product.source_record_id}
          </Badge>
          {product.source_url ? (
            <a
              href={product.source_url}
              target="_blank"
              rel="noreferrer"
              className="text-accent block max-w-[140px] truncate text-sm font-medium transition-colors hover:underline"
              title={product.source_url}
            >
              {product.source_url.replace(/^https?:\/\/(www\.)?/, '')}
            </a>
          ) : null}
        </div>
      </td>
      {ENRICHED_FIELD_LABELS.map(([key]) => {
        const value = product[key];
        const display = formatValue(value);
        const isEnriched = product.status === 'enriched' && Boolean(display && display !== '--');
        const isProcessing = product.status === 'pending' || product.status === 'running';

        return (
          <td key={String(key)}>
            {isEnriched ? (
              <span
                className="text-foreground block max-w-[260px] truncate leading-relaxed font-normal tracking-tight"
                style={{ fontSize: 'var(--table-font-size)' }}
                title={display}
              >
                {display}
              </span>
            ) : isProcessing ? (
              <div className="flex items-center gap-1.5 opacity-40">
                <Loader2 className="text-accent size-3 animate-spin" />
                <span className="text-sm font-medium tracking-wide uppercase">Processing</span>
              </div>
            ) : (
              <span className="text-muted/40 font-mono text-sm">--</span>
            )}
          </td>
        );
      })}
    </tr>
  );
}

function recordTitle(record: DataEnrichmentSourceRecordInput) {
  const title = record.data?.title;
  return typeof title === 'string' && title.trim()
    ? title
    : record.source_url?.replace(/^https?:\/\/(www\.)?/, '') || `Record #${record.id}`;
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '';
  if (Array.isArray(value)) return value.join(', ');
  if (typeof value === 'object') {
    // Handle price object from EnrichmentStatus
    if ('amount' in value || 'price_min' in value) {
      const p = value as Record<string, unknown>;
      const amount = p.amount ?? p.price_min;
      const currency = (p.currency as string) || '';
      if (typeof amount === 'number') {
        return `${currency} ${amount.toFixed(2)}`.trim();
      }
    }
    return JSON.stringify(value);
  }
  return String(value);
}
