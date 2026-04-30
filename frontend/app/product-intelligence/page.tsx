"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronDown, Code2, Download, ExternalLink, ImageOff, Info, Layers, Play, Search, Settings, X } from "lucide-react";
import type { Route } from "next";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { DataRegionEmpty, InlineAlert, PageHeader } from "../../components/ui/patterns";
import {
  Badge,
  Button,
  Dropdown,
  Input,
  TableBody,
} from "../../components/ui/primitives";
import { cn } from "../../lib/utils";
import { api } from "../../lib/api";
import type {
  ProductIntelligenceJobDetail,
  ProductIntelligenceDiscoveryResponse,
  ProductIntelligenceOptions,
  ProductIntelligenceSourceRecordInput,
} from "../../lib/api/types";
import { STORAGE_KEYS } from "../../lib/constants/storage-keys";
import {
  DiscoveryStatus,
  DiscoveryTableLoading,
  ExternalCandidateImage,
  JsonModal,
  ProductIntelligenceJobRow,
  SEARCH_PROVIDER_OPTIONS,
  SettingsDrawer,
  searchProviderLabel,
} from "./product-intelligence-components";

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
  search_provider: "google_native",
  private_label_mode: "flag",
  confidence_threshold: 0.4,
  allowed_domains: [],
  excluded_domains: [],
  llm_enrichment_enabled: false,
};

const MAX_SOURCE_PRODUCTS_LIMIT = 500;
const MAX_CANDIDATES_PER_PRODUCT_LIMIT = 25;

