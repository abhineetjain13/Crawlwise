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
import type { CrawlConfig, CrawlPhase, CrawlRecord, CrawlRun } from "../../lib/api/types";
import { CRAWL_DEFAULTS, CRAWL_LIMITS } from "../../lib/constants/crawl-defaults";
import { ACTIVE_STATUSES, TERMINAL_STATUSES } from "../../lib/constants/crawl-statuses";
import { STORAGE_KEYS } from "../../lib/constants/storage-keys";
import { POLLING_INTERVALS, UI_DELAYS } from "../../lib/constants/timing";
import { cn } from "../../lib/utils";

type CrawlTab = "category" | "pdp";
type CategoryMode = "single" | "sitemap" | "bulk";
type PdpMode = "single" | "batch" | "csv";
type ValidationState = "idle" | "valid" | "invalid";
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
type IntelligenceCandidate = {
  key: string;
  recordId: number;
  recordUrl: string;
  recordTitle: string;
  fieldName: string;
  displayLabel: string;
  groupLabel: string;
  value: unknown;
  href?: string;
  sortOrder: number;
};
type IntelligenceRecordGroup = {
  key: string;
  recordId: number;
  recordUrl: string;
  recordTitle: string;
  items: IntelligenceCandidate[];
};

export default function CrawlPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const runId = Number(searchParams.get("run_id") || searchParams.get("runId") || 0) || null;
  const [crawlPhase, setCrawlPhase] = useState<CrawlPhase>(() => (runId ? "running" : "config"));
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
  const [liveJumpAvailable, setLiveJumpAvailable] = useState(false);
  const [bulkBanner, setBulkBanner] = useState("");
  const [runActionPending, setRunActionPending] = useState<"pause" | "resume" | "kill" | null>(null);
  const [selectedCandidateKeys, setSelectedCandidateKeys] = useState<Record<string, boolean>>({});
  const [candidateEdits, setCandidateEdits] = useState<Record<string, { fieldName: string; value?: string }>>({});
  const [expandedIntelligenceGroups, setExpandedIntelligenceGroups] = useState<Record<string, boolean>>({});
  const [commitPending, setCommitPending] = useState(false);
  const [commitError, setCommitError] = useState("");
  const logViewportRef = useRef<HTMLDivElement | null>(null);
  const previousRunIdRef = useRef<number | null>(runId);
  const previousRunStatusRef = useRef<CrawlRun["status"] | null>(null);
  const terminalSyncRef = useRef<string | null>(null);
  const queryClient = useQueryClient();

  const runQuery = useQuery({
    queryKey: ["crawl-run", runId],
    queryFn: () => api.getCrawl(runId as number),
    enabled: runId !== null,
    refetchInterval: (query) => (query.state.data && ACTIVE_STATUSES.has(query.state.data.status) ? POLLING_INTERVALS.ACTIVE_JOB_MS : false),
  });
  const run = runQuery.data;

  const recordsQuery = useQuery({
    queryKey: ["crawl-records", runId],
    queryFn: () => api.getRecords(runId as number, { limit: 1000 }),
    enabled: runId !== null && Boolean(run),
    refetchInterval: () => {
      const latestRun = queryClient.getQueryData<CrawlRun>(["crawl-run", runId]);
      return latestRun && ACTIVE_STATUSES.has(latestRun.status) ? POLLING_INTERVALS.RECORDS_MS : false;
    },
  });
  const logsQuery = useQuery({
    queryKey: ["crawl-logs", runId],
    queryFn: () => api.getCrawlLogs(runId as number),
    enabled: runId !== null,
    refetchInterval: () => {
      const latestRun = queryClient.getQueryData<CrawlRun>(["crawl-run", runId]);
      return latestRun && ACTIVE_STATUSES.has(latestRun.status) ? POLLING_INTERVALS.LOGS_MS : false;
    },
  });
  const reviewQuery = useQuery({
    queryKey: ["crawl-review", runId],
    queryFn: () => api.getReview(runId as number),
    enabled: runId !== null && Boolean(run && TERMINAL_STATUSES.has(run.status)),
  });

  const records = useMemo(() => recordsQuery.data?.items ?? [], [recordsQuery.data?.items]);
  const logs = useMemo(
    () => (logsQuery.data ?? []).slice(-CRAWL_DEFAULTS.MAX_LIVE_LOGS),
    [logsQuery.data],
  );
  const review = reviewQuery.data;
  const terminal = run ? TERMINAL_STATUSES.has(run.status) : false;
  const live = Boolean(run && ACTIVE_STATUSES.has(run.status));
  const showRunLoadingState = runId !== null && runQuery.isLoading && !run;

  useEffect(() => {
    if (!run) {
      return;
    }
    previousRunStatusRef.current = run.status;
    if (terminal) {
      // Transition immediately — no delay gap that causes a blank screen flash
      setCrawlPhase("complete");
      return;
    }
    setCrawlPhase("running");
  }, [run, terminal]);

  useEffect(() => {
    if (runId === null) {
      setCrawlPhase("config");
      return;
    }
    if (!run) {
      setCrawlPhase("running");
    }
  }, [run, runId]);

  useEffect(() => {
    if (previousRunIdRef.current === runId) {
      return;
    }

    setSelectedIds([]);
    setJsonCompact(false);
    setOutputTab("table");
    setBulkBanner("");
    setRunActionPending(null);
    setSelectedCandidateKeys({});
    setCandidateEdits({});
    setExpandedIntelligenceGroups({});
    setCommitPending(false);
    setCommitError("");
    setLaunchError("");
    setPreviewOpen(false);
    setPendingDispatch(null);
    previousRunStatusRef.current = null;
    terminalSyncRef.current = null;

    if (runId === null) {
      clearConfigState();
      setCrawlPhase("config");
    } else {
      setCrawlPhase("running");
    }

    previousRunIdRef.current = runId;
  }, [runId]);

  useEffect(() => {
    if (!runId || !run || !terminal) {
      terminalSyncRef.current = null;
      return;
    }

    const syncKey = `${run.id}:${run.status}:${run.completed_at ?? ""}:${run.updated_at}`;
    if (terminalSyncRef.current === syncKey) {
      return;
    }
    terminalSyncRef.current = syncKey;

    void Promise.allSettled([
      runQuery.refetch(),
      recordsQuery.refetch(),
      logsQuery.refetch(),
      reviewQuery.refetch(),
    ]);
  }, [logsQuery, recordsQuery, reviewQuery, run, runId, runQuery, terminal]);

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

  const intelligenceCandidates = useMemo<IntelligenceCandidate[]>(() => {
    const grouped = new Map<string, IntelligenceCandidate>();

    for (const record of records) {
      const recordUrl = extractRecordUrl(record) || record.source_url;
      const recordTitle = stringifyCell(record.data?.title).trim() || recordUrl || `Record ${record.id}`;
      const candidateMap = record.source_trace?.candidates;
      if (candidateMap && typeof candidateMap === "object" && !Array.isArray(candidateMap)) {
        for (const [fieldName, rawRows] of Object.entries(candidateMap as Record<string, unknown>)) {
          if (!Array.isArray(rawRows)) {
            continue;
          }
          for (const rawRow of rawRows) {
            if (!rawRow || typeof rawRow !== "object") {
              continue;
            }
            const row = rawRow as Record<string, unknown>;
            const rawValue = row.value ?? row.sample_value;
            const displayValue = stringifyCell(rawValue).trim();
            if (!displayValue) {
              continue;
            }
            const displayLabel = stringifyCell(row.display_label).trim() || humanizeFieldName(fieldName);
            const groupLabel = stringifyCell(row.group_label).trim() || "General";
            const href = stringifyCell(row.href).trim() || "";
            const sortOrder = Number(row.table_index ?? 0) * 10000 + Number(row.row_index ?? 0);
            const key = `${record.id}:${groupLabel}:${displayLabel}:${displayValue}`;
            const existing = grouped.get(key);
            if (existing) {
              if (!existing.href && href) existing.href = href;
              existing.sortOrder = Math.min(existing.sortOrder, sortOrder || existing.sortOrder || Number.MAX_SAFE_INTEGER);
              continue;
            }
            grouped.set(key, {
              key,
              recordId: record.id,
              recordUrl,
              recordTitle,
              fieldName,
              displayLabel,
              groupLabel,
              value: rawValue,
              href: href || undefined,
              sortOrder: sortOrder || Number.MAX_SAFE_INTEGER,
            });
          }
        }
      }

      const llmSuggestions = record.source_trace?.llm_cleanup_suggestions;
      if (llmSuggestions && typeof llmSuggestions === "object" && !Array.isArray(llmSuggestions)) {
        for (const [fieldName, rawSuggestion] of Object.entries(llmSuggestions as Record<string, unknown>)) {
          if (!rawSuggestion || typeof rawSuggestion !== "object") {
            continue;
          }
          const suggestion = rawSuggestion as Record<string, unknown>;
          const rawValue = suggestion.suggested_value;
          const displayValue = stringifyCell(rawValue).trim();
          if (!displayValue) {
            continue;
          }
          const key = `${record.id}:Suggested:${fieldName}:${displayValue}`;
          const existing = grouped.get(key);
          if (existing) {
            continue;
          }
          grouped.set(key, {
            key,
            recordId: record.id,
            recordUrl,
            recordTitle,
            fieldName,
            displayLabel: humanizeFieldName(fieldName),
            groupLabel: "Suggested",
            value: rawValue,
            sortOrder: Number.MAX_SAFE_INTEGER,
          });
        }
      }
    }

    return Array.from(grouped.values())
      .sort((left, right) => {
        if (left.recordId !== right.recordId) return left.recordId - right.recordId;
        if (left.groupLabel !== right.groupLabel) return left.groupLabel.localeCompare(right.groupLabel);
        if (left.sortOrder !== right.sortOrder) return left.sortOrder - right.sortOrder;
        if (left.displayLabel !== right.displayLabel) return left.displayLabel.localeCompare(right.displayLabel);
        return String(left.value ?? "").localeCompare(String(right.value ?? ""));
      });
  }, [records]);

  const intelligenceRecordGroups = useMemo<IntelligenceRecordGroup[]>(() => {
    const groups = new Map<string, IntelligenceRecordGroup>();
    for (const item of intelligenceCandidates) {
      const key = `${item.recordId}:${item.recordUrl}`;
      const existing = groups.get(key);
      if (existing) {
        existing.items.push(item);
        continue;
      }
      groups.set(key, {
        key,
        recordId: item.recordId,
        recordUrl: item.recordUrl,
        recordTitle: item.recordTitle,
        items: [item],
      });
    }
    return Array.from(groups.values()).sort((left, right) => left.recordId - right.recordId);
  }, [intelligenceCandidates]);

  useEffect(() => {
    if (!intelligenceRecordGroups.length) {
      setExpandedIntelligenceGroups({});
      return;
    }
    setExpandedIntelligenceGroups((current) => {
      const next: Record<string, boolean> = {};
      let hasExpanded = false;
      for (const group of intelligenceRecordGroups) {
        if (current[group.key]) {
          next[group.key] = true;
          hasExpanded = true;
        }
      }
      if (!hasExpanded) {
        next[intelligenceRecordGroups[0].key] = true;
      }
      return next;
    });
  }, [intelligenceRecordGroups]);

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
  const resultUrls = useMemo(
    () => uniqueStrings(records.map((record) => extractRecordUrl(record))),
    [records],
  );
  const selectedResultUrls = useMemo(
    () => uniqueStrings(selectedRecords.map((record) => extractRecordUrl(record))),
    [selectedRecords],
  );
  const listingRun = useMemo(() => isListingRun(run), [run]);
  const batchFromResultsUrls = selectedResultUrls.length ? selectedResultUrls : resultUrls;
  const batchFromResultsLabel = selectedResultUrls.length
    ? `Batch Crawl Selected (${selectedResultUrls.length})`
    : `Batch Crawl Results (${resultUrls.length})`;

  const summary = {
    records: Number(run?.result_summary?.record_count ?? records.length) || 0,
    pages: Number(run?.result_summary?.processed_urls ?? run?.result_summary?.completed_urls ?? 0) || 0,
    fields: visibleColumns.length,
    duration: formatDuration(run?.created_at, run?.completed_at),
  };

  function clearConfigState() {
    setCrawlTab("pdp");
    setCategoryMode("single");
    setPdpMode("single");
    setTargetUrl("");
    setBulkUrls("");
    setCsvFile(null);
    setSmartExtraction(false);
    setAdvancedEnabled(false);
    setRequestDelay(String(CRAWL_DEFAULTS.REQUEST_DELAY_MS));
    setMaxRecords(String(CRAWL_DEFAULTS.MAX_RECORDS));
    setMaxPages(String(CRAWL_DEFAULTS.MAX_PAGES));
    setProxyEnabled(false);
    setProxyInput("");
    setAdditionalDraft("");
    setAdditionalFields([]);
    setFieldRows([]);
    setConfigError("");
    setLaunchError("");
    setSelectedCandidateKeys({});
    setCandidateEdits({});
    setCommitError("");
    setCommitPending(false);
    setSelectedIds([]);
    setOutputTab("table");
    setJsonCompact(false);
  }

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

  async function commitSelectedCandidates(candidateKeys?: string[]) {
    if (!runId) {
      return;
    }
    const allowedKeys = candidateKeys ? new Set(candidateKeys) : null;
    const selectedItems = intelligenceCandidates
      .filter((item) => (allowedKeys ? allowedKeys.has(item.key) : selectedCandidateKeys[item.key]))
      .map((item) => ({
        record_id: item.recordId,
        field_name: (candidateEdits[item.key]?.fieldName ?? item.displayLabel).trim(),
        value: candidateEdits[item.key]?.value ?? item.value,
      }));
    const validItems = selectedItems.filter((item) => item.field_name && !isEmptyCandidateValue(item.value));
    if (!validItems.length) {
      return;
    }
    setCommitPending(true);
    setCommitError("");
    try {
      await api.commitSelectedFields(runId, validItems);
      setSelectedCandidateKeys({});
      await Promise.all([recordsQuery.refetch(), logsQuery.refetch()]);
    } catch (error) {
      setCommitError(error instanceof Error ? error.message : "Unable to save selected fields.");
    } finally {
      setCommitPending(false);
    }
  }

  function setGroupCandidateSelection(group: IntelligenceRecordGroup, checked: boolean) {
    setSelectedCandidateKeys((current) => {
      const next = { ...current };
      for (const item of group.items) {
        if (checked) {
          next[item.key] = true;
        } else {
          delete next[item.key];
        }
      }
      return next;
    });
  }

  async function commitRecordGroup(group: IntelligenceRecordGroup) {
    const selectedKeys = group.items.filter((item) => selectedCandidateKeys[item.key]).map((item) => item.key);
    if (selectedKeys.length) {
      await commitSelectedCandidates(selectedKeys);
      return;
    }
    setSelectedCandidateKeys((current) => ({ ...current, ...Object.fromEntries(group.items.map((item) => [item.key, true])) }));
    await commitSelectedCandidates(group.items.map((item) => item.key));
  }

  function resetToConfig() {
    clearConfigState();
    setCrawlPhase("config");
    setPreviewOpen(false);
    setPendingDispatch(null);
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
      router.replace((`/crawl?run_id=${response.run_id}`) as Route);
    } catch (error) {
      setLaunchError(error instanceof Error ? error.message : "Unable to launch crawl.");
    }
  }

  function triggerBatchCrawlFromResults() {
    const urls = batchFromResultsUrls;
    if (!urls.length) {
      return;
    }
    window.sessionStorage.setItem(
      STORAGE_KEYS.BULK_PREFILL,
      JSON.stringify({
        urls,
        additional_fields: additionalFields,
      }),
    );
    setCrawlTab("pdp");
    setPdpMode("batch");
    setBulkUrls(urls.join("\n"));
    setBulkBanner(`${urls.length} URLs loaded into PDP batch crawl.`);
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
        title="Crawl Studio"
        actions={
          <div className="flex flex-wrap items-center gap-2">
            {crawlPhase !== "config" ? (
              <Button variant="accent" type="button" onClick={resetToConfig}>
                New Crawl
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
            aria-label="Close banner"
            className="inline-flex size-7 items-center justify-center rounded-md text-muted transition hover:text-foreground"
          >
            <X className="size-4" aria-hidden="true" />
          </button>
        </div>
      ) : null}

      {showRunLoadingState ? (
        <Card className="space-y-3 px-6 py-8">
          <SectionHeader title="Loading Crawl" description="Fetching run details and restoring the workspace." />
          <div className="text-sm text-muted">Run #{runId} is loading.</div>
        </Card>
      ) : null}

      {!showRunLoadingState && crawlPhase === "config" ? (
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

      {!showRunLoadingState && crawlPhase === "running" ? (
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
              description="Auto-scrolls while you stay at the bottom."
              action={
                <div className="flex items-center gap-2">
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
            <LogTerminal logs={logs} live viewportRef={logViewportRef} />
          </Card>
        </div>
      ) : null}

      {!showRunLoadingState && crawlPhase === "complete" ? (
        <Card className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius-lg)] border border-border bg-[var(--bg-elevated)] px-4 py-3">
            <div className="min-w-0 flex-1">
              {run?.url ? (
                <a
                  href={run.url}
                  target="_blank"
                  rel="noreferrer"
                  className="block truncate text-[13px] font-medium text-accent underline-offset-2 hover:underline"
                >
                  {run.url}
                </a>
              ) : (
                <p className="text-[13px] text-muted">Waiting for completed run data.</p>
              )}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {listingRun && batchFromResultsUrls.length ? (
                <Button variant="accent" type="button" onClick={triggerBatchCrawlFromResults}>
                  <ArrowRightCircle className="size-3.5" />
                  {batchFromResultsLabel}
                </Button>
              ) : null}
              <a href={api.exportCsv(runId as number)} target="_blank" rel="noreferrer">
                <Button variant="accent" type="button" className="shadow-[var(--shadow-sm)]">
                  <Download className="size-3.5" />
                  CSV
                </Button>
              </a>
              <a href={api.exportJson(runId as number)} target="_blank" rel="noreferrer">
                <Button variant="accent" type="button" className="shadow-[var(--shadow-sm)]">
                  <Download className="size-3.5" />
                  JSON
                </Button>
              </a>
            </div>
          </div>

          <div className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border">
              <div className="flex items-center gap-0">
                <OutputTab active={outputTab === "table"} onClick={() => setOutputTab("table")}>
                  {`Table (${summary.fields})`}
                </OutputTab>
                <OutputTab active={outputTab === "json"} onClick={() => setOutputTab("json")}>JSON</OutputTab>
                <OutputTab active={outputTab === "intelligence"} onClick={() => setOutputTab("intelligence")}>Intelligence</OutputTab>
                <OutputTab active={outputTab === "logs"} onClick={() => setOutputTab("logs")}>Logs</OutputTab>
              </div>
              <div className="pb-2 text-sm text-muted">
                Time Taken: <span className="font-semibold text-foreground">{summary.duration}</span>
              </div>
            </div>

            {outputTab === "table" ? (
              <div className="space-y-3">
                {recordsQuery.isLoading && !records.length ? (
                  <div className="space-y-2">
                    {Array.from({ length: 5 }, (_, i) => (
                      <div key={i} className="skeleton h-9 w-full rounded-[var(--radius-md)]" />
                    ))}
                  </div>
                ) : records.length ? (
                  <RecordsTable
                    records={records}
                    visibleColumns={visibleColumns}
                    selectedIds={selectedIds}
                    onSelectAll={(checked) => setSelectedIds(checked ? records.map((r) => r.id) : [])}
                    onToggleRow={(id, checked) =>
                      setSelectedIds((current) =>
                        checked ? uniqueNumbers([...current, id]) : current.filter((v) => v !== id),
                      )
                    }
                  />
                ) : (
                  <div className="grid min-h-40 place-items-center rounded-[10px] border border-dashed border-border bg-panel/60 text-sm text-muted">No records captured yet.</div>
                )}
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
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone="neutral">
                      {intelligenceCandidates.length} rows
                    </Badge>
                    <Badge tone="neutral">
                      {Object.values(selectedCandidateKeys).filter(Boolean).length} selected
                    </Badge>
                    <Button
                      variant="ghost"
                      type="button"
                      onClick={() => {
                        setSelectedCandidateKeys({});
                        setCandidateEdits({});
                      }}
                      disabled={!Object.keys(selectedCandidateKeys).length && !Object.keys(candidateEdits).length}
                    >
                      Clear
                    </Button>
                    <Button
                      variant="accent"
                      type="button"
                      onClick={() => void commitSelectedCandidates()}
                      disabled={!intelligenceCandidates.some((item) => selectedCandidateKeys[item.key]) || commitPending}
                    >
                      {commitPending ? "Saving..." : "Save Selected"}
                    </Button>
                  </div>
                </div>
                {commitError ? <div className="rounded-md border border-danger/20 bg-danger/10 px-3 py-2 text-sm text-danger">{commitError}</div> : null}
                {intelligenceCandidates.length ? (
                  <div className="space-y-4">
                    <div className="flex items-center gap-2 rounded-md border border-border bg-panel px-3 py-2">
                      <input
                        type="checkbox"
                        checked={intelligenceCandidates.length > 0 && intelligenceCandidates.every((item) => selectedCandidateKeys[item.key])}
                        onChange={(event) => {
                          if (event.target.checked) {
                            setSelectedCandidateKeys(Object.fromEntries(intelligenceCandidates.map((item) => [item.key, true])));
                            return;
                          }
                          setSelectedCandidateKeys({});
                        }}
                      />
                      <span className="text-sm text-muted">Select all visible rows</span>
                    </div>
                    {intelligenceRecordGroups.map((group) => {
                      const selectedCount = group.items.filter((item) => selectedCandidateKeys[item.key]).length;
                      const expanded = Boolean(expandedIntelligenceGroups[group.key]);
                      return (
                        <div key={group.key} className="overflow-hidden rounded-md border border-border">
                          <button
                            type="button"
                            onClick={() => setExpandedIntelligenceGroups((current) => ({ ...current, [group.key]: !expanded }))}
                            className="flex w-full items-start justify-between gap-3 bg-panel px-4 py-3 text-left"
                          >
                            <div className="min-w-0 flex-1">
                              <div className="truncate text-sm font-semibold text-foreground">{group.recordTitle}</div>
                              <div className="truncate text-xs text-muted">{group.recordUrl}</div>
                            </div>
                            <div className="flex items-center gap-2">
                              <Badge tone="neutral">{group.items.length} rows</Badge>
                              <Badge tone="neutral">{selectedCount} selected</Badge>
                              <ChevronDown className={cn("size-4 shrink-0 transition-transform", expanded ? "rotate-180" : "")} />
                            </div>
                          </button>
                          {expanded ? (
                            <div className="space-y-3 border-t border-border bg-[var(--bg-elevated)] p-3">
                              <div className="flex flex-wrap items-center gap-2">
                                <Button
                                  variant="ghost"
                                  type="button"
                                  onClick={() => setGroupCandidateSelection(group, selectedCount !== group.items.length)}
                                >
                                  {selectedCount === group.items.length ? "Unselect Link" : "Select Link"}
                                </Button>
                                <Button
                                  variant="accent"
                                  type="button"
                                  onClick={() => void commitRecordGroup(group)}
                                  disabled={commitPending}
                                >
                                  {commitPending ? "Saving..." : "Save Link"}
                                </Button>
                              </div>
                              <div className="overflow-auto rounded-md border border-border">
                                <table className="compact-data-table min-w-[1080px]">
                                  <thead>
                                    <tr>
                                      <th className="w-10" />
                                      <th className="w-[220px]">Field</th>
                                      <th className="w-[160px]">Section</th>
                                      <th>Value</th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {group.items.map((item) => {
                                      const editedFieldName = candidateEdits[item.key]?.fieldName ?? item.displayLabel;
                                      const editedValue = candidateEdits[item.key]?.value ?? presentCandidateValue(item.value);
                                      return (
                                        <tr key={item.key}>
                                          <td className="w-10">
                                            <input
                                              type="checkbox"
                                              checked={Boolean(selectedCandidateKeys[item.key])}
                                              onChange={(event) => {
                                                const checked = event.target.checked;
                                                setSelectedCandidateKeys((current) => {
                                                  if (checked) {
                                                    return { ...current, [item.key]: true };
                                                  }
                                                  const next = { ...current };
                                                  delete next[item.key];
                                                  return next;
                                                });
                                              }}
                                            />
                                          </td>
                                          <td className="w-[220px]" title={editedFieldName}>
                                            <Input
                                              value={editedFieldName}
                                              onChange={(event) => setCandidateEdits((current) => ({
                                                ...current,
                                                [item.key]: {
                                                  fieldName: event.target.value,
                                                  value: current[item.key]?.value,
                                                },
                                              }))}
                                              className="h-8 border-0 bg-transparent px-0 text-sm shadow-none"
                                            />
                                          </td>
                                          <td className="text-xs text-muted">{item.groupLabel || "General"}</td>
                                          <td title={editedValue}>
                                            <div className="flex items-center gap-2">
                                              <Input
                                                value={editedValue}
                                                onChange={(event) => setCandidateEdits((current) => ({
                                                  ...current,
                                                  [item.key]: {
                                                    fieldName: current[item.key]?.fieldName ?? item.displayLabel,
                                                    value: event.target.value,
                                                  },
                                                }))}
                                                className="h-8 border-0 bg-transparent px-0 font-mono text-sm shadow-none"
                                              />
                                              {item.href ? (
                                                <a
                                                  href={item.href}
                                                  target="_blank"
                                                  rel="noreferrer"
                                                  className="shrink-0 text-xs text-accent underline-offset-2 hover:underline"
                                                  title={item.href}
                                                >
                                                  Open
                                                </a>
                                              ) : null}
                                            </div>
                                          </td>
                                        </tr>
                                      );
                                    })}
                                  </tbody>
                                </table>
                              </div>
                            </div>
                          ) : null}
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <div className="text-sm text-muted">No field candidates are available for this run.</div>
                )}
              </Card>
            ) : null}

            {outputTab === "logs" ? (
              <Card className="space-y-3 p-4">
                <LogTerminal logs={logs} viewportRef={logViewportRef} />
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

function uniqueStrings(values: string[]) {
  return Array.from(new Set(values.map((value) => value.trim()).filter(Boolean)));
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

function isListingRun(run?: CrawlRun) {
  return inferRunModule(run) === "category";
}

function inferRunModule(run?: CrawlRun): CrawlTab | null {
  if (!run) {
    return null;
  }
  const settings = run.settings && typeof run.settings === "object" ? run.settings : {};
  const configuredModule = typeof settings.crawl_module === "string" ? settings.crawl_module : "";
  if (configuredModule === "category" || configuredModule === "pdp") {
    return configuredModule;
  }

  const configuredMode = typeof settings.crawl_mode === "string" ? settings.crawl_mode : "";
  if (configuredMode === "bulk" || configuredMode === "sitemap") {
    return "category";
  }
  if (configuredMode === "batch" || configuredMode === "csv") {
    return "pdp";
  }

  const surface = String(run.surface || "").toLowerCase();
  if (surface.includes("listing")) {
    return "category";
  }
  if (surface.includes("detail")) {
    return "pdp";
  }

  return null;
}

function stringifyCell(value: unknown) {
  if (value == null) return "";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

function humanizeFieldName(value: string) {
  const normalized = String(value || "")
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (!normalized) return "";
  return normalized.charAt(0).toUpperCase() + normalized.slice(1);
}

function presentCandidateValue(value: unknown) {
  const trimmed = stringifyCell(value).trim();
  if (!trimmed) return "";
  const schemaMatch = trimmed.match(/^https?:\/\/schema\.org\/([A-Za-z]+)$/i);
  if (!schemaMatch) return trimmed;
  const token = schemaMatch[1].replace(/([a-z])([A-Z])/g, "$1 $2");
  return token.charAt(0).toUpperCase() + token.slice(1);
}

function isEmptyCandidateValue(value: unknown) {
  if (value === null || value === undefined) return true;
  if (typeof value === "string") return value.trim().length === 0;
  if (Array.isArray(value)) return value.length === 0;
  if (typeof value === "object") return Object.keys(value).length === 0;
  return false;
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
  if (normalized === "WARN") return "border-transparent bg-transparent text-warning";
  if (normalized === "ERROR") return "border-transparent bg-transparent text-danger";
  if (normalized === "PROXY") return "border-transparent bg-transparent text-accent";
  return "border-transparent bg-transparent text-[var(--text-secondary)]";
}

function normalizeLogLevel(level: string) {
  return String(level || "").trim().toUpperCase();
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
  const modalRef = useRef<HTMLDivElement | null>(null);
  const previouslyFocusedRef = useRef<HTMLElement | null>(null);
  const urls = dispatch.urls ?? (dispatch.url ? [dispatch.url] : []);
  const proxyCount = Array.isArray(dispatch.settings.proxy_list) ? dispatch.settings.proxy_list.length : 0;
  const smartExtraction = Boolean(dispatch.settings.llm_enabled);
  const proxyEnabled = Boolean(dispatch.settings.proxy_enabled);

  useEffect(() => {
    previouslyFocusedRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    getFocusableElements(modalRef.current)[0]?.focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onCancel();
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
  }, [onCancel]);

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4 backdrop-blur-sm" role="presentation">
      <div
        ref={modalRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="crawl-preview-title"
        aria-describedby="crawl-preview-description"
        className="w-full max-w-[540px] rounded-[var(--radius-xl)] border border-border bg-background-elevated p-5 shadow-[var(--shadow-modal)]"
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <div id="crawl-preview-title" className="text-base font-semibold tracking-[-0.02em]">Review Before Running</div>
            <div id="crawl-preview-description" className="text-sm text-muted">Confirm the payload before the job is dispatched.</div>
          </div>
          <button type="button" onClick={onCancel} aria-label="Close preview" className="inline-flex size-8 items-center justify-center rounded-md border border-border text-muted transition hover:text-foreground">
            <X className="size-4" aria-hidden="true" />
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
          <span className={cn("inline-flex items-center px-1.5 py-0.5 text-[10px] font-semibold tracking-[0.08em]", logTone(log.level))}>
            {normalizeLogLevel(log.level)}
          </span>{" "}
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
    <div className="overflow-hidden rounded-[var(--radius-lg)] border border-[var(--border-strong)] bg-[var(--bg-elevated)]">
      <div className="flex min-h-[76px] items-center justify-between gap-4 px-4 py-3.5">
        <div className="flex min-w-0 items-start gap-3">
          <div className={cn("mt-0.5 shrink-0 transition-colors", checked ? "text-foreground" : "text-[var(--text-secondary)]")}>
            {icon}
          </div>
          <div className="min-w-0">
            <div className="text-[12px] font-semibold uppercase tracking-[0.08em] text-[var(--text-primary)]">{label}</div>
            <div className="text-sm text-[var(--text-secondary)]">{description}</div>
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
        <div className="text-sm text-[var(--text-secondary)]">{label}</div>
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

function getFocusableElements(container: HTMLDivElement | null) {
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
          {state === "valid" ? <CheckCircle2 className="size-4 text-success" /> : state === "invalid" ? <CircleAlert className="size-4 text-danger" /> : null}
        </div>
      </div>
    </label>
  );
}

const RecordsTable = memo(function RecordsTable({
  records,
  visibleColumns,
  selectedIds,
  onSelectAll,
  onToggleRow,
}: Readonly<{
  records: CrawlRecord[];
  visibleColumns: string[];
  selectedIds: number[];
  onSelectAll: (checked: boolean) => void;
  onToggleRow: (id: number, checked: boolean) => void;
}>) {
  return (
    <div className="overflow-auto rounded-[10px] border border-border">
      <table className="compact-data-table min-w-[960px]">
        <thead>
          <tr>
            <th className="w-10">
              <input
                type="checkbox"
                checked={selectedIds.length === records.length && records.length > 0}
                onChange={(e) => onSelectAll(e.target.checked)}
              />
            </th>
            {visibleColumns.map((col) => <th key={col}>{col}</th>)}
          </tr>
        </thead>
        <tbody>
          {records.map((record) => (
            <tr key={record.id}>
              <td>
                <input
                  type="checkbox"
                  checked={selectedIds.includes(record.id)}
                  onChange={(e) => onToggleRow(record.id, e.target.checked)}
                />
              </td>
              {visibleColumns.map((col) => (
                <td key={col} title={stringifyCell(readRecordValue(record, col))}>
                  <span className="block max-w-[260px] truncate">
                    {stringifyCell(readRecordValue(record, col)) || <span className="text-muted/50">--</span>}
                  </span>
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
});

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
