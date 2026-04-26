"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronDown, Code2, Copy, Download, ExternalLink, ImageOff, Info, Layers, Loader2, Play, Search, Settings, X } from "lucide-react";
import type { Route } from "next";
import { useRouter } from "next/navigation";
import React, { useEffect, useMemo, useState } from "react";

import { DataRegionEmpty, InlineAlert, PageHeader } from "../../components/ui/patterns";
import {
 Badge,
 Button,
 Dropdown,
 Field,
 Input,
 TableBody,
 Textarea,
 Tooltip,
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

type PrefillPayload = {
  source_run_id?: number | null;
  source_domain?: string;
  records?: ProductIntelligenceSourceRecordInput[];
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
const SEARCH_PROVIDER_OPTIONS: Array<{ value: ProductIntelligenceOptions["search_provider"]; label: string }> = [
  { value: "serpapi", label: "SerpAPI" },
  { value: "google_native", label: "Google Native" },
];

const MATCH_SCORE_TOOLTIP =
  "Match score = title similarity x 0.34 + brand match x 0.24 + identifier match x 0.25 + price band x 0.05 + source authority up to 0.12. Title similarity is token overlap/sequence match. Brand, identifier, and price add only when they match. Brand DTC, retailer, and marketplace domains add authority. High is 60%+, medium is 40-59%, low is below 40%.";

function hideBrokenImage(event: React.SyntheticEvent<HTMLImageElement>): void {
  event.currentTarget.style.display = "none";
}

function ExternalCandidateImage({
  src,
  alt,
  className,
}: Readonly<{
  src: string;
  alt: string;
  className: string;
}>) {
  return (
    <>
      {/* eslint-disable-next-line @next/next/no-img-element -- external candidate URLs are not known at build time */}
      <img
        src={src}
        alt={alt}
        className={className}
        onError={hideBrokenImage}
      />
    </>
  );
}

export default function ProductIntelligencePage() {
  const router = useRouter();
  const [prefill, setPrefill] = useState<PrefillPayload>({});
  const [options, setOptions] = useState<ProductIntelligenceOptions>(DEFAULT_OPTIONS);
  const [allowedDomainsText, setAllowedDomainsText] = useState("");
  const [excludedDomainsText, setExcludedDomainsText] = useState("");
  const [discovery, setDiscovery] = useState<ProductIntelligenceDiscoveryResponse | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [selectedUrls, setSelectedUrls] = useState<string[]>([]);
  const [jsonModalCandidate, setJsonModalCandidate] = useState<ProductIntelligenceDiscoveryResponse["candidates"][number] | null>(null);
  const [activeJobId, setActiveJobId] = useState<number | null>(null);
  const [configOpen, setConfigOpen] = useState(false);
  const [optionsEdited, setOptionsEdited] = useState(false);
  const [prefillChecked, setPrefillChecked] = useState(false);
  const [searchText, setSearchText] = useState("");
  const [confidenceFilter, setConfidenceFilter] = useState<"all" | "high" | "medium" | "low">("all");

  const jobsQuery = useQuery({
    queryKey: ["product-intelligence-jobs"],
    queryFn: () => api.listProductIntelligenceJobs({ limit: 20 }),
  });
  const detailQuery = useQuery({
    queryKey: ["product-intelligence-job", activeJobId],
    queryFn: () => api.getProductIntelligenceJob(activeJobId ?? 0),
    enabled: activeJobId !== null,
  });

  useEffect(() => {
    const stored = window.sessionStorage.getItem(STORAGE_KEYS.PRODUCT_INTELLIGENCE_PREFILL);
    if (!stored) {
      setPrefillChecked(true);
      return;
    }
    try {
      const parsed = JSON.parse(stored) as PrefillPayload;
      setPrefill({
        source_run_id: typeof parsed.source_run_id === "number" ? parsed.source_run_id : null,
        source_domain: parsed.source_domain ?? "",
        records: Array.isArray(parsed.records) ? parsed.records : [],
      });
      if (Array.isArray(parsed.records) && parsed.records.length > 0) {
        setActiveJobId(null);
        setDiscovery(null);
      }
    } catch {
      setError("Unable to read Product Intelligence prefill.");
    } finally {
      window.sessionStorage.removeItem(STORAGE_KEYS.PRODUCT_INTELLIGENCE_PREFILL);
      setPrefillChecked(true);
    }
  }, []);

  useEffect(() => {
    if (!detailQuery.data) {
      return;
    }
    const hydrated = detailToDiscovery(detailQuery.data);
    setDiscovery(hydrated);
    if (optionsEdited) {
      return;
    }
    const hydratedOptions = detailOptions(detailQuery.data.job.options);
    setOptions((current) => ({ ...hydratedOptions, search_provider: current.search_provider }));
    setAllowedDomainsText(hydratedOptions.allowed_domains.join("\n"));
    setExcludedDomainsText(hydratedOptions.excluded_domains.join("\n"));
    setSelectedUrls([]);
  }, [detailQuery.data, optionsEdited]);

  // Auto-select most recent job on initial load
  useEffect(() => {
    if (!prefillChecked) return;
    if ((prefill.records ?? []).length > 0) return;
    if (activeJobId !== null || discovery !== null) return;
    if (!jobsQuery.data?.length) return;
    setActiveJobId(jobsQuery.data[0].id);
  }, [jobsQuery.data, activeJobId, discovery, prefill.records, prefillChecked]);

  const sourceRecords = prefill.records ?? [];
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
  const uniqueSelectedUrls = useMemo(() => Array.from(new Set(selectedUrls)), [selectedUrls]);
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
    setDiscovery(null);
    setSelectedUrls([]);
    try {
      const sourceRecordIds = visibleSourceRecords
        .map((record) => record.id)
        .filter((value): value is number => typeof value === "number");
      const canUseRecordIds = sourceRecordIds.length === visibleSourceRecords.length;
      const submittedOptions = {
        ...options,
        search_provider: searchProvider(options.search_provider),
        allowed_domains: parseDomainLines(allowedDomainsText),
        excluded_domains: parseDomainLines(excludedDomainsText),
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
      setDiscovery(response);
      setActiveJobId(response.job_id);
      setOptions(detailOptions(response.options));
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
              variant="secondary"
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
        provider={options.search_provider}
        sourceCount={visibleSourceRecords.length}
        maxCandidates={options.max_candidates_per_product}
       />
      ) : null}

      {/* ── Main Results ── */}
      <div>
   {/* Left Column: Card Grid */}
   <div className="space-y-4">
    {/* ── Discovery Results ── */}
    <section className="panel panel-raised overflow-hidden">
     {/* Merged Toolbar */}
     <header className="flex flex-wrap items-center gap-2 border-b border-[var(--divider)] px-3 py-2">
      {discovery?.candidates.length ? (
       <input
        type="checkbox"
        className="h-3.5 w-3.5 rounded border-[var(--divider)] text-accent focus:ring-accent cursor-pointer"
        checked={filteredCandidates.length > 0 && filteredCandidates.every((c) => selectedUrls.includes(c.url))}
        onChange={toggleAllUrls}
        aria-label="Select all filtered URLs"
        title="Select all filtered URLs"
       />
      ) : null}
      <h2 className="text-xs font-bold tracking-wider text-foreground/70 shrink-0">Discovered URLs</h2>
      {discovery?.candidates.length ? (
       <>
        <div className="relative min-w-[140px] flex-1">
         <Input
          type="text"
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
          placeholder="Search..."
          className="h-7 text-xs"
         />
        </div>
        <Dropdown
         value={confidenceFilter}
         onChange={(v) => setConfidenceFilter(v as "all" | "high" | "medium" | "low")}
         options={[
          { value: "all", label: "All" },
          { value: "high", label: `High — ${confidenceDistribution.high}` },
          { value: "medium", label: `Med — ${confidenceDistribution.medium}` },
          { value: "low", label: `Low — ${confidenceDistribution.low}` },
         ]}
         ariaLabel="Filter by confidence"
         className="w-[140px]"
        />
       </>
      ) : null}
      <div className="ml-auto flex items-center gap-1.5">
       {selectedDomainSummary ? (
        <Badge tone="accent" className="h-5 px-1.5 text-xs">{selectedDomainSummary.count} selected</Badge>
       ) : null}
       <Button
        type="button"
        variant="ghost"
        size="icon"
        onClick={() => setConfigOpen(true)}
        aria-label="Settings"
        className="h-7 w-7"
       >
        <Settings className="size-3.5" />
       </Button>
       <Button
        type="button"
        variant="secondary"
        size="icon"
        onClick={() => downloadRows("urls", "csv", discovery)}
        disabled={!discovery?.candidates.length}
        className="h-7 w-7"
        aria-label="Download CSV"
       >
        <Download className="size-3" />
       </Button>
       <Button
        type="button"
        variant="secondary"
        size="icon"
        onClick={() => downloadRows("urls", "json", discovery)}
        disabled={!discovery?.candidates.length}
        className="h-7 w-7"
        aria-label="Download JSON"
       >
        <Code2 className="size-3" />
       </Button>
      </div>
     </header>

     {/* ── Grouped Results ── */}
     {pending ? (
       <DiscoveryTableLoading provider={options.search_provider} />
      ) : groupedCandidates.length ? (
       <div className="divide-y divide-[var(--divider)]">
        {groupedCandidates.map((group, groupIndex) => (
         <details key={group.sourceIndex} className="group" open={groupIndex === 0}>
          <summary className="flex cursor-pointer list-none items-center gap-3 px-3 py-2.5 hover:bg-[var(--bg-alt)] select-none">
           <div className="min-w-0 flex-1">
            <div className="truncate text-xs font-semibold text-foreground" title={group.sourceTitle}>
             {group.sourceTitle}
            </div>
            <div className="flex items-center gap-2 text-xs text-muted">
             <span>{group.sourceBrand || "—"}</span>
             <span className="font-mono">{formatPrice(group.sourcePrice, group.sourceCurrency)}</span>
            </div>
           </div>
           <Badge tone="neutral" className="h-5 px-1.5 text-xs shrink-0">{group.candidates.length} found</Badge>
           <ChevronDown className="size-3.5 text-muted transition-transform group-open:rotate-180 shrink-0" />
          </summary>

          <div className="flex gap-2.5 overflow-x-auto px-3 py-2.5 bg-[var(--bg-alt)]/50">
           {group.candidates.map((candidate) => {
            const selected = uniqueSelectedUrls.includes(candidate.url);
            const score = candidateConfidence(candidate);
            const intelligence = isRecord(candidate.intelligence) ? candidate.intelligence : {};
            const record = isRecord(intelligence.canonical_record) ? intelligence.canonical_record : {};
            const imageUrl = stringField(record.image_url);
            const hasImage = imageUrl !== "--";
            return (
             <div
              key={candidate.url}
              className="flex w-[280px] shrink-0 flex-col gap-2 rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-surface)] p-2.5 transition-shadow"
             >
              {/* Horizontal row: image left, text right */}
              <div className="flex gap-2.5">
               {/* Thumbnail */}
               <div className="aspect-square w-[70px] shrink-0 overflow-hidden rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-alt)]">
                {hasImage ? (
                 <ExternalCandidateImage
                  src={imageUrl}
                  alt={stringField(record.title)}
                  className="size-full object-contain"
                 />
                ) : (
                 <div className="flex size-full items-center justify-center text-muted">
                  <ImageOff className="size-4" />
                 </div>
                )}
               </div>

               {/* Title / description / price / domain */}
               <div className="min-w-0 flex-1 flex flex-col justify-center">
                {candidate.url ? (
                 <a
                  href={candidate.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  title={candidate.url}
                  className="group/link inline-flex max-w-full items-center gap-1 truncate text-sm font-medium text-foreground hover:text-accent hover:underline"
                 >
                  <span className="truncate">{stringField(record.title) || candidate.url}</span>
                  <ExternalLink className="size-3 shrink-0 opacity-50 group-hover/link:opacity-100" aria-hidden="true" />
                 </a>
                ) : (
                 <div className="truncate text-sm font-medium text-foreground" title={stringField(record.title)}>
                  {stringField(record.title) || "—"}
                 </div>
                )}
                <div className="mt-0.5 line-clamp-2 text-xs leading-tight text-muted" title={stringField(record.description)}>
                 {stringField(record.description) || "—"}
                </div>
                <div className="mt-1 text-xs font-mono text-foreground">
                 {formatExtractedPrice(record.price, record.currency)}
                </div>
                <div className="mt-0.5 truncate text-xs text-muted">
                 {candidate.url ? (
                  <a
                   href={candidate.url}
                   target="_blank"
                   rel="noopener noreferrer"
                   className="hover:text-accent hover:underline"
                   title={candidate.url}
                  >
                   {candidate.domain}
                  </a>
                 ) : (
                  candidate.domain
                 )}
                </div>
               </div>
              </div>

              {/* Score + actions */}
              <div className="mt-auto flex items-center justify-between gap-1">
               <Badge tone={score >= 0.6 ? "success" : score >= 0.4 ? "warning" : "neutral"} className="h-5 px-1.5 text-xs">
                {Math.round(score * 100)}%
               </Badge>
               <div className="flex items-center gap-1">
                <input
                 type="checkbox"
                 checked={selected}
                 onChange={(e) => { e.stopPropagation(); if (candidate.url) toggleUrl(candidate.url); }}
                 onClick={(e) => e.stopPropagation()}
                 className="h-3.5 w-3.5 rounded border-[var(--divider)] text-accent focus:ring-accent cursor-pointer"
                 title="Select for batch crawl"
                 aria-label="Select for batch crawl"
                />
                <Button
                 type="button"
                 variant="ghost"
                 size="sm"
                 className="h-5 px-1.5 text-xs"
                 onClick={(e) => { e.stopPropagation(); setJsonModalCandidate(candidate); }}
                >
                 <Code2 className="mr-1 size-3" /> JSON
                </Button>
               </div>
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
           className="flex items-center gap-3 px-3 py-2.5 hover:bg-[var(--bg-alt)]"
          >
           <span className="font-mono text-xs text-muted w-6 shrink-0">{index + 1}</span>
           <div className="min-w-0 flex-1">
            <div className="truncate text-xs font-semibold text-foreground" title={title}>
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
      <div className="panel panel-raised flex items-center gap-3 px-4 py-2.5 shadow-[var(--shadow-lg)]">
       <Layers className="size-4 shrink-0 text-accent" />
       <span className="text-xs font-semibold text-foreground">{uniqueSelectedUrls.length} URLs selected</span>
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
    <section className="panel panel-raised overflow-hidden">
     <details className="group" open>
      <summary className="flex cursor-pointer items-center justify-between px-4 py-2.5 text-xs font-semibold text-foreground hover:bg-[var(--bg-alt)] select-none">
       <span>Session History</span>
       <ChevronDown className="size-3.5 text-muted transition-transform group-open:rotate-180" />
      </summary>
      <div className="max-h-[240px] overflow-auto border-t border-[var(--divider)]">
       {(() => {
        if (jobsQuery.isError) return <div className="p-4 text-center text-xs text-danger">Error loading history</div>;
        if (jobsQuery.isLoading) return <div className="p-4 text-center text-xs text-muted">Loading history...</div>;
        if (!jobsQuery.data?.length) return <div className="p-4 text-center text-xs text-muted">No sessions.</div>;
        return (
         <table className="min-w-full">
          <TableBody>
           {jobsQuery.data.map((job) => (
            <ProductIntelligenceJobRow
             key={job.id}
             job={job}
             active={activeJobId === job.id}
             onOpen={() => setActiveJobId(job.id)}
            />
           ))}
          </TableBody>
         </table>
        );
       })()}
      </div>
     </details>
    </section>

      {/* Settings Drawer */}
      {configOpen && (
       <>
        <div
         className="fixed inset-0 z-40 bg-black/20"
         onClick={() => setConfigOpen(false)}
         aria-hidden="true"
        />
        <div className="fixed right-0 top-0 z-50 h-full w-[380px] max-w-full overflow-y-auto border-l border-[var(--divider)] bg-[var(--bg-elevated)] p-5 shadow-[var(--shadow-xl)] animate-in slide-in-from-right-4 duration-200">
         <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-foreground">Configuration</h2>
          <Button type="button" variant="ghost" size="icon" className="h-7 w-7" onClick={() => setConfigOpen(false)} aria-label="Close settings">
           <X className="size-3.5" />
          </Button>
         </div>
         <div className="mt-4 space-y-4">
          <Field label="Provider">
           <Dropdown
            value={options.search_provider}
            onChange={(value) => {
             setOptionsEdited(true);
             setOptions((current) => ({ ...current, search_provider: searchProvider(value) }));
            }}
            options={SEARCH_PROVIDER_OPTIONS}
           />
          </Field>
          <Field label="Max Sources">
           <Input
            type="number"
            min={1}
            max={MAX_SOURCE_PRODUCTS_LIMIT}
            value={options.max_source_products}
            onChange={(event) => {
             setOptionsEdited(true);
             setOptions((current) => ({ ...current, max_source_products: clampInt(event.target.value, 1, MAX_SOURCE_PRODUCTS_LIMIT, DEFAULT_OPTIONS.max_source_products) }));
            }}
           />
          </Field>
          <Field label="Max URLs">
           <Input
            type="number"
            min={1}
            max={MAX_CANDIDATES_PER_PRODUCT_LIMIT}
            value={options.max_candidates_per_product}
            onChange={(event) => {
             setOptionsEdited(true);
             setOptions((current) => ({ ...current, max_candidates_per_product: clampInt(event.target.value, 1, MAX_CANDIDATES_PER_PRODUCT_LIMIT, DEFAULT_OPTIONS.max_candidates_per_product) }));
            }}
           />
          </Field>
          <Field label="Private Label">
           <Dropdown
            value={options.private_label_mode}
            onChange={(value) => {
             setOptionsEdited(true);
             setOptions((current) => ({ ...current, private_label_mode: value as ProductIntelligenceOptions["private_label_mode"] }));
            }}
            options={[
             { value: "flag", label: "Flag" },
             { value: "exclude", label: "Exclude" },
             { value: "include", label: "Include" },
            ]}
           />
          </Field>
          <Field label="LLM Cleanup">
           <div className="surface-muted flex h-[var(--control-height)] items-center justify-between rounded-[var(--radius-md)] px-3 shadow-sm">
            <span className="text-xs font-medium text-muted">Enable Enrichment</span>
            <input
             type="checkbox"
             checked={options.llm_enrichment_enabled}
             onChange={(event) => {
              setOptionsEdited(true);
              setOptions((current) => ({ ...current, llm_enrichment_enabled: event.target.checked }));
             }}
             className="h-3.5 w-3.5 rounded border-[var(--divider)] text-accent focus:ring-accent"
            />
           </div>
          </Field>
          <Field label="Allowed Domains">
           <Textarea
            value={allowedDomainsText}
            onChange={(event) => {
             setOptionsEdited(true);
             setAllowedDomainsText(event.target.value);
            }}
            className="min-h-[76px] text-xs"
            placeholder="ralphlauren.com"
           />
          </Field>
          <Field label="Excluded Domains">
           <Textarea
            value={excludedDomainsText}
            onChange={(event) => {
             setOptionsEdited(true);
             setExcludedDomainsText(event.target.value);
            }}
            className="min-h-[76px] text-xs"
            placeholder="amazon.com"
           />
          </Field>
         </div>
        </div>
       </>
      )}

      {/* JSON Modal */}
      {jsonModalCandidate && (
       <JsonModal candidate={jsonModalCandidate} onClose={() => setJsonModalCandidate(null)} />
      )}
      </div>
  );
}

function JsonModal({
 candidate,
 onClose,
}: Readonly<{
 candidate: ProductIntelligenceDiscoveryResponse["candidates"][number];
 onClose: () => void;
}>) {
 const intelligence = isRecord(candidate.intelligence) ? candidate.intelligence : {};
 const hasIntelligence = Object.keys(intelligence).length > 0;
 const text = JSON.stringify(hasIntelligence ? intelligence : (candidate.payload ?? {}), null, 2);

 return (
  <>
   <div className="fixed inset-0 z-50 bg-black/40" onClick={onClose} aria-hidden="true" />
   <div className="fixed left-1/2 top-1/2 z-50 flex max-h-[80vh] w-[640px] max-w-[90vw] -translate-x-1/2 -translate-y-1/2 flex-col rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-elevated)] shadow-[var(--shadow-xl)]">
    <div className="flex items-center justify-between border-b border-[var(--divider)] px-4 py-3">
     <h3 className="text-sm font-semibold text-foreground">Raw JSON</h3>
     <Button type="button" variant="ghost" size="icon" className="h-7 w-7" onClick={onClose} aria-label="Close">
      <X className="size-3.5" />
     </Button>
    </div>
    <div className="flex-1 overflow-auto p-4">
     <pre className="crawl-terminal crawl-terminal-json text-xs leading-relaxed">{text}</pre>
    </div>
    <div className="flex items-center justify-end gap-2 border-t border-[var(--divider)] px-4 py-3">
     <Button type="button" variant="ghost" size="sm" className="h-7 text-xs" onClick={() => void navigator.clipboard.writeText(text)}>
      <Copy className="mr-1 size-3" /> Copy
     </Button>
     <Button
      type="button"
      variant="accent"
      size="sm"
      className="h-7 text-xs"
      onClick={() => {
       const blob = new Blob([text], { type: "application/json" });
       const url = URL.createObjectURL(blob);
       const a = document.createElement("a");
       a.href = url;
       a.download = `candidate-${candidate.domain || "data"}.json`;
       a.click();
       URL.revokeObjectURL(url);
      }}
     >
      <Download className="mr-1 size-3" /> Download
     </Button>
    </div>
   </div>
  </>
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

function ProductIntelligenceJobRow({
 job,
 active,
 onOpen,
}: Readonly<{
 job: {
  id: number;
  status: string;
  summary: Record<string, unknown>;
  created_at: string;
 };
 active: boolean;
 onOpen: () => void;
}>) {
 const candidateCount = Number(job.summary?.candidate_count ?? 0);
 return (
  <tr className={cn("border-b border-[var(--divider)] last:border-0 hover:bg-[var(--bg-alt)] transition-colors", active && "bg-[var(--bg-alt)]")}>
   <td className="p-0">
    <button type="button" onClick={onOpen} className="flex w-full flex-col text-left gap-1.5 p-2.5 focus:outline-none">
     <div className="flex w-full items-center justify-between">
      <span className="font-mono text-sm font-medium text-accent hover:underline">#{job.id}</span>
      <Badge tone={job.status === "complete" ? "success" : job.status === "failed" ? "danger" : "neutral"} className="scale-90 origin-right">
       {job.status}
      </Badge>
     </div>
     <div className="flex w-full items-center justify-between text-xs text-muted">
      <span>{candidateCount} URLs found</span>
      <span className="font-mono">{formatShortDate(job.created_at)}</span>
     </div>
    </button>
   </td>
  </tr>
 );
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

function DiscoveryStatus({
 provider,
 sourceCount,
 maxCandidates,
}: Readonly<{
 provider: string;
 sourceCount: number;
 maxCandidates: number;
}>) {
 const providerLabel = searchProviderLabel(provider);
 return (
  <div className="flex flex-wrap items-center gap-3 rounded-[var(--radius-md)] border border-[var(--accent)]/30 bg-[var(--accent-subtle)] px-4 py-3 text-xs text-foreground">
   <Loader2 className="size-4 animate-spin text-accent" aria-hidden="true" />
   <div className="min-w-[180px] flex-1">
    <div className="font-semibold">{providerLabel} discovery running</div>
    <div className="mt-0.5 text-muted">
     Searching {sourceCount} source product{sourceCount === 1 ? "" : "s"}, filtering source domains, ranking brand sites before aggregators.
    </div>
   </div>
   <div className="flex items-center gap-2">
    <Badge tone="info" className="h-5 px-1.5 text-xs">{providerLabel}</Badge>
    <Badge tone="neutral" className="h-5 px-1.5 text-xs">Max {maxCandidates}/product</Badge>
   </div>
  </div>
 );
}

function DiscoveryTableLoading({ provider }: Readonly<{ provider: string }>) {
 const providerLabel = searchProviderLabel(provider);
 return (
  <div className="flex min-h-[220px] flex-col items-center justify-center gap-4 px-6 py-10 text-center">
   <div className="relative">
    <div className="size-12 rounded-full border border-[var(--accent)]/25 bg-[var(--accent-subtle)]" />
    <Loader2 className="absolute left-1/2 top-1/2 size-5 -translate-x-1/2 -translate-y-1/2 animate-spin text-accent" aria-hidden="true" />
   </div>
   <div>
    <div className="text-sm font-semibold text-foreground">{providerLabel} is searching product candidates</div>
    <div className="mt-1 max-w-[520px] text-xs leading-5 text-muted">
     Querying organic results, removing blocked/source domains, classifying domains, and scoring each result from title, brand, identifiers, price, and source authority.
    </div>
   </div>
   <div className="grid w-full max-w-[560px] gap-2 text-left sm:grid-cols-3">
    <DiscoveryLoadingStep label="Search" detail="Provider request active" />
    <DiscoveryLoadingStep label="Filter" detail="Source domain excluded" />
    <DiscoveryLoadingStep label="Rank" detail="Brand DTC first" />
   </div>
  </div>
 );
}

function searchProviderLabel(provider: string) {
 const option = SEARCH_PROVIDER_OPTIONS.find((item) => item.value === provider);
 return option?.label ?? provider;
}

function DiscoveryLoadingStep({ label, detail }: Readonly<{ label: string; detail: string }>) {
 return (
  <div className="rounded-[var(--radius-md)] border border-[var(--divider)] bg-[var(--bg-alt)] px-3 py-2">
   <div className="flex items-center gap-2 text-xs font-semibold text-foreground">
    <span className="size-1.5 rounded-full bg-accent" />
    {label}
   </div>
   <div className="mt-1 text-xs text-muted">{detail}</div>
  </div>
 );
}

function MatchBadge({ score }: Readonly<{ score: number }>) {
 return (
  <Tooltip content={MATCH_SCORE_TOOLTIP}>
   <span className="inline-flex cursor-help">
    <Badge
     tone={score >= 0.6 ? "success" : score >= 0.4 ? "warning" : "neutral"}
     className="h-5 px-1.5 text-xs"
    >
     {Math.round(score * 100)}%
    </Badge>
   </span>
  </Tooltip>
 );
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
 return text || "--";
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
 return "--";
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

function formatShortDate(value: string) {
 const parsed = new Date(value);
 if (Number.isNaN(parsed.getTime())) {
  return "--";
 }
 return parsed.toLocaleString(undefined, {
  year: "numeric",
  month: "short",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
 });
}