function loadPrefillPayload(): PrefillLoadResult {
  if (typeof window === "undefined") {
    return { error: "", payload: {} };
  }

  const stored = window.sessionStorage.getItem(STORAGE_KEYS.PRODUCT_INTELLIGENCE_PREFILL);
  if (!stored) {
    return { error: "", payload: {} };
  }

  try {
    const parsed = JSON.parse(stored) as PrefillPayload;
    return {
      error: "",
      payload: {
        source_run_id: typeof parsed.source_run_id === "number" ? parsed.source_run_id : null,
        source_domain: parsed.source_domain ?? "",
        records: Array.isArray(parsed.records) ? parsed.records : [],
      },
    };
  } catch {
    return { error: "Unable to read Product Intelligence prefill.", payload: {} };
  } finally {
    window.sessionStorage.removeItem(STORAGE_KEYS.PRODUCT_INTELLIGENCE_PREFILL);
  }
}
export default function ProductIntelligencePage() {
  const router = useRouter();
  const [initialPrefill] = useState(loadPrefillPayload);
  const prefill = initialPrefill.payload;
  const [options, setOptions] = useState<ProductIntelligenceOptions>(DEFAULT_OPTIONS);
  const [allowedDomainsText, setAllowedDomainsText] = useState("");
  const [excludedDomainsText, setExcludedDomainsText] = useState("");
  const [discoveryOverride, setDiscoveryOverride] = useState<ProductIntelligenceDiscoveryResponse | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState(initialPrefill.error);
  const [selectedUrls, setSelectedUrls] = useState<string[]>([]);
  const [jsonModalCandidate, setJsonModalCandidate] = useState<ProductIntelligenceDiscoveryResponse["candidates"][number] | null>(null);
  const [activeJobId, setActiveJobId] = useState<number | null>(null);
  const [configOpen, setConfigOpen] = useState(false);
  const [optionsEdited, setOptionsEdited] = useState(false);
  const [searchText, setSearchText] = useState("");
  const [confidenceFilter, setConfidenceFilter] = useState<"all" | "high" | "medium" | "low">("all");

  const jobsQuery = useQuery({
    queryKey: ["product-intelligence-jobs"],
    queryFn: () => api.listProductIntelligenceJobs({ limit: 20 }),
  });
  const sourceRecords = prefill.records ?? [];
  const defaultJobId = sourceRecords.length ? null : jobsQuery.data?.[0]?.id ?? null;
  const resolvedActiveJobId = activeJobId ?? defaultJobId;
  const detailQuery = useQuery({
    queryKey: ["product-intelligence-job", resolvedActiveJobId],
    queryFn: () => api.getProductIntelligenceJob(resolvedActiveJobId ?? 0),
    enabled: resolvedActiveJobId !== null,
  });
  const detailHydratedOptions = useMemo(
    () => (detailQuery.data ? detailOptions(detailQuery.data.job.options) : DEFAULT_OPTIONS),
    [detailQuery.data],
  );
  const discovery = discoveryOverride ?? (detailQuery.data ? detailToDiscovery(detailQuery.data) : null);
  const effectiveOptions = optionsEdited || !detailQuery.data ? options : detailHydratedOptions;
  const effectiveAllowedDomainsText = optionsEdited ? allowedDomainsText : detailHydratedOptions.allowed_domains.join("\n");
  const effectiveExcludedDomainsText = optionsEdited ? excludedDomainsText : detailHydratedOptions.excluded_domains.join("\n");
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
  const activeSourceRunId =
    sourceRecords.length
      ? prefill.source_run_id ?? sourceRecords.find((record) => typeof record.run_id === "number")?.run_id ?? null
      : detailQuery.data?.job.source_run_id
      ?? visibleSourceRecords.find((record) => typeof record.run_id === "number")?.run_id
      ?? prefill.source_run_id
      ?? null;
  const uniqueSelectedUrls = useMemo(
    () => Array.from(new Set(selectedUrls)).filter((url) => (discovery?.candidates ?? []).some((candidate) => candidate.url === url)),
    [discovery, selectedUrls],
  );
  const allCandidateUrls = useMemo(
    () => Array.from(new Set((discovery?.candidates ?? []).map((candidate) => candidate.url).filter(Boolean))),
    [discovery],
  );
  const filteredCandidates = useMemo(() => {
    const all = discovery?.candidates ?? [];
    return all.filter((c) => {
      if (searchText) {
        const q = searchText.toLowerCase();
        const matchesSearch =
          (c.source_title ?? "").toLowerCase().includes(q) ||
          (c.source_brand ?? "").toLowerCase().includes(q) ||
          (c.domain ?? "").toLowerCase().includes(q) ||
          (c.url ?? "").toLowerCase().includes(q);
        if (!matchesSearch) return false;
      }
      if (confidenceFilter !== "all") {
        const score = candidateConfidence(c);
        if (confidenceFilter === "high" && score < 0.6) return false;
        if (confidenceFilter === "medium" && (score < 0.4 || score >= 0.6)) return false;
        if (confidenceFilter === "low" && score >= 0.4) return false;
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
      medium: all.filter((c) => { const s = candidateConfidence(c); return s >= 0.4 && s < 0.6; }).length,
      low: all.filter((c) => candidateConfidence(c) < 0.4).length,
    };
  }, [discovery]);
  const selectedDomainSummary = useMemo(() => {
    if (!uniqueSelectedUrls.length) return null;
    const domains = Array.from(new Set(
      (discovery?.candidates ?? []).filter((c) => uniqueSelectedUrls.includes(c.url)).map((c) => c.domain).filter(Boolean)
    ));
    return { count: uniqueSelectedUrls.length, domains };
  }, [discovery, uniqueSelectedUrls]);

  async function discover() {
    if (!visibleSourceRecords.length) {
      return;
    }
    setPending(true);
    setError("");
    setDiscoveryOverride(null);
    setSelectedUrls([]);
    try {
      const sourceRecordIds = visibleSourceRecords
        .map((record) => record.id)
        .filter((value): value is number => typeof value === "number");
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
      const echoedProvider = searchProvider(response.search_provider ?? response.options?.search_provider);
      if (echoedProvider !== submittedOptions.search_provider) {
        setError(`Provider mismatch: submitted ${searchProviderLabel(submittedOptions.search_provider)}, backend used ${searchProviderLabel(echoedProvider)}.`);
      }
      setDiscoveryOverride(response);
      setActiveJobId(response.job_id);
      const nextOptions = detailOptions(response.options);
      setOptions(nextOptions);
      setAllowedDomainsText(nextOptions.allowed_domains.join("\n"));
      setExcludedDomainsText(nextOptions.excluded_domains.join("\n"));
      setOptionsEdited(false);
      await jobsQuery.refetch();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to discover candidates.");
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
        domain: "commerce",
        urls: uniqueSelectedUrls,
      }),
    );
    router.replace("/crawl?module=pdp&mode=batch" as Route);
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
          ].filter(Boolean).join(" · ") || "Discover matching product URLs from source records"
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
              {pending ? "Discovering..." : "Discover URLs"}
            </Button>
            <Button
              type="button"
              variant="accent"
              onClick={sendSelectedToBatchCrawl}
              disabled={!uniqueSelectedUrls.length}
              className="h-[var(--control-height)]"
            >
              <Play className="size-3.5" />
              Batch Crawl {uniqueSelectedUrls.length ? `(${uniqueSelectedUrls.length})` : ""}
            </Button>
          </div>
        }
      />

      {error ? <InlineAlert tone="danger" message={error} /> : null}
      {pending ? (
        <DiscoveryStatus
          provider={effectiveOptions.search_provider}
          sourceCount={visibleSourceRecords.length}
          maxCandidates={effectiveOptions.max_candidates_per_product}
        />
      ) : null}

      {/* ── Main Results ── */}
      <div>
        {/* Left Column: Card Grid */}
        <div className="space-y-4">
            {/* ── Discovery Results ── */}
          <section className="overflow-hidden rounded-[var(--radius-xl)] border border-border bg-panel shadow-card">
            {/* Merged Toolbar */}
            <header className="flex flex-wrap items-center gap-4 border-b border-divider px-4 py-3">
              <div className="flex items-center gap-3 shrink-0">
                {discovery?.candidates.length ? (
                  <input
                    type="checkbox"
                    className="h-3.5 w-3.5 rounded border-divider text-accent focus:ring-accent cursor-pointer"
                    checked={filteredCandidates.length > 0 && filteredCandidates.every((c) => selectedUrls.includes(c.url))}
                    onChange={toggleAllUrls}
                    aria-label="Select all filtered URLs"
                    title="Select all filtered URLs"
                  />
                ) : null}
                <h2 className="type-label font-normal text-[10px] tracking-widest text-muted">DISCOVERED CANDIDATES</h2>
              </div>
              
              {discovery?.candidates.length ? (
                <div className="flex flex-1 items-center gap-2">
                  <div className="relative min-w-[200px] flex-1">
                    <Search className="absolute left-2.5 top-1/2 size-3 -translate-y-1/2 text-muted" />
                    <Input
                      type="text"
                      value={searchText}
                      onChange={(e) => setSearchText(e.target.value)}
                      placeholder="Filter by title, domain, or brand..."
                      className="h-8 pl-8 text-xs border-transparent bg-background-alt focus:bg-background focus:border-accent/20"
                    />
                  </div>
                  <Dropdown
                    value={confidenceFilter}
                    onChange={(v) => setConfidenceFilter(v as "all" | "high" | "medium" | "low")}
                    options={[
                      { value: "all", label: "All Confidence" },
                      { value: "high", label: `High (${confidenceDistribution.high})` },
                      { value: "medium", label: `Med (${confidenceDistribution.medium})` },
                      { value: "low", label: `Low (${confidenceDistribution.low})` },
                    ]}
                    ariaLabel="Filter by confidence"
                    className="w-[160px] h-8 text-xs"
                  />
                </div>
              ) : null}
              
              <div className="flex items-center gap-2">
                {selectedDomainSummary ? (
                  <>
                    <div className="flex items-center gap-2 px-2 py-1 rounded bg-accent border border-accent">
                      <span className="text-[10px] font-bold text-white uppercase tracking-tight">{selectedDomainSummary.count} selected</span>
                    </div>
                    <div className="h-4 w-px bg-divider mx-1" />
                  </>
                ) : null}
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  onClick={() => setConfigOpen(true)}
                  aria-label="Settings"
                  className="h-8 w-8 text-muted hover:text-foreground"
                >
                  <Settings className="size-4" />
                </Button>
                <div className="flex items-center gap-1">
                  <Button
                    type="button"
                    variant="secondary"
                    size="icon"
                    onClick={() => downloadRows("urls", "csv", discovery)}
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
                    onClick={() => downloadRows("urls", "json", discovery)}
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
              <DiscoveryTableLoading provider={options.search_provider} />
            ) : groupedCandidates.length ? (
              <div className="divide-y divide-[var(--divider)]">
                {groupedCandidates.map((group, groupIndex) => (
                  <details key={group.sourceIndex} className="group" open={groupIndex === 0}>
                    <summary className="flex cursor-pointer list-none items-center gap-4 px-4 py-3 hover:bg-background-alt/50 select-none transition-colors">
                      <div className="flex size-6 shrink-0 items-center justify-center rounded-full border border-divider bg-background text-[10px] font-bold text-muted group-open:bg-accent group-open:text-white group-open:border-accent">
                        {group.candidates.length}
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="truncate text-sm font-normal font-sans text-foreground" title={group.sourceTitle}>
                            {group.sourceTitle}
                          </span>
                          <Badge tone="neutral" className="h-4 px-1.5 text-[9px] uppercase tracking-wider opacity-60">Source</Badge>
                        </div>
                        <div className="flex items-center gap-3 mt-0.5">
                          {group.sourceBrand && group.sourceBrand !== "--" && (
                            <span className="text-xs text-muted flex items-center gap-1.5">
                              <Layers className="size-3 opacity-50" />
                              {group.sourceBrand}
                            </span>
                          )}
                          {group.sourceBrand && group.sourceBrand !== "--" && group.sourcePrice && (
                            <span className="h-1 w-1 rounded-full bg-divider" />
                          )}
                          {group.sourcePrice && (
                            <span className="font-mono text-xs text-foreground font-medium">
                              {formatPrice(group.sourcePrice, group.sourceCurrency)}
                            </span>
                          )}
                        </div>
                      </div>
                      <ChevronDown className="size-4 text-muted transition-transform group-open:rotate-180 shrink-0" />
                    </summary>

                    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3 p-4 bg-background-alt/30 border-t border-divider">
                      {group.candidates.map((candidate) => {
                        const selected = uniqueSelectedUrls.includes(candidate.url);
                        const score = candidateConfidence(candidate);
                        const intelligence = isRecord(candidate.intelligence) ? candidate.intelligence : {};
                        const record = isRecord(intelligence.canonical_record) ? intelligence.canonical_record : {};
                        const imageUrl = stringField(record.image_url);
                        const recordPrice = stringField(record.price);
                        const recordCurrency = stringField(record.currency);
                        
                        return (
                          <div
                            key={candidate.url}
                            className={cn(
                              "group/card relative flex flex-col rounded-[var(--radius-lg)] border border-border bg-panel p-3 transition-all hover:border-accent/40 hover:shadow-md",
                              selected && "border-accent/60 bg-accent-subtle/20 shadow-sm"
                            )}
                          >
                            <div className="flex gap-4">
                              {/* Thumbnail with Overlay Badge */}
                              <div className="relative aspect-square w-[100px] shrink-0 overflow-hidden rounded-[var(--radius-md)] border border-divider bg-white p-1.5 shadow-sm">
                                {Boolean(imageUrl) ? (
                                  <ExternalCandidateImage
                                    src={imageUrl}
                                    alt={stringField(record.title)}
                                    className="size-full object-contain mix-blend-multiply"
                                  />
                                ) : (
                                  <div className="flex size-full items-center justify-center text-muted/30">
                                    <ImageOff className="size-8" />
                                  </div>
                                )}
                                <div className={cn(
                                  "absolute bottom-1.5 right-1.5 rounded-md px-1.5 py-0.5 text-[10px] font-bold border shadow-sm",
                                  score >= 0.6 ? "bg-success text-white border-success" : 
                                  score >= 0.4 ? "bg-warning text-white border-warning" : 
                                  "bg-background-elevated text-muted border-divider"
                                )}>
                                  {Math.round(score * 100)}%
                                </div>
                              </div>

                              <div className="min-w-0 flex-1 flex flex-col justify-between py-0.5">
                                <div className="space-y-1.5">
                                  <div className="flex items-start justify-between gap-3">
                                    <a
                                      href={candidate.url}
                                      target="_blank"
                                      rel="noopener noreferrer"
                                      className="group/link text-xs font-normal font-sans tracking-tight text-foreground leading-snug line-clamp-2 hover:text-accent transition-colors"
                                    >
                                      {stringField(record.title) || candidate.url}
                                    </a>
                                    <input
                                      type="checkbox"
                                      checked={selected}
                                      onChange={(e) => { e.stopPropagation(); if (candidate.url) toggleUrl(candidate.url); }}
                                      className="mt-0.5 h-4 w-4 rounded border-divider text-accent focus:ring-accent cursor-pointer shrink-0"
                                    />
                                  </div>
                                  
                                  <div className="flex flex-col gap-1">
                                    {recordPrice && recordPrice !== "--" && (
                                      <div className="text-sm font-bold text-foreground">
                                        {formatExtractedPrice(recordPrice, recordCurrency)}
                                      </div>
                                    )}
                                    {(stringField(record.brand) || candidate.source_brand) && (
                                      <div className="text-[10px] uppercase tracking-wider text-muted font-medium">
                                        {stringField(record.brand) || candidate.source_brand}
                                      </div>
                                    )}
                                  </div>
                                </div>

                                <div className="text-[10px] text-muted/80 font-mono truncate mt-2" title={candidate.domain}>
                                  {candidate.domain}
                                </div>
                              </div>
                            </div>

                            <div className="mt-3 flex items-center justify-between border-t border-divider pt-2.5">
                              <Button
                                type="button"
                                variant="ghost"
                                size="sm"
                                className="h-6 px-2 text-[10px] font-bold uppercase tracking-tight text-muted hover:text-accent"
                                onClick={() => setJsonModalCandidate(candidate)}
                              >
                                <Code2 className="mr-1.5 size-3" /> Raw JSON
                              </Button>
                              <a
                                href={candidate.url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="flex items-center gap-1 text-[10px] font-bold uppercase tracking-tight text-accent hover:underline"
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
                  const price = formatPrice(data.price, typeof data.currency === "string" ? data.currency : "");
                  const url = (typeof data.url === "string" && data.url) || record.source_url || "";
                  return (
                    <div
                      key={`${record.id ?? "src"}-${index}`}
                      className="flex items-center gap-3 px-3 py-2.5 hover:bg-background-alt"
                    >
                      <span className="font-mono text-xs text-muted w-6 shrink-0">{index + 1}</span>
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-xs font-medium text-foreground" title={title}>
                          {title}
                        </div>
                        <div className="flex items-center gap-2 text-xs text-muted">
                          <span>{brand}</span>
                          <span className="font-mono">{price}</span>
                          {url ? (
                            <a
                              href={url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="truncate text-accent hover:underline"
                              title={url}
                            >
                              {url}
                            </a>
                          ) : null}
                        </div>
                      </div>
                      <Badge tone="neutral" className="h-5 px-1.5 text-xs shrink-0">Pending</Badge>
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
            <div className="sticky bottom-4 z-20 animate-fade-in">
              <div className="flex items-center gap-3 rounded-[var(--radius-xl)] border border-border bg-panel px-4 py-2.5 shadow-lg">
                <Layers className="size-4 shrink-0 text-accent" />
                <span className="text-xs font-medium text-foreground">{uniqueSelectedUrls.length} URLs selected</span>
                <span className="text-xs text-muted">from {selectedDomainSummary?.domains.length ?? 0} domain{(selectedDomainSummary?.domains.length ?? 0) !== 1 ? "s" : ""}</span>
                <div className="ml-auto flex items-center gap-2">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => setSelectedUrls([])}
                    className="h-7 px-2 text-muted"
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

      {/* ── Session History (collapsible) ── */}
      <section className="overflow-hidden rounded-[var(--radius-xl)] border border-border bg-panel shadow-card">
        <details className="group" open>
          <summary className="flex cursor-pointer items-center justify-between px-4 py-2.5 text-xs font-medium text-foreground hover:bg-background-alt select-none">
            <span>Session History</span>
            <ChevronDown className="size-3.5 text-muted transition-transform group-open:rotate-180" />
          </summary>
          <div className="max-h-[240px] overflow-auto border-t border-divider">
            {(() => {
              if (jobsQuery.isError) return <div className="p-4 text-center text-xs text-danger">Error loading history</div>;
              if (jobsQuery.isLoading) return <div className="p-4 text-center text-xs text-muted">Loading history...</div>;
              if (!jobsQuery.data?.length) return <div className="p-4 text-center text-xs text-muted">No sessions.</div>;
              return (
                <table className="compact-data-table">
                  <TableBody>
                    {jobsQuery.data.map((job) => (
                      <ProductIntelligenceJobRow
                        key={job.id}
                        job={job}
                        active={resolvedActiveJobId === job.id}
                        onOpen={() => openJob(job.id)}
                      />
                    ))}
                  </TableBody>
                </table>
              );
            })()}
          </div>
        </details>
      </section>

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
    </div>
  );
}

function detailToDiscovery(detail: ProductIntelligenceJobDetail): ProductIntelligenceDiscoveryResponse {
  const sourcesById = new Map<number, { source: ProductIntelligenceJobDetail["source_products"][number]; index: number }>();
  detail.source_products.forEach((source, index) => {
    if (sourcesById.has(source.id)) {
      console.warn("Duplicate Product Intelligence source id; keeping first.", {
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
      source_url: source?.source_url ?? "",
      source_title: source?.title ?? "",
      source_brand: source?.brand ?? "",
      source_price: source?.price ?? null,
      source_currency: source?.currency ?? "",
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

function detailOptions(value: Record<string, unknown> | null | undefined): ProductIntelligenceOptions {
  const raw = isRecord(value) ? value : {};
  return {
    ...DEFAULT_OPTIONS,
    max_source_products: clampInt(raw.max_source_products, 1, MAX_SOURCE_PRODUCTS_LIMIT, DEFAULT_OPTIONS.max_source_products),
    max_candidates_per_product: clampInt(raw.max_candidates_per_product, 1, MAX_CANDIDATES_PER_PRODUCT_LIMIT, DEFAULT_OPTIONS.max_candidates_per_product),
    search_provider: searchProvider(raw.search_provider),
    private_label_mode: privateLabelMode(raw.private_label_mode),
    confidence_threshold: clampFloat(raw.confidence_threshold, 0, 1, DEFAULT_OPTIONS.confidence_threshold),
    allowed_domains: stringArray(raw.allowed_domains),
    excluded_domains: stringArray(raw.excluded_domains),
    llm_enrichment_enabled: Boolean(raw.llm_enrichment_enabled),
  };
}

function privateLabelMode(value: unknown): ProductIntelligenceOptions["private_label_mode"] {
  return value === "include" || value === "exclude" || value === "flag" ? value : DEFAULT_OPTIONS.private_label_mode;
}

function searchProvider(value: unknown): ProductIntelligenceOptions["search_provider"] {
  return value === "google_native" || value === "serpapi" ? value : DEFAULT_OPTIONS.search_provider;
}

function parseDomainLines(value: string) {
  return value
    .split(/[\n,]+/)
    .map((line) => line.trim().toLowerCase())
    .filter(Boolean);
}

function stringArray(value: unknown) {
  return Array.isArray(value)
    ? value.map((item) => String(item || "").trim().toLowerCase()).filter(Boolean)
    : [];
}

function candidateConfidence(candidate: ProductIntelligenceDiscoveryResponse["candidates"][number]) {
  const intelligence = isRecord(candidate.intelligence) ? candidate.intelligence : {};
  const parsed = Number(intelligence.confidence_score ?? 0);
  return Number.isFinite(parsed) ? Math.min(Math.max(parsed, 0), 1) : 0;
}

function toIntelligenceRow(candidate: ProductIntelligenceDiscoveryResponse["candidates"][number]) {
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
    confidence_label: String(intelligence.confidence_label ?? ""),
    cleanup_source: String(intelligence.cleanup_source ?? ""),
    score_reasons: isRecord(intelligence.score_reasons) ? intelligence.score_reasons : {},
  };
}

const PREFERRED_INTELLIGENCE_COLUMNS = [
  "title",
  "description",
  "brand",
  "price",
  "currency",
  "availability",
  "sku",
  "mpn",
  "gtin",
  "image_url",
  "url",
];

function intelligenceColumnNames(rows: Array<ReturnType<typeof toIntelligenceRow>>) {
  const columns = new Set<string>();
  for (const row of rows) {
    for (const key of Object.keys(row.record)) {
      if (!key.startsWith("_") && !isEmptyValue(row.record[key])) {
        columns.add(key);
      }
    }
    columns.add("url");
  }
  return [
    ...PREFERRED_INTELLIGENCE_COLUMNS.filter((column) => columns.has(column)),
    ...Array.from(columns)
      .filter((column) => !PREFERRED_INTELLIGENCE_COLUMNS.includes(column))
      .sort((left, right) => left.localeCompare(right)),
  ];
}

function intelligenceCellValue(row: ReturnType<typeof toIntelligenceRow>, column: string) {
  if (column === "price") {
    return formatExtractedPrice(row.record.price, row.record.currency);
  }
  if (column === "currency") {
    return stringField(row.record.currency);
  }
  if (column === "url") {
    return stringField(row.record.url || row.url);
  }
  return formatIntelligenceValue(row.record[column]);
}

function formatExtractedPrice(price: unknown, currency: unknown) {
  if (isEmptyValue(price)) {
    return "--";
  }
  const currencyText = String(currency ?? "").trim();
  if (typeof price === "number" && currencyText) {
    return formatPrice(price, currencyText);
  }
  return String(price);
}

function formatIntelligenceValue(value: unknown) {
  if (isEmptyValue(value)) {
    return "--";
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

function isEmptyValue(value: unknown) {
  return value === undefined || value === null || String(value).trim() === "";
}

function longIntelligenceColumn(column: string) {
  return column === "description" || column === "snippet" || column === "image_url" || column === "url";
}

function stringField(value: unknown) {
  const text = String(value ?? "").trim();
  return text === "--" || text === "null" || text === "undefined" ? "" : text;
}

function downloadRows(tab: "urls" | "intelligence", kind: "csv" | "json", discovery: ProductIntelligenceDiscoveryResponse | null) {
  const rows: Array<Record<string, unknown>> = tab === "urls"
    ? (discovery?.candidates ?? []).map((candidate) => ({ ...candidate }))
    : (discovery?.candidates ?? []).map(toIntelligenceExportRow);
  const body = kind === "csv" ? toCsv(rows) : JSON.stringify(rows, null, 2);
  const type = kind === "csv" ? "text/csv;charset=utf-8" : "application/json;charset=utf-8";
  const url = URL.createObjectURL(new Blob([body], { type }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `product-intelligence-${tab}.${kind}`;
  anchor.click();
  URL.revokeObjectURL(url);
}

function toIntelligenceExportRow(candidate: ProductIntelligenceDiscoveryResponse["candidates"][number]) {
  const row = toIntelligenceRow(candidate);
  return {
    source_title: row.source_title,
    source_brand: row.source_brand,
    result_url: row.url,
    result_domain: row.domain,
    title: row.record.title ?? "",
    brand: row.record.brand ?? "",
    price: row.record.price ?? "",
    currency: row.record.currency ?? "",
    confidence_score: row.confidence_score,
    confidence_label: row.confidence_label,
    cleanup_source: row.cleanup_source,
    score_reasons: row.score_reasons,
  };
}

function toCsv(rows: Array<Record<string, unknown>>) {
  const headers = Array.from(new Set(rows.flatMap((row) => Object.keys(row))));
  const lines = [headers.join(",")];
  for (const row of rows) {
    lines.push(headers.map((header) => csvCell(row[header])).join(","));
  }
  return lines.join("\n");
}

function csvCell(value: unknown) {
  const text = typeof value === "object" && value !== null ? JSON.stringify(value) : String(value ?? "");
  return `"${text.replace(/"/g, '""')}"`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function displayValue(data: Record<string, unknown>, fields: string[]) {
  for (const field of fields) {
    const value = data[field];
    if (value !== undefined && value !== null && value !== "") {
      return String(value);
    }
  }
  return "";
}

function formatPrice(value: unknown, currency = "") {
  const numeric = typeof value === "number" ? value : Number(String(value ?? "").replace(/[^0-9.]+/g, ""));
  if (!Number.isFinite(numeric) || numeric <= 0) {
    return null;
  }
  const prefix = currency || "$";
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
