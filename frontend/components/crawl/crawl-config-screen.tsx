"use client";

import { Plus, Shield, SlidersHorizontal, Sparkles, X } from "lucide-react";
import type { Route } from "next";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

import { PageHeader, SectionHeader, TabBar } from "../ui/patterns";
import { Button, Card, Input, Textarea } from "../ui/primitives";
import { api } from "../../lib/api";
import type { AdvancedCrawlMode, CrawlConfig, CrawlSurface } from "../../lib/api/types";
import { CRAWL_DEFAULTS, CRAWL_LIMITS } from "../../lib/constants/crawl-defaults";
import { STORAGE_KEYS } from "../../lib/constants/storage-keys";
import { UI_DELAYS } from "../../lib/constants/timing";
import { telemetryErrorPayload, trackEvent } from "../../lib/telemetry/events";
import {
  AdditionalFieldInput,
  clampNumber,
  type CategoryMode,
  type CrawlTab,
  type FieldRow,
  ManualFieldEditor,
  type PendingDispatch,
  parseRequestedCategoryMode,
  parseRequestedCrawlTab,
  parseLines,
  parseRequestedPdpMode,
  type PdpMode,
  SettingSection,
  SliderRow,
  validateAdditionalFieldName,
  normalizeField,
  uniqueFields,
} from "./shared";

type CrawlConfigScreenProps = {
  requestedTab: CrawlTab | null;
  requestedCategoryMode: CategoryMode | null;
  requestedPdpMode: PdpMode | null;
};

const ADVANCED_MODE_OPTIONS = new Set<AdvancedCrawlMode>(["auto", "scroll", "load_more", "view_all", "paginate"]);

