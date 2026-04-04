"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRightCircle,
  ChevronDown,
  ChevronsDown,
  CheckCircle2,
  CircleAlert,
  Copy,
  Download,
  GripVertical,
  Plus,
  RotateCcw,
  Shield,
  SlidersHorizontal,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import type { Route } from "next";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, memo, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode, RefObject } from "react";

import { PageHeader, SectionHeader } from "../../components/ui/patterns";
import { Badge, Button, Card, Input, Textarea } from "../../components/ui/primitives";
import { api } from "../../lib/api";
import type { CrawlConfig, CrawlMode, CrawlPhase, CrawlRecord, CrawlRun } from "../../lib/api/types";
import { CRAWL_DEFAULTS, CRAWL_LIMITS } from "../../lib/constants/crawl-defaults";
import { ACTIVE_STATUSES, TERMINAL_STATUSES } from "../../lib/constants/crawl-statuses";
import { STORAGE_KEYS } from "../../lib/constants/storage-keys";
import { POLLING_INTERVALS, UI_DELAYS } from "../../lib/constants/timing";
import { cn } from "../../lib/utils";

type CrawlTab = "category" | "pdp";
type CategoryMode = "single" | "sitemap" | "bulk";
type PdpMode = "single" | "batch" | "csv";
type ValidationState = "idle" | "valid" | "invalid";
type LogLevel = "INFO" | "WARN" | "ERROR" | "PROXY";
type FieldRow = {
  id: string;
  fieldName: string;
  xpath: string;
  regex: string;
  xpathState: ValidationState;
  regexState: ValidationState;
};
type PendingDispatch = {
  runType: "crawl" | "batch" | "csv";
  surface: string;
  url?: string;
  urls?: string[];
  settings: Record<string, unknown>;
  additionalFields: string[];
  csvFile: File | null;
};
type OutputTabKey = "table" | "json" | "intelligence" | "logs";
type SuggestionState = "pending" | "accepted" | "rejected" | "committed";
type IntelligenceSuggestion = {
  key: string;
  recordId: number;
  fieldName: string;
  value: string;
  source: string;
  currentValue: string;
  note: string;
  supportingSources: string[];
  state: SuggestionState;
};
type LlmCleanupStatus = {
  status: string;
  message?: string;
  count?: number;
};
type BulkPrefill = {
  urls: string[];
  additional_fields?: string[];
  module?: CrawlTab;
  mode?: CategoryMode | PdpMode;
  sourceRunId?: number;
  sourceUrl?: string;
};

const LOG_FILTERS: LogLevel[] = ["INFO", "WARN", "ERROR", "PROXY"];

