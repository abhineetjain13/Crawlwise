'use client';

import { useQuery } from '@tanstack/react-query';
import {
  ChevronDown,
  Code2,
  Download,
  ExternalLink,
  History,
  ImageOff,
  Info,
  Layers,
  Play,
  Search,
  Settings,
  X,
} from 'lucide-react';
import type { Route } from 'next';
import { useRouter } from 'next/navigation';
import { useMemo, useState } from 'react';

import { HistoryDrawer, type HistoryItem } from '../../components/ui/history-drawer';

import { DataRegionEmpty, InlineAlert, PageHeader } from '../../components/ui/patterns';
import { Badge, Button, Dropdown, Input } from '../../components/ui/primitives';
import { cn } from '../../lib/utils';
import { api } from '../../lib/api';
import type {
  ProductIntelligenceJobDetail,
  ProductIntelligenceDiscoveryResponse,
  ProductIntelligenceOptions,
  ProductIntelligenceSourceRecordInput,
} from '../../lib/api/types';
import { STORAGE_KEYS } from '../../lib/constants/storage-keys';
import {
  DiscoveryStatus,
  DiscoveryTableLoading,
  ExternalCandidateImage,
  JsonModal,
  SEARCH_PROVIDER_OPTIONS,
  SettingsDrawer,
  searchProviderLabel,
} from './product-intelligence-components';

type PrefillPayload = {
  source_run_id?: number | null;
  source_domain?: string;
  records?: ProductIntelligenceSourceRecordInput[];
};

type PrefillLoadResult = {
  error: string;
  payload: PrefillPayload;
};

const DEFAULT_OPTIONS: ProductIntelligenceOptions = {
  max_source_products: 10,
  max_candidates_per_product: 2,
  search_provider: 'google_native',
  private_label_mode: 'flag',
  confidence_threshold: 0.4,
  allowed_domains: [],
  excluded_domains: [],
  llm_enrichment_enabled: false,
};

const MAX_SOURCE_PRODUCTS_LIMIT = 500;
const MAX_CANDIDATES_PER_PRODUCT_LIMIT = 25;

