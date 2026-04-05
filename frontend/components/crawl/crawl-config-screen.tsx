"use client";

import { Plus, Shield, SlidersHorizontal, Sparkles, X } from "lucide-react";
import type { Route } from "next";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useMemo, useState } from "react";

import { PageHeader, SectionHeader } from "../ui/patterns";
import { Button, Card, Input, Textarea } from "../ui/primitives";
import { api } from "../../lib/api";
import type { AdvancedCrawlMode, CrawlConfig } from "../../lib/api/types";
import { CRAWL_DEFAULTS, CRAWL_LIMITS } from "../../lib/constants/crawl-defaults";
import { STORAGE_KEYS } from "../../lib/constants/storage-keys";
import { UI_DELAYS } from "../../lib/constants/timing";
import {
  AdditionalFieldInput,
  clampNumber,
  type CategoryMode,
  type CrawlTab,
  type FieldRow,
  ManualFieldEditor,
  parseLines,
  type PdpMode,
  type PendingDispatch,
  PreviewModal,
  SegmentedMode,
  SettingSection,
  SliderRow,
  TabBar,
  normalizeField,
  uniqueFields,
} from "./shared";

type CrawlConfigScreenProps = {
  requestedTab: CrawlTab | null;
  requestedCategoryMode: CategoryMode | null;
  requestedPdpMode: PdpMode | null;
};