export default function CrawlPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [crawlPhase, setCrawlPhase] = useState<CrawlPhase>("config");
  const [crawlTab, setCrawlTab] = useState<CrawlTab>("pdp");
  const [categoryMode, setCategoryMode] = useState<CategoryMode>("single");
  const [pdpMode, setPdpMode] = useState<PdpMode>("single");
  const [targetUrl, setTargetUrl] = useState("");
  const [bulkUrls, setBulkUrls] = useState("");
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [smartExtraction, setSmartExtraction] = useState(false);
  const [advancedEnabled, setAdvancedEnabled] = useState(false);
  const [requestDelay, setRequestDelay] = useState(String(CRAWL_DEFAULTS.REQUEST_DELAY_MS));
  const [maxRecords, setMaxRecords] = useState(String(CRAWL_DEFAULTS.MAX_RECORDS));
  const [maxPages, setMaxPages] = useState(String(CRAWL_DEFAULTS.MAX_PAGES));
  const [proxyEnabled, setProxyEnabled] = useState(false);
  const [proxyInput, setProxyInput] = useState("");
  const [additionalDraft, setAdditionalDraft] = useState("");
  const [additionalFields, setAdditionalFields] = useState<string[]>([]);
  const [fieldRows, setFieldRows] = useState<FieldRow[]>([]);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [pendingDispatch, setPendingDispatch] = useState<PendingDispatch | null>(null);
  const [configError, setConfigError] = useState("");
  const [launchError, setLaunchError] = useState("");
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [jsonCompact, setJsonCompact] = useState(false);
  const [outputTab, setOutputTab] = useState<OutputTabKey>("table");
  const [logSearch, setLogSearch] = useState("");
  const [logFilters, setLogFilters] = useState<Record<LogLevel, boolean>>({
    INFO: true,
    WARN: true,
    ERROR: true,
    PROXY: true,
  });
  const [liveJumpAvailable, setLiveJumpAvailable] = useState(false);
  const [bulkBanner, setBulkBanner] = useState("");
  const [runActionPending, setRunActionPending] = useState<"pause" | "resume" | "kill" | null>(null);
  const [suggestionState, setSuggestionState] = useState<Record<string, SuggestionState>>({});
  const [commitPending, setCommitPending] = useState(false);
  const [commitError, setCommitError] = useState("");
  const [savedOutputFields, setSavedOutputFields] = useState<string[]>([]);
  const [saveOutputFieldsPending, setSaveOutputFieldsPending] = useState(false);
  const [saveOutputFieldsMessage, setSaveOutputFieldsMessage] = useState("");
  const [saveOutputFieldsError, setSaveOutputFieldsError] = useState("");
  const logViewportRef = useRef<HTMLDivElement | null>(null);
  const runId = Number(searchParams.get("runId") || 0) || null;
  const legacyRunRedirect = runId !== null;
  const requestedModule = readRequestedModule(searchParams);
  const requestedMode = readRequestedMode(searchParams);
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!runId) {
      return;
    }
    router.replace((`/runs/${runId}`) as Route);
  }, [router, runId]);

  useEffect(() => {
    if (requestedModule) {
      setCrawlTab(requestedModule);
    }
    if (requestedMode && isCategoryMode(requestedMode)) {
      setCategoryMode(requestedMode);
    }
    if (requestedMode && isPdpMode(requestedMode)) {
      setPdpMode(requestedMode);
    }
  }, [requestedMode, requestedModule]);

  const runQuery = useQuery({
    queryKey: ["crawl-run", runId],
    queryFn: () => api.getCrawl(runId as number),
    enabled: runId !== null && !legacyRunRedirect,
    refetchInterval: (query) => (query.state.data && ACTIVE_STATUSES.has(query.state.data.status) ? POLLING_INTERVALS.ACTIVE_JOB_MS : false),
  });
  const run = runQuery.data;

  const recordsQuery = useQuery({
    queryKey: ["crawl-records", runId],
    queryFn: () => api.getRecords(runId as number, { limit: 1000 }),
    enabled: runId !== null && Boolean(run) && !legacyRunRedirect,
    refetchInterval: () => {
      const latestRun = queryClient.getQueryData<CrawlRun>(["crawl-run", runId]);
      return latestRun && ACTIVE_STATUSES.has(latestRun.status) ? POLLING_INTERVALS.RECORDS_MS : false;
    },
  });
  const logsQuery = useQuery({
    queryKey: ["crawl-logs", runId],
    queryFn: () => api.getCrawlLogs(runId as number),
    enabled: runId !== null && !legacyRunRedirect,
    refetchInterval: () => {
      const latestRun = queryClient.getQueryData<CrawlRun>(["crawl-run", runId]);
      return latestRun && ACTIVE_STATUSES.has(latestRun.status) ? POLLING_INTERVALS.LOGS_MS : false;
    },
  });
  const reviewQuery = useQuery({
    queryKey: ["crawl-review", runId],
    queryFn: () => api.getReview(runId as number),
    enabled: runId !== null && Boolean(run && TERMINAL_STATUSES.has(run.status)) && !legacyRunRedirect,
  });

  const records = useMemo(() => recordsQuery.data?.items ?? [], [recordsQuery.data?.items]);
  const logs = useMemo(() => logsQuery.data ?? [], [logsQuery.data]);
  const review = reviewQuery.data;
  const terminal = run ? TERMINAL_STATUSES.has(run.status) : false;
  const live = Boolean(run && ACTIVE_STATUSES.has(run.status));
  const llmCleanupStatus = useMemo<LlmCleanupStatus | null>(() => {
    for (const record of records) {
      const status = record.source_trace?.llm_cleanup_status;
      if (status && typeof status === "object" && !Array.isArray(status)) {
        return {
          status: String((status as Record<string, unknown>).status ?? ""),
          message: typeof (status as Record<string, unknown>).message === "string" ? String((status as Record<string, unknown>).message) : undefined,
          count: typeof (status as Record<string, unknown>).count === "number" ? Number((status as Record<string, unknown>).count) : undefined,
        };
      }
    }
    return null;
  }, [records]);

  useEffect(() => {
    if (runId === null) {
      setCrawlPhase("config");
      return;
    }
    setPreviewOpen(false);
    setPendingDispatch(null);
    setCrawlPhase("running");
  }, [runId]);

  useEffect(() => {
    if (!run) {
      return;
    }
    if (terminal) {
      const timer = window.setTimeout(() => setCrawlPhase("complete"), UI_DELAYS.PHASE_TRANSITION_MS);
      return () => window.clearTimeout(timer);
    }
    setCrawlPhase("running");
  }, [run, terminal]);

  useEffect(() => {
    const stored = window.sessionStorage.getItem(STORAGE_KEYS.BULK_PREFILL);
    if (!stored) {
      return;
    }
    try {
      const parsed = JSON.parse(stored) as BulkPrefill;
      if (Array.isArray(parsed.urls) && parsed.urls.length) {
        const requestedTab = parsed.module ?? "pdp";
        const mode = parsed.mode ?? "batch";
        setCrawlTab(requestedTab);
        if (requestedTab === "category" && isCategoryMode(mode)) {
          setCategoryMode(mode);
        }
        if (requestedTab === "pdp" && isPdpMode(mode)) {
          setPdpMode(mode);
        }
        setBulkUrls(parsed.urls.join("\n"));
        if (Array.isArray(parsed.additional_fields)) {
          setAdditionalFields(uniqueFields(parsed.additional_fields));
        }
        setBulkBanner(`${parsed.urls.length} URLs loaded from previous crawl results.`);
      }
    } catch {
      // Ignore malformed prefill data.
    } finally {
      window.sessionStorage.removeItem(STORAGE_KEYS.BULK_PREFILL);
    }
  }, []);

  useEffect(() => {
    if (!live || !logViewportRef.current) {
      return;
    }
    const frame = window.requestAnimationFrame(() => {
      const node = logViewportRef.current;
      if (!node) {
        return;
      }
      const { scrollHeight, scrollTop, clientHeight } = node;
      const atBottom = scrollHeight - scrollTop - clientHeight < CRAWL_DEFAULTS.SCROLL_THRESHOLD_PX;
      if (atBottom) {
        node.scrollTop = scrollHeight;
        setLiveJumpAvailable(false);
      } else {
        setLiveJumpAvailable(true);
      }
    });
    return () => window.cancelAnimationFrame(frame);
  }, [logs, live]);

  useEffect(() => {
    if (!bulkBanner) {
      return;
    }
    const timer = window.setTimeout(() => setBulkBanner(""), UI_DELAYS.BANNER_AUTO_HIDE_MS);
    return () => window.clearTimeout(timer);
  }, [bulkBanner]);

  useEffect(() => {
    if (review && !additionalFields.length) {
      setAdditionalFields(uniqueFields(review.canonical_fields.length ? review.canonical_fields : review.normalized_fields));
    }
  }, [additionalFields.length, review]);

  useEffect(() => {
    setSaveOutputFieldsMessage("");
    setSaveOutputFieldsError("");
    setSavedOutputFields([]);
  }, [runId]);

  const visibleColumns = useMemo(() => {
    const columns = new Set<string>();
    for (const record of records) {
      Object.keys(record.data ?? {}).forEach((key) => {
        if (!key.startsWith("_")) {
          columns.add(key);
        }
      });
    }
    return Array.from(columns);
  }, [records]);

  useEffect(() => {
    if (!review) {
      return;
    }
    const preferredFields = uniqueFields([
      ...Object.values(review.domain_mapping ?? {}).map((value) => String(value || "")),
      ...(review.normalized_fields ?? []),
      ...visibleColumns,
    ]);
    setSavedOutputFields((current) => (current.length ? current : preferredFields));
  }, [review, visibleColumns]);

  const intelligenceSuggestions = useMemo<IntelligenceSuggestion[]>(() => {
    return records.flatMap((record) => {
      const suggestions = record.source_trace?.llm_cleanup_suggestions;
      if (!suggestions || typeof suggestions !== "object") {
        return [];
      }
      return Object.entries(suggestions as Record<string, unknown>).flatMap(([fieldName, raw]) => {
        if (!raw || typeof raw !== "object") {
          return [];
        }
        const value = stringifyCell((raw as Record<string, unknown>).suggested_value).trim();
        if (!value) {
          return [];
        }
        const rawRecord = raw as Record<string, unknown>;
        const key = `${record.id}:${fieldName}`;
        const backendStatus = String(rawRecord.status ?? "pending_review");
        const note = stringifyCell(rawRecord.note).trim();
        const supportingSources = Array.isArray(rawRecord.supporting_sources)
          ? (rawRecord.supporting_sources as unknown[])
            .map((item) => String(item || "").trim())
            .filter(Boolean)
          : [];
        return [{
          key,
          recordId: record.id,
          fieldName,
          value,
          source: String(rawRecord.source ?? "llm"),
          currentValue: stringifyCell(record.data?.[fieldName]).trim(),
          note,
          supportingSources,
          state: suggestionState[key]
            ?? (backendStatus === "accepted" ? "committed" : "pending"),
        }];
      });
    });
  }, [records, suggestionState]);

  const config = useMemo<CrawlConfig>(
    () => ({
      module: crawlTab,
      mode: crawlTab === "category" ? categoryMode : pdpMode,
      target_url: targetUrl,
      bulk_urls: bulkUrls,
      csv_file: csvFile,
      smart_extraction: smartExtraction,
      advanced_enabled: advancedEnabled,
      request_delay_ms: clampNumber(
        requestDelay,
        CRAWL_LIMITS.MIN_REQUEST_DELAY_MS,
        CRAWL_LIMITS.MAX_REQUEST_DELAY_MS,
        CRAWL_DEFAULTS.REQUEST_DELAY_MS,
      ),
      max_records: clampNumber(maxRecords, CRAWL_LIMITS.MIN_RECORDS, CRAWL_LIMITS.MAX_RECORDS, CRAWL_DEFAULTS.MAX_RECORDS),
      max_pages: clampNumber(maxPages, CRAWL_LIMITS.MIN_PAGES, CRAWL_LIMITS.MAX_PAGES, CRAWL_DEFAULTS.MAX_PAGES),
      proxy_enabled: proxyEnabled,
      proxy_lines: proxyEnabled ? parseLines(proxyInput) : [],
      additional_fields: additionalFields,
    }),
    [additionalFields, advancedEnabled, bulkUrls, categoryMode, crawlTab, csvFile, maxPages, maxRecords, proxyEnabled, proxyInput, requestDelay, smartExtraction, targetUrl, pdpMode],
  );

  const selectedRecords = useMemo(
    () => records.filter((record) => selectedIds.includes(record.id)),
    [records, selectedIds],
  );

  const filteredLogs = useMemo(() => {
    const search = logSearch.trim().toLowerCase();
    return logs.filter((log) => {
      if (!logFilters[normalizeLogLevel(log.level)]) {
        return false;
      }
      return !search || `${log.level} ${log.message}`.toLowerCase().includes(search);
    });
  }, [logFilters, logSearch, logs]);

  const summary = {
    records: records.length,
    pages: Number(run?.result_summary?.processed_urls ?? run?.result_summary?.completed_urls ?? 0) || 0,
    fields: visibleColumns.length,
    duration: formatDuration(run?.created_at, run?.completed_at),
  };

  async function runControl(action: "pause" | "resume" | "kill") {
    if (!runId) {
      return;
    }
    setRunActionPending(action);
    setLaunchError("");
    try {
      if (action === "pause") {
        await api.pauseCrawl(runId);
      } else if (action === "resume") {
        await api.resumeCrawl(runId);
      } else {
        await api.killCrawl(runId);
      }
      await Promise.all([runQuery.refetch(), logsQuery.refetch(), recordsQuery.refetch()]);
    } catch (error) {
      setLaunchError(error instanceof Error ? error.message : `Unable to ${action} crawl.`);
    } finally {
      setRunActionPending(null);
    }
  }

  async function commitAcceptedSuggestions() {
    if (!runId) {
      return;
    }
    const acceptedItems = intelligenceSuggestions
      .filter((item) => item.state === "accepted")
      .map((item) => ({
        record_id: item.recordId,
        field_name: item.fieldName,
        value: item.value,
      }));
    if (!acceptedItems.length) {
      return;
    }
    setCommitPending(true);
    setCommitError("");
    try {
      await api.commitLlmSuggestions(runId, acceptedItems);
      setSuggestionState((current) => {
        const next = { ...current };
        for (const item of intelligenceSuggestions) {
          if (item.state === "accepted") {
            next[item.key] = "committed";
          }
        }
        return next;
      });
      await Promise.all([recordsQuery.refetch(), logsQuery.refetch()]);
    } catch (error) {
      setCommitError(error instanceof Error ? error.message : "Unable to commit accepted suggestions.");
    } finally {
      setCommitPending(false);
    }
  }

  async function saveDomainOutputFields() {
    if (!runId || !review) {
      return;
    }
    const selectedFields = uniqueFields(savedOutputFields);
    if (!selectedFields.length) {
      setSaveOutputFieldsError("Select at least one field to reuse for this domain.");
      setSaveOutputFieldsMessage("");
      return;
    }
    setSaveOutputFieldsPending(true);
    setSaveOutputFieldsError("");
    setSaveOutputFieldsMessage("");
    try {
      await api.saveReview(runId, {
        selections: selectedFields.map((field) => ({
          source_field: field,
          output_field: field,
          selected: true,
        })),
        extra_fields: [],
      });
      setSaveOutputFieldsMessage(`Saved ${selectedFields.length} field${selectedFields.length === 1 ? "" : "s"} for future ${normalizeDomainFromUrl(run?.url ?? "") || "domain"} crawls.`);
      await reviewQuery.refetch();
    } catch (error) {
      setSaveOutputFieldsError(error instanceof Error ? error.message : "Unable to save output fields.");
    } finally {
      setSaveOutputFieldsPending(false);
    }
  }

  function resetToConfig() {
    setCrawlPhase("config");
    setPreviewOpen(false);
    setPendingDispatch(null);
    setSelectedIds([]);
    router.replace("/crawl");
  }

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
      setCrawlPhase("running");
      router.replace((`/runs/${response.run_id}`) as Route);
    } catch (error) {
      setLaunchError(error instanceof Error ? error.message : "Unable to launch crawl.");
    }
  }

  if (legacyRunRedirect && runId) {
    return (
      <div className="space-y-4">
        <PageHeader title="Redirecting To Run" description={`Opening run #${runId}.`} />
        <Card className="px-4 py-6 text-sm text-muted">
          Loading the dedicated run details page.
        </Card>
      </div>
    );
  }

  function triggerBulkCrawlSelected() {
    const urls = selectedRecords
      .map((record) => extractRecordUrl(record))
      .filter((value): value is string => Boolean(value));
    if (!urls.length) {
      return;
    }
    window.sessionStorage.setItem(
      STORAGE_KEYS.BULK_PREFILL,
      JSON.stringify({
        urls,
        module: "pdp",
        mode: "batch",
        additional_fields: additionalFields,
      }),
    );
    setCrawlTab("pdp");
    setPdpMode("batch");
    setBulkUrls(urls.join("\n"));
    setBulkBanner(`${urls.length} URLs loaded from previous crawl results.`);
    setCrawlPhase("config");
    router.replace("/crawl?module=pdp&mode=batch");
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
      <PageHeader
        title="Crawlers"
        actions={
          <div className="flex flex-wrap items-center gap-2">
            {crawlPhase !== "config" ? (
              <Button variant="secondary" type="button" onClick={resetToConfig}>
                New Crawl
              </Button>
            ) : null}
            {crawlPhase === "complete" && crawlTab === "category" && selectedRecords.length ? (
              <Button variant="secondary" type="button" onClick={triggerBulkCrawlSelected}>
                <ArrowRightCircle className="size-3.5" />
                Bulk Crawl Selected
              </Button>
            ) : null}
          </div>
        }
      />

      {runId && !run ? (
        <Card className="space-y-3 p-4">
          <SectionHeader title="Opening Run" description="Loading the run workspace." />
          <div className="text-sm text-muted">Loading run #{runId}...</div>
        </Card>
      ) : null}

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

      {!runId && crawlPhase === "config" ? (
        <form className="grid gap-4 xl:grid-cols-[minmax(0,1.45fr)_360px]" onSubmit={startPreview}>
          <div className="space-y-4">
            <Card className="space-y-4">
              <SectionHeader
                title="Target URL"
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
                <TabBar
                  value={categoryMode}
                  onChange={(value) => setCategoryMode(value as CategoryMode)}
                  options={[
                    { value: "single", label: "Single Page" },
                    { value: "sitemap", label: "Sitemap" },
                    { value: "bulk", label: "Bulk" },
                  ]}
                />
              ) : (
                <TabBar
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
                    placeholder={crawlTab === "category" ? "https://example.com/collections/chairs" : "https://example.com/products/oak-chair"}
                    className="font-mono text-sm"
                    aria-label="Target URL input"
                  />
                </label>
              )}

              <AdditionalFieldInput
                value={additionalDraft}
                fields={additionalFields}
                onChange={setAdditionalDraft}
                onCommit={(value) =>
                  setAdditionalFields((current) => uniqueFields([...current, value]))
                }
                onRemove={(value) =>
                  setAdditionalFields((current) => current.filter((field) => field !== value))
                }
              />
            </Card>

            <Card className="space-y-4">
              <div className="flex items-center justify-between gap-4">
                <SectionHeader title="Field Configuration" />
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
                      onDelete={() =>
                        setFieldRows((current) => current.filter((entry) => entry.id !== row.id))
                      }
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
              <SectionHeader title="Run Settings" />
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
                    description="Enable LLM fallback when selectors miss."
                    icon={<Sparkles className="size-4" />}
                    checked={smartExtraction}
                    onChange={setSmartExtraction}
                  />
                  <SettingSection
                    label="Advanced Crawl"
                    description="Request delay, records, and page limits."
                    icon={<SlidersHorizontal className="size-4" />}
                    checked={advancedEnabled}
                    onChange={setAdvancedEnabled}
                  >
                    <div className="space-y-4 rounded-[var(--radius-lg)] border border-border bg-background px-4 py-4">
                      <SliderRow label="Request Delay" value={requestDelay} min={CRAWL_LIMITS.MIN_REQUEST_DELAY_MS} max={CRAWL_LIMITS.MAX_REQUEST_DELAY_MS} step={100} suffix=" ms" onChange={setRequestDelay} onReset={() => setRequestDelay(String(CRAWL_DEFAULTS.REQUEST_DELAY_MS))} />
                      <SliderRow label="Max Records" value={maxRecords} min={CRAWL_LIMITS.MIN_RECORDS} max={CRAWL_LIMITS.MAX_RECORDS} step={1} onChange={setMaxRecords} onReset={() => setMaxRecords(String(CRAWL_DEFAULTS.MAX_RECORDS))} />
                      <SliderRow label="Max Pages" value={maxPages} min={CRAWL_LIMITS.MIN_PAGES} max={CRAWL_LIMITS.MAX_PAGES} step={1} onChange={setMaxPages} onReset={() => setMaxPages(String(CRAWL_DEFAULTS.MAX_PAGES))} />
                    </div>
                  </SettingSection>
                  <SettingSection
                    label="Proxy"
                    description="Route requests through the proxy list."
                    icon={<Shield className="size-4" />}
                    checked={proxyEnabled}
                    onChange={setProxyEnabled}
                  >
                    <div className="space-y-3 rounded-[var(--radius-lg)] border border-border bg-background px-4 py-4">
                      <div className="label-caps">Proxy Pool</div>
                      <Textarea
                        value={proxyInput}
                        onChange={(event) => setProxyInput(event.target.value)}
                        placeholder={"host:port\nhost:port:user:pass"}
                        className="min-h-[140px] font-mono text-sm"
                        aria-label="Proxy pool input"
                      />
                    </div>
                  </SettingSection>
                </div>
              </div>
            </Card>
          </div>
        </form>
      ) : null}

      {crawlPhase === "running" ? (
        <div className="grid gap-4 xl:grid-cols-[minmax(320px,0.32fr)_minmax(0,0.68fr)]">
          <Card className="space-y-4">
            <SectionHeader title="Progress" description={run ? `Run ${run.id} is ${run.status.replace(/_/g, " ")}.` : "Loading run state..."} />
            <PreviewRow label="Run ID" value={run ? `#${run.id}` : "--"} mono inline />
            <PreviewRow label="Crawl Type" value={run?.run_type ?? "--"} inline />
            <PreviewRow label="Target" value={run?.url ?? "--"} mono inline />
            <PreviewRow label="Records" value={String(summary.records)} inline />
            <PreviewRow label="Pages" value={String(summary.pages)} inline />
            <PreviewRow label="Elapsed" value={summary.duration} inline />
            <ProgressBar percent={progressPercent(run)} />
            {run?.status === "paused" ? <div className="rounded-md border border-warning/30 bg-warning/10 px-3 py-2 text-sm text-foreground">Job paused. Output so far is preserved.</div> : null}
            {launchError ? <div className="rounded-md border border-danger/20 bg-danger/10 px-3 py-2 text-sm text-danger">{launchError}</div> : null}
            <div className="flex flex-wrap gap-2">
              <ActionButton
                label={runActionPending === "pause" ? "Pausing..." : "Pause"}
                onClick={() => void runControl("pause")}
                disabled={run?.status !== "running" || runActionPending !== null}
              />
              <ActionButton
                label={runActionPending === "resume" ? "Resuming..." : "Resume"}
                onClick={() => void runControl("resume")}
                disabled={run?.status !== "paused" || runActionPending !== null}
              />
              <ActionButton
                label={runActionPending === "kill" ? "Killing..." : "Hard Kill"}
                onClick={() => void runControl("kill")}
                disabled={!run || !ACTIVE_STATUSES.has(run.status) || runActionPending !== null}
                danger
              />
            </div>
          </Card>

          <Card className="space-y-4">
            <SectionHeader
              title="Live Log Stream"
              description="Auto-scrolls while you stay at the bottom. Logs fall back to polling every 2 seconds."
              action={
                <div className="flex items-center gap-2">
                  <Button variant="ghost" type="button" onClick={() => setLogSearch("")}>
                    Clear Display
                  </Button>
                  {liveJumpAvailable ? (
                    <button
                      type="button"
                      onClick={() => {
                        scrollViewportToBottom(logViewportRef);
                        setLiveJumpAvailable(false);
                      }}
                      className="inline-flex items-center gap-1 rounded-md border border-border bg-panel px-2.5 py-1.5 text-xs"
                    >
                      <ChevronsDown className="size-3.5" aria-hidden="true" />
                      Jump to Latest
                    </button>
                  ) : null}
                </div>
              }
            />
            <div className="flex flex-wrap items-center gap-2">
              {LOG_FILTERS.map((level) => (
                <button
                  key={level}
                  type="button"
                  onClick={() => setLogFilters((current) => ({ ...current, [level]: !current[level] }))}
                  className={cn(
                    "rounded-md border px-2.5 py-1 text-xs font-medium transition",
                    logFilters[level] ? "border-accent bg-accent-subtle" : "border-border bg-panel text-muted",
                  )}
                >
                  {level}
                </button>
              ))}
              <Input value={logSearch} onChange={(event) => setLogSearch(event.target.value)} placeholder="Search logs" className="h-8 max-w-56 text-xs" />
            </div>
            <LogTerminal logs={filteredLogs} live viewportRef={logViewportRef} />
          </Card>
        </div>
      ) : null}

      {crawlPhase === "complete" ? (
        <Card className="space-y-4">
          <SectionHeader
            title="Output Workspace"
            description={run ? `Run ${run.id} is complete.` : "Waiting for completed run data."}
            action={
              <div className="flex flex-wrap items-center gap-2">
                {crawlTab === "category" && selectedRecords.length ? (
                  <Button variant="secondary" type="button" onClick={triggerBulkCrawlSelected}>
                    <ArrowRightCircle className="size-3.5" />
                    Bulk Crawl ({selectedRecords.length})
                  </Button>
                ) : null}
                <a href={api.exportCsv(runId as number)} target="_blank" rel="noreferrer">
                  <Button variant="secondary" type="button">
                    <Download className="size-3.5" />
                    CSV
                  </Button>
                </a>
                <a href={api.exportJson(runId as number)} target="_blank" rel="noreferrer">
                  <Button variant="secondary" type="button">
                    <Download className="size-3.5" />
                    JSON
                  </Button>
                </a>
              </div>
            }
          />

          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
            <Metric label="Records" value={summary.records} />
            <Metric label="Duration" value={summary.duration} />
            <Metric label="Pages" value={summary.pages} />
            <Metric label="Fields" value={summary.fields} />
            <Metric label="Status" value={run?.status.replace(/_/g, " ") ?? "--"} />
          </div>

          <div className="space-y-4">
            <div className="flex items-center gap-0 border-b border-border">
              <OutputTab active={outputTab === "table"} onClick={() => setOutputTab("table")}>Table</OutputTab>
              <OutputTab active={outputTab === "json"} onClick={() => setOutputTab("json")}>JSON</OutputTab>
              <OutputTab active={outputTab === "intelligence"} onClick={() => setOutputTab("intelligence")}>Intelligence</OutputTab>
              <OutputTab active={outputTab === "logs"} onClick={() => setOutputTab("logs")}>Logs</OutputTab>
            </div>

            {outputTab === "table" ? (
              <div className="space-y-3">
                {records.length ? (
                  <div className="overflow-auto rounded-[10px] border border-border">
                    <table className="compact-data-table min-w-[960px]">
                      <thead>
                        <tr>
                          <th className="w-10">
                            <input
                              type="checkbox"
                              checked={selectedIds.length === records.length && records.length > 0}
                              onChange={(event) => setSelectedIds(event.target.checked ? records.map((record) => record.id) : [])}
                            />
                          </th>
                          {visibleColumns.map((column) => (
                            <th key={column}>{column}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {records.map((record) => (
                          <tr key={record.id}>
                            <td>
                              <input
                                type="checkbox"
                                checked={selectedIds.includes(record.id)}
                                onChange={(event) =>
                                  setSelectedIds((current) =>
                                    event.target.checked ? uniqueNumbers([...current, record.id]) : current.filter((value) => value !== record.id),
                                  )
                                }
                              />
                            </td>
                            {visibleColumns.map((column) => (
                              <td key={column} title={stringifyCell(readRecordValue(record, column))}>
                                <span className="block max-w-[260px] truncate">{stringifyCell(readRecordValue(record, column)) || <span className="text-muted/50">--</span>}</span>
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <div className="grid min-h-40 place-items-center rounded-[10px] border border-dashed border-border bg-panel/60 text-sm text-muted">No records captured yet.</div>
                )}
                <div className="flex flex-wrap items-center gap-2">
                  <Button variant="secondary" type="button" disabled={!selectedRecords.length} onClick={triggerBulkCrawlSelected}>
                    <ArrowRightCircle className="size-3.5" />
                    Bulk Crawl Selected
                  </Button>
                  <Badge tone="neutral">{selectedRecords.length} selected</Badge>
                </div>
              </div>
            ) : null}

            {outputTab === "json" ? (
              <Card className="space-y-3 p-4">
                <div className="label-caps">JSON</div>
                <div className="flex items-center justify-between">
                  <div className="text-sm text-muted">Pretty-printed by default.</div>
                  <div className="flex items-center gap-2">
                    <Button
                      variant="ghost"
                      type="button"
                      onClick={() => {
                        copyJson(records).catch(() => {});
                      }}
                    >
                      <Copy className="size-3.5" />
                      Copy
                    </Button>
                    <Button variant="secondary" type="button" onClick={() => setJsonCompact((value) => !value)}>
                      {jsonCompact ? "Pretty" : "Compact"}
                    </Button>
                  </div>
                </div>
                <pre className="crawl-terminal max-h-[480px] overflow-auto text-[12px]">
                  {jsonCompact ? JSON.stringify(records.map(cleanRecord)) : JSON.stringify(records.map(cleanRecord), null, 2)}
                </pre>
              </Card>
            ) : null}

            {outputTab === "intelligence" ? (
              <Card className="space-y-4 p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="label-caps">LLM Cleanup</div>
                    <div className="text-sm text-muted">Accepted suggestions are only committed after explicit confirmation.</div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Button
                      variant="secondary"
                      type="button"
                      onClick={() => setSuggestionState((current) => Object.fromEntries(intelligenceSuggestions.map((item) => [item.key, item.state === "committed" ? "committed" : "accepted"])) as Record<string, SuggestionState>)}
                      disabled={!intelligenceSuggestions.length}
                    >
                      Accept All
                    </Button>
                    <Button
                      variant="ghost"
                      type="button"
                      onClick={() => setSuggestionState((current) => Object.fromEntries(intelligenceSuggestions.map((item) => [item.key, item.state === "committed" ? "committed" : "rejected"])) as Record<string, SuggestionState>)}
                      disabled={!intelligenceSuggestions.length}
                    >
                      Reject All
                    </Button>
                  </div>
                </div>
                {commitError ? <div className="rounded-md border border-danger/20 bg-danger/10 px-3 py-2 text-sm text-danger">{commitError}</div> : null}
                {intelligenceSuggestions.length ? (
                  <div className="space-y-2">
                    {intelligenceSuggestions.map((item) => (
                      <div key={item.key} className="grid gap-3 rounded-md border border-border bg-background p-3 xl:grid-cols-[minmax(0,0.7fr)_minmax(0,1fr)_auto]">
                        <div className="space-y-1">
                          <div className="text-sm font-medium text-foreground">{item.fieldName}</div>
                          <div className="text-xs text-muted">Record #{item.recordId} · {item.source}</div>
                          {item.supportingSources.length ? (
                            <div className="text-xs text-muted">Evidence: {item.supportingSources.join(", ")}</div>
                          ) : null}
                        </div>
                        <div className="space-y-1">
                          {item.currentValue ? (
                            <div className="text-xs text-muted">Current: <span className="font-mono">{item.currentValue}</span></div>
                          ) : null}
                          <div className="font-mono text-sm text-foreground">{item.value}</div>
                          {item.note ? <div className="text-xs text-muted">{item.note}</div> : null}
                        </div>
                        <div className="flex items-center gap-2">
                          <Button variant="secondary" type="button" onClick={() => setSuggestionState((current) => ({ ...current, [item.key]: "accepted" }))} disabled={item.state === "committed"}>
                            Accept
                          </Button>
                          <Button variant="ghost" type="button" onClick={() => setSuggestionState((current) => ({ ...current, [item.key]: "rejected" }))} disabled={item.state === "committed"}>
                            Reject
                          </Button>
                          <Badge tone={suggestionBadgeTone(item.state)}>
                            {item.state}
                          </Badge>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : review ? (
                  <div className="space-y-2 text-sm text-muted">
                    <div>{review.normalized_fields.length} normalized fields</div>
                    <div>{review.discovered_fields.length} discovered fields</div>
                    <div>{Object.keys(review.selector_suggestions ?? {}).length} selector groups</div>
                    <div className="rounded-md border border-border bg-background p-3 text-foreground">
                      {formatLlmCleanupStatus(llmCleanupStatus)}
                    </div>
                  </div>
                ) : (
                  <div className="text-sm text-muted">No intelligence payload available for this run.</div>
                )}
                <div className="flex justify-end">
                  <Button
                    variant="accent"
                    type="button"
                    onClick={() => void commitAcceptedSuggestions()}
                    disabled={!intelligenceSuggestions.some((item) => item.state === "accepted") || commitPending}
                  >
                    {commitPending ? "Committing..." : "Commit Accepted Fields"}
                  </Button>
                </div>
                {review ? (
                  <div className="space-y-3 rounded-md border border-border bg-background p-4">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <div className="label-caps">Domain Output Fields</div>
                        <div className="text-sm text-muted">
                          Choose which fields should stay in the saved output schema for this domain. Future crawls for the same domain will request them automatically.
                        </div>
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        <Button
                          variant="secondary"
                          type="button"
                          onClick={() => setSavedOutputFields(uniqueFields(visibleColumns))}
                          disabled={!visibleColumns.length}
                        >
                          Use Current Output
                        </Button>
                        <Button
                          variant="ghost"
                          type="button"
                          onClick={() => setSavedOutputFields([])}
                          disabled={!savedOutputFields.length}
                        >
                          Clear
                        </Button>
                      </div>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {uniqueFields([
                        ...(review.discovered_fields ?? []),
                        ...(review.normalized_fields ?? []),
                        ...visibleColumns,
                      ]).map((field) => {
                        const selected = savedOutputFields.includes(field);
                        return (
                          <button
                            key={field}
                            type="button"
                            onClick={() =>
                              setSavedOutputFields((current) =>
                                current.includes(field)
                                  ? current.filter((value) => value !== field)
                                  : uniqueFields([...current, field]),
                              )
                            }
                            className={cn(
                              "rounded-md border px-2.5 py-1.5 text-xs font-medium transition",
                              selected
                                ? "border-accent bg-accent-subtle text-foreground"
                                : "border-border bg-panel text-muted",
                            )}
                          >
                            {field}
                          </button>
                        );
                      })}
                    </div>
                    {saveOutputFieldsError ? <div className="rounded-md border border-danger/20 bg-danger/10 px-3 py-2 text-sm text-danger">{saveOutputFieldsError}</div> : null}
                    {saveOutputFieldsMessage ? <div className="rounded-md border border-success/20 bg-success/10 px-3 py-2 text-sm text-success">{saveOutputFieldsMessage}</div> : null}
                    <div className="flex items-center justify-between gap-3">
                      <div className="text-sm text-muted">{savedOutputFields.length} field{savedOutputFields.length === 1 ? "" : "s"} selected</div>
                      <Button
                        variant="accent"
                        type="button"
                        onClick={() => void saveDomainOutputFields()}
                        disabled={saveOutputFieldsPending || !savedOutputFields.length}
                      >
                        {saveOutputFieldsPending ? "Saving..." : "Save Domain Output Fields"}
                      </Button>
                    </div>
                  </div>
                ) : null}
              </Card>
            ) : null}

            {outputTab === "logs" ? (
              <Card className="space-y-3 p-4">
                <div className="flex items-center justify-between">
                  <div className="label-caps">Logs</div>
                  <Input value={logSearch} onChange={(event) => setLogSearch(event.target.value)} placeholder="Search" className="h-8 max-w-40 text-xs" />
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  {LOG_FILTERS.map((level) => (
                    <button
                      key={level}
                      type="button"
                      onClick={() => setLogFilters((current) => ({ ...current, [level]: !current[level] }))}
                      className={cn("rounded-md border px-2.5 py-1 text-xs font-medium transition", logFilters[level] ? "border-accent bg-accent-subtle" : "border-border bg-panel text-muted")}
                    >
                      {level}
                    </button>
                  ))}
                </div>
                <LogTerminal logs={filteredLogs} viewportRef={logViewportRef} />
              </Card>
            ) : null}
          </div>
        </Card>
      ) : null}

      {previewOpen && pendingDispatch ? (
        <PreviewModal dispatch={pendingDispatch} onCancel={() => { setPreviewOpen(false); setPendingDispatch(null); }} onLaunch={() => void launchPending()} launchError={launchError} />
      ) : null}
    </div>
  );
}

function buildDispatch(config: CrawlConfig): PendingDispatch {
  const additionalFields = uniqueFields(config.additional_fields);
  const commonSettings = {
    llm_enabled: config.smart_extraction,
    advanced_enabled: config.advanced_enabled,
    sleep_ms: config.request_delay_ms,
    max_records: config.max_records,
    max_pages: config.max_pages,
    proxy_enabled: config.proxy_enabled,
    proxy_list: config.proxy_enabled ? config.proxy_lines : [],
    additional_fields: additionalFields,
    crawl_module: config.module,
    crawl_mode: config.mode,
  };
  if (config.module === "category") {
    if (config.mode === "bulk") {
      const urls = parseLines(config.bulk_urls);
      if (!urls.length) throw new Error("Bulk crawl needs at least one URL.");
      return { runType: "batch", surface: "ecommerce_listing", url: urls[0], urls, settings: { ...commonSettings, urls }, additionalFields, csvFile: null };
    }
    if (!config.target_url.trim()) throw new Error("Enter a target URL.");
    return { runType: "crawl", surface: "ecommerce_listing", url: config.target_url.trim(), settings: commonSettings, additionalFields, csvFile: null };
  }
  if (config.mode === "csv") {
    if (!config.csv_file) throw new Error("Select a CSV file.");
    return { runType: "csv", surface: "ecommerce_detail", url: config.target_url.trim(), settings: commonSettings, additionalFields, csvFile: config.csv_file };
  }
  if (config.mode === "batch") {
    const urls = parseLines(config.bulk_urls);
    if (!urls.length) throw new Error("Batch crawl needs at least one URL.");
    return { runType: "batch", surface: "ecommerce_detail", url: urls[0], urls, settings: { ...commonSettings, urls }, additionalFields, csvFile: null };
  }
  if (!config.target_url.trim()) throw new Error("Enter a target URL.");
  return { runType: "crawl", surface: "ecommerce_detail", url: config.target_url.trim(), settings: commonSettings, additionalFields, csvFile: null };
}

function canPreview(config: CrawlConfig) {
  try {
    buildDispatch(config);
    return true;
  } catch {
    return false;
  }
}

function uniqueFields(values: string[]) {
  return Array.from(new Set(values.map(normalizeField).filter(Boolean)));
}

function uniqueNumbers(values: number[]) {
  return Array.from(new Set(values));
}

function normalizeField(value: string) {
  return value.trim().toLowerCase().replace(/\s+/g, "_");
}

function parseLines(value: string) {
  return value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

function clampNumber(value: string, min: number, max: number, fallback: number) {
  const parsed = Number.parseInt(value, 10);
  if (Number.isNaN(parsed)) return fallback;
  return Math.min(max, Math.max(min, parsed));
}

function extractRecordUrl(record: CrawlRecord) {
  return stringifyCell(record.data?.url ?? record.raw_data?.url ?? record.source_url).trim();
}

function stringifyCell(value: unknown) {
  if (value == null) return "";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

function readRecordValue(record: CrawlRecord, field: string) {
  const data = record.data && typeof record.data === "object" ? record.data : {};
  const raw = record.raw_data && typeof record.raw_data === "object" ? record.raw_data : {};
  if (field in data) return data[field];
  if (field in raw) return raw[field];
  if (field === "source_url") return record.source_url;
  return "";
}

function formatDuration(start?: string | null, end?: string | null) {
  if (!start) return "--";
  const started = new Date(start).getTime();
  const finished = end ? new Date(end).getTime() : Date.now();
  if (!Number.isFinite(started) || !Number.isFinite(finished)) return "--";
  const seconds = Math.max(0, Math.floor((finished - started) / 1000));
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

function progressPercent(run: CrawlRun | undefined) {
  const value = typeof run?.result_summary?.progress === "number" ? run.result_summary.progress : 0;
  return Math.min(100, Math.max(0, value));
}

function ProgressBar({ percent }: Readonly<{ percent: number }>) {
  return (
    <div className="space-y-1">
      <div className="h-1.5 rounded-full bg-border">
        <div className={cn("h-1.5 rounded-full bg-accent transition-all", percent > 90 && "bg-danger")} style={{ width: `${percent}%` }} />
      </div>
      <div className="text-xs text-muted">{percent}% complete</div>
    </div>
  );
}

function validateXPath(value: string): ValidationState {
  if (!value.trim()) return "idle";
  try {
    document.evaluate(value, document, null, XPathResult.ANY_TYPE, null);
    return "valid";
  } catch {
    return "invalid";
  }
}

function validateRegex(value: string): ValidationState {
  if (!value.trim()) return "idle";
  try {
    new RegExp(value);
    return "valid";
  } catch {
    return "invalid";
  }
}

function copyJson(records: CrawlRecord[]) {
  return navigator.clipboard.writeText(JSON.stringify(records.map(cleanRecord), null, 2));
}

function cleanRecord(record: CrawlRecord) {
  return Object.fromEntries(
    Object.entries(record.data ?? {}).filter(([key, value]) => !key.startsWith("_") && value !== null && value !== "" && !(Array.isArray(value) && value.length === 0)),
  );
}

function logTone(level: string) {
  const normalized = normalizeLogLevel(level);
  if (normalized === "WARN") return "text-warning";
  if (normalized === "ERROR") return "text-danger";
  if (normalized === "PROXY") return "text-accent";
  return "text-muted";
}

function normalizeLogLevel(level: string) {
  return String(level || "").trim().toUpperCase() as LogLevel;
}

function useLogViewport(_logsLength: number, ref?: RefObject<HTMLDivElement | null>) {
  const internalRef = useRef<HTMLDivElement | null>(null);
  return ref ?? internalRef;
}

function scrollViewportToBottom(ref: RefObject<HTMLDivElement | null>) {
  window.requestAnimationFrame(() => {
    const node = ref.current;
    if (!node) {
      return;
    }
    node.scrollTop = node.scrollHeight;
  });
}

function PreviewModal({
  dispatch,
  onCancel,
  onLaunch,
  launchError,
}: Readonly<{
  dispatch: PendingDispatch;
  onCancel: () => void;
  onLaunch: () => void;
  launchError: string;
}>) {
  const modalRef = useRef<HTMLDialogElement | null>(null);
  const previouslyFocusedRef = useRef<HTMLElement | null>(null);
  const cancelCallbackRef = useRef(onCancel);
  const urls = dispatch.urls ?? (dispatch.url ? [dispatch.url] : []);
  const proxyCount = Array.isArray(dispatch.settings.proxy_list) ? dispatch.settings.proxy_list.length : 0;
  const smartExtraction = Boolean(dispatch.settings.llm_enabled);
  const proxyEnabled = Boolean(dispatch.settings.proxy_enabled);

  useEffect(() => {
    cancelCallbackRef.current = onCancel;
  }, [onCancel]);

  useEffect(() => {
    previouslyFocusedRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    getFocusableElements(modalRef.current)[0]?.focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        cancelCallbackRef.current();
        return;
      }
      if (event.key !== "Tab") {
        return;
      }
      const focusable = getFocusableElements(modalRef.current);
      if (!focusable.length) {
        event.preventDefault();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const activeElement = document.activeElement;
      if (event.shiftKey && activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      previouslyFocusedRef.current?.focus();
    };
  }, []);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
      <dialog
        open
        ref={modalRef}
        aria-labelledby="crawl-preview-title"
        aria-describedby="crawl-preview-description"
        aria-modal="true"
        className="m-0 mx-auto w-full max-w-[560px] rounded-[var(--radius-xl)] border border-border bg-background-elevated p-6 shadow-[var(--shadow-modal)]"
      >
        <div className="relative">
          <div className="max-w-[420px]">
            <div id="crawl-preview-title" className="text-base font-semibold tracking-[-0.02em]">Review Before Running</div>
            <div id="crawl-preview-description" className="mt-1 text-sm text-muted">Confirm the payload before the job is dispatched.</div>
          </div>
          <button type="button" onClick={onCancel} aria-label="Close preview" className="absolute right-0 top-0 inline-flex size-8 items-center justify-center rounded-md border border-border text-muted transition hover:text-foreground">
            <X className="size-4" aria-hidden="true" />
          </button>
        </div>
        <div className="mt-5 grid gap-2 sm:grid-cols-2">
          <PreviewRow label="Target URL" value={dispatch.url ?? urls[0] ?? "--"} mono />
          <PreviewRow label="Mode" value={dispatch.runType} />
          <PreviewRow label="Proxy" value={proxyEnabled ? `${proxyCount} configured` : "Inactive"} />
          <PreviewRow label="Smart Extraction" value={smartExtraction ? "On" : "Off"} />
          <PreviewRow label="Max Records" value={String(dispatch.settings.max_records)} />
          <PreviewRow label="Max Pages" value={String(dispatch.settings.max_pages)} />
        </div>
        <div className="mt-5">
          <div className="label-caps mb-2">Additional Fields</div>
          <div className="flex flex-wrap gap-1.5">
            {dispatch.additionalFields.length ? dispatch.additionalFields.map((field) => <Badge key={field} tone="neutral">{field}</Badge>) : <span className="text-sm text-muted">None</span>}
          </div>
        </div>
        {launchError ? <div className="mt-4 rounded-md border border-danger/20 bg-danger/10 px-3 py-2 text-sm text-danger">{launchError}</div> : null}
        <div className="mt-6 flex justify-end gap-2">
          <Button variant="ghost" type="button" onClick={onCancel}>
            Cancel
          </Button>
          <Button variant="accent" type="button" onClick={onLaunch}>
            Launch Job
          </Button>
        </div>
      </dialog>
    </div>
  );
}

const LogTerminal = memo(function LogTerminal({
  logs,
  live = false,
  viewportRef,
}: Readonly<{
  logs: Array<{ id: number; level: string; message: string; created_at: string }>;
  live?: boolean;
  viewportRef?: RefObject<HTMLDivElement | null>;
}>) {
  const ref = useLogViewport(logs.length, viewportRef);
  return (
    <div ref={ref} className="crawl-terminal max-h-[320px] min-h-[260px] space-y-1.5" role="log" aria-live={live ? "polite" : "off"} aria-atomic="false">
      {logs.length ? logs.map((log) => (
        <div key={log.id} className="font-mono text-[12px] leading-6">
          <span className="text-muted">[{formatTimestamp(log.created_at)}]</span>{" "}
          <span className={logTone(log.level)}>[{normalizeLogLevel(log.level)}]</span>{" "}
          <span>{log.message}</span>
        </div>
      )) : <div className="text-sm text-muted">{live ? "Waiting for log output..." : "No logs captured for this run."}</div>}
    </div>
  );
});

function TabBar({
  value,
  onChange,
  options,
}: Readonly<{
  value: string;
  onChange: (value: string) => void;
  options: Array<{ value: string; label: string }>;
}>) {
  return (
    <div className="inline-flex h-[30px] items-center rounded-[var(--radius-md)] border border-border bg-panel p-0.5">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          onClick={() => onChange(option.value)}
          className={cn(
            "rounded-[4px] px-3 py-1 text-sm font-medium transition-colors",
            value === option.value
              ? "bg-accent text-white shadow-[var(--shadow-sm)]"
              : "text-muted hover:text-foreground",
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

function SettingSection({
  label,
  description,
  icon,
  checked,
  onChange,
  children,
}: Readonly<{ label: string; description: string; icon: ReactNode; checked: boolean; onChange: (value: boolean) => void; children?: ReactNode }>) {
  return (
    <div className="overflow-hidden rounded-[var(--radius-lg)] border border-border bg-panel">
      <div className="flex min-h-[76px] items-center justify-between gap-4 px-4 py-3.5">
        <div className="flex min-w-0 items-start gap-3">
          <div className={cn("mt-0.5 shrink-0 transition-colors", checked ? "text-foreground" : "text-muted")}>
            {icon}
          </div>
          <div className="min-w-0">
            <div className="label-caps">{label}</div>
            <div className="text-sm text-muted">{description}</div>
          </div>
        </div>
        <Toggle checked={checked} onChange={onChange} ariaLabel={label} />
      </div>
      {children ? (
        <div
          className={cn(
            "overflow-hidden transition-[max-height] duration-200 ease-out",
            checked ? "max-h-[480px]" : "max-h-0",
          )}
        >
          <div className="border-t border-border p-4">
            {children}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function Toggle({
  checked,
  onChange,
  ariaLabel,
}: Readonly<{ checked: boolean; onChange: (value: boolean) => void; ariaLabel?: string }>) {
  return (
    <button
      type="button"
      aria-label={ariaLabel}
      aria-pressed={checked}
      onClick={() => onChange(!checked)}
      className={cn("relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors", checked ? "bg-accent" : "bg-border")}
    >
      <span className={cn("inline-block size-4 rounded-full bg-white shadow-sm transition-transform", checked ? "translate-x-4" : "translate-x-0.5")} />
    </button>
  );
}

function SliderRow({
  label,
  value,
  min,
  max,
  step,
  onChange,
  onReset,
  suffix,
}: Readonly<{ label: string; value: string; min: number; max: number; step: number; onChange: (value: string) => void; onReset: () => void; suffix?: string }>) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between gap-3">
        <div className="text-sm">{label}</div>
        <button type="button" onClick={onReset} className="inline-flex items-center gap-1 text-xs text-muted hover:text-foreground"><RotateCcw className="size-3.5" />Reset</button>
      </div>
      <div className="flex items-center gap-3">
        <input type="range" min={min} max={max} step={step} value={clampNumber(value, min, max, min)} onChange={(event) => onChange(event.target.value)} className="h-1.5 w-full rounded-full bg-border" />
        <Input value={suffix ? `${value}${suffix}` : value} onChange={(event) => onChange(event.target.value.replace(/[^\d]/g, ""))} onBlur={() => onChange(String(clampNumber(value, min, max, min)))} className="h-8 w-24 text-right font-mono text-xs" />
      </div>
    </div>
  );
}

function AdditionalFieldInput({
  value,
  fields,
  onChange,
  onCommit,
  onRemove,
}: Readonly<{ value: string; fields: string[]; onChange: (value: string) => void; onCommit: (value: string) => void; onRemove: (value: string) => void }>) {
  const chips = uniqueFields([...fields, ...parseLines(value.replace(/,/g, "\n"))]);
  function handleChange(next: string) {
    const parts = next.split(",");
    parts
      .slice(0, -1)
      .map((part) => normalizeField(part))
      .filter(Boolean)
      .forEach(onCommit);
    onChange(parts.at(-1) ?? "");
  }
  function handleBlur() {
    parseLines(value).map(normalizeField).filter(Boolean).forEach(onCommit);
    onChange("");
  }
  return (
    <label className="grid gap-1.5">
      <span className="label-caps">Additional Fields</span>
      <Input value={value} onChange={(event) => handleChange(event.target.value)} onBlur={handleBlur} placeholder="price, sku, availability, brand" className="font-mono text-sm" />
      {chips.length ? (
        <div className="flex flex-wrap gap-1.5">
          {chips.map((field) => <button key={field} type="button" onClick={() => onRemove(field)} aria-label={`Remove ${field}`} className="inline-flex items-center gap-1 rounded-md border border-border bg-panel px-2 py-1 text-xs"><span>{field}</span><X className="size-3.5" aria-hidden="true" /></button>)}
        </div>
      ) : null}
    </label>
  );
}

function ManualFieldEditor({ row, onChange, onDelete }: Readonly<{ row: FieldRow; onChange: (patch: Partial<FieldRow>) => void; onDelete: () => void }>) {
  return (
    <div className="grid gap-2 rounded-md border border-border bg-background p-3 xl:grid-cols-[24px_minmax(160px,0.8fr)_minmax(240px,1fr)_minmax(200px,1fr)_auto]">
      <div className="flex items-center justify-center text-muted"><GripVertical className="size-4" /></div>
      <label className="grid gap-1">
        <span className="label-caps">Field</span>
        <Input value={row.fieldName} onChange={(event) => onChange({ fieldName: event.target.value })} placeholder="price" className="font-mono text-sm" />
      </label>
      <ValidatedField label="XPath" value={row.xpath} state={row.xpathState} placeholder="//span[@class='price']" onChange={(value) => onChange({ xpath: value })} onBlur={(value) => onChange({ xpathState: validateXPath(value) })} />
      <ValidatedField label="Regex" value={row.regex} state={row.regexState} placeholder="\\$[\\d,.]+" onChange={(value) => onChange({ regex: value })} onBlur={(value) => onChange({ regexState: validateRegex(value) })} />
      <div className="flex items-end justify-end"><button type="button" onClick={onDelete} aria-label={`Delete ${row.fieldName || "manual field"}`} className="inline-flex size-8 items-center justify-center rounded-[var(--radius-md)] border border-border text-danger hover:bg-danger/10"><Trash2 className="size-3.5" aria-hidden="true" /></button></div>
    </div>
  );
}

function getFocusableElements(container: HTMLElement | null) {
  if (!container) {
    return [] as HTMLElement[];
  }
  return Array.from(
    container.querySelectorAll<HTMLElement>(
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ),
  ).filter((element) => !element.hasAttribute("hidden") && element.getAttribute("aria-hidden") !== "true");
}

function ValidatedField({
  label,
  value,
  state,
  placeholder,
  onChange,
  onBlur,
}: Readonly<{ label: string; value: string; state: ValidationState; placeholder: string; onChange: (value: string) => void; onBlur: (value: string) => void }>) {
  return (
    <label className="grid gap-1">
      <span className="label-caps">{label}</span>
      <div className="relative">
        <Input value={value} onChange={(event) => onChange(event.target.value)} onBlur={(event) => onBlur(event.target.value)} placeholder={placeholder} className="pr-10 font-mono text-sm" />
        <div className="pointer-events-none absolute inset-y-0 right-3 flex items-center">
          {validationStateIcon(state)}
        </div>
      </div>
    </label>
  );
}

function suggestionBadgeTone(state: SuggestionState) {
  if (state === "committed" || state === "accepted") return "success" as const;
  if (state === "rejected") return "danger" as const;
  return "neutral" as const;
}

function validationStateIcon(state: ValidationState) {
  if (state === "valid") return <CheckCircle2 className="size-4 text-success" />;
  if (state === "invalid") return <CircleAlert className="size-4 text-danger" />;
  return null;
}

function ActionButton({
  label,
  danger,
  disabled,
  onClick,
}: Readonly<{ label: string; danger?: boolean; disabled?: boolean; onClick?: () => void }>) {
  return (
    <Button
      type="button"
      variant={danger ? "danger" : "secondary"}
      disabled={disabled}
      onClick={onClick}
      className="h-8 px-3 text-xs"
    >
      {label}
    </Button>
  );
}

function OutputTab({
  active = false,
  children,
  onClick,
}: Readonly<{ active?: boolean; children: ReactNode; onClick: () => void }>) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn("relative px-4 py-2 text-sm font-medium", active ? "text-foreground after:absolute after:inset-x-0 after:bottom-0 after:h-0.5 after:bg-accent" : "text-muted")}
    >
      {children}
    </button>
  );
}

function Metric({ label, value }: Readonly<{ label: string; value: string | number }>) {
  return <div className="rounded-[var(--radius-lg)] border border-border bg-panel p-4 shadow-[var(--shadow-sm)]"><div className="label-caps">{label}</div><div className="mt-1 text-[24px] font-bold tracking-[var(--tracking-tight)]">{value}</div></div>;
}

function PreviewRow({
  label,
  value,
  mono,
  inline = false,
}: Readonly<{ label: string; value: string; mono?: boolean; inline?: boolean }>) {
  return (
    <div className={cn("rounded-[var(--radius-md)] border border-border bg-panel px-3 py-3", inline && "flex items-start justify-between gap-4")}>
      <div className="label-caps shrink-0">{label}</div>
      <div className={cn("text-left text-sm text-foreground", !inline && "mt-1", inline && "min-w-0 text-right", mono && "break-all font-mono text-xs")}>{value || "--"}</div>
    </div>
  );
}

function formatLlmCleanupStatus(status: LlmCleanupStatus | null) {
  if (!status) {
    return "No pending LLM cleanup suggestions were stored for this run.";
  }
  if (status.message) {
    return status.message;
  }
  if (status.status === "ready" && typeof status.count === "number") {
    return `LLM cleanup generated ${status.count} suggestion${status.count === 1 ? "" : "s"}.`;
  }
  if (status.status === "empty") {
    return "LLM cleanup review ran but returned no suggestions.";
  }
  if (status.status === "skipped") {
    return status.message || "LLM cleanup was skipped because deterministic extraction already resolved the available fields.";
  }
  if (status.status === "no_evidence") {
    return "No candidate evidence was available for cleanup review.";
  }
  if (status.status === "error") {
    return "LLM cleanup review failed.";
  }
  if (status.status === "xpath_error") {
    return "LLM XPath discovery failed before cleanup review.";
  }
  return "No pending LLM cleanup suggestions were stored for this run.";
}

function formatTimestamp(value: string) {
  try {
    return new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return value;
  }
}

function readRequestedModule(searchParams: ReturnType<typeof useSearchParams>): CrawlTab | null {
  const moduleParam = searchParams.get("module");
  if (moduleParam === "category" || moduleParam === "pdp") {
    return moduleParam;
  }
  const legacyTab = searchParams.get("tab");
  if (legacyTab === "category" || legacyTab === "pdp") {
    return legacyTab;
  }
  if (legacyTab === "batch" || legacyTab === "csv") {
    return "pdp";
  }
  return null;
}

function readRequestedMode(searchParams: ReturnType<typeof useSearchParams>): CrawlMode | null {
  const explicitMode = searchParams.get("mode");
  if (explicitMode && isCrawlMode(explicitMode)) {
    return explicitMode;
  }
  const legacyTab = searchParams.get("tab");
  if (legacyTab === "batch" || legacyTab === "csv") {
    return legacyTab;
  }
  return null;
}

function normalizeDomainFromUrl(value: string) {
  try {
    return new URL(value).hostname.replace(/^www\./, "").toLowerCase();
  } catch {
    return "";
  }
}

function isCrawlMode(value: string): value is CrawlMode {
  return value === "single" || value === "sitemap" || value === "bulk" || value === "batch" || value === "csv";
}

function isCategoryMode(value: string): value is CategoryMode {
  return value === "single" || value === "sitemap" || value === "bulk";
}

function isPdpMode(value: string): value is PdpMode {
  return value === "single" || value === "batch" || value === "csv";
}
