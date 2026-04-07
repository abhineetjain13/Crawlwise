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

/**
 * Renders the crawl configuration screen and manages crawl type, mode, field settings, and launch behavior.
 * @example
 * CrawlConfigScreen({ requestedTab: "pdp", requestedCategoryMode: "single", requestedPdpMode: "batch" })
 * <CrawlConfigScreen />
 * @param {Readonly<CrawlConfigScreenProps>} props - Initial crawl tab and mode values derived from routing.
 * @returns {JSX.Element} The crawl configuration UI.
 */
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
  const [antiBotEnabled, setAntiBotEnabled] = useState(false);
  const [requestDelay, setRequestDelay] = useState(String(CRAWL_DEFAULTS.REQUEST_DELAY_MS));
  const [maxRecords, setMaxRecords] = useState(String(CRAWL_DEFAULTS.MAX_RECORDS));
  const [maxPages, setMaxPages] = useState(String(CRAWL_DEFAULTS.MAX_PAGES));
  const [maxScrolls, setMaxScrolls] = useState(String(CRAWL_DEFAULTS.MAX_SCROLLS));
  const [proxyEnabled, setProxyEnabled] = useState(false);
  const [proxyInput, setProxyInput] = useState("");
  const [additionalDraft, setAdditionalDraft] = useState("");
  const [additionalFields, setAdditionalFields] = useState<string[]>([]);
  const [fieldRows, setFieldRows] = useState<FieldRow[]>([]);
  const [configError, setConfigError] = useState("");
  const [bulkBanner, setBulkBanner] = useState("");

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
      anti_bot_enabled: antiBotEnabled,
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
      antiBotEnabled,
    ],
  );

  /**
  * Starts a crawl by validating the current configuration, submitting the appropriate crawl request, and redirecting to the crawl status page.
  * @example
  * startCrawl(event)
  * void
  * @param {FormEvent} event - The form submission event used to prevent the default browser behavior.
  * @returns {Promise<void>} A promise that resolves when the crawl request is submitted and navigation/error handling completes.
  **/
  async function startCrawl(event: FormEvent) {
    event.preventDefault();
    setConfigError("");
    try {
      const dispatch = buildDispatch(config);
      let response: { run_id: number };
      if (dispatch.runType === "csv") {
        if (!dispatch.csvFile) {
          throw new Error("CSV file is missing.");
        }
        response = await api.createCsvCrawl({
          file: dispatch.csvFile,
          surface: dispatch.surface,
          additionalFields: dispatch.additionalFields,
          settings: dispatch.settings,
        });
      } else {
        response = await api.createCrawl({
          run_type: dispatch.runType,
          url: dispatch.url,
          urls: dispatch.urls,
          surface: dispatch.surface,
          settings: dispatch.settings,
          additional_fields: dispatch.additionalFields,
        });
      }
      router.replace((`/crawl?run_id=${response.run_id}`) as Route);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unable to launch crawl.";
      setConfigError(message);
    }
  }

  /**
  * Adds a new manual field row to the field list with default empty values and idle states.
  * @example
  * addManualField()
  * { id: "1700000000000-0", fieldName: "", xpath: "", regex: "", xpathState: "idle", regexState: "idle" }
  * @returns {void} No return value.
  **/
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
      <form className="grid gap-4 xl:grid-cols-[minmax(0,1.45fr)_360px]" onSubmit={(event) => void startCrawl(event)}>
        <div className="space-y-4">
          <Card className="space-y-5">
            <SectionHeader
              title="Target URL"
              description="Choose the crawl type, set your entry point, and define which fields should be captured."
            />
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex flex-wrap items-center gap-3">
                <TabBar
                  value={crawlTab}
                  onChange={(value) => setCrawlTab(value as CrawlTab)}
                  options={[
                    { value: "category", label: "Category Crawl" },
                    { value: "pdp", label: "PDP Crawl" },
                  ]}
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
              </div>
              <Button
                variant="accent"
                type="submit"
                disabled={!canPreview(config)}
              >
                Start Crawl
              </Button>
            </div>

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
                description="Add manual selectors for fields you want to force or test."
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
            <SectionHeader title="Crawl Settings" description="Set crawl behaviour and network controls." />
            <div className="space-y-4">
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
                  label="Anti-Bot Browser Mode"
                  description="Adds browser-style waits for protected sites."
                  icon={<Shield className="size-4" />}
                  checked={antiBotEnabled}
                  onChange={setAntiBotEnabled}
                />
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

    </div>
  );
}

/**
* Builds a dispatch payload from crawl configuration, validating required inputs based on the selected mode and module.
* @example
* buildDispatch(config)
* { runType: "crawl", surface: "web", url: "https://example.com", settings: { ... }, additionalFields: [], csvFile: null }
* @param {CrawlConfig} config - Crawl configuration used to construct the pending dispatch payload.
* @returns {PendingDispatch} A validated pending dispatch object for starting the crawl.
**/
function buildDispatch(config: CrawlConfig): PendingDispatch {
  const additionalFields = uniqueFields(config.additional_fields);
  const commonSettings = {
    llm_enabled: config.smart_extraction,
    advanced_enabled: config.advanced_enabled,
    advanced_mode: config.advanced_enabled ? config.advanced_mode : null,
    anti_bot_enabled: config.anti_bot_enabled,
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

/**
* Determines whether a string looks like a job posting URL based on known host and path patterns.
* @example
* looksLikeJobUrl("https://www.linkedin.com/jobs/view/123456789")
* true
* @param {string} value - URL string to evaluate.
* @returns {boolean} Returns true if the URL appears to be a job listing URL; otherwise false.
**/
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
