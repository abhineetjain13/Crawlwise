"use client";

import { useQuery } from "@tanstack/react-query";
import { Code2, Download, ExternalLink, Play, Search } from "lucide-react";
import type { Route } from "next";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { InlineAlert, PageHeader, TableSurface } from "../../components/ui/patterns";
import {
 Badge,
 Button,
 Dropdown,
 Field,
 Input,
 Table,
 TableBody,
 TableCell,
 TableHead,
 TableHeader,
 TableRow,
 Textarea,
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
  max_source_products: 5,
  max_candidates_per_product: 3,
  search_provider: "serpapi",
  private_label_mode: "flag",
  confidence_threshold: 0.4,
  allowed_domains: [],
  excluded_domains: [],
  llm_enrichment_enabled: false,
};

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
  const [activeUrl, setActiveUrl] = useState("");
  const [activeJobId, setActiveJobId] = useState<number | null>(null);
  const [activeTab, setActiveTab] = useState<"urls" | "intelligence">("urls");

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
      return;
    }
    try {
      const parsed = JSON.parse(stored) as PrefillPayload;
      setPrefill({
        source_run_id: typeof parsed.source_run_id === "number" ? parsed.source_run_id : null,
        source_domain: parsed.source_domain ?? "",
        records: Array.isArray(parsed.records) ? parsed.records : [],
      });
    } catch {
      setError("Unable to read Product Intelligence prefill.");
    } finally {
      window.sessionStorage.removeItem(STORAGE_KEYS.PRODUCT_INTELLIGENCE_PREFILL);
    }
  }, []);

  useEffect(() => {
    if (!detailQuery.data) {
      return;
    }
    const hydrated = detailToDiscovery(detailQuery.data);
    setDiscovery(hydrated);
    const hydratedOptions = detailOptions(detailQuery.data.job.options);
    setOptions(hydratedOptions);
    setAllowedDomainsText(hydratedOptions.allowed_domains.join("\n"));
    setExcludedDomainsText(hydratedOptions.excluded_domains.join("\n"));
    setSelectedUrls([]);
    setActiveUrl(hydrated.candidates[0]?.url ?? "");
  }, [detailQuery.data]);

  const sourceRecords = prefill.records ?? [];
  const visibleSourceRecords = detailQuery.data
    ? detailQuery.data.source_products.map((source) => ({
      id: source.source_record_id,
      run_id: source.source_run_id,
      source_url: source.source_url,
      data: source.payload,
    }))
    : sourceRecords;
  const activeSourceRunId =
    detailQuery.data?.job.source_run_id
    ?? visibleSourceRecords.find((record) => typeof record.run_id === "number")?.run_id
    ?? prefill.source_run_id
    ?? null;
  const uniqueSelectedUrls = useMemo(() => Array.from(new Set(selectedUrls)), [selectedUrls]);
  const allCandidateUrls = useMemo(
    () => Array.from(new Set((discovery?.candidates ?? []).map((candidate) => candidate.url).filter(Boolean))),
    [discovery],
  );
  const activeCandidate = (discovery?.candidates ?? []).find((candidate) => candidate.url === activeUrl) ?? null;
  const intelligenceRows = useMemo(() => (discovery?.candidates ?? []).map(toIntelligenceRow), [discovery]);
  const intelligenceColumns = useMemo(() => intelligenceColumnNames(intelligenceRows), [intelligenceRows]);

  async function discover() {
    if (!visibleSourceRecords.length) {
      return;
    }
    setPending(true);
    setError("");
    setDiscovery(null);
    setSelectedUrls([]);
    setActiveUrl("");
    try {
      const sourceRecordIds = visibleSourceRecords
        .map((record) => record.id)
        .filter((value): value is number => typeof value === "number");
      const canUseRecordIds = sourceRecordIds.length === visibleSourceRecords.length;
      const response = await api.discoverProductIntelligence({
        source_run_id: activeSourceRunId,
        source_record_ids: canUseRecordIds ? sourceRecordIds : [],
        source_records: canUseRecordIds ? [] : visibleSourceRecords,
        options: {
          ...options,
          allowed_domains: parseDomainLines(allowedDomainsText),
          excluded_domains: parseDomainLines(excludedDomainsText),
        },
      });
      setDiscovery(response);
      setActiveJobId(response.job_id);
      setActiveUrl(response.candidates[0]?.url ?? "");
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
    setSelectedUrls((current) => (current.length === allCandidateUrls.length ? [] : allCandidateUrls));
  }

  return (
    <div className="page-stack gap-4">
      <PageHeader
        title="Product Intelligence"
        description=""
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

  <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-[minmax(0,1fr)_350px]">
   <div className="space-y-4">
    {/* Configuration Card */}
    <section className="panel panel-raised overflow-hidden">
     <header className="flex h-10 items-center justify-between border-b border-[var(--divider)] px-4">
      <h2 className="text-xs font-bold tracking-wider text-foreground/70">Configuration</h2>
      <div className="flex gap-2">
       {prefill.source_run_id ? <Badge tone="info" className="h-5 px-1.5 text-[10px]">Run #{prefill.source_run_id}</Badge> : null}
       <Badge tone="neutral" className="h-5 px-1.5 text-[10px]">{visibleSourceRecords.length} rows</Badge>
      </div>
     </header>
     <div className="p-4">
      <div className="grid gap-4 md:grid-cols-3">
       {/* Settings Columns */}
       <div className="grid gap-4 md:col-span-2 md:grid-cols-2 content-start">
        <Field label="Provider">
         <Dropdown
          value={options.search_provider}
          onChange={(value) => setOptions((current) => ({ ...current, search_provider: value }))}
          options={[
           { value: "serpapi", label: "SerpAPI" },
           { value: "duckduckgo", label: "DuckDuckGo" },
          ]}
         />
        </Field>
        <Field label="Max Sources">
         <Input
          type="number"
          min={1}
          max={25}
          value={options.max_source_products}
          onChange={(event) => setOptions((current) => ({ ...current, max_source_products: clampInt(event.target.value, 1, 25, 5) }))}
         />
        </Field>
        <Field label="Max URLs">
         <Input
          type="number"
          min={1}
          max={10}
          value={options.max_candidates_per_product}
          onChange={(event) => setOptions((current) => ({ ...current, max_candidates_per_product: clampInt(event.target.value, 1, 10, 3) }))}
         />
        </Field>
        <Field label="Private Label">
         <Dropdown
          value={options.private_label_mode}
          onChange={(value) => setOptions((current) => ({ ...current, private_label_mode: value as ProductIntelligenceOptions["private_label_mode"] }))}
          options={[
           { value: "flag", label: "Flag" },
           { value: "exclude", label: "Exclude" },
           { value: "include", label: "Include" },
          ]}
         />
        </Field>
        <Field label="LLM Cleanup">
         <div className="surface-muted flex h-[var(--control-height)] items-center justify-between rounded-[var(--radius-md)] px-3 shadow-sm">
          <span className="text-[11px] font-medium text-muted">Enable Enrichment</span>
          <input
           type="checkbox"
           checked={options.llm_enrichment_enabled}
           onChange={(event) => setOptions((current) => ({ ...current, llm_enrichment_enabled: event.target.checked }))}
           className="h-3.5 w-3.5 rounded border-[var(--divider)] text-accent focus:ring-accent"
          />
         </div>
        </Field>
       </div>

       {/* Domains Column */}
       <div className="grid gap-4 content-start">
        <Field label="Allowed Domains">
         <Textarea
          value={allowedDomainsText}
          onChange={(event) => setAllowedDomainsText(event.target.value)}
          className="min-h-[76px] text-xs"
          placeholder="ralphlauren.com"
         />
        </Field>
        <Field label="Excluded Domains">
         <Textarea
          value={excludedDomainsText}
          onChange={(event) => setExcludedDomainsText(event.target.value)}
          className="min-h-[76px] text-xs"
          placeholder="amazon.com"
         />
        </Field>
       </div>
      </div>
     </div>
    </section>

    {/* Results Card */}
    <section className="panel panel-raised overflow-hidden">
     <header className="flex h-12 items-center justify-between border-b border-[var(--divider)] px-4">
      <div className="flex items-center gap-4">
       <div className="flex rounded-[var(--radius-md)] border border-[var(--divider)] bg-[var(--bg-alt)] p-0.5">
        <button
         type="button"
         onClick={() => setActiveTab("urls")}
         className={`h-7 px-3 text-xs font-medium rounded-[var(--radius-sm)] transition-all ${
          activeTab === "urls"
           ? "bg-[var(--bg-panel)] text-foreground shadow-sm"
           : "text-muted hover:text-foreground"
         }`}
        >
         Discovered URLs
        </button>
        <button
         type="button"
         onClick={() => setActiveTab("intelligence")}
         className={`h-7 px-3 text-xs font-medium rounded-[var(--radius-sm)] transition-all ${
          activeTab === "intelligence"
           ? "bg-[var(--bg-panel)] text-foreground shadow-sm"
           : "text-muted hover:text-foreground"
         }`}
        >
         Data Intelligence
        </button>
       </div>
       <div className="hidden items-center gap-2 sm:flex">
        <Badge tone="neutral" className="h-5 px-1.5 text-[10px]">{discovery?.candidate_count ?? 0} total</Badge>
        <Badge tone="success" className="h-5 px-1.5 text-[10px]">{uniqueSelectedUrls.length} selected</Badge>
       </div>
      </div>
      <div className="flex items-center gap-2">
       <Button
        type="button"
        variant="secondary"
        size="sm"
        onClick={() => downloadRows(activeTab, "csv", discovery)}
        disabled={!discovery?.candidates.length}
        className="h-7 px-2"
       >
        <Download className="size-3" /> CSV
       </Button>
       <Button
        type="button"
        variant="secondary"
        size="sm"
        onClick={() => downloadRows(activeTab, "json", discovery)}
        disabled={!discovery?.candidates.length}
        className="h-7 px-2"
       >
        <Download className="size-3" /> JSON
       </Button>
       {activeTab === "urls" && (
        <button
         type="button"
         className="ml-2 text-xs font-medium text-accent hover:underline focus:outline-none disabled:opacity-50"
         onClick={toggleAllUrls}
         disabled={!allCandidateUrls.length}
        >
         {uniqueSelectedUrls.length === allCandidateUrls.length && allCandidateUrls.length ? "Clear All" : "Select All"}
        </button>
       )}
      </div>
     </header>

     <TableSurface className="rounded-none border-0 shadow-none">
      <div className="max-h-[600px] overflow-auto">
       <Table className="border-collapse">
        <TableHeader className="bg-[var(--bg-alt)] sticky top-0 z-10">
         <TableRow className="hover:bg-transparent border-b border-[var(--divider)]">
          {activeTab === "urls" ? (
           <>
            <TableHead className="w-10 px-3">Use</TableHead>
            <TableHead className="px-3">Source Product</TableHead>
            <TableHead className="px-3">Discovery Result</TableHead>
            <TableHead className="w-20 px-3">Match</TableHead>
            <TableHead className="w-10 px-3 text-right">View</TableHead>
           </>
          ) : (
           <>
            <TableHead className="px-3">Source</TableHead>
            {intelligenceColumns.map((column) => (
             <TableHead key={column} className="min-w-[160px] px-3">
              {column.replace(/_/g, " ").replace(/\b\w/g, (l) => l.toUpperCase())}
             </TableHead>
            ))}
            <TableHead className="w-10 px-3 text-right">View</TableHead>
           </>
          )}
         </TableRow>
        </TableHeader>
        <TableBody>
         {activeTab === "urls" ? (
          (discovery?.candidates.length ?? 0) ? (
           discovery!.candidates.map((candidate) => {
            const selected = uniqueSelectedUrls.includes(candidate.url);
            const isActive = activeUrl === candidate.url;
            return (
             <TableRow
              key={`${candidate.source_index}:${candidate.url}`}
              className={cn(isActive && "bg-[var(--accent-subtle)] hover:bg-[var(--accent-subtle)]")}
              onClick={() => setActiveUrl(candidate.url)}
             >
              <TableCell className="px-3 py-2">
               <input
                type="checkbox"
                checked={selected}
                onChange={(e) => {
                 e.stopPropagation();
                 toggleUrl(candidate.url);
                }}
                className="h-4 w-4 rounded border-[var(--divider)] text-accent focus:ring-accent"
               />
              </TableCell>
              <TableCell className="px-3 py-2 max-w-[200px]">
               <div className="truncate font-medium text-foreground" title={candidate.source_title || "Untitled"}>{candidate.source_title || "Untitled"}</div>
               <div className="mt-0.5 flex items-center gap-2 text-[11px] text-muted">
                <span className="truncate" title={candidate.source_brand || "No brand"}>{candidate.source_brand || "No brand"}</span>
                <span className="font-mono">{formatPrice(candidate.source_price, candidate.source_currency)}</span>
               </div>
              </TableCell>
              <TableCell className="px-3 py-2 min-w-[200px]">
               <div className="flex items-center gap-2 mb-1">
                <Badge tone={candidate.source_type === "brand_dtc" ? "success" : "neutral"} className="h-4 px-1 text-[9px] tracking-wider">
                 {candidate.source_type || "unknown"}
                </Badge>
                <span className="text-[11px] text-muted font-mono">Rank {candidate.search_rank}</span>
               </div>
               <a
                href={candidate.url}
                target="_blank"
                rel="noreferrer"
                onClick={(e) => e.stopPropagation()}
                className="flex items-center gap-1.5 truncate text-xs text-accent hover:underline" title={candidate.url}
               >
                <ExternalLink className="size-3 shrink-0" />
                {candidate.domain || candidate.url}
               </a>
              </TableCell>
              <TableCell className="px-3 py-2">
               <MatchBadge score={candidateConfidence(candidate)} />
              </TableCell>
              <TableCell className="px-3 py-2 text-right">
               <Button
                size="icon"
                variant={isActive ? "accent" : "ghost"}
                className="h-7 w-7"
                onClick={(e) => {
                 e.stopPropagation();
                 setActiveUrl(candidate.url);
                }}
               >
                <Code2 className="size-3.5" />
               </Button>
              </TableCell>
             </TableRow>
            );
           })
          ) : (
           <TableRow>
            <TableCell colSpan={5} className="py-20 text-center text-muted">
             No discovery results yet. Use Discover URLs in the top bar.
            </TableCell>
           </TableRow>
          )
         ) : (
          intelligenceRows.length ? (
           intelligenceRows.map((row) => {
            const isActive = activeUrl === row.url;
            return (
             <TableRow
              key={`${row.source_index}:${row.url}:intelligence`}
              className={cn(isActive && "bg-[var(--accent-subtle)] hover:bg-[var(--accent-subtle)]")}
              onClick={() => setActiveUrl(row.url)}
             >
              <TableCell className="px-3 py-2 max-w-[200px]">
               <div className="truncate font-medium text-foreground" title={row.source_title || "Untitled"}>{row.source_title || "Untitled"}</div>
               <div className="mt-0.5 flex items-center gap-2 text-[11px] text-muted">
                <span className="truncate" title={row.source_brand || "No brand"}>{row.source_brand || "No brand"}</span>
                <span className="font-mono">{formatPrice(row.source_price, row.source_currency)}</span>
               </div>
              </TableCell>
              {intelligenceColumns.map((column) => {
               const value = intelligenceCellValue(row, column);
               return (
                <TableCell key={column} className="max-w-[260px] min-w-[160px] px-3 py-2 text-xs">
                 {(column === "url" || column === "image_url") && value !== "--" ? (
                  <a href={value} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()} className="block truncate text-accent hover:underline" title={value}>
                   {value}
                  </a>
                 ) : (
                  <span className={cn("block text-foreground", longIntelligenceColumn(column) ? "line-clamp-2" : "truncate")} title={value}>
                   {value}
                  </span>
                 )}
                </TableCell>
               );
              })}
              <TableCell className="px-3 py-2 text-right">
               <Button
                size="icon"
                variant={isActive ? "accent" : "ghost"}
                className="h-7 w-7"
                onClick={(e) => {
                 e.stopPropagation();
                 setActiveUrl(row.url);
                }}
               >
                <Code2 className="size-3.5" />
               </Button>
              </TableCell>
             </TableRow>
            );
           })
          ) : (
            <TableRow>
            <TableCell colSpan={Math.max(3, intelligenceColumns.length + 2)} className="py-20 text-center text-muted">
             No data intelligence yet. Use Discover URLs.
            </TableCell>
           </TableRow>
          )
         )}
        </TableBody>
       </Table>
      </div>
     </TableSurface>
    </section>
   </div>

   {/* Right Column / Sidebar */}
   <div className="space-y-4">
    {activeUrl && activeCandidate && (
     <section className="panel panel-raised overflow-hidden animate-in slide-in-from-right-4 duration-200">
      <header className="flex h-10 items-center justify-between border-b border-[var(--divider)] bg-[var(--bg-alt)] px-4">
       <h3 className="text-xs font-bold tracking-wider text-foreground/70">Intelligence Inspector</h3>
       <Badge tone="accent" className="h-5 px-1.5 text-[10px]">{activeCandidate.domain}</Badge>
      </header>
      <div className="p-0">
       <pre className="crawl-terminal crawl-terminal-json max-h-[400px] overflow-auto rounded-none border-0 text-[11px] leading-relaxed">
        {JSON.stringify(activeCandidate.intelligence || activeCandidate.payload, null, 2)}
       </pre>
      </div>
     </section>
    )}

    <section className="panel panel-raised overflow-hidden">
     <header className="flex h-10 items-center justify-between border-b border-[var(--divider)] px-4">
      <h2 className="text-xs font-bold tracking-wider text-foreground/70">Input Sources</h2>
      <Badge tone="neutral" className="h-5 px-1.5 text-[10px]">{visibleSourceRecords.length} rows</Badge>
     </header>
     <div className="max-h-[300px] overflow-auto">
      {visibleSourceRecords.length ? (
       visibleSourceRecords.map((record, index) => (
        <button
         key={`${record.run_id ?? "local"}:${record.id ?? record.source_url}:${index}`}
         type="button"
         className="flex w-full flex-col gap-1 border-b border-[var(--divider)] px-4 py-2 text-left last:border-b-0 hover:bg-[var(--bg-alt)] focus:outline-none focus:bg-[var(--bg-alt)] transition-colors"
        >
         <div className="truncate text-xs font-medium text-foreground/90">
          {displayValue(record.data, ["title", "name", "product_title"]) || "Untitled"}
         </div>
         <div className="flex w-full items-center justify-between text-[10px] text-muted">
          <span className="truncate">{displayValue(record.data, ["brand", "manufacturer"]) || "No brand"}</span>
          <span className="shrink-0 pl-2 font-mono text-foreground/60">{formatPrice(displayValue(record.data, ["price", "sale_price", "current_price"]))}</span>
         </div>
        </button>
       ))
      ) : (
       <div className="p-8 text-center text-xs text-muted">No sources selected.</div>
      )}
     </div>
    </section>

    <section className="panel panel-raised overflow-hidden">
     <header className="flex h-10 items-center border-b border-[var(--divider)] px-4">
      <h2 className="text-xs font-bold tracking-wider text-foreground/70">Session History</h2>
     </header>
     <div className="max-h-[300px] overflow-auto">
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
    </section>
    </div>
   </div>
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
  max_source_products: clampInt(raw.max_source_products, 1, 25, DEFAULT_OPTIONS.max_source_products),
  max_candidates_per_product: clampInt(raw.max_candidates_per_product, 1, 10, DEFAULT_OPTIONS.max_candidates_per_product),
  search_provider: String(raw.search_provider || DEFAULT_OPTIONS.search_provider),
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

function MatchBadge({ score }: Readonly<{ score: number }>) {
 return (
  <Badge
   tone={score >= 0.6 ? "success" : score >= 0.4 ? "warning" : "neutral"}
   className="h-5 px-1.5 text-[10px]"
  >
   {Math.round(score * 100)}%
  </Badge>
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