function loadPrefillPayload(): PrefillLoadResult {
  if (typeof window === 'undefined') {
    return { error: '', payload: {} };
  }

  const stored = window.sessionStorage.getItem(STORAGE_KEYS.PRODUCT_INTELLIGENCE_PREFILL);
  if (!stored) {
    return { error: '', payload: {} };
  }

  try {
    const parsed = JSON.parse(stored) as PrefillPayload;
    return {
      error: '',
      payload: {
        source_run_id: typeof parsed.source_run_id === 'number' ? parsed.source_run_id : null,
        source_domain: parsed.source_domain ?? '',
        records: Array.isArray(parsed.records) ? parsed.records : [],
      },
    };
  } catch {
    return { error: 'Unable to read Product Intelligence prefill.', payload: {} };
  } finally {
    window.sessionStorage.removeItem(STORAGE_KEYS.PRODUCT_INTELLIGENCE_PREFILL);
  }
}
export default function ProductIntelligencePage() {
  const router = useRouter();
  const [initialPrefill] = useState(loadPrefillPayload);
  const prefill = initialPrefill.payload;
  const [options, setOptions] = useState<ProductIntelligenceOptions>(DEFAULT_OPTIONS);
  const [allowedDomainsText, setAllowedDomainsText] = useState('');
  const [excludedDomainsText, setExcludedDomainsText] = useState('');
  const [discoveryOverride, setDiscoveryOverride] =
    useState<ProductIntelligenceDiscoveryResponse | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState(initialPrefill.error);
  const [selectedUrls, setSelectedUrls] = useState<string[]>([]);
  const [jsonModalCandidate, setJsonModalCandidate] = useState<
    ProductIntelligenceDiscoveryResponse['candidates'][number] | null
  >(null);
  const [activeJobId, setActiveJobId] = useState<number | null>(null);
  const [configOpen, setConfigOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [optionsEdited, setOptionsEdited] = useState(false);
  const [searchText, setSearchText] = useState('');
  const [confidenceFilter, setConfidenceFilter] = useState<'all' | 'high' | 'medium' | 'low'>(
    'all',
  );

  const jobsQuery = useQuery({
    queryKey: ['product-intelligence-jobs'],
    queryFn: () => api.listProductIntelligenceJobs({ limit: 20 }),
  });

  const historyItems: HistoryItem[] = useMemo(() => {
    return (jobsQuery.data ?? []).map((job) => ({
      id: job.id,
      status: job.status,
      created_at: job.created_at,
      label: job.source_run_id ? `From Run #${job.source_run_id}` : 'Direct Input',
      meta: `${Number(job.summary?.candidate_count ?? 0)} URLs found`,
    }));
  }, [jobsQuery.data]);
  const sourceRecords = prefill.records ?? [];
  const defaultJobId = sourceRecords.length ? null : (jobsQuery.data?.[0]?.id ?? null);
  const resolvedActiveJobId = activeJobId ?? defaultJobId;
  const detailQuery = useQuery({
    queryKey: ['product-intelligence-job', resolvedActiveJobId],
    queryFn: () => api.getProductIntelligenceJob(resolvedActiveJobId ?? 0),
    enabled: resolvedActiveJobId !== null,
  });
  const detailHydratedOptions = useMemo(
    () => (detailQuery.data ? detailOptions(detailQuery.data.job.options) : DEFAULT_OPTIONS),
    [detailQuery.data],
  );
  const discovery =
    discoveryOverride ?? (detailQuery.data ? detailToDiscovery(detailQuery.data) : null);
  const effectiveOptions = optionsEdited || !detailQuery.data ? options : detailHydratedOptions;
  const effectiveSearchProvider = effectiveOptions.search_provider;
  const effectiveAllowedDomainsText = optionsEdited
    ? allowedDomainsText
    : detailHydratedOptions.allowed_domains.join('\n');
  const effectiveExcludedDomainsText = optionsEdited
    ? excludedDomainsText
    : detailHydratedOptions.excluded_domains.join('\n');
  const visibleSourceRecords = sourceRecords.length
    ? sourceRecords
    : detailQuery.data
      ? detailQuery.data.source_products.map((source) => ({
          id: source.source_record_id,
          run_id: source.source_run_id,
          source_url: source.source_url,
          data: source.payload,
        }))
      : [];
  const activeSourceRunId = sourceRecords.length
    ? (prefill.source_run_id ??
      sourceRecords.find((record) => typeof record.run_id === 'number')?.run_id ??
      null)
    : (detailQuery.data?.job.source_run_id ??
      visibleSourceRecords.find((record) => typeof record.run_id === 'number')?.run_id ??
      prefill.source_run_id ??
      null);
  const uniqueSelectedUrls = useMemo(
    () =>
      Array.from(new Set(selectedUrls)).filter((url) =>
        (discovery?.candidates ?? []).some((candidate) => candidate.url === url),
      ),
    [discovery, selectedUrls],
  );
  const allCandidateUrls = useMemo(
    () =>
      Array.from(
        new Set((discovery?.candidates ?? []).map((candidate) => candidate.url).filter(Boolean)),
      ),
    [discovery],
  );
  const filteredCandidates = useMemo(() => {
    const all = discovery?.candidates ?? [];
    return all.filter((c) => {
      if (searchText) {
        const q = searchText.toLowerCase();
        const matchesSearch =
          (c.source_title ?? '').toLowerCase().includes(q) ||
          (c.source_brand ?? '').toLowerCase().includes(q) ||
          (c.domain ?? '').toLowerCase().includes(q) ||
          (c.url ?? '').toLowerCase().includes(q);
        if (!matchesSearch) return false;
      }
      if (confidenceFilter !== 'all') {
        const score = candidateConfidence(c);
        if (confidenceFilter === 'high' && score < 0.6) return false;
        if (confidenceFilter === 'medium' && (score < 0.4 || score >= 0.6)) return false;
        if (confidenceFilter === 'low' && score >= 0.4) return false;
      }
      return true;
    });
  }, [discovery, searchText, confidenceFilter]);
  const groupedCandidates = useMemo(() => {
    const groups = new Map<number, typeof filteredCandidates>();
    filteredCandidates.forEach((c) => {
      const idx = c.source_index ?? 0;
      if (!groups.has(idx)) groups.set(idx, []);
      groups.get(idx)!.push(c);
    });
    return Array.from(groups.entries()).map(([sourceIndex, candidates]) => ({
      sourceIndex,
      sourceTitle: candidates[0].source_title,
      sourceBrand: candidates[0].source_brand,
      sourcePrice: candidates[0].source_price,
      sourceCurrency: candidates[0].source_currency,
      sourceUrl: candidates[0].source_url,
      candidates,
    }));
  }, [filteredCandidates]);

  const confidenceDistribution = useMemo(() => {
    const all = discovery?.candidates ?? [];
    return {
      high: all.filter((c) => candidateConfidence(c) >= 0.6).length,
      medium: all.filter((c) => {
        const s = candidateConfidence(c);
        return s >= 0.4 && s < 0.6;
      }).length,
      low: all.filter((c) => candidateConfidence(c) < 0.4).length,
    };
  }, [discovery]);
  const selectedDomainSummary = useMemo(() => {
    if (!uniqueSelectedUrls.length) return null;
    const domains = Array.from(
      new Set(
        (discovery?.candidates ?? [])
          .filter((c) => uniqueSelectedUrls.includes(c.url))
          .map((c) => c.domain)
          .filter(Boolean),
      ),
    );
    return { count: uniqueSelectedUrls.length, domains };
  }, [discovery, uniqueSelectedUrls]);

  async function discover() {
    if (!visibleSourceRecords.length) {
      return;
    }
    setPending(true);
    setError('');
    setDiscoveryOverride(null);
    setSelectedUrls([]);
    try {
      const sourceRecordIds = visibleSourceRecords
        .map((record) => record.id)
        .filter((value): value is number => typeof value === 'number');
      const canUseRecordIds = sourceRecordIds.length === visibleSourceRecords.length;
      const submittedOptions = {
        ...effectiveOptions,
        search_provider: searchProvider(effectiveOptions.search_provider),
        allowed_domains: parseDomainLines(effectiveAllowedDomainsText),
        excluded_domains: parseDomainLines(effectiveExcludedDomainsText),
      };
      const response = await api.discoverProductIntelligence({
        source_run_id: activeSourceRunId,
        source_record_ids: canUseRecordIds ? sourceRecordIds : [],
        source_records: canUseRecordIds ? [] : visibleSourceRecords,
        options: submittedOptions,
      });
      const echoedProvider = searchProvider(
        response.search_provider ?? response.options?.search_provider,
      );
      if (echoedProvider !== submittedOptions.search_provider) {
        setError(
          `Provider mismatch: submitted ${searchProviderLabel(submittedOptions.search_provider)}, backend used ${searchProviderLabel(echoedProvider)}.`,
        );
      }
      setDiscoveryOverride(response);
      setActiveJobId(response.job_id);
      const nextOptions = detailOptions(response.options);
      setOptions(nextOptions);
      setAllowedDomainsText(nextOptions.allowed_domains.join('\n'));
      setExcludedDomainsText(nextOptions.excluded_domains.join('\n'));
      setOptionsEdited(false);
      await jobsQuery.refetch();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to discover candidates.');
    } finally {
      setPending(false);
    }
  }

  function toggleUrl(url: string) {
    setSelectedUrls((current) =>
      current.includes(url) ? current.filter((item) => item !== url) : [...current, url],
    );
  }

  function sendSelectedToBatchCrawl() {
    if (!uniqueSelectedUrls.length) {
      return;
    }
    window.sessionStorage.setItem(
      STORAGE_KEYS.BULK_PREFILL,
      JSON.stringify({
        domain: 'commerce',
        urls: uniqueSelectedUrls,
      }),
    );
    router.replace('/crawl?module=pdp&mode=batch' as Route);
  }

  function toggleAllUrls() {
    const filteredUrls = filteredCandidates.map((c) => c.url).filter(Boolean);
    const allFilteredSelected = filteredUrls.every((url) => selectedUrls.includes(url));
    if (allFilteredSelected && filteredUrls.length > 0) {
      setSelectedUrls((current) => current.filter((url) => !filteredUrls.includes(url)));
    } else {
      setSelectedUrls((current) => Array.from(new Set([...current, ...filteredUrls])));
    }
  }

  function openJob(jobId: number) {
    setActiveJobId(jobId);
    setDiscoveryOverride(null);
    setSelectedUrls([]);
    setOptionsEdited(false);
  }

  return (
    <div className="page-stack gap-4">
      <PageHeader
        title="Product Intelligence"
        description={
          [
            visibleSourceRecords.length > 0 ? `${visibleSourceRecords.length} sources` : null,
            discovery ? `${discovery.candidate_count} discovered` : null,
            uniqueSelectedUrls.length > 0 ? `${uniqueSelectedUrls.length} selected` : null,
          ]
            .filter(Boolean)
            .join(' · ') || 'Discover matching product URLs from source records'
        }
        actions={
          <div className="flex w-full flex-wrap items-center justify-end gap-2">
            <Button
              type="button"
              variant="accent"
              onClick={() => void discover()}
              disabled={pending || !visibleSourceRecords.length}
              className="h-[var(--control-height)] px-4"
            >
              <Search className="size-3.5" />
              {pending ? 'Discovering...' : 'Discover URLs'}
            </Button>
            <Button
              type="button"
              variant="accent"
              onClick={sendSelectedToBatchCrawl}
              disabled={!uniqueSelectedUrls.length}
              className="h-[var(--control-height)]"
            >
              <Play className="size-3.5" />
              Batch Crawl {uniqueSelectedUrls.length ? `(${uniqueSelectedUrls.length})` : ''}
            </Button>
          </div>
        }
      />

      {error ? <InlineAlert tone="danger" message={error} /> : null}
      {pending ? (
        <DiscoveryStatus
          provider={effectiveSearchProvider}
          sourceCount={visibleSourceRecords.length}
          maxCandidates={effectiveOptions.max_candidates_per_product}
        />
      ) : null}

      {/* ── Main Results ── */}
      <div>
        {/* Left Column: Card Grid */}
        <div className="space-y-4">
          {/* ── Discovery Results ── */}
          <section className="border-border bg-panel shadow-card overflow-hidden rounded-[var(--radius-xl)] border">
            {/* Merged Toolbar */}
            <header className="border-divider flex flex-wrap items-center gap-4 border-b px-4 py-3">
              <div className="flex shrink-0 items-center gap-3">
                {discovery?.candidates.length ? (
                  <input
                    type="checkbox"
                    className="border-divider text-accent focus:ring-accent h-3.5 w-3.5 cursor-pointer rounded"
                    checked={
                      filteredCandidates.length > 0 &&
                      filteredCandidates.every((c) => selectedUrls.includes(c.url))
                    }
                    onChange={toggleAllUrls}
                    aria-label="Select all filtered URLs"
                    title="Select all filtered URLs"
                  />
                ) : null}
                <h2 className="type-label-mono text-muted uppercase">DISCOVERED CANDIDATES</h2>
              </div>

              {discovery?.candidates.length ? (
                <div className="flex flex-1 items-center gap-2">
                  <div className="relative min-w-[200px] flex-1">
                    <Search className="text-muted absolute top-1/2 left-2.5 size-3 -translate-y-1/2" />
                    <Input
                      type="text"
                      value={searchText}
                      onChange={(e) => setSearchText(e.target.value)}
                      placeholder="Filter by title, domain, or brand..."
                      className="bg-background-alt focus:bg-background focus:border-accent/20 type-body h-8 border-transparent pl-8"
                    />
                  </div>
                  <Dropdown
                    value={confidenceFilter}
                    onChange={(v) => setConfidenceFilter(v as 'all' | 'high' | 'medium' | 'low')}
                    options={[
                      { value: 'all', label: 'All Confidence' },
                      { value: 'high', label: `High (${confidenceDistribution.high})` },
                      { value: 'medium', label: `Med (${confidenceDistribution.medium})` },
                      { value: 'low', label: `Low (${confidenceDistribution.low})` },
                    ]}
                    ariaLabel="Filter by confidence"
                    className="type-control h-8 w-[160px]"
                  />
                </div>
              ) : null}

              <div className="flex items-center gap-2">
                {selectedDomainSummary ? (
                  <>
                    <div className="bg-accent border-accent flex items-center gap-2 rounded border px-2 py-1">
                      <span className="type-label-mono font-bold text-white uppercase">
                        {selectedDomainSummary.count} selected
                      </span>
                    </div>
                    <div className="bg-divider mx-1 h-4 w-px" />
                  </>
                ) : null}
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  onClick={() => setConfigOpen(true)}
                  aria-label="Settings"
                  className="text-muted hover:text-foreground h-8 w-8"
                >
                  <Settings className="size-4" />
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  onClick={() => setHistoryOpen(true)}
                  aria-label="Run History"
                  className="text-muted hover:text-foreground h-8 w-8"
                >
                  <History className="size-4" />
                </Button>
                <div className="flex items-center gap-1">
                  <Button
                    type="button"
                    variant="secondary"
                    size="icon"
                    onClick={() => downloadRows('urls', 'csv', discovery)}
                    disabled={!discovery?.candidates.length}
                    className="h-8 w-8"
                    aria-label="Download CSV"
                  >
                    <Download className="size-3.5" />
                  </Button>
                  <Button
                    type="button"
                    variant="secondary"
                    size="icon"
                    onClick={() => downloadRows('urls', 'json', discovery)}
                    disabled={!discovery?.candidates.length}
                    className="h-8 w-8"
                    aria-label="Download JSON"
                  >
                    <Code2 className="size-3.5" />
                  </Button>
                </div>
              </div>
            </header>

            {/* ── Grouped Results ── */}
            {pending ? (
              <DiscoveryTableLoading provider={effectiveSearchProvider} />
            ) : groupedCandidates.length ? (
              <div className="divide-y divide-[var(--divider)]">
                {groupedCandidates.map((group, groupIndex) => (
                  <details key={group.sourceIndex} className="group" open={groupIndex === 0}>
                    <summary className="hover:bg-background-alt/50 flex cursor-pointer list-none items-center gap-4 px-4 py-3 transition-colors select-none">
                      <div className="border-divider bg-background text-muted group-open:bg-accent group-open:border-accent type-caption-mono flex size-6 shrink-0 items-center justify-center rounded-full border font-bold group-open:text-white">
                        {group.candidates.length}
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span
                            className="text-foreground type-body truncate font-medium"
                            title={group.sourceTitle}
                          >
                            {group.sourceTitle}
                          </span>
                          <Badge
                            tone="neutral"
                            className="type-label-mono h-4 px-1.5 uppercase opacity-60"
                          >
                            Source
                          </Badge>
                        </div>
                        <div className="mt-0.5 flex items-center gap-3">
                          {group.sourceBrand && group.sourceBrand !== '--' && (
                            <span className="text-muted type-caption flex items-center gap-1.5">
                              <Layers className="size-3 opacity-50" />
                              {group.sourceBrand}
                            </span>
                          )}
                          {group.sourceBrand && group.sourceBrand !== '--' && group.sourcePrice && (
                            <span className="bg-divider h-1 w-1 rounded-full" />
                          )}
                          {group.sourcePrice && (
                            <span className="text-foreground type-caption-mono font-medium">
                              {formatPrice(group.sourcePrice, group.sourceCurrency)}
                            </span>
                          )}
                        </div>
                      </div>
                      <ChevronDown className="text-muted size-4 shrink-0 transition-transform group-open:rotate-180" />
                    </summary>

                    <div className="bg-background-alt/30 border-divider grid grid-cols-1 gap-3 border-t p-4 md:grid-cols-2 xl:grid-cols-3">
                      {group.candidates.map((candidate) => {
                        const selected = uniqueSelectedUrls.includes(candidate.url);
                        const score = candidateConfidence(candidate);
                        const intelligence = isRecord(candidate.intelligence)
                          ? candidate.intelligence
                          : {};
                        const record = isRecord(intelligence.canonical_record)
                          ? intelligence.canonical_record
                          : {};
                        const imageUrl = stringField(record.image_url);
                        const recordPrice = stringField(record.price);
                        const recordCurrency = stringField(record.currency);

                        return (
                          <div
                            key={candidate.url}
                            className={cn(
                              'group/card border-border bg-panel hover:border-accent/40 relative flex flex-col rounded-[var(--radius-md)] border p-3 transition-all hover:shadow-md',
                              selected && 'border-accent/60 bg-accent-subtle/20 shadow-sm',
                            )}
                          >
                            <div className="flex gap-4">
                              {/* Thumbnail with Overlay Badge */}
                              <div className="border-divider relative aspect-square w-[100px] shrink-0 overflow-hidden rounded-[var(--radius-md)] border bg-white p-1.5 shadow-sm">
                                {Boolean(imageUrl) ? (
                                  <ExternalCandidateImage
                                    src={imageUrl}
                                    alt={stringField(record.title)}
                                    className="size-full object-contain mix-blend-multiply"
                                  />
                                ) : (
                                  <div className="text-muted/30 flex size-full items-center justify-center">
                                    <ImageOff className="size-8" />
                                  </div>
                                )}
                                <div
                                  className={cn(
                                    'type-caption-mono absolute right-1.5 bottom-1.5 rounded-md border px-1.5 py-0.5 font-bold shadow-sm',
                                    score >= 0.6
                                      ? 'bg-success border-success text-white'
                                      : score >= 0.4
                                        ? 'bg-warning border-warning text-white'
                                        : 'bg-background-elevated text-muted border-divider',
                                  )}
                                >
                                  {Math.round(score * 100)}%
                                </div>
                              </div>

                              <div className="flex min-w-0 flex-1 flex-col justify-between py-0.5">
                                <div className="space-y-1.5">
                                  <div className="flex items-start justify-between gap-3">
                                    <a
                                      href={candidate.url}
                                      target="_blank"
                                      rel="noopener noreferrer"
                                      className="group/link text-foreground hover:text-accent type-body line-clamp-2 font-normal transition-colors"
                                    >
                                      {stringField(record.title) || candidate.url}
                                    </a>
                                    <input
                                      type="checkbox"
                                      checked={selected}
                                      onChange={(e) => {
                                        e.stopPropagation();
                                        if (candidate.url) toggleUrl(candidate.url);
                                      }}
                                      aria-label={`Select product for batch crawl: ${
                                        stringField(record.title) || candidate.url
                                      }`}
                                      className="border-divider text-accent focus:ring-accent mt-0.5 h-4 w-4 shrink-0 cursor-pointer rounded"
                                    />
                                  </div>

                                  <div className="flex flex-col gap-1">
                                    {recordPrice && recordPrice !== '--' && (
                                      <div className="text-foreground type-body font-semibold">
                                        {formatExtractedPrice(recordPrice, recordCurrency)}
                                      </div>
                                    )}
                                    {(stringField(record.brand) || candidate.source_brand) && (
                                      <div className="text-muted type-label-mono uppercase">
                                        {stringField(record.brand) || candidate.source_brand}
                                      </div>
                                    )}
                                  </div>
                                </div>

                                <div
                                  className="text-muted/80 type-caption-mono mt-2 truncate"
                                  title={candidate.domain}
                                >
                                  {candidate.domain}
                                </div>
                              </div>
                            </div>

                            <div className="border-divider mt-3 flex items-center justify-between border-t pt-2.5">
                              <Button
                                type="button"
                                variant="ghost"
                                size="sm"
                                className="text-muted hover:text-accent type-label-mono h-6 px-2 uppercase"
                                onClick={() => setJsonModalCandidate(candidate)}
                              >
                                <Code2 className="mr-1.5 size-3" /> Raw JSON
                              </Button>
                              <a
                                href={candidate.url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-accent type-label-mono flex items-center gap-1 uppercase hover:underline"
                              >
                                View Source <ExternalLink className="size-2.5" />
                              </a>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </details>
                ))}
              </div>
            ) : visibleSourceRecords.length ? (
              <div className="divide-y divide-[var(--divider)]">
                {visibleSourceRecords.map((record, index) => {
                  const data = isRecord(record.data) ? record.data : {};
                  const title = stringField(data.title ?? data.name ?? data.product_title);
                  const brand = stringField(data.brand ?? data.brand_name);
                  const price = formatPrice(
                    data.price,
                    typeof data.currency === 'string' ? data.currency : '',
                  );
                  const url = (typeof data.url === 'string' && data.url) || record.source_url || '';
                  return (
                    <div
                      key={`${record.id ?? 'src'}-${index}`}
                      className="hover:bg-background-alt flex items-center gap-3 px-3 py-2.5"
                    >
                      <span className="text-muted type-caption-mono w-6 shrink-0">{index + 1}</span>
                      <div className="min-w-0 flex-1">
                        <div
                          className="text-foreground type-body truncate font-medium"
                          title={title}
                        >
                          {title}
                        </div>
                        <div className="text-muted type-caption flex items-center gap-2">
                          <span>{brand}</span>
                          <span className="type-caption-mono">{price}</span>
                          {url ? (
                            <a
                              href={url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="link-accent truncate hover:underline"
                              title={url}
                            >
                              {url}
                            </a>
                          ) : null}
                        </div>
                      </div>
                      <Badge tone="neutral" className="h-5 shrink-0 px-1.5 text-xs">
                        Pending
                      </Badge>
                    </div>
                  );
                })}
              </div>
            ) : (
              <DataRegionEmpty
                title="No discovery results yet"
                description="Add source products from a crawl run, configure search options, then click Discover URLs to find matching products across the web."
              />
            )}
          </section>

          {/* ── Bulk Action Bar (slides in when URLs selected) ── */}
          {uniqueSelectedUrls.length > 0 && (
            <div className="animate-fade-in sticky bottom-4 z-20">
              <div className="border-border bg-panel flex items-center gap-3 rounded-[var(--radius-xl)] border px-4 py-2.5 shadow-lg">
                <Layers className="text-accent size-4 shrink-0" />
                <span className="text-foreground type-body font-medium">
                  {uniqueSelectedUrls.length} URLs selected
                </span>
                <span className="text-muted type-body">
                  from {selectedDomainSummary?.domains.length ?? 0} domain
                  {(selectedDomainSummary?.domains.length ?? 0) !== 1 ? 's' : ''}
                </span>
                <div className="ml-auto flex items-center gap-2">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => setSelectedUrls([])}
                    className="text-muted h-7 px-2"
                  >
                    <X className="size-3" /> Clear
                  </Button>
                  <Button
                    type="button"
                    variant="accent"
                    size="sm"
                    onClick={sendSelectedToBatchCrawl}
                    className="h-7 px-3"
                  >
                    <Play className="size-3" /> Batch Crawl
                  </Button>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      <SettingsDrawer
        open={configOpen}
        onClose={() => setConfigOpen(false)}
        options={effectiveOptions}
        onOptionsChange={(patch) => {
          setOptionsEdited(true);
          setOptions((current) => ({ ...current, ...patch }));
        }}
        allowedDomainsText={effectiveAllowedDomainsText}
        onAllowedDomainsTextChange={(value) => {
          setOptionsEdited(true);
          setAllowedDomainsText(value);
        }}
        excludedDomainsText={effectiveExcludedDomainsText}
        onExcludedDomainsTextChange={(value) => {
          setOptionsEdited(true);
          setExcludedDomainsText(value);
        }}
        maxSourceProductsLimit={MAX_SOURCE_PRODUCTS_LIMIT}
        maxCandidatesPerProductLimit={MAX_CANDIDATES_PER_PRODUCT_LIMIT}
        defaultOptions={DEFAULT_OPTIONS}
      />

      {/* JSON Modal */}
      {jsonModalCandidate && (
        <JsonModal candidate={jsonModalCandidate} onClose={() => setJsonModalCandidate(null)} />
      )}
      <HistoryDrawer
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        items={historyItems}
        activeId={resolvedActiveJobId}
        onSelect={(id) => openJob(id)}
        title="Intelligence History"
      />
    </div>
  );
}

function detailToDiscovery(
  detail: ProductIntelligenceJobDetail,
): ProductIntelligenceDiscoveryResponse {
  const sourcesById = new Map<
    number,
    { source: ProductIntelligenceJobDetail['source_products'][number]; index: number }
  >();
  detail.source_products.forEach((source, index) => {
    if (sourcesById.has(source.id)) {
      console.warn('Duplicate Product Intelligence source id; keeping first.', {
        job_id: detail.job.id,
        source_id: source.id,
        duplicate_index: index,
        first_index: sourcesById.get(source.id)?.index,
      });
      return;
    }
    sourcesById.set(source.id, { source, index });
  });
  const candidates = detail.candidates.map((candidate) => {
    const sourceEntry = sourcesById.get(candidate.source_product_id);
    const source = sourceEntry?.source;
    return {
      source_record_id: source?.source_record_id ?? null,
      source_run_id: source?.source_run_id ?? null,
      source_url: source?.source_url ?? '',
      source_title: source?.title ?? '',
      source_brand: source?.brand ?? '',
      source_price: source?.price ?? null,
      source_currency: source?.currency ?? '',
      source_index: sourceEntry?.index ?? 0,
      url: candidate.url,
      domain: candidate.domain,
      source_type: candidate.source_type,
      query_used: candidate.query_used,
      search_rank: candidate.search_rank,
      payload: candidate.payload ?? {},
      intelligence: isRecord(candidate.payload?.intelligence) ? candidate.payload.intelligence : {},
    };
  });
  return {
    job_id: detail.job.id,
    options: detail.job.options ?? {},
    source_count: detail.source_products.length,
    candidate_count: candidates.length,
    candidates,
  };
}

function detailOptions(
  value: Record<string, unknown> | null | undefined,
): ProductIntelligenceOptions {
  const raw = isRecord(value) ? value : {};
  return {
    ...DEFAULT_OPTIONS,
    max_source_products: clampInt(
      raw.max_source_products,
      1,
      MAX_SOURCE_PRODUCTS_LIMIT,
      DEFAULT_OPTIONS.max_source_products,
    ),
    max_candidates_per_product: clampInt(
      raw.max_candidates_per_product,
      1,
      MAX_CANDIDATES_PER_PRODUCT_LIMIT,
      DEFAULT_OPTIONS.max_candidates_per_product,
    ),
    search_provider: searchProvider(raw.search_provider),
    private_label_mode: privateLabelMode(raw.private_label_mode),
    confidence_threshold: clampFloat(
      raw.confidence_threshold,
      0,
      1,
      DEFAULT_OPTIONS.confidence_threshold,
    ),
    allowed_domains: stringArray(raw.allowed_domains),
    excluded_domains: stringArray(raw.excluded_domains),
    llm_enrichment_enabled: Boolean(raw.llm_enrichment_enabled),
  };
}

function privateLabelMode(value: unknown): ProductIntelligenceOptions['private_label_mode'] {
  return value === 'include' || value === 'exclude' || value === 'flag'
    ? value
    : DEFAULT_OPTIONS.private_label_mode;
}

function searchProvider(value: unknown): ProductIntelligenceOptions['search_provider'] {
  return value === 'google_native' || value === 'serpapi' ? value : DEFAULT_OPTIONS.search_provider;
}

function parseDomainLines(value: string) {
  return value
    .split(/[\n,]+/)
    .map((line) => line.trim().toLowerCase())
    .filter(Boolean);
}

function stringArray(value: unknown) {
  return Array.isArray(value)
    ? value
        .map((item) =>
          String(item || '')
            .trim()
            .toLowerCase(),
        )
        .filter(Boolean)
    : [];
}

function candidateConfidence(
  candidate: ProductIntelligenceDiscoveryResponse['candidates'][number],
) {
  const intelligence = isRecord(candidate.intelligence) ? candidate.intelligence : {};
  const parsed = Number(intelligence.confidence_score ?? 0);
  return Number.isFinite(parsed) ? Math.min(Math.max(parsed, 0), 1) : 0;
}

function toIntelligenceRow(candidate: ProductIntelligenceDiscoveryResponse['candidates'][number]) {
  const intelligence = isRecord(candidate.intelligence) ? candidate.intelligence : {};
  const record = isRecord(intelligence.canonical_record) ? intelligence.canonical_record : {};
  const parsedConfidence = Number(intelligence.confidence_score ?? 0);
  const confidenceScore = Number.isFinite(parsedConfidence) ? parsedConfidence : 0;
  return {
    source_index: candidate.source_index,
    source_title: candidate.source_title,
    source_brand: candidate.source_brand,
    source_price: candidate.source_price,
    source_currency: candidate.source_currency,
    url: candidate.url,
    domain: candidate.domain,
    record,
    confidence_score: confidenceScore,
    confidence_label: String(intelligence.confidence_label ?? ''),
    cleanup_source: String(intelligence.cleanup_source ?? ''),
    score_reasons: isRecord(intelligence.score_reasons) ? intelligence.score_reasons : {},
  };
}

const PREFERRED_INTELLIGENCE_COLUMNS = [
  'title',
  'description',
  'brand',
  'price',
  'currency',
  'availability',
  'sku',
  'mpn',
  'gtin',
  'image_url',
  'url',
];

function intelligenceColumnNames(rows: Array<ReturnType<typeof toIntelligenceRow>>) {
  const columns = new Set<string>();
  for (const row of rows) {
    for (const key of Object.keys(row.record)) {
      if (!key.startsWith('_') && !isEmptyValue(row.record[key])) {
        columns.add(key);
      }
    }
    columns.add('url');
  }
  return [
    ...PREFERRED_INTELLIGENCE_COLUMNS.filter((column) => columns.has(column)),
    ...Array.from(columns)
      .filter((column) => !PREFERRED_INTELLIGENCE_COLUMNS.includes(column))
      .sort((left, right) => left.localeCompare(right)),
  ];
}

function intelligenceCellValue(row: ReturnType<typeof toIntelligenceRow>, column: string) {
  if (column === 'price') {
    return formatExtractedPrice(row.record.price, row.record.currency);
  }
  if (column === 'currency') {
    return stringField(row.record.currency);
  }
  if (column === 'url') {
    return stringField(row.record.url || row.url);
  }
  return formatIntelligenceValue(row.record[column]);
}

function formatExtractedPrice(price: unknown, currency: unknown) {
  if (isEmptyValue(price)) {
    return '--';
  }
  const currencyText = String(currency ?? '').trim();
  if (typeof price === 'number' && currencyText) {
    return formatPrice(price, currencyText);
  }
  return String(price);
}

function formatIntelligenceValue(value: unknown) {
  if (isEmptyValue(value)) {
    return '--';
  }
  if (typeof value === 'object') {
    return JSON.stringify(value);
  }
  return String(value);
}

function isEmptyValue(value: unknown) {
  return value === undefined || value === null || String(value).trim() === '';
}

function longIntelligenceColumn(column: string) {
  return (
    column === 'description' || column === 'snippet' || column === 'image_url' || column === 'url'
  );
}

function stringField(value: unknown) {
  const text = String(value ?? '').trim();
  return text === '--' || text === 'null' || text === 'undefined' ? '' : text;
}

function downloadRows(
  tab: 'urls' | 'intelligence',
  kind: 'csv' | 'json',
  discovery: ProductIntelligenceDiscoveryResponse | null,
) {
  const rows: Array<Record<string, unknown>> =
    tab === 'urls'
      ? (discovery?.candidates ?? []).map((candidate) => ({ ...candidate }))
      : (discovery?.candidates ?? []).map(toIntelligenceExportRow);
  const body = kind === 'csv' ? toCsv(rows) : JSON.stringify(rows, null, 2);
  const type = kind === 'csv' ? 'text/csv;charset=utf-8' : 'application/json;charset=utf-8';
  const url = URL.createObjectURL(new Blob([body], { type }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `product-intelligence-${tab}.${kind}`;
  anchor.click();
  URL.revokeObjectURL(url);
}

function toIntelligenceExportRow(
  candidate: ProductIntelligenceDiscoveryResponse['candidates'][number],
) {
  const row = toIntelligenceRow(candidate);
  return {
    source_title: row.source_title,
    source_brand: row.source_brand,
    result_url: row.url,
    result_domain: row.domain,
    title: row.record.title ?? '',
    brand: row.record.brand ?? '',
    price: row.record.price ?? '',
    currency: row.record.currency ?? '',
    confidence_score: row.confidence_score,
    confidence_label: row.confidence_label,
    cleanup_source: row.cleanup_source,
    score_reasons: row.score_reasons,
  };
}

function toCsv(rows: Array<Record<string, unknown>>) {
  const headers = Array.from(new Set(rows.flatMap((row) => Object.keys(row))));
  const lines = [headers.join(',')];
  for (const row of rows) {
    lines.push(headers.map((header) => csvCell(row[header])).join(','));
  }
  return lines.join('\n');
}

function csvCell(value: unknown) {
  const text =
    typeof value === 'object' && value !== null ? JSON.stringify(value) : String(value ?? '');
  return `"${text.replace(/"/g, '""')}"`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function displayValue(data: Record<string, unknown>, fields: string[]) {
  for (const field of fields) {
    const value = data[field];
    if (value !== undefined && value !== null && value !== '') {
      return String(value);
    }
  }
  return '';
}

function formatPrice(value: unknown, currency = '') {
  const numeric =
    typeof value === 'number' ? value : Number(String(value ?? '').replace(/[^0-9.]+/g, ''));
  if (!Number.isFinite(numeric) || numeric <= 0) {
    return null;
  }
  const prefix = currency || '$';
  return `${prefix}${numeric.toFixed(2)}`;
}

function clampInt(value: unknown, min: number, max: number, fallback: number) {
  const parsed = Number.parseInt(String(value), 10);
  if (!Number.isFinite(parsed)) {
    return fallback;
  }
  return Math.min(Math.max(parsed, min), max);
}

function clampFloat(value: unknown, min: number, max: number, fallback: number) {
  const parsed = Number.parseFloat(String(value));
  if (!Number.isFinite(parsed)) {
    return fallback;
  }
  return Math.min(Math.max(parsed, min), max);
}
