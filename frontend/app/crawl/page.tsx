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
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode, RefObject } from "react";

import { PageHeader, SectionHeader } from "../../components/ui/patterns";
import { Badge, Button, Card, Input, Textarea } from "../../components/ui/primitives";
import { api } from "../../lib/api";
import type { CrawlConfig, CrawlPhase, CrawlRecord, CrawlRun } from "../../lib/api/types";
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
  state: SuggestionState;
};

const TERMINAL_STATUSES = new Set<CrawlRun["status"]>(["completed", "killed", "failed", "proxy_exhausted"]);
const ACTIVE_STATUSES = new Set<CrawlRun["status"]>(["pending", "running", "paused"]);
const LOG_FILTERS: LogLevel[] = ["INFO", "WARN", "ERROR", "PROXY"];
const DEFAULT_REQUEST_DELAY = 500;
const DEFAULT_MAX_RECORDS = 100;
const DEFAULT_MAX_PAGES = 10;
const BULK_PREFILL_KEY = "bulk-crawl-prefill-v1";

export default function CrawlPage() {
  const router = useRouter();
  const pathname = usePathname();
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
  const [requestDelay, setRequestDelay] = useState(String(DEFAULT_REQUEST_DELAY));
  const [maxRecords, setMaxRecords] = useState(String(DEFAULT_MAX_RECORDS));
  const [maxPages, setMaxPages] = useState(String(DEFAULT_MAX_PAGES));
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
  const logViewportRef = useRef<HTMLDivElement | null>(null);
  const runId = Number(searchParams.get("runId") || 0) || null;
  const queryClient = useQueryClient();

  const runQuery = useQuery({
    queryKey: ["crawl-run", runId],
    queryFn: () => api.getCrawl(runId as number),
    enabled: runId !== null,
    refetchInterval: (query) => (query.state.data && ACTIVE_STATUSES.has(query.state.data.status) ? 2000 : false),
  });
  const run = runQuery.data;

  const recordsQuery = useQuery({
    queryKey: ["crawl-records", runId],
    queryFn: () => api.getRecords(runId as number, { limit: 1000 }),
    enabled: runId !== null && Boolean(run),
    refetchInterval: () => {
      const latestRun = queryClient.getQueryData<CrawlRun>(["crawl-run", runId]);
      return latestRun && ACTIVE_STATUSES.has(latestRun.status) ? 2000 : false;
    },
  });
  const logsQuery = useQuery({
    queryKey: ["crawl-logs", runId],
    queryFn: () => api.getCrawlLogs(runId as number),
    enabled: runId !== null,
    refetchInterval: () => {
      const latestRun = queryClient.getQueryData<CrawlRun>(["crawl-run", runId]);
      return latestRun && ACTIVE_STATUSES.has(latestRun.status) ? 2000 : false;
    },
  });
  const reviewQuery = useQuery({
    queryKey: ["crawl-review", runId],
    queryFn: () => api.getReview(runId as number),
    enabled: runId !== null && Boolean(run && TERMINAL_STATUSES.has(run.status)),
  });

  const records = useMemo(() => recordsQuery.data?.items ?? [], [recordsQuery.data?.items]);
  const logs = useMemo(() => logsQuery.data ?? [], [logsQuery.data]);
  const review = reviewQuery.data;
  const terminal = run ? TERMINAL_STATUSES.has(run.status) : false;
  const live = Boolean(run && ACTIVE_STATUSES.has(run.status));

  useEffect(() => {
    if (!run) {
      return;
    }
    if (terminal) {
      const timer = window.setTimeout(() => setCrawlPhase("complete"), 1500);
      return () => window.clearTimeout(timer);
    }
    setCrawlPhase("running");
  }, [run, terminal]);

  useEffect(() => {
    const stored = window.sessionStorage.getItem(BULK_PREFILL_KEY);
    if (!stored) {
      return;
    }
    try {
      const parsed = JSON.parse(stored) as { urls: string[]; additional_fields?: string[] };
      if (Array.isArray(parsed.urls) && parsed.urls.length) {
        setCrawlTab("category");
        setCategoryMode("bulk");
        setBulkUrls(parsed.urls.join("\n"));
        if (Array.isArray(parsed.additional_fields)) {
          setAdditionalFields(uniqueFields(parsed.additional_fields));
        }
        setBulkBanner(`${parsed.urls.length} URLs loaded from previous crawl results.`);
      }
    } catch {
      // Ignore malformed prefill data.
    } finally {
      window.sessionStorage.removeItem(BULK_PREFILL_KEY);
    }
  }, []);

  useEffect(() => {
    if (!live || !logViewportRef.current) {
      return;
    }
    const node = logViewportRef.current;
    const atBottom = node.scrollHeight - node.scrollTop - node.clientHeight < 50;
    if (atBottom) {
      node.scrollTop = node.scrollHeight;
    } else {
      setLiveJumpAvailable(true);
    }
  }, [logs, live]);

  useEffect(() => {
    if (!bulkBanner) {
      return;
    }
    const timer = window.setTimeout(() => setBulkBanner(""), 5000);
    return () => window.clearTimeout(timer);
  }, [bulkBanner]);

  useEffect(() => {
    if (review && !additionalFields.length) {
      setAdditionalFields(uniqueFields(review.canonical_fields.length ? review.canonical_fields : review.normalized_fields));
    }
  }, [additionalFields.length, review]);

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
        const key = `${record.id}:${fieldName}`;
        const backendStatus = String((raw as Record<string, unknown>).status ?? "pending_review");
        return [{
          key,
          recordId: record.id,
          fieldName,
          value,
          source: String((raw as Record<string, unknown>).source ?? "llm"),
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
      request_delay_ms: clampNumber(requestDelay, 0, 5000, DEFAULT_REQUEST_DELAY),
      max_records: clampNumber(maxRecords, 1, 10000, DEFAULT_MAX_RECORDS),
      max_pages: clampNumber(maxPages, 1, 500, DEFAULT_MAX_PAGES),
      proxy_enabled: proxyEnabled,
      proxy_lines: proxyEnabled ? parseLines(proxyInput) : [],
      additional_fields: additionalFields,
    }),
    [additionalFields, advancedEnabled, bulkUrls, categoryMode, crawlTab, csvFile, maxPages, maxRecords, proxyEnabled, proxyInput, requestDelay, smartExtraction, targetUrl, pdpMode],
  );

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
      router.replace((`/crawl?runId=${response.run_id}`) as Route);
    } catch (error) {
      setLaunchError(error instanceof Error ? error.message : "Unable to launch crawl.");
    }
  }

  function triggerBulkCrawlSelected() {
    const urls = selectedRecords
      .map((record) => extractRecordUrl(record))
      .filter((value): value is string => Boolean(value));
    if (!urls.length) {
      return;
    }
    window.sessionStorage.setItem(
      BULK_PREFILL_KEY,
      JSON.stringify({
        urls,
        additional_fields: additionalFields,
      }),
    );
    setCrawlTab("category");
    setCategoryMode("bulk");
    setBulkUrls(urls.join("\n"));
    setBulkBanner(`${urls.length} URLs loaded from previous crawl results.`);
    setCrawlPhase("config");
    router.replace("/crawl");
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

      {bulkBanner ? (
        <div className="surface-banner flex items-center justify-between px-4 py-3 text-sm">
          <div>{bulkBanner}</div>
          <button
            type="button"
            onClick={() => setBulkBanner("")}
            className="inline-flex size-7 items-center justify-center rounded-md text-muted transition hover:text-foreground"
          >
            <X className="size-4" />
          </button>
        </div>
      ) : null}

      {crawlPhase === "config" ? (
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
                <SegmentedMode
                  value={categoryMode}
                  onChange={(value) => setCategoryMode(value as CategoryMode)}
                  options={[
                    { value: "single", label: "Single Page" },
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
                  <Textarea
                    value={bulkUrls}
                    onChange={(event) => setBulkUrls(event.target.value)}
                    placeholder={"https://example.com/page-1\nhttps://example.com/page-2"}
                    className="min-h-[220px] font-mono text-sm"
                  />
                </label>
              ) : crawlTab === "pdp" && pdpMode === "csv" ? (
                <label className="grid gap-1.5">
                  <Input
                    type="file"
                    accept=".csv,text/csv"
                    onChange={(event) => setCsvFile(event.target.files?.[0] ?? null)}
                    className="h-auto py-3"
                  />
                </label>
              ) : (
                <label className="grid gap-1.5">
                  <Input
                    value={targetUrl}
                    onChange={(event) => setTargetUrl(event.target.value)}
                    placeholder={crawlTab === "category" ? "https://example.com/collections/chairs" : "https://example.com/products/oak-chair"}
                    className="font-mono text-sm"
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
                      <SliderRow label="Request Delay" value={requestDelay} min={0} max={5000} step={100} suffix=" ms" onChange={setRequestDelay} onReset={() => setRequestDelay(String(DEFAULT_REQUEST_DELAY))} />
                      <SliderRow label="Max Records" value={maxRecords} min={1} max={10000} step={1} onChange={setMaxRecords} onReset={() => setMaxRecords(String(DEFAULT_MAX_RECORDS))} />
                      <SliderRow label="Max Pages" value={maxPages} min={1} max={500} step={1} onChange={setMaxPages} onReset={() => setMaxPages(String(DEFAULT_MAX_PAGES))} />
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
            <PreviewRow label="Run ID" value={run ? `#${run.id}` : "--"} mono />
            <PreviewRow label="Crawl Type" value={run?.run_type ?? "--"} />
            <PreviewRow label="Target" value={run?.url ?? "--"} mono />
            <PreviewRow label="Records" value={String(summary.records)} />
            <PreviewRow label="Pages" value={String(summary.pages)} />
            <PreviewRow label="Elapsed" value={summary.duration} />
            <ProgressBar percent={progressPercent(run)} />
            {run?.status === "paused" ? <div className="rounded-md border border-warning/30 bg-warning/10 px-3 py-2 text-sm text-foreground">Job paused. Output so far is preserved.</div> : null}
            {launchError ? <div className="rounded-md border border-danger/20 bg-danger/10 px-3 py-2 text-sm text-danger">{launchError}</div> : null}
            <div className="flex flex-wrap gap-2">
              <ActionButton
                label={runActionPending === "pause" ? "Pausing..." : "Pause"}
                onClick={() => void runControl("pause")}
                disabled={!run || run.status !== "running" || runActionPending !== null}
              />
              <ActionButton
                label={runActionPending === "resume" ? "Resuming..." : "Resume"}
                onClick={() => void runControl("resume")}
                disabled={!run || run.status !== "paused" || runActionPending !== null}
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
                        if (logViewportRef.current) {
                          logViewportRef.current.scrollTop = logViewportRef.current.scrollHeight;
                        }
                        setLiveJumpAvailable(false);
                      }}
                      className="inline-flex items-center gap-1 rounded-md border border-border bg-panel px-2.5 py-1.5 text-xs"
                    >
                      <ChevronsDown className="size-3.5" />
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
                    <Button variant="ghost" type="button" onClick={() => void copyJson(records)}>
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
                        </div>
                        <div className="font-mono text-sm text-foreground">{item.value}</div>
                        <div className="flex items-center gap-2">
                          <Button variant="secondary" type="button" onClick={() => setSuggestionState((current) => ({ ...current, [item.key]: "accepted" }))} disabled={item.state === "committed"}>
                            Accept
                          </Button>
                          <Button variant="ghost" type="button" onClick={() => setSuggestionState((current) => ({ ...current, [item.key]: "rejected" }))} disabled={item.state === "committed"}>
                            Reject
                          </Button>
                          <Badge tone={item.state === "committed" ? "success" : item.state === "accepted" ? "success" : item.state === "rejected" ? "danger" : "neutral"}>
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
                    <div className="rounded-md border border-border bg-background p-3 text-foreground">No pending LLM cleanup suggestions were stored for this run.</div>
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
  void navigator.clipboard.writeText(JSON.stringify(records.map(cleanRecord), null, 2));
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

function useLogViewport(logsLength: number, ref?: RefObject<HTMLDivElement | null>) {
  const internalRef = useRef<HTMLDivElement | null>(null);
  const viewportRef = ref ?? internalRef;
  useEffect(() => {
    if (viewportRef.current) {
      viewportRef.current.scrollTop = viewportRef.current.scrollHeight;
    }
  }, [logsLength, viewportRef]);
  return viewportRef;
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
  const urls = dispatch.urls ?? (dispatch.url ? [dispatch.url] : []);
  const proxyCount = Array.isArray(dispatch.settings.proxy_list) ? dispatch.settings.proxy_list.length : 0;
  const smartExtraction = Boolean(dispatch.settings.llm_enabled);
  const proxyEnabled = Boolean(dispatch.settings.proxy_enabled);
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4 backdrop-blur-sm">
      <div className="w-full max-w-[540px] rounded-[var(--radius-xl)] border border-border bg-background-elevated p-5 shadow-[var(--shadow-modal)]">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="text-base font-semibold tracking-[-0.02em]">Review Before Running</div>
            <div className="text-sm text-muted">Confirm the payload before the job is dispatched.</div>
          </div>
          <button type="button" onClick={onCancel} className="inline-flex size-8 items-center justify-center rounded-md border border-border text-muted transition hover:text-foreground">
            <X className="size-4" />
          </button>
        </div>
        <div className="mt-4 space-y-2">
          <PreviewRow label="Target URL" value={dispatch.url ?? urls[0] ?? "--"} mono />
          <PreviewRow label="Mode" value={dispatch.runType} />
          <PreviewRow label="Proxy" value={proxyEnabled ? `${proxyCount} configured` : "Inactive"} />
          <PreviewRow label="Smart Extraction" value={smartExtraction ? "On" : "Off"} />
          <PreviewRow label="Max Records" value={String(dispatch.settings.max_records)} />
          <PreviewRow label="Max Pages" value={String(dispatch.settings.max_pages)} />
        </div>
        <div className="mt-4">
          <div className="label-caps mb-2">Additional Fields</div>
          <div className="flex flex-wrap gap-1.5">
            {dispatch.additionalFields.length ? dispatch.additionalFields.map((field) => <Badge key={field} tone="neutral">{field}</Badge>) : <span className="text-sm text-muted">None</span>}
          </div>
        </div>
        {launchError ? <div className="mt-4 rounded-md border border-danger/20 bg-danger/10 px-3 py-2 text-sm text-danger">{launchError}</div> : null}
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="ghost" type="button" onClick={onCancel}>
            Cancel
          </Button>
          <Button variant="accent" type="button" onClick={onLaunch}>
            Launch Job
          </Button>
        </div>
      </div>
    </div>
  );
}

function LogTerminal({
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
    <div ref={ref} className="crawl-terminal max-h-[320px] min-h-[260px] space-y-1.5">
      {logs.length ? logs.map((log) => (
        <div key={log.id} className="font-mono text-[12px] leading-6">
          <span className="text-muted">[{formatTimestamp(log.created_at)}]</span>{" "}
          <span className={logTone(log.level)}>[{normalizeLogLevel(log.level)}]</span>{" "}
          <span>{log.message}</span>
        </div>
      )) : <div className="text-sm text-muted">{live ? "Waiting for log output..." : "No logs captured for this run."}</div>}
    </div>
  );
}

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

function SegmentedMode({
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
          {chips.map((field) => <button key={field} type="button" onClick={() => onRemove(field)} className="inline-flex items-center gap-1 rounded-md border border-border bg-panel px-2 py-1 text-xs"><span>{field}</span><X className="size-3.5" /></button>)}
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
      <div className="flex items-end justify-end"><button type="button" onClick={onDelete} className="inline-flex size-8 items-center justify-center rounded-[var(--radius-md)] border border-border text-danger hover:bg-danger/10"><Trash2 className="size-3.5" /></button></div>
    </div>
  );
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
          {state === "valid" ? <CheckCircle2 className="size-4 text-success" /> : state === "invalid" ? <CircleAlert className="size-4 text-danger" /> : null}
        </div>
      </div>
    </label>
  );
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

function PreviewRow({ label, value, mono }: Readonly<{ label: string; value: string; mono?: boolean }>) {
  return <div className="flex items-start justify-between gap-4 rounded-[var(--radius-md)] border border-border bg-panel px-3 py-2"><div className="shrink-0 label-caps">{label}</div><div className={cn("min-w-0 max-w-[65%] overflow-hidden break-all text-right text-sm", mono && "font-mono text-xs")}>{value || "--"}</div></div>;
}

function formatTimestamp(value: string) {
  try {
    return new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return value;
  }
}