export function CrawlConfigScreen({
  requestedTab,
  requestedCategoryMode,
  requestedPdpMode,
}: Readonly<CrawlConfigScreenProps>) {
  const router = useRouter();
  const [crawlTab, setCrawlTab] = useState<CrawlTab>(() => requestedTab ?? "pdp");
  const [categoryMode, setCategoryMode] = useState<CategoryMode>(() => requestedCategoryMode ?? "single");
  const [pdpMode, setPdpMode] = useState<PdpMode>(() => requestedPdpMode ?? "single");
  const [targetUrl, setTargetUrl] = useState("");
  const [bulkUrls, setBulkUrls] = useState("");
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [smartExtraction, setSmartExtraction] = useState(false);
  const [advancedEnabled, setAdvancedEnabled] = useState(false);
  const [advancedMode, setAdvancedMode] = useState<AdvancedCrawlMode>("auto");
  const [requestDelay, setRequestDelay] = useState(String(CRAWL_DEFAULTS.REQUEST_DELAY_MS));
  const [maxRecords, setMaxRecords] = useState(String(CRAWL_DEFAULTS.MAX_RECORDS));
  const [maxPages, setMaxPages] = useState(String(CRAWL_DEFAULTS.MAX_PAGES));
  const [maxScrolls, setMaxScrolls] = useState(String(CRAWL_DEFAULTS.MAX_SCROLLS));
  const [proxyEnabled, setProxyEnabled] = useState(false);
  const [proxyInput, setProxyInput] = useState("");
  const [additionalDraft, setAdditionalDraft] = useState("");
  const [additionalFields, setAdditionalFields] = useState<string[]>([]);
  const [fieldRows, setFieldRows] = useState<FieldRow[]>([]);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [pendingDispatch, setPendingDispatch] = useState<PendingDispatch | null>(null);
  const [configError, setConfigError] = useState("");
  const [launchError, setLaunchError] = useState("");
  const [bulkBanner, setBulkBanner] = useState("");
  const [siteMemoryBanner, setSiteMemoryBanner] = useState("");
  const [appliedMemoryDomain, setAppliedMemoryDomain] = useState("");

  const activeMode = crawlTab === "category" ? categoryMode : pdpMode;

  useEffect(() => {
    const nextTab = requestedTab ?? "pdp";
    const nextCategoryMode = requestedCategoryMode ?? "single";
    const nextPdpMode = requestedPdpMode ?? "single";
    setCrawlTab((current) => (current === nextTab ? current : nextTab));
    setCategoryMode((current) => (current === nextCategoryMode ? current : nextCategoryMode));
    setPdpMode((current) => (current === nextPdpMode ? current : nextPdpMode));
  }, [requestedCategoryMode, requestedPdpMode, requestedTab]);

  useEffect(() => {
    const routeMode = crawlTab === "category" ? requestedCategoryMode : requestedPdpMode;
    if (requestedTab === crawlTab && routeMode === activeMode) {
      return;
    }
    router.replace((`/crawl?module=${crawlTab}&mode=${activeMode}`) as Route);
  }, [activeMode, crawlTab, requestedCategoryMode, requestedPdpMode, requestedTab, router]);

  useEffect(() => {
    const stored = window.sessionStorage.getItem(STORAGE_KEYS.BULK_PREFILL);
    if (!stored) {
      return;
    }
    try {
      const parsed = JSON.parse(stored) as { urls: string[]; additional_fields?: string[] };
      if (Array.isArray(parsed.urls) && parsed.urls.length) {
        setCrawlTab("pdp");
        setPdpMode("batch");
        setBulkUrls(parsed.urls.join("\n"));
        if (Array.isArray(parsed.additional_fields)) {
          setAdditionalFields(uniqueFields(parsed.additional_fields));
        }
        setBulkBanner(`${parsed.urls.length} URLs loaded into PDP batch crawl.`);
      }
    } catch {
      // Ignore malformed prefill data.
    } finally {
      window.sessionStorage.removeItem(STORAGE_KEYS.BULK_PREFILL);
    }
  }, []);

  useEffect(() => {
    if (!bulkBanner) {
      return;
    }
    const timer = window.setTimeout(() => setBulkBanner(""), UI_DELAYS.BANNER_AUTO_HIDE_MS);
    return () => window.clearTimeout(timer);
  }, [bulkBanner]);

  const siteMemoryLookupUrl = useMemo(() => {
    if (targetUrl.trim()) {
      return targetUrl.trim();
    }
    const firstBulkUrl = parseLines(bulkUrls)[0];
    return firstBulkUrl ?? "";
  }, [bulkUrls, targetUrl]);

  useEffect(() => {
    let cancelled = false;
    const domain = normalizeDomain(siteMemoryLookupUrl);
    if (!domain || domain === appliedMemoryDomain) {
      return;
    }
    void (async () => {
      try {
        const memory = await api.getSiteMemory(domain);
        if (cancelled) {
          return;
        }
        const memoryFields = uniqueFields(memory.payload.fields ?? []);
        const selectorRows = flattenSiteMemorySelectors(memory.payload.selectors);
        setAdditionalFields((current) => uniqueFields([...memoryFields, ...current]));
        setFieldRows((current) => mergeFieldRowsFromSiteMemory(current, selectorRows));
        const loadedCount = memoryFields.length + selectorRows.length;
        if (loadedCount) {
          setSiteMemoryBanner(`Loaded ${loadedCount} reusable field${loadedCount === 1 ? "" : "s"} from Site Memory for ${domain}.`);
        }
        setAppliedMemoryDomain(domain);
      } catch (error) {
        if (!cancelled) {
          setAppliedMemoryDomain(domain);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [appliedMemoryDomain, siteMemoryLookupUrl]);

  const config = useMemo<CrawlConfig>(
    () => ({
      module: crawlTab,
      mode: crawlTab === "category" ? categoryMode : pdpMode,
      target_url: targetUrl,
      bulk_urls: bulkUrls,
      csv_file: csvFile,
      smart_extraction: smartExtraction,
      advanced_enabled: advancedEnabled,
      advanced_mode: advancedMode,
      request_delay_ms: clampNumber(
        requestDelay,
        CRAWL_LIMITS.MIN_REQUEST_DELAY_MS,
        CRAWL_LIMITS.MAX_REQUEST_DELAY_MS,
        CRAWL_DEFAULTS.REQUEST_DELAY_MS,
      ),
      max_records: clampNumber(maxRecords, CRAWL_LIMITS.MIN_RECORDS, CRAWL_LIMITS.MAX_RECORDS, CRAWL_DEFAULTS.MAX_RECORDS),
      max_pages: clampNumber(maxPages, CRAWL_LIMITS.MIN_PAGES, CRAWL_LIMITS.MAX_PAGES, CRAWL_DEFAULTS.MAX_PAGES),
      max_scrolls: clampNumber(maxScrolls, CRAWL_LIMITS.MIN_SCROLLS, CRAWL_LIMITS.MAX_SCROLLS, CRAWL_DEFAULTS.MAX_SCROLLS),
      proxy_enabled: proxyEnabled,
      proxy_lines: proxyEnabled ? parseLines(proxyInput) : [],
      additional_fields: additionalFields,
    }),
    [
      additionalFields,
      advancedEnabled,
      advancedMode,
      bulkUrls,
      categoryMode,
      crawlTab,
      csvFile,
      maxPages,
      maxRecords,
      maxScrolls,
      pdpMode,
      proxyEnabled,
      proxyInput,
      requestDelay,
      smartExtraction,
      targetUrl,
    ],
  );

  function startPreview(event: FormEvent) {
    event.preventDefault();
    setConfigError("");
    try {
      const dispatch = buildDispatch(config);
      setPendingDispatch(dispatch);
      setPreviewOpen(true);
    } catch (error) {
      setConfigError(error instanceof Error ? error.message : "Unable to prepare crawl.");
    }
  }

  async function launchPending() {
    if (!pendingDispatch) {
      return;
    }
    setLaunchError("");
    try {
      let response: { run_id: number };
      if (pendingDispatch.runType === "csv") {
        if (!pendingDispatch.csvFile) {
          throw new Error("CSV file is missing.");
        }
        response = await api.createCsvCrawl({
          file: pendingDispatch.csvFile,
          surface: pendingDispatch.surface,
          additionalFields: pendingDispatch.additionalFields,
          settings: pendingDispatch.settings,
        });
      } else {
        response = await api.createCrawl({
          run_type: pendingDispatch.runType,
          url: pendingDispatch.url,
          urls: pendingDispatch.urls,
          surface: pendingDispatch.surface,
          settings: pendingDispatch.settings,
          additional_fields: pendingDispatch.additionalFields,
        });
      }
      setPreviewOpen(false);
      setPendingDispatch(null);
      router.replace((`/crawl?run_id=${response.run_id}`) as Route);
    } catch (error) {
      setLaunchError(error instanceof Error ? error.message : "Unable to launch crawl.");
    }
  }

  function addManualField() {
    setFieldRows((current) => [
      ...current,
      {
        id: `${Date.now()}-${current.length}`,
        fieldName: "",
        xpath: "",
        regex: "",
        xpathState: "idle",
        regexState: "idle",
      },
    ]);
  }

  return (
    <div className="space-y-4">
      <PageHeader title="Crawl Studio" />

      {bulkBanner ? (
        <div className="surface-banner flex items-center justify-between px-4 py-3 text-sm">
          <div>{bulkBanner}</div>
          <button
            type="button"
            onClick={() => setBulkBanner("")}
            aria-label="Close banner"
            className="inline-flex size-7 items-center justify-center rounded-md text-muted transition hover:text-foreground"
          >
            <X className="size-4" aria-hidden="true" />
          </button>
        </div>
      ) : null}
      {siteMemoryBanner ? (
        <div className="surface-banner flex items-center justify-between px-4 py-3 text-sm">
          <div>{siteMemoryBanner}</div>
          <button
            type="button"
            onClick={() => setSiteMemoryBanner("")}
            aria-label="Close site memory banner"
            className="inline-flex size-7 items-center justify-center rounded-md text-muted transition hover:text-foreground"
          >
            <X className="size-4" aria-hidden="true" />
          </button>
        </div>
      ) : null}

      <form className="grid gap-4 xl:grid-cols-[minmax(0,1.45fr)_360px]" onSubmit={startPreview}>
        <div className="space-y-4">
          <Card className="space-y-5">
            <SectionHeader
              title="Target URL"
              description="Choose the crawl surface, set your entry point, and define which fields should be captured."
              action={
                <Button
                  variant="accent"
                  type="button"
                  disabled={!canPreview(config)}
                  onClick={() => {
                    try {
                      setPendingDispatch(buildDispatch(config));
                      setPreviewOpen(true);
                      setConfigError("");
                    } catch (error) {
                      setConfigError(error instanceof Error ? error.message : "Unable to prepare crawl.");
                    }
                  }}
                >
                  Review Before Running
                </Button>
              }
            />
            {crawlTab === "category" ? (
              <SegmentedMode
                value={categoryMode}
                onChange={(value) => setCategoryMode(value as CategoryMode)}
                options={[
                  { value: "single", label: "Single" },
                  { value: "sitemap", label: "Sitemap" },
                  { value: "bulk", label: "Bulk" },
                ]}
              />
            ) : (
              <SegmentedMode
                value={pdpMode}
                onChange={(value) => setPdpMode(value as PdpMode)}
                options={[
                  { value: "single", label: "Single" },
                  { value: "batch", label: "Batch" },
                  { value: "csv", label: "CSV Upload" },
                ]}
              />
            )}

            {(crawlTab === "category" && categoryMode === "bulk") || (crawlTab === "pdp" && pdpMode === "batch") ? (
              <label className="grid gap-1.5">
                <span className="label-caps">URLs (one per line)</span>
                <Textarea
                  value={bulkUrls}
                  onChange={(event) => setBulkUrls(event.target.value)}
                  placeholder={"https://example.com/page-1\nhttps://example.com/page-2"}
                  className="min-h-[220px] font-mono text-sm"
                  aria-label="Bulk URLs input"
                />
              </label>
            ) : crawlTab === "pdp" && pdpMode === "csv" ? (
              <label className="grid gap-1.5">
                <span className="label-caps">CSV File</span>
                <Input
                  type="file"
                  accept=".csv,text/csv"
                  onChange={(event) => setCsvFile(event.target.files?.[0] ?? null)}
                  className="h-auto py-3"
                  aria-label="CSV file input"
                />
              </label>
            ) : (
              <label className="grid gap-1.5">
                <span className="label-caps">Target URL</span>
                <Input
                  value={targetUrl}
                  onChange={(event) => setTargetUrl(event.target.value)}
                  placeholder={
                    crawlTab === "category"
                      ? "https://example.com/collections/chairs"
                      : "https://example.com/products/oak-chair"
                  }
                  className="font-mono text-sm"
                  aria-label="Target URL input"
                />
              </label>
            )}

            <AdditionalFieldInput
              value={additionalDraft}
              fields={additionalFields}
              onChange={setAdditionalDraft}
              onCommit={(value) => setAdditionalFields((current) => uniqueFields([...current, value]))}
              onRemove={(value) => setAdditionalFields((current) => current.filter((field) => field !== value))}
            />
          </Card>

          <Card className="space-y-4">
            <div className="flex items-center justify-between gap-4">
              <SectionHeader
                title="Field Configuration"
                description="Manual selectors layer on top of reusable Site Memory fields."
              />
              <Button variant="ghost" type="button" onClick={addManualField}>
                <Plus className="size-3.5" />
                New Field
              </Button>
            </div>
            <div className="space-y-3">
              {fieldRows.length ? (
                fieldRows.map((row) => (
                  <ManualFieldEditor
                    key={row.id}
                    row={row}
                    onChange={(patch) =>
                      setFieldRows((current) =>
                        current.map((entry) => (entry.id === row.id ? { ...entry, ...patch } : entry)),
                      )
                    }
                    onDelete={() => setFieldRows((current) => current.filter((entry) => entry.id !== row.id))}
                  />
                ))
              ) : (
                <div className="rounded-[var(--radius-lg)] border border-dashed border-border bg-panel px-4 py-6 text-sm text-muted">
                  No manual fields yet.
                </div>
              )}
            </div>
          </Card>

          {configError ? (
            <div className="rounded-[var(--radius-lg)] border border-danger/20 bg-danger/10 px-4 py-3 text-sm text-danger">
              {configError}
            </div>
          ) : null}
        </div>

        <div className="space-y-4 xl:sticky xl:top-[68px] xl:self-start">
          <Card className="space-y-4">
            <SectionHeader title="Run Settings" description="Set crawl behavior, extraction assist, and network controls." />
            <div className="space-y-4">
              <div className="space-y-1.5">
                <div className="label-caps">Crawl Surface</div>
                <TabBar
                  value={crawlTab}
                  onChange={(value) => setCrawlTab(value as CrawlTab)}
                  options={[
                    { value: "category", label: "Category Crawl" },
                    { value: "pdp", label: "PDP Crawl" },
                  ]}
                />
              </div>

              <div className="space-y-2">
                <SettingSection
                  label="Smart Extraction"
                  description="AI-assisted enrichment"
                  icon={<Sparkles className="size-4" />}
                  checked={smartExtraction}
                  onChange={setSmartExtraction}
                />
                <SettingSection
                  label="Advanced Crawl"
                  description="Pagination, scrolling, and limits."
                  icon={<SlidersHorizontal className="size-4" />}
                  checked={advancedEnabled}
                  onChange={setAdvancedEnabled}
                >
                  <div className="space-y-2.5 rounded-[var(--radius-xl)] border border-border bg-[var(--advanced-panel-bg)] px-3 py-3 shadow-[var(--advanced-panel-highlight)]">
                    <div className="grid grid-cols-[auto_minmax(0,1fr)] items-center gap-3">
                      <div className="text-sm font-medium text-[var(--text-secondary)]">Mode</div>
                      <select
                        aria-label="Advanced crawl mode"
                        value={advancedMode}
                        onChange={(event) => setAdvancedMode(event.target.value as AdvancedCrawlMode)}
                        className="control-select focus-ring h-9 w-full"
                      >
                        <option value="auto">Auto</option>
                        <option value="scroll">Scroll</option>
                        <option value="load_more">Load More</option>
                        <option value="paginate">Paginate</option>
                      </select>
                    </div>
                    <div className="space-y-2">
                      <SliderRow
                        label="Request Delay"
                        value={requestDelay}
                        min={CRAWL_LIMITS.MIN_REQUEST_DELAY_MS}
                        max={CRAWL_LIMITS.MAX_REQUEST_DELAY_MS}
                        step={100}
                        suffix=" ms"
                        onChange={setRequestDelay}
                        onReset={() => setRequestDelay(String(CRAWL_DEFAULTS.REQUEST_DELAY_MS))}
                      />
                      <SliderRow
                        label="Max Records"
                        value={maxRecords}
                        min={CRAWL_LIMITS.MIN_RECORDS}
                        max={CRAWL_LIMITS.MAX_RECORDS}
                        step={1}
                        onChange={setMaxRecords}
                        onReset={() => setMaxRecords(String(CRAWL_DEFAULTS.MAX_RECORDS))}
                      />
                      <SliderRow
                        label="Max Pages"
                        value={maxPages}
                        min={CRAWL_LIMITS.MIN_PAGES}
                        max={CRAWL_LIMITS.MAX_PAGES}
                        step={1}
                        onChange={setMaxPages}
                        onReset={() => setMaxPages(String(CRAWL_DEFAULTS.MAX_PAGES))}
                      />
                      <SliderRow
                        label="Max Scrolls"
                        value={maxScrolls}
                        min={CRAWL_LIMITS.MIN_SCROLLS}
                        max={CRAWL_LIMITS.MAX_SCROLLS}
                        step={1}
                        onChange={setMaxScrolls}
                        onReset={() => setMaxScrolls(String(CRAWL_DEFAULTS.MAX_SCROLLS))}
                      />
                    </div>
                  </div>
                </SettingSection>
                <SettingSection
                  label="Proxy"
                  description="Use a proxy pool."
                  icon={<Shield className="size-4" />}
                  checked={proxyEnabled}
                  onChange={setProxyEnabled}
                >
                  <div className="space-y-2 rounded-[var(--radius-lg)] border border-border bg-background px-3 py-3">
                    <div className="label-caps">Proxy Pool</div>
                    <Textarea
                      value={proxyInput}
                      onChange={(event) => setProxyInput(event.target.value)}
                      placeholder={"host:port\nhost:port:user:pass"}
                      className="min-h-[104px] font-mono text-sm"
                      aria-label="Proxy pool input"
                    />
                  </div>
                </SettingSection>
              </div>
            </div>
          </Card>
        </div>
      </form>

      {previewOpen && pendingDispatch ? (
        <PreviewModal
          dispatch={pendingDispatch}
          onCancel={() => {
            setPreviewOpen(false);
            setPendingDispatch(null);
          }}
          onLaunch={() => void launchPending()}
          launchError={launchError}
        />
      ) : null}
    </div>
  );
}

function buildDispatch(config: CrawlConfig): PendingDispatch {
  const additionalFields = uniqueFields(config.additional_fields);
  const commonSettings = {
    llm_enabled: config.smart_extraction,
    advanced_enabled: config.advanced_enabled,
    advanced_mode: config.advanced_enabled ? config.advanced_mode : null,
    sleep_ms: config.request_delay_ms,
    max_records: config.max_records,
    max_pages: config.max_pages,
    max_scrolls: config.max_scrolls,
    proxy_enabled: config.proxy_enabled,
    proxy_list: config.proxy_enabled ? config.proxy_lines : [],
    additional_fields: additionalFields,
    crawl_module: config.module,
    crawl_mode: config.mode,
  };
  const inferredSurface = inferDispatchSurface(config);

  if (config.module === "category") {
    if (config.mode === "bulk") {
      const urls = parseLines(config.bulk_urls);
      if (!urls.length) throw new Error("Bulk crawl needs at least one URL.");
      return {
        runType: "batch",
        surface: inferredSurface,
        url: urls[0],
        urls,
        settings: { ...commonSettings, urls },
        additionalFields,
        csvFile: null,
      };
    }
    if (!config.target_url.trim()) throw new Error("Enter a target URL.");
    return {
      runType: "crawl",
      surface: inferredSurface,
      url: config.target_url.trim(),
      settings: commonSettings,
      additionalFields,
      csvFile: null,
    };
  }

  if (config.mode === "csv") {
    if (!config.csv_file) throw new Error("Select a CSV file.");
    return {
      runType: "csv",
      surface: inferredSurface,
      url: config.target_url.trim() || undefined,
      settings: commonSettings,
      additionalFields,
      csvFile: config.csv_file,
    };
  }

  if (config.mode === "batch") {
    const urls = parseLines(config.bulk_urls);
    if (!urls.length) throw new Error("Batch crawl needs at least one URL.");
    return {
      runType: "batch",
      surface: inferredSurface,
      url: urls[0],
      urls,
      settings: { ...commonSettings, urls },
      additionalFields,
      csvFile: null,
    };
  }

  if (!config.target_url.trim()) throw new Error("Enter a target URL.");
  return {
    runType: "crawl",
    surface: inferredSurface,
    url: config.target_url.trim(),
    settings: commonSettings,
    additionalFields,
    csvFile: null,
  };
}

function inferDispatchSurface(config: CrawlConfig) {
  const fallbackSurface = config.module === "category" ? "ecommerce_listing" : "ecommerce_detail";
  const sampleUrl =
    config.target_url.trim() ||
    parseLines(config.bulk_urls)[0] ||
    "";
  if (!looksLikeJobUrl(sampleUrl)) {
    return fallbackSurface;
  }
  return config.module === "category" ? "job_listing" : "job_detail";
}

function looksLikeJobUrl(value: string) {
  try {
    const url = new URL(value);
    const host = url.hostname.toLowerCase();
    const pathAndQuery = `${url.pathname}${url.search}`.toLowerCase();
    const hostHints = [
      "dice.com",
      "linkedin.com",
      "indeed.",
      "greenhouse.io",
      "idealist.org",
      "usajobs.gov",
      "remotive.com",
    ];
    const pathHints = [
      "/job-detail/",
      "/viewjob",
      "/jobs",
      "/job/",
      "/position",
      "/positions",
      "/opening",
      "/openings",
      "/career",
      "/careers",
      "/search/results",
    ];
    const hasHostHint = hostHints.some((hint) => host.includes(hint));
    return hasHostHint && pathHints.some((hint) => pathAndQuery.includes(hint));
  } catch {
    return false;
  }
}

function canPreview(config: CrawlConfig) {
  try {
    buildDispatch(config);
    return true;
  } catch {
    return false;
  }
}

function normalizeDomain(value: string) {
  try {
    return new URL(value).hostname.replace(/^www\./, "").toLowerCase();
  } catch {
    return "";
  }
}

function flattenSiteMemorySelectors(selectors: Record<string, Array<{ xpath?: string | null; regex?: string | null }>>) {
  return Object.entries(selectors).flatMap(([fieldName, rows]) =>
    rows
      .map((row, index) => ({
        id: `site-memory-${fieldName}-${index}`,
        fieldName,
        xpath: row.xpath?.trim() ?? "",
        regex: row.regex?.trim() ?? "",
        xpathState: "idle" as const,
        regexState: "idle" as const,
      }))
      .filter((row) => row.xpath || row.regex),
  );
}

function mergeFieldRowsFromSiteMemory(current: FieldRow[], incoming: FieldRow[]) {
  const next = [...current];
  const seen = new Set(current.map((row) => `${normalizeField(row.fieldName)}|${row.xpath}|${row.regex}`));
  for (const row of incoming) {
    const key = `${normalizeField(row.fieldName)}|${row.xpath}|${row.regex}`;
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    next.push(row);
  }
  return next;
}