export function CrawlConfigScreen({
  requestedTab,
  requestedCategoryMode,
  requestedPdpMode,
}: Readonly<CrawlConfigScreenProps>) {
  const router = useRouter();
  const [crawlTab, setCrawlTab] = useState<CrawlTab>(() => requestedTab ?? "category");
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
  const [isSubmitting, setIsSubmitting] = useState(false);
  /** While set, ignore route→state sync until the URL shows PDP (bulk prefill). */
  const bulkPrefillRouteSyncGuardRef = useRef(false);

  const activeMode = crawlTab === "category" ? categoryMode : pdpMode;
  const surface: CrawlSurface = crawlTab === "category" ? "ecommerce_listing" : "ecommerce_detail";

  useEffect(() => {
    if (bulkPrefillRouteSyncGuardRef.current) {
      if (requestedTab === "pdp") {
        bulkPrefillRouteSyncGuardRef.current = false;
      }
      return;
    }
    const nextTab = requestedTab ?? "category";
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
    const nextUrl = `/crawl?module=${crawlTab}&mode=${activeMode}`;
    if (typeof window !== "undefined") {
      const currentUrl = `${window.location.pathname}${window.location.search}`;
      if (currentUrl !== nextUrl) {
        window.history.replaceState(null, "", nextUrl);
      }
    }
  }, [activeMode, crawlTab, requestedCategoryMode, requestedPdpMode, requestedTab]);

  useEffect(() => {
    const stored = window.sessionStorage.getItem(STORAGE_KEYS.BULK_PREFILL);
    if (!stored) {
      return;
    }
    try {
      const parsed = JSON.parse(stored) as { urls: string[]; additional_fields?: string[] };
      if (Array.isArray(parsed.urls) && parsed.urls.length) {
        bulkPrefillRouteSyncGuardRef.current = true;
        setCrawlTab("pdp");
        setPdpMode("batch");
        setBulkUrls(parsed.urls.join("\n"));
        if (Array.isArray(parsed.additional_fields)) {
          setAdditionalFields(uniqueFields(parsed.additional_fields));
        }
        setBulkBanner(`${parsed.urls.length} URLs loaded into PDP batch crawl.`);
        router.replace("/crawl?module=pdp&mode=batch" as Route);
      }
    } catch {
      // Ignore malformed prefill data.
    } finally {
      window.sessionStorage.removeItem(STORAGE_KEYS.BULK_PREFILL);
    }
  }, [router]);

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
      surface,
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
      surface,
      smartExtraction,
      targetUrl,
      antiBotEnabled,
    ],
  );

  async function startCrawl(event: FormEvent) {
    event.preventDefault();
    if (isSubmitting) {
      return;
    }
    setConfigError("");
    setIsSubmitting(true);
    try {
      const dispatch = buildDispatch(config, fieldRows);
      const surfaceMismatch = isSurfaceMismatch(config.module, dispatch.surface);
      if (surfaceMismatch) {
        trackEvent("crawl_submit_surface_mismatch", {
          module: config.module,
          mode: config.mode,
          selected_surface: config.surface,
          effective_surface: dispatch.surface,
        });
      }
      if (config.advanced_enabled) {
        trackEvent("advanced_mode_selected_vs_effective", {
          module: config.module,
          selected_advanced_mode: config.advanced_mode,
          effective_advanced_mode: dispatch.settings.advanced_mode ?? null,
        });
      }
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
      trackEvent(
        "crawl_submit_error_rate",
        telemetryErrorPayload(error, {
          module: config.module,
          mode: config.mode,
          surface: config.surface,
          advanced_enabled: config.advanced_enabled,
          advanced_mode: config.advanced_mode,
          smart_extraction: config.smart_extraction,
          run_type_hint: inferRunTypeHint(config),
        }),
      );
      setConfigError(message);
    } finally {
      setIsSubmitting(false);
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
                  onChange={(value) => {
                    const parsed = parseRequestedCrawlTab(value);
                    if (parsed) {
                      setCrawlTab(parsed);
                    }
                  }}
                  options={[
                    { value: "category", label: "Category Crawl" },
                    { value: "pdp", label: "PDP Crawl" },
                  ]}
                />
                {crawlTab === "category" ? (
                  <TabBar
                    value={categoryMode}
                    compact
                    onChange={(value) => {
                      const parsed = parseRequestedCategoryMode(value);
                      if (parsed) {
                        setCategoryMode(parsed);
                      }
                    }}
                    options={[
                      { value: "single", label: "Single" },
                      { value: "sitemap", label: "Sitemap" },
                      { value: "bulk", label: "Bulk" },
                    ]}
                  />
                ) : (
                  <TabBar
                    value={pdpMode}
                    compact
                    onChange={(value) => {
                      const parsed = parseRequestedPdpMode(value);
                      if (parsed) {
                        setPdpMode(parsed);
                      }
                    }}
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
                disabled={!canPreview(config, fieldRows) || isSubmitting}
              >
                {isSubmitting ? "Starting..." : "Start Crawl"}
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
                  key="csv-file-input"
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
                  key="target-url-input"
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
                  <div className="space-y-2.5 px-1 py-1">
                    <div className="grid grid-cols-[auto_minmax(0,1fr)] items-center gap-3">
                      <div className="text-sm font-medium text-[var(--text-secondary)]">Mode</div>
                      <select
                        aria-label="Advanced crawl mode"
                        value={advancedMode}
                        onChange={(event) => {
                          const next = event.target.value;
                          if (ADVANCED_MODE_OPTIONS.has(next as AdvancedCrawlMode)) {
                            setAdvancedMode(next as AdvancedCrawlMode);
                          }
                        }}
                        className="control-select focus-ring h-9 w-full"
                      >
                        <option value="auto">Auto</option>
                        <option value="scroll">Scroll</option>
                        <option value="load_more">Load More</option>
                        <option value="view_all">View All</option>
                        <option value="paginate">Paginate</option>
                      </select>
                    </div>
                    <p className="text-xs text-muted">
                      Auto keeps backend auto-detection enabled. Explicit modes map directly to backend behavior, and View All maps to
                      Load More.
                    </p>
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
                  <div className="space-y-2 px-1 py-1">
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

function isSurfaceMismatch(module: CrawlConfig["module"], surface: CrawlSurface) {
  if (module === "category") {
    return !surface.endsWith("listing");
  }
  return !surface.endsWith("detail");
}

function resolveDispatchSurface(config: CrawlConfig) {
  return config.surface;
}

function inferRunTypeHint(config: CrawlConfig) {
  if (config.module === "category") {
    return config.mode === "bulk" ? "batch" : "crawl";
  }
  if (config.mode === "csv") {
    return "csv";
  }
  if (config.mode === "batch") {
    return "batch";
  }
  return "crawl";
}

function buildExtractionContract(fieldRows: FieldRow[]) {
  const extractionContract = fieldRows
    .map((row) => {
      const fieldName = normalizeField(row.fieldName);
      const xpath = row.xpath.trim();
      const regex = row.regex.trim();
      if (!fieldName || (!xpath && !regex)) {
        return null;
      }
      const reason = validateAdditionalFieldName(fieldName);
      if (reason) {
        throw new Error(`Invalid manual field "${row.fieldName || fieldName}": ${reason}`);
      }
      return {
        field_name: fieldName,
        xpath: xpath || undefined,
        regex: regex || undefined,
      };
    })
    .filter((row): row is { field_name: string; xpath?: string; regex?: string } => Boolean(row));
  return extractionContract;
}

export function buildDispatch(config: CrawlConfig, fieldRows: FieldRow[] = []): PendingDispatch {
  const additionalFields = uniqueFields(config.additional_fields);
  const invalidAdditionalField = additionalFields.find((field) => validateAdditionalFieldName(field));
  if (invalidAdditionalField) {
    const reason = validateAdditionalFieldName(invalidAdditionalField);
    throw new Error(`Invalid additional field "${invalidAdditionalField}": ${reason}`);
  }
  const resolvedAdvancedMode = config.advanced_enabled ? config.advanced_mode : null;
  const surface = resolveDispatchSurface(config);
  const commonSettings = {
    llm_enabled: config.smart_extraction,
    advanced_enabled: config.advanced_enabled,
    advanced_mode: resolvedAdvancedMode,
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
    extraction_contract: buildExtractionContract(fieldRows),
  };

  if (config.module === "category") {
    if (config.mode === "bulk") {
      const urls = parseLines(config.bulk_urls);
      if (!urls.length) throw new Error("Bulk crawl needs at least one URL.");
      return {
        runType: "batch",
        surface,
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
      surface,
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
      surface,
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
      surface,
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
    surface,
    url: config.target_url.trim(),
    settings: commonSettings,
    additionalFields,
    csvFile: null,
  };
}

function canPreview(config: CrawlConfig, fieldRows: FieldRow[]) {
  try {
    buildDispatch(config, fieldRows);
    return true;
  } catch {
    return false;
  }
}
