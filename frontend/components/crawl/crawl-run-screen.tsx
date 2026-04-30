"use client";

import "./crawl.module.css";

import { useQuery } from "@tanstack/react-query";
import { ArrowRightCircle, Brain, Check, ChevronsDown, Clock, Copy, Download, Info, Plus, Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { cn } from "../../lib/utils";
import {
  DataRegionEmpty,
  DataRegionLoading,
  InlineAlert,
  PageHeader,
  RunSummaryChips,
  RunWorkspaceShell,
  SectionHeader,
  TabBar,
} from "../ui/patterns";
import { Badge, Button, Card, Dropdown, Field, Input, Textarea, Toggle, Tooltip } from "../ui/primitives";
import { api } from "../../lib/api";
import { getApiWebSocketBaseUrl } from "../../lib/api/client";
import type { CrawlLog, CrawlRecord, CrawlRun, DomainRunProfile, ResultSummaryQualityLevel } from "../../lib/api/types";
import { CRAWL_DEFAULTS } from "../../lib/constants/crawl-defaults";
import { ACTIVE_STATUSES } from "../../lib/constants/crawl-statuses";
import { STORAGE_KEYS } from "../../lib/constants/storage-keys";
import { POLLING_INTERVALS, RETRY_LIMITS } from "../../lib/constants/timing";
import { getDomain } from "../../lib/format/domain";
import { telemetryErrorPayload, trackEvent } from "../../lib/telemetry/events";
import { parseApiDate } from "../../lib/format/date";
import { humanizeStatus, runsStatusTone as statusTone } from "../../lib/ui/status";
import {
  ActionButton,
  cleanRecord,
  copyJson,
  decodeUrlsForDisplay,
  extractRecordUrl,
  extractionVerdict,
  extractionVerdictTone,
  formatDuration,
  formatDurationMs,
  estimateDataQuality,
  humanizeVerdict,
  humanizeQuality,
  inferDomainFromSurface,
  isListingRun,
  LogTerminal,
  type OutputTabKey,
  qualityTone,
  RecordsTable,
  scoreFieldQuality,
  scrollViewportToBottom,
  uniqueNumbers,
  uniqueStrings,
} from "./shared";
import { useRunStatusFlags, useTerminalSync } from "./use-run-polling";

type CrawlRunScreenProps = {
  runId: number;
};

function defaultDomainRunProfile(): DomainRunProfile {
  return {
    version: 1,
    fetch_profile: {
      fetch_mode: "auto",
      extraction_source: "raw_html",
      js_mode: "auto",
      include_iframes: false,
      traversal_mode: null,
      request_delay_ms: 500,
    },
    locality_profile: {
      geo_country: "auto",
      language_hint: null,
      currency_hint: null,
    },
    diagnostics_profile: {
      capture_html: true,
      capture_screenshot: false,
      capture_network: "matched_only",
      capture_response_headers: true,
      capture_browser_diagnostics: true,
    },
    source_run_id: null,
    saved_at: null,
  };
}

function cloneDomainRunProfile(profile: DomainRunProfile | null | undefined): DomainRunProfile {
  const base = defaultDomainRunProfile();
  if (!profile) {
    return base;
  }
  return {
    version: 1,
    fetch_profile: {
      ...base.fetch_profile,
      ...(profile.fetch_profile ?? {}),
    },
    locality_profile: {
      ...base.locality_profile,
      ...(profile.locality_profile ?? {}),
    },
    diagnostics_profile: {
      ...base.diagnostics_profile,
      ...(profile.diagnostics_profile ?? {}),
    },
    source_run_id: profile.source_run_id ?? null,
    saved_at: profile.saved_at ?? null,
  };
}

function renderLearningValue(value: unknown) {
  if (value == null) {
    return "—";
  }
  if (
    typeof value === "string"
    || typeof value === "number"
    || typeof value === "boolean"
    || typeof value === "bigint"
    || typeof value === "symbol"
  ) {
    return String(value);
  }
  try {
    return JSON.stringify(value);
  } catch {
    return "[unserializable]";
  }
}

function isSafeHref(href: string) {
  try {
    const base = typeof window === "undefined" ? "http://localhost" : window.location.origin;
    const url = new URL(href, base);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}

type ProductIntelligencePrefillPayload = {
  source_run_id: number | null;
  source_domain: string;
  records: Array<Pick<CrawlRecord, "id" | "run_id" | "source_url" | "data">>;
};

export function storeProductIntelligencePrefill(
  payload: ProductIntelligencePrefillPayload,
  storage: Storage = window.sessionStorage,
) {
  try {
    storage.setItem(
      STORAGE_KEYS.PRODUCT_INTELLIGENCE_PREFILL,
      JSON.stringify(payload),
    );
  } catch (error) {
    console.error("Unable to store full Product Intelligence prefill.", error);
    const reducedPayload = {
      ...payload,
      records: payload.records
        .slice(0, CRAWL_DEFAULTS.TABLE_PAGE_SIZE * 4)
        .map((record) => ({
          id: record.id,
          run_id: record.run_id,
          source_url: record.source_url,
          data: {},
        })),
    };
    try {
      storage.setItem(
        STORAGE_KEYS.PRODUCT_INTELLIGENCE_PREFILL,
        JSON.stringify(reducedPayload),
      );
    } catch (fallbackError) {
      console.error("Unable to store reduced Product Intelligence prefill.", fallbackError);
      storage.removeItem(STORAGE_KEYS.PRODUCT_INTELLIGENCE_PREFILL);
    }
  }
}

export function CrawlRunScreen({ runId }: Readonly<CrawlRunScreenProps>) {
  const router = useRouter();
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [outputTab, setOutputTab] = useState<OutputTabKey>("table");
  const [recipeProfile, setRecipeProfile] = useState<DomainRunProfile>(() => defaultDomainRunProfile());
  const [recipeActionPending, setRecipeActionPending] = useState<"profile" | `field:${string}:${"keep" | "reject"}` | null>(null);
  const [recipeActionError, setRecipeActionError] = useState("");
  const [liveJumpAvailable, setLiveJumpAvailable] = useState(false);
  const [runActionPending, setRunActionPending] = useState<"kill" | null>(null);
  const [runActionError, setRunActionError] = useState("");
  const [tablePage, setTablePage] = useState(1);
  const [tableRecords, setTableRecords] = useState<CrawlRecord[]>([]);
  const [tableTotal, setTableTotal] = useState(0);
  const [jsonVisibleCount, setJsonVisibleCount] = useState(CRAWL_DEFAULTS.TABLE_PAGE_SIZE * 4);
  const [logItems, setLogItems] = useState<CrawlLog[]>([]);
  const [logCursorAfterId, setLogCursorAfterId] = useState<number | undefined>(undefined);
  const [logSocketConnected, setLogSocketConnected] = useState(false);
  const logCursorRef = useRef<number | undefined>(undefined);
  const logViewportRef = useRef<HTMLDivElement | null>(null);
  const sessionStartMsRef = useRef<number>(Date.now());
  const pollErrorEventKeysRef = useRef<Set<string>>(new Set());
  const terminalRecordsRetryAttemptsRef = useRef(0);

  const runQuery = useQuery({
    queryKey: ["crawl-run", runId],
    queryFn: () => api.getCrawl(runId),
    refetchInterval: false,
    refetchOnMount: "always",
  });
  const { refetch: refetchRunQuery } = runQuery;
  const run = runQuery.data;
  const { live, terminal } = useRunStatusFlags(run);
  const shouldFetchTableRecords = Boolean(run) && outputTab === "table";
  const shouldFetchJsonRecords = Boolean(run) && outputTab === "json";
  const shouldFetchLogs = Boolean(run) && (live || outputTab === "logs");
  const shouldFetchMarkdown = Boolean(run) && terminal && outputTab === "markdown";

  const runCreatedMs = run?.created_at ? parseApiDate(run.created_at).getTime() : null;
  const effectiveStartMs = runCreatedMs ?? sessionStartMsRef.current;
  const [localNow, setLocalNow] = useState(Date.now());
  const recordsFetchLimit = Math.min(
    800,
    Math.max(CRAWL_DEFAULTS.TABLE_PAGE_SIZE * 2, jsonVisibleCount),
  );

  useEffect(() => {
    if (!live) return;
    const interval = setInterval(() => setLocalNow(Date.now()), 1000);
    return () => clearInterval(interval);
  }, [live]);

  const tableRecordsQuery = useQuery({
    queryKey: ["crawl-records-table", runId, tablePage],
    queryFn: () => api.getRecords(runId, { page: tablePage, limit: CRAWL_DEFAULTS.TABLE_PAGE_SIZE * 4 }),
    enabled: shouldFetchTableRecords,
    refetchInterval: false,
    refetchOnMount: "always",
  });
  const { refetch: refetchTableRecords } = tableRecordsQuery;

  const jsonRecordsQuery = useQuery({
    queryKey: ["crawl-records-json", runId, recordsFetchLimit],
    queryFn: () => api.getRecords(runId, { limit: recordsFetchLimit }),
    enabled: shouldFetchJsonRecords,
    refetchInterval: false,
    refetchOnMount: "always",
  });
  const { refetch: refetchJsonRecords } = jsonRecordsQuery;

  const logsQuery = useQuery({
    queryKey: ["crawl-logs", runId],
    queryFn: () => api.getCrawlLogs(runId, { afterId: logCursorRef.current, limit: CRAWL_DEFAULTS.MAX_LIVE_LOGS }),
    enabled: shouldFetchLogs,
    refetchInterval: false,
  });
  const { refetch: refetchLogsQuery } = logsQuery;
  const markdownQuery = useQuery({
    queryKey: ["crawl-markdown", runId],
    queryFn: () => api.getMarkdown(runId),
    enabled: shouldFetchMarkdown,
    refetchInterval: false,
  });
  const { refetch: refetchMarkdownQuery } = markdownQuery;
  const domainRecipeQuery = useQuery({
    queryKey: ["crawl-domain-recipe", runId],
    queryFn: () => api.getDomainRecipe(runId),
    enabled: Boolean(run) && terminal,
    refetchInterval: false,
    refetchOnMount: "always",
  });
  const { refetch: refetchDomainRecipeQuery } = domainRecipeQuery;

  const records = useMemo(() => jsonRecordsQuery.data?.items ?? [], [jsonRecordsQuery.data?.items]);
  const recordsFetchCapReached = useMemo(
    () => records.length >= recordsFetchLimit && recordsFetchLimit >= 800,
    [records, recordsFetchLimit],
  );
  const recordsTotal = jsonRecordsQuery.data?.meta?.total ?? records.length;
  const jsonRecords = useMemo(
    () => records.slice(0, Math.min(records.length, jsonVisibleCount)),
    [records, jsonVisibleCount],
  );
  const deferredJsonRecords = useDeferredValue(jsonRecords);
  const hasMoreTableRecords = tableRecords.length < tableTotal;
  const hasMoreJsonRecords =
    jsonRecords.length < records.length || (records.length < recordsTotal && !recordsFetchCapReached);
  const logs = useMemo(() => logItems.slice(-CRAWL_DEFAULTS.MAX_LIVE_LOGS), [logItems]);
  const markdown = markdownQuery.data ?? "";
  const domainRecipe = domainRecipeQuery.data;
  const recordsJson = useMemo(
    () =>
      outputTab === "json"
        ? JSON.stringify(deferredJsonRecords.map((record) => decodeUrlsForDisplay(cleanRecord(record))), null, 2)
        : "",
    [deferredJsonRecords, outputTab],
  );
  const showRunLoadingState = runQuery.isLoading && !run;
  const panelRefreshErrors = useMemo(() => [
    {
      key: "run",
      label: "run",
      error: runQuery.error,
      refetch: refetchRunQuery,
    },
    {
      key: "records",
      label: "records",
      error: tableRecordsQuery.error ?? jsonRecordsQuery.error,
      refetch: async () => {
        const tasks: Array<Promise<unknown>> = [];
        if (tableRecordsQuery.error) {
          tasks.push(refetchTableRecords());
        }
        if (jsonRecordsQuery.error) {
          tasks.push(refetchJsonRecords());
        }
        if (!tasks.length) {
          tasks.push(refetchTableRecords(), refetchJsonRecords());
        }
        await Promise.allSettled(tasks);
      },
    },
    {
      key: "logs",
      label: "logs",
      error: logsQuery.error,
      refetch: refetchLogsQuery,
    },
    {
      key: "markdown",
      label: "markdown",
      error: markdownQuery.error,
      refetch: refetchMarkdownQuery,
    },
    {
      key: "domain-recipe",
      label: "domain recipe",
      error: domainRecipeQuery.error,
      refetch: refetchDomainRecipeQuery,
    },
  ].filter((panel) => panel.error), [
    runQuery.error,
    tableRecordsQuery.error,
    jsonRecordsQuery.error,
    logsQuery.error,
    markdownQuery.error,
    domainRecipeQuery.error,
    refetchRunQuery,
    refetchTableRecords,
    refetchJsonRecords,
    refetchLogsQuery,
    refetchMarkdownQuery,
    refetchDomainRecipeQuery,
  ]);

  useEffect(() => {
    if (!domainRecipe) {
      return;
    }
    setRecipeProfile(cloneDomainRunProfile(domainRecipe.saved_run_profile));
    setRecipeActionError("");
  }, [domainRecipe]);

  useTerminalSync(run, terminal, [runQuery, tableRecordsQuery, jsonRecordsQuery, logsQuery, markdownQuery]);

  useEffect(() => {
    if (!tableRecordsQuery.data) {
      return;
    }
    const nextItems = tableRecordsQuery.data.items ?? [];
    const nextTotal = tableRecordsQuery.data.meta?.total ?? nextItems.length;
    setTableTotal(nextTotal);
    setTableRecords((current) => {
      if (tablePage === 1) {
        return nextItems;
      }
      const byId = new Map<number, CrawlRecord>();
      for (const row of current) byId.set(row.id, row);
      for (const row of nextItems) byId.set(row.id, row);
      return Array.from(byId.values()).sort((a, b) => a.id - b.id);
    });
  }, [tableRecordsQuery.data, tablePage]);

  useEffect(() => {
    if (!logsQuery.data || !logsQuery.data.length) {
      return;
    }
    setLogItems((current) => {
      const byId = new Map<number, CrawlLog>();
      for (const row of current) byId.set(row.id, row);
      for (const row of logsQuery.data) byId.set(row.id, row);
      return Array.from(byId.values())
        .sort((a, b) => a.id - b.id)
        .slice(-CRAWL_DEFAULTS.MAX_LIVE_LOGS);
    });
    const latest = logsQuery.data.at(-1);
    if (latest?.id !== undefined) {
      setLogCursorAfterId((current) => (current && current > latest.id ? current : latest.id));
    }
  }, [logsQuery.data]);

  useEffect(() => {
    logCursorRef.current = logCursorAfterId;
  }, [logCursorAfterId]);

  useEffect(() => {
    const isJsdom = typeof navigator !== "undefined" && /jsdom/i.test(navigator.userAgent);
    if (!shouldFetchLogs || typeof window === "undefined" || typeof WebSocket === "undefined" || isJsdom) {
      setLogSocketConnected(false);
      return;
    }
    const socketCursor = logCursorRef.current;
    const query = new URLSearchParams();
    if (socketCursor !== undefined) {
      query.set("after_id", String(socketCursor));
    }
    const queryString = query.toString();
    const wsUrl = `${getApiWebSocketBaseUrl()}/api/crawls/${runId}/logs/ws${queryString ? `?${queryString}` : ""}`;
    const ws = new WebSocket(wsUrl);

    ws.onopen = () => setLogSocketConnected(true);
    ws.onclose = () => {
      setLogSocketConnected(false);
      // When the backend closes the stream at terminal status, refresh immediately
      // so the completed screen appears without manual page refresh.
      void refetchRunQuery();
      void refetchLogsQuery();
    };
    ws.onerror = () => setLogSocketConnected(false);
    ws.onmessage = (event) => {
      try {
        const parsed = JSON.parse(event.data) as CrawlLog;
        if (!parsed || typeof parsed.id !== "number") {
          return;
        }
        setLogItems((current) => {
          const byId = new Map<number, CrawlLog>();
          for (const row of current) byId.set(row.id, row);
          byId.set(parsed.id, parsed);
          return Array.from(byId.values())
            .sort((a, b) => a.id - b.id)
            .slice(-CRAWL_DEFAULTS.MAX_LIVE_LOGS);
        });
        setLogCursorAfterId((current) => (current && current > parsed.id ? current : parsed.id));
      } catch {
        // Ignore malformed websocket payloads and rely on polling fallback.
      }
    };
    return () => ws.close();
  }, [refetchLogsQuery, refetchRunQuery, runId, shouldFetchLogs]);

  useEffect(() => {
    if (!live) {
      return;
    }

    const refetchPanels = () => {
      const tasks: Array<Promise<unknown>> = [refetchRunQuery()];
      if (shouldFetchTableRecords) {
        tasks.push(refetchTableRecords());
      }
      if (shouldFetchJsonRecords) {
        tasks.push(refetchJsonRecords());
      }
      if (shouldFetchLogs && !logSocketConnected) {
        tasks.push(refetchLogsQuery());
      }
      if (shouldFetchMarkdown) {
        tasks.push(refetchMarkdownQuery());
      }
      void Promise.allSettled(tasks);
    };

    const intervalId = window.setInterval(refetchPanels, POLLING_INTERVALS.ACTIVE_JOB_MS);
    return () => window.clearInterval(intervalId);
  }, [
    live,
    logSocketConnected,
    shouldFetchLogs,
    shouldFetchJsonRecords,
    shouldFetchMarkdown,
    shouldFetchTableRecords,
    refetchRunQuery,
    refetchTableRecords,
    refetchJsonRecords,
    refetchLogsQuery,
    refetchMarkdownQuery,
  ]);

  useEffect(() => {
    for (const panel of panelRefreshErrors) {
      const message = panel.error instanceof Error ? panel.error.message : "Unknown error";
      const eventKey = `${runId}:${panel.key}:${message}`;
      if (pollErrorEventKeysRef.current.has(eventKey)) {
        continue;
      }
      pollErrorEventKeysRef.current.add(eventKey);
      trackEvent(
        "run_screen_poll_error_rate",
        telemetryErrorPayload(panel.error, {
          run_id: runId,
          panel: panel.key,
          live,
          terminal,
        }),
      );
    }
  }, [live, panelRefreshErrors, runId, terminal]);

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

  const terminalRecordCount = Math.max(
    tableTotal,
    recordsTotal,
    Number(run?.result_summary?.record_count ?? 0) || 0,
  );

  useEffect(() => {
    if (!run) {
      return;
    }
    if (
      (run.status === "failed" || run.status === "proxy_exhausted") &&
      outputTab === "table" &&
      terminalRecordCount === 0
    ) {
      setOutputTab("logs");
    }
  }, [outputTab, run, terminalRecordCount]);

  const visibleColumns = useMemo(() => {
    const columns = new Set<string>();
    for (const record of [...tableRecords, ...records]) {
      for (const source of [record.data, record.raw_data]) {
        Object.keys(source ?? {}).forEach((key) => {
          if (!key.startsWith("_")) {
            columns.add(key);
          }
        });
      }
    }
    return Array.from(columns);
  }, [tableRecords, records]);

  const filteredTableRecords = tableRecords;

  useEffect(() => {
    const availableRecordIds = new Set(
      (outputTab === "table" ? filteredTableRecords : records).map((record) => record.id),
    );
    setSelectedIds((current) => {
      const next = current.filter((id) => availableRecordIds.has(id));
      if (next.length === current.length && next.every((id, index) => id === current[index])) {
        return current;
      }
      return next;
    });
  }, [filteredTableRecords, outputTab, records]);

  const selectedRecords = useMemo(
    () => (outputTab === "table" ? filteredTableRecords : records).filter((record) => selectedIds.includes(record.id)),
    [filteredTableRecords, outputTab, records, selectedIds],
  );
  const batchSourceRecords = useMemo(
    () => (tableRecords.length ? tableRecords : records),
    [records, tableRecords],
  );
  const resultUrls = useMemo(
    () => uniqueStrings(batchSourceRecords.map((record) => extractRecordUrl(record))),
    [batchSourceRecords],
  );
  const selectedResultUrls = useMemo(
    () => uniqueStrings(selectedRecords.map((record) => extractRecordUrl(record))),
    [selectedRecords],
  );
  const listingRun = useMemo(() => isListingRun(run), [run]);
  const verdict = extractionVerdict(run);
  const runErrorMessage =
    typeof run?.result_summary?.error === "string" ? run.result_summary.error : "";
  const persistedQualityLevel = useMemo(() => {
    const level = String(run?.result_summary?.quality_summary?.level ?? "").trim().toLowerCase();
    if (level === "high" || level === "medium" || level === "low" || level === "unknown") {
      return level as ResultSummaryQualityLevel;
    }
    return null;
  }, [run?.result_summary?.quality_summary?.level]);
  const quality = useMemo(
    () => estimateDataQuality(tableRecords.length ? tableRecords : records, visibleColumns),
    [tableRecords, records, visibleColumns],
  );
  const completedQualityLevel = terminal ? (persistedQualityLevel ?? quality.level) : quality.level;
  const emptyRecordsState = verdict === "blocked"
    ? {
      title: "Access blocked",
      description: "The target site blocked acquisition for this run. Check Logs or browser diagnostics for challenge details.",
    }
    : {
      title: "No records captured yet",
      description: "Records will appear here once extraction returns rows.",
    };
  const batchFromResultsUrls = selectedResultUrls.length ? selectedResultUrls : resultUrls;
  const batchFromResultsLabel = selectedResultUrls.length
    ? `Batch Crawl Selected (${selectedResultUrls.length})`
    : `Batch Crawl (${resultUrls.length})`;
  const productIntelligenceRecords = selectedRecords.length ? selectedRecords : batchSourceRecords;
  const productIntelligenceLabel = selectedRecords.length
    ? `Product Intelligence Selected (${selectedRecords.length})`
    : `Product Intelligence (${productIntelligenceRecords.length})`;

  const summaryRecordsFromRun = Number(run?.result_summary?.record_count ?? 0) || 0;
  const summaryRecordsFromTable =
    Number(tableRecordsQuery.data?.meta?.total ?? tableRecordsQuery.data?.items?.length ?? 0) || 0;
  const summaryPagesFromRun =
    Number(run?.result_summary?.processed_urls ?? run?.result_summary?.completed_urls ?? 0) || 0;
  const summaryCurrentUrlIndex = Number(run?.result_summary?.current_url_index ?? 0) || 0;
  const summary = {
    records: Math.max(summaryRecordsFromRun, recordsTotal, summaryRecordsFromTable),
    pages: Math.max(
      summaryPagesFromRun,
      summaryCurrentUrlIndex,
      Number(run?.result_summary?.progress ?? 0) > 0 ? 1 : 0,
    ),
    fields: visibleColumns.length,
    duration:
      (terminal ? formatDurationMs(run?.result_summary?.duration_ms) : null) ??
      formatDuration(
        new Date(effectiveStartMs).toISOString(),
        terminal ? run?.completed_at : new Date(localNow).toISOString(),
      ),
  };

  const knownTableRecordsTotal = Math.max(
    tableTotal,
    tableRecordsQuery.data?.meta?.total ?? 0,
  );
  const terminalRecordsExpected =
    terminal && (summaryRecordsFromRun > 0 || verdict === "success" || verdict === "partial");
  const terminalRecordsNeedSync =
    terminalRecordsExpected &&
    knownTableRecordsTotal < Math.max(1, summaryRecordsFromRun);

  useEffect(() => {
    if (!terminalRecordsNeedSync) {
      terminalRecordsRetryAttemptsRef.current = 0;
      return;
    }

    const intervalId = window.setInterval(() => {
      if (
        terminalRecordsRetryAttemptsRef.current >=
        RETRY_LIMITS.TERMINAL_RECORDS_RETRY_LIMIT
      ) {
        window.clearInterval(intervalId);
        return;
      }
      terminalRecordsRetryAttemptsRef.current += 1;
      void Promise.allSettled([refetchTableRecords(), refetchJsonRecords()]);
    }, POLLING_INTERVALS.RECORDS_MS);

    return () => window.clearInterval(intervalId);
  }, [refetchJsonRecords, refetchTableRecords, terminalRecordsNeedSync]);

  function downloadExport(kind: "csv" | "json" | "markdown") {
    setRunActionError("");
    const filename = `run-${runId}.${kind === "markdown" ? "md" : kind}`;
    try {
      const href =
        kind === "csv"
          ? api.exportCsv(runId)
          : kind === "json"
            ? api.exportJson(runId)
            : api.exportMarkdown(runId);
      const anchor = document.createElement("a");
      anchor.href = href;
      anchor.download = filename;
      anchor.style.display = "none";
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
    } catch (error) {
      setRunActionError(error instanceof Error ? error.message : "Unable to download export.");
    }
  }

  async function runControl() {
    setRunActionPending("kill");
    setRunActionError("");
    try {
      await api.killCrawl(runId);
      await Promise.all([
        runQuery.refetch(),
        logsQuery.refetch(),
        tableRecordsQuery.refetch(),
        jsonRecordsQuery.refetch(),
        markdownQuery.refetch(),
      ]);
    } catch (error) {
      setRunActionError(error instanceof Error ? error.message : "Unable to kill crawl.");
    } finally {
      setRunActionPending(null);
    }
  }

  function resetToConfig() {
    router.replace("/crawl?module=category&mode=single");
  }

  async function retryFailedPanels() {
    if (!panelRefreshErrors.length) {
      return;
    }
    await Promise.allSettled(panelRefreshErrors.map((panel) => panel.refetch()));
  }

  function triggerBatchCrawlFromResults() {
    const urls = batchFromResultsUrls;
    if (!urls.length) {
      return;
    }
    const domain = inferDomainFromSurface(run?.surface) ?? "commerce";
    window.sessionStorage.setItem(
      STORAGE_KEYS.BULK_PREFILL,
      JSON.stringify({
        domain,
        urls,
      }),
    );
    router.replace("/crawl?module=pdp&mode=batch");
  }

  function triggerProductIntelligenceFromResults() {
    if (!productIntelligenceRecords.length) {
      return;
    }
    storeProductIntelligencePrefill({
      source_run_id: run?.id ?? null,
      source_domain: run?.url ?? "",
      records: productIntelligenceRecords.map((record) => ({
        id: record.id,
        run_id: record.run_id,
        source_url: record.source_url,
        data: record.data,
      })),
    });
    router.replace("/product-intelligence");
  }

  async function saveRecipeRunProfile() {
    setRecipeActionPending("profile");
    setRecipeActionError("");
    try {
      await api.saveDomainRunProfile(runId, {
        profile: recipeProfile,
      });
      await refetchDomainRecipeQuery();
    } catch (error) {
      setRecipeActionError(error instanceof Error ? error.message : "Unable to save the domain run profile.");
    } finally {
      setRecipeActionPending(null);
    }
  }

  async function applyFieldLearningAction(fieldName: string, action: "keep" | "reject", selectorKind?: string | null, selectorValue?: string | null, sourceRecordIds?: number[]) {
    const pendingKey = `field:${fieldName}:${action}` as const;
    setRecipeActionPending(pendingKey);
    setRecipeActionError("");
    try {
      await api.applyDomainRecipeFieldAction(runId, {
        field_name: fieldName,
        action,
        selector_kind: selectorKind ?? null,
        selector_value: selectorValue ?? null,
        source_record_ids: sourceRecordIds ?? [],
      });
      await refetchDomainRecipeQuery();
    } catch (error) {
      setRecipeActionError(error instanceof Error ? error.message : `Unable to ${action} this field learning signal.`);
    } finally {
      setRecipeActionPending(null);
    }
  }

  if (runQuery.error) {
    return (
      <div className="page-stack">
        <PageHeader
          title="Crawl Studio"
          actions={
            <Button variant="primary" type="button" className="h-[var(--control-height)]" onClick={resetToConfig}>
              <Plus className="size-3.5" />
              New Crawl
            </Button>
          }
        />
        <Card className="space-y-3 px-6 py-8">
          <SectionHeader title="Unable to Load Crawl" description="The run workspace could not be restored." />
          <div className="text-sm leading-[var(--leading-relaxed)] text-danger">
            {runQuery.error instanceof Error ? runQuery.error.message : "Unknown crawl loading error."}
          </div>
        </Card>
      </div>
    );
  }

  return (
    <div className="page-stack gap-4">
      <PageHeader
        title={run?.url ? (
          <span className="flex items-center gap-1.5">
            Run Details: <a href={run.url} target="_blank" rel="noreferrer" className="type-mono-standard text-accent underline-offset-2 hover:underline">{getDomain(run.url)}</a>
          </span>
        ) : "Crawl Results"}
        actions={
          <Button variant="primary" type="button" className="h-[var(--control-height)]" onClick={resetToConfig}>
            <Plus className="size-3.5" />
            New Crawl
          </Button>
        }
      />



      {showRunLoadingState ? (
        <Card className="space-y-3 px-6 py-8">
          <SectionHeader title="Loading Crawl" description="Fetching run details and restoring the workspace." />
          <div className="text-sm leading-[var(--leading-relaxed)] text-muted">Run #{runId} is loading.</div>
        </Card>
      ) : null}

      {panelRefreshErrors.length ? (
        <Card className="space-y-3">
          <SectionHeader
            title="Some live panels failed to refresh"
            description="Data may be stale until these requests recover."
          />
          <InlineAlert
            message={(
              <div className="space-y-1">
                {panelRefreshErrors.map((panel) => (
                  <div key={panel.key}>
                    Unable to refresh {panel.label}:{""}
                    {panel.error instanceof Error ? panel.error.message : "Unknown error."}
                  </div>
                ))}
              </div>
            )}
          />
          <div>
            <Button variant="secondary" type="button" className="h-[var(--control-height)]" onClick={() => void retryFailedPanels()}>
              Retry failed panels
            </Button>
          </div>
        </Card>
      ) : null}
      {!showRunLoadingState && !terminal ? (
        <Card className="section-card overflow-hidden">
          <header className="cs-panel-header">
            <span className="cs-panel-title flex items-center gap-2">
              Live Log Stream
              {logSocketConnected ? <span className="cs-live-dot is-success" /> : <span className="cs-live-dot" />}
            </span>
            <div className="flex items-center gap-3">
              {run ? (
                <span className="inline-flex items-center gap-1.5 rounded border border-divider bg-background-elevated px-2.5 py-1 font-mono text-sm tabular-nums text-foreground">
                  <Clock className="size-3.5" />
                  {(() => {
                    const elapsedMs = Math.max(0, localNow - effectiveStartMs);
                    const totalS = Math.floor(elapsedMs / 1000);
                    const m = Math.floor(totalS / 60);
                    const s = totalS % 60;
                    return `${m}m ${String(s).padStart(2, "0")}s`;
                  })()}
                </span>
              ) : null}

              {liveJumpAvailable ? (
                <button
                  type="button"
                  onClick={() => {
                    scrollViewportToBottom(logViewportRef);
                    setLiveJumpAvailable(false);
                  }}
                  className="bg-background-alt rounded-lg shadow-card inline-flex items-center gap-1 px-2.5 py-1.5 text-sm leading-[var(--leading-normal)]"
                >
                  <ChevronsDown className="size-3.5" aria-hidden="true" />
                  Jump to Latest
                </button>
              ) : null}
              <ActionButton
                label={runActionPending === "kill" ? "Killing..." : "Hard Kill"}
                onClick={() => void runControl()}
                disabled={!run || !ACTIVE_STATUSES.has(run.status) || runActionPending !== null}
                danger
              />
            </div>
          </header>
          <LogTerminal logs={logs} records={batchSourceRecords} requestedFields={run?.requested_fields ?? []} live viewportRef={logViewportRef} />
        </Card>
      ) : null}

      {!showRunLoadingState && terminal ? (
        <div className="space-y-4">
          <Card className="section-card">
            {runErrorMessage ? <InlineAlert tone="danger" message={runErrorMessage} /> : null}
            {runActionError ? <InlineAlert tone="danger" message={runActionError} /> : null}
            <RunWorkspaceShell
              header={
                run?.url ? (
                  <a
                    href={run.url}
                    target="_blank"
                    rel="noreferrer"
                    className="type-mono-standard link-accent block truncate leading-[1.4] underline-offset-2 hover:underline"
                  >
                    {run.url}
                  </a>
                ) : (
                  <p className="text-sm leading-[var(--leading-relaxed)] text-muted">Waiting for completed run data.</p>
                )
              }
              actions={
                <>
                  {listingRun && batchFromResultsUrls.length ? (
                    <Button variant="accent" type="button" onClick={triggerBatchCrawlFromResults}>
                      <ArrowRightCircle className="size-3.5" />
                      {batchFromResultsLabel}
                    </Button>
                  ) : null}
                  {listingRun && productIntelligenceRecords.length ? (
                    <Button variant="secondary" type="button" onClick={triggerProductIntelligenceFromResults}>
                      <Brain className="size-3.5" />
                      {productIntelligenceLabel}
                    </Button>
                  ) : null}
                  <Button variant="secondary" type="button" onClick={() => void downloadExport("csv")}>
                    <Download className="size-3.5" />
                    Excel (CSV)
                  </Button>
                  <Button variant="secondary" type="button" onClick={() => void downloadExport("json")}>
                    <Download className="size-3.5" />
                    JSON
                  </Button>
                  <Button variant="secondary" type="button" onClick={() => void downloadExport("markdown")}>
                    <Download className="size-3.5" />
                    Markdown
                  </Button>
                </>
              }
              tabs={
                <TabBar
                  value={outputTab}
                  variant="underline"
                  onChange={(value) => setOutputTab(value as OutputTabKey)}
                  options={[
                    { value: "table", label: `Table (${summary.records})` },
                    { value: "json", label: "JSON" },
                    { value: "markdown", label: "Markdown" },
                    { value: "logs", label: "Logs" },
                    { value: "learning", label: "Learning" },
                    { value: "run_config", label: "Run Config" },
                  ]}
                />
              }
              summary={
                <RunSummaryChips
                  duration={summary.duration}
                  verdict={humanizeVerdict(verdict).toLowerCase()}
                  quality={humanizeQuality(completedQualityLevel).toLowerCase()}
                />
              } content={
                <>
                  {outputTab === "table" ? (
                    <div className="space-y-3 min-h-[55vh]">
                      {tableRecordsQuery.isLoading && !tableRecords.length ? (
                        <DataRegionLoading count={5} className="px-0" />
                      ) : tableRecords.length ? (
                        <div className="space-y-3">
                          <RecordsTable
                            records={filteredTableRecords}
                            visibleColumns={visibleColumns}
                            selectedIds={selectedIds}
                            onSelectAll={(checked) => setSelectedIds(checked ? filteredTableRecords.map((record) => record.id) : [])}
                            onToggleRow={(id, checked) =>
                              setSelectedIds((current) =>
                                checked ? uniqueNumbers([...current, id]) : current.filter((value) => value !== id),
                              )
                            }
                          />
                          {hasMoreTableRecords ? (
                            <div className="surface-muted flex items-center justify-between rounded-lg px-3 py-2 text-sm leading-[var(--leading-normal)] text-muted">
                              <span>
                                Showing {tableRecords.length} of {tableTotal} records
                              </span>
                              <Button
                                variant="secondary"
                                type="button"
                                onClick={() => setTablePage((current) => current + 1)}
                              >
                                Load More
                              </Button>
                            </div>
                          ) : null}
                          {tableRecords.length < tableTotal && hasMoreTableRecords ? (
                            <InlineAlert
                              tone="warning"
                              message={`Table view is currently showing ${tableRecords.length} of ${tableTotal} records. Load more rows or export JSON/CSV for the full dataset.`}
                            />
                          ) : null}
                        </div>
                      ) : (
                        <DataRegionEmpty
                          title={emptyRecordsState.title}
                          description={emptyRecordsState.description}
                          className="px-0"
                        />
                      )}
                    </div>
                  ) : null}

                  {outputTab === "json" ? (
                    <div className="relative min-h-[55vh]">
                      <div className="absolute right-2 top-2 z-10 flex items-center gap-2">
                        <Button variant="ghost" type="button" onClick={() => void copyJson(records)}>
                          <Copy className="size-3.5" />
                          Copy
                        </Button>
                      </div>
                      <pre className="crawl-terminal crawl-terminal-json min-h-[55vh] max-h-[72vh] overflow-y-auto pt-14 pb-4">
                        {recordsJson}
                      </pre>
                      {hasMoreJsonRecords ? (
                        <div className="surface-muted mt-2 flex items-center justify-between rounded-[var(--radius-md)] px-3 py-2 text-sm leading-[var(--leading-normal)] text-muted">
                          <span>
                            JSON previewing {jsonRecords.length} of {recordsTotal} records
                          </span>
                          <Button
                            variant="secondary"
                            type="button"
                            onClick={() => setJsonVisibleCount((current) => current + CRAWL_DEFAULTS.TABLE_PAGE_SIZE * 4)}
                          >
                            Load More JSON
                          </Button>
                        </div>
                      ) : null}
                      {records.length < recordsTotal && recordsFetchCapReached ? (
                        <InlineAlert
                          tone="warning"
                          message={`JSON preview capped at ${records.length} records for performance. Use JSON export for all ${recordsTotal} records.`}
                        />
                      ) : null}
                    </div>
                  ) : null}

                  {outputTab === "markdown" ? (
                    <div className="relative min-h-[55vh]">
                      <div className="absolute right-2 top-2 z-10 flex items-center gap-2">
                        <Button
                          variant="ghost"
                          type="button"
                          onClick={() => void navigator.clipboard.writeText(markdown)}
                          disabled={!markdown}
                        >
                          <Copy className="size-3.5" />
                          Copy
                        </Button>
                      </div>
                      {markdownQuery.isLoading && !markdown ? (
                        <div className="surface-muted space-y-2 rounded-lg px-3 pb-3 pt-12">
                          {Array.from({ length: 8 }, (_, index) => (
                            <div key={index} className="skeleton h-5 w-full rounded-[var(--radius-md)]" />
                          ))}
                        </div>
                      ) : markdown ? (
                        <div className="surface-muted min-h-[55vh] max-h-[72vh] rounded-lg overflow-y-auto px-3 pb-3 pt-12">
                          <article className="markdown-document max-w-none">
                            <ReactMarkdown
                              remarkPlugins={[remarkGfm]}
                              components={{
                                a: ({ node: _node, ...props }) =>
                                  props.href && isSafeHref(props.href) ? (
                                    <a {...props} target="_blank" rel="noopener noreferrer" />
                                  ) : (
                                    <span>{props.children}</span>
                                  ),
                              }}
                            >
                              {markdown}
                            </ReactMarkdown>
                          </article>
                        </div>
                      ) : (
                        <div className="surface-muted grid min-h-40 place-items-center rounded-lg border-dashed text-sm leading-[var(--leading-relaxed)] text-muted">
                          No markdown is available for this run.
                        </div>
                      )}
                    </div>
                  ) : null}

                  {outputTab === "logs" ? (
                    <div className="min-h-[55vh]">
                      <LogTerminal logs={logs} records={batchSourceRecords} requestedFields={run?.requested_fields ?? []} viewportRef={logViewportRef} />
                    </div>
                  ) : null}

                  {outputTab === "learning" ? (
                    <div className="space-y-4 min-h-[55vh]">
                      {domainRecipeQuery.isLoading ? (
                        <Card className="section-card">
                          <SectionHeader title="Run Learning" description="Loading keep and reject recommendations for this run." />
                        </Card>
                      ) : domainRecipe ? (
                        <div className="space-y-4">
                          {recipeActionError ? <InlineAlert tone="danger" message={recipeActionError} /> : null}
                          <Card className="section-card space-y-4">
                            <SectionHeader
                              title="Run Learning"
                              description={`Review extraction evidence for ${domainRecipe.domain} on ${domainRecipe.surface}. Keep what should compound, reject what should not.`}
                            />
                            <div className="grid gap-3 md:grid-cols-2">
                              <div className="surface-muted rounded-lg px-3 py-3 text-sm leading-[var(--leading-relaxed)] text-secondary">
                                <div className="field-label mb-1">Requested Coverage</div>
                                Requested: {domainRecipe.requested_field_coverage.requested.join(", ") || "None"}
                                <br />
                                Found: {domainRecipe.requested_field_coverage.found.join(", ") || "None"}
                                <br />
                                Missing: {domainRecipe.requested_field_coverage.missing.join(", ") || "None"}
                              </div>
                              <div className="surface-muted rounded-lg px-3 py-3 text-sm leading-[var(--leading-relaxed)] text-secondary">
                                <div className="field-label mb-1">Acquisition Evidence</div>
                                Method: {domainRecipe.acquisition_evidence.actual_fetch_method || "—"}
                                <br />
                                Browser Used: {domainRecipe.acquisition_evidence.browser_used ? "Yes" : "No"}
                                <br />
                                Browser Reason: {domainRecipe.acquisition_evidence.browser_reason || "—"}
                                <br />
                                Cookie Memory: {domainRecipe.acquisition_evidence.cookie_memory_available ? "Saved" : domainRecipe.acquisition_evidence.browser_used ? "No reusable state observed" : "Not applicable"}
                              </div>
                            </div>

                            <div className="space-y-3">
                              <div>
                                <div className="field-label mb-0">Field Learning</div>
                                <p className="mt-1 text-sm leading-[var(--leading-normal)] text-secondary">Keep accepted field evidence or reject bad field evidence for future runs on this domain and surface.</p>
                              </div>
                              {domainRecipe.field_learning.length ? (
                                <div className="space-y-2">
                                  {domainRecipe.field_learning.map((item) => {
                                    const keepPending = recipeActionPending === `field:${item.field_name}:keep`;
                                    const rejectPending = recipeActionPending === `field:${item.field_name}:reject`;
                                    return (
                                      <div key={`${item.field_name}:${item.selector_kind ?? "source"}:${item.selector_value ?? item.source_labels.join(",")}`} className="rounded-lg border border-divider bg-background px-3 py-3 text-sm">
                                        <div className="flex flex-wrap items-start justify-between gap-3">
                                          <div className="min-w-0 flex-1">
                                            <div className="flex flex-wrap items-center gap-2">
                                              <span className="font-medium text-foreground">{item.field_name}</span>
                                              {item.selector_kind ? <Badge tone="info">{item.selector_kind}</Badge> : <Badge tone="neutral">non-selector</Badge>}
                                              {item.feedback ? <Badge tone={item.feedback.action === "reject" ? "warning" : "success"}>{item.feedback.action}</Badge> : null}
                                            </div>
                                            <div className="mt-1 text-xs text-muted">
                                              Value: {renderLearningValue(item.value)} · Sources: {item.source_labels.join(", ") || "—"}
                                            </div>
                                            {item.selector_value ? <code className="mt-2 block truncate text-xs">{item.selector_value}</code> : null}
                                          </div>
                                          <div className="flex flex-wrap gap-2">
                                            <Button variant="secondary" type="button" size="sm" disabled={recipeActionPending !== null} onClick={() => void applyFieldLearningAction(item.field_name, "keep", item.selector_kind, item.selector_value, item.source_record_ids)}>
                                              {keepPending ? "Keeping..." : "Keep"}
                                            </Button>
                                            <Button variant="ghost" type="button" size="sm" disabled={recipeActionPending !== null} onClick={() => void applyFieldLearningAction(item.field_name, "reject", item.selector_kind, item.selector_value, item.source_record_ids)}>
                                              {rejectPending ? "Rejecting..." : "Reject"}
                                            </Button>
                                          </div>
                                        </div>
                                      </div>
                                    );
                                  })}
                                </div>
                              ) : (
                                <div className="surface-muted rounded-lg border-dashed px-3 py-3 text-sm leading-[var(--leading-relaxed)] text-secondary">
                                  No field learning signals were captured for this run.
                                </div>
                              )}
                            </div>
                          </Card>
                        </div>
                      ) : (
                        <DataRegionEmpty
                          title="No learning data available"
                          description="This run did not produce reusable field-learning evidence."
                          className="px-0"
                        />
                      )}
                    </div>
                  ) : null}

                  {outputTab === "run_config" ? (
                    <div className="space-y-4 min-h-[55vh]">
                      {domainRecipeQuery.isLoading ? (
                        <Card className="section-card">
                          <SectionHeader title="Run Config" description="Loading saved run profile defaults for this domain." />
                        </Card>
                      ) : domainRecipe ? (
                        <Card className="section-card space-y-4">
                          <SectionHeader
                            title="Run Config"
                            description={`Edit and save the reusable fetch profile for ${domainRecipe.domain}. These defaults are applied to future single-URL runs on ${domainRecipe.surface}.`}
                          />
                          {recipeActionError ? <InlineAlert tone="danger" message={recipeActionError} /> : null}
                          <div className="flex items-center justify-between gap-3">
                            <div className="text-sm leading-[var(--leading-relaxed)] text-secondary">
                              Saved profile source run: {domainRecipe.saved_run_profile?.source_run_id ?? "—"} · Last saved: {domainRecipe.saved_run_profile?.saved_at ?? "Not saved yet"}
                            </div>
                            <Button
                              variant="accent"
                              type="button"
                              onClick={() => void saveRecipeRunProfile()}
                              disabled={recipeActionPending === "profile"}
                            >
                              {recipeActionPending === "profile" ? "Saving..." : "Save Run Profile"}
                            </Button>
                          </div>
                          <div className="grid gap-3 md:grid-cols-3">
                            <div className="grid gap-3 md:col-span-2 md:grid-cols-2 content-start">
                              <Field label="Fetch Mode">
                                <Dropdown
                                  value={recipeProfile.fetch_profile.fetch_mode}
                                  onChange={(value) =>
                                    setRecipeProfile((current) => ({
                                      ...current,
                                      fetch_profile: {
                                        ...current.fetch_profile,
                                        fetch_mode: value,
                                      },
                                    }))
                                  }
                                  options={[
                                    { value: "auto", label: "Auto" },
                                    { value: "http_only", label: "HTTP Only" },
                                    { value: "browser_only", label: "Browser Only" },
                                    { value: "http_then_browser", label: "HTTP Then Browser" },
                                  ]}
                                />
                              </Field>
                              <Field label="Extraction Source">
                                <Dropdown
                                  value={recipeProfile.fetch_profile.extraction_source}
                                  onChange={(value) =>
                                    setRecipeProfile((current) => ({
                                      ...current,
                                      fetch_profile: {
                                        ...current.fetch_profile,
                                        extraction_source: value,
                                      },
                                    }))
                                  }
                                  options={[
                                    { value: "raw_html", label: "Raw HTML" },
                                    { value: "rendered_dom", label: "Rendered DOM" },
                                    { value: "rendered_dom_visual", label: "Rendered DOM + Visual" },
                                    { value: "network_payload_first", label: "Network Payload First" },
                                  ]}
                                />
                              </Field>
                              <Field label="JS Mode">
                                <Dropdown
                                  value={recipeProfile.fetch_profile.js_mode}
                                  onChange={(value) =>
                                    setRecipeProfile((current) => ({
                                      ...current,
                                      fetch_profile: {
                                        ...current.fetch_profile,
                                        js_mode: value,
                                      },
                                    }))
                                  }
                                  options={[
                                    { value: "auto", label: "Auto" },
                                    { value: "enabled", label: "Enabled" },
                                    { value: "disabled", label: "Disabled" },
                                  ]}
                                />
                              </Field>
                              <Field label="Traversal Mode">
                                <Dropdown
                                  value={recipeProfile.fetch_profile.traversal_mode ?? ""}
                                  onChange={(value) =>
                                    setRecipeProfile((current) => ({
                                      ...current,
                                      fetch_profile: {
                                        ...current.fetch_profile,
                                        traversal_mode: value ? value : null,
                                      },
                                    }))
                                  }
                                  options={[
                                    { value: "", label: "Off" },
                                    { value: "auto", label: "Auto" },
                                    { value: "scroll", label: "Scroll" },
                                    { value: "load_more", label: "Load More" },
                                    { value: "view_all", label: "View All" },
                                    { value: "paginate", label: "Paginate" },
                                  ]}
                                />
                              </Field>
                              <Field label="Geo Country">
                                <Input
                                  aria-label="Geo Country"
                                  value={recipeProfile.locality_profile.geo_country}
                                  onChange={(event) =>
                                    setRecipeProfile((current) => ({
                                      ...current,
                                      locality_profile: {
                                        ...current.locality_profile,
                                        geo_country: event.target.value || "auto",
                                      },
                                    }))
                                  }
                                />
                              </Field>
                              <Field label="Language Hint">
                                <Input
                                  aria-label="Language Hint"
                                  value={recipeProfile.locality_profile.language_hint ?? ""}
                                  onChange={(event) =>
                                    setRecipeProfile((current) => ({
                                      ...current,
                                      locality_profile: {
                                        ...current.locality_profile,
                                        language_hint: event.target.value || null,
                                      },
                                    }))
                                  }
                                />
                              </Field>
                              <Field label="Currency Hint">
                                <Input
                                  aria-label="Currency Hint"
                                  value={recipeProfile.locality_profile.currency_hint ?? ""}
                                  onChange={(event) =>
                                    setRecipeProfile((current) => ({
                                      ...current,
                                      locality_profile: {
                                        ...current.locality_profile,
                                        currency_hint: event.target.value || null,
                                      },
                                    }))
                                  }
                                />
                              </Field>
                              <Field label="Network Capture">
                                <Dropdown
                                  value={recipeProfile.diagnostics_profile.capture_network}
                                  onChange={(value) =>
                                    setRecipeProfile((current) => ({
                                      ...current,
                                      diagnostics_profile: {
                                        ...current.diagnostics_profile,
                                        capture_network: value,
                                      },
                                    }))
                                  }
                                  options={[
                                    { value: "off", label: "Off" },
                                    { value: "matched_only", label: "Matched Only" },
                                    { value: "all_small_json", label: "All Small JSON" },
                                  ]}
                                />
                              </Field>
                            </div>
                            <div className="flex flex-col gap-3">
                              <div className="surface-muted flex h-[var(--control-height)] items-center justify-between rounded-[var(--radius-md)] px-3 py-1.5 shadow-sm">
                                <span className="text-sm font-medium">Include iframes</span>
                                <Toggle
                                  checked={recipeProfile.fetch_profile.include_iframes}
                                  onChange={(checked) =>
                                    setRecipeProfile((current) => ({
                                      ...current,
                                      fetch_profile: {
                                        ...current.fetch_profile,
                                        include_iframes: checked,
                                      },
                                    }))
                                  }
                                />
                              </div>
                              <div className="surface-muted flex h-[var(--control-height)] items-center justify-between rounded-[var(--radius-md)] px-3 py-1.5 shadow-sm">
                                <span className="text-sm font-medium">Capture HTML</span>
                                <Toggle
                                  checked={recipeProfile.diagnostics_profile.capture_html}
                                  onChange={(checked) =>
                                    setRecipeProfile((current) => ({
                                      ...current,
                                      diagnostics_profile: {
                                        ...current.diagnostics_profile,
                                        capture_html: checked,
                                      },
                                    }))
                                  }
                                />
                              </div>
                              <div className="surface-muted flex h-[var(--control-height)] items-center justify-between rounded-[var(--radius-md)] px-3 py-1.5 shadow-sm">
                                <span className="text-sm font-medium">Capture Screenshot</span>
                                <Toggle
                                  checked={recipeProfile.diagnostics_profile.capture_screenshot}
                                  onChange={(checked) =>
                                    setRecipeProfile((current) => ({
                                      ...current,
                                      diagnostics_profile: {
                                        ...current.diagnostics_profile,
                                        capture_screenshot: checked,
                                      },
                                    }))
                                  }
                                />
                              </div>
                              <div className="surface-muted flex h-[var(--control-height)] items-center justify-between rounded-[var(--radius-md)] px-3 py-1.5 shadow-sm">
                                <span className="text-sm font-medium">Capture Response Headers</span>
                                <Toggle
                                  checked={recipeProfile.diagnostics_profile.capture_response_headers}
                                  onChange={(checked) =>
                                    setRecipeProfile((current) => ({
                                      ...current,
                                      diagnostics_profile: {
                                        ...current.diagnostics_profile,
                                        capture_response_headers: checked,
                                      },
                                    }))
                                  }
                                />
                              </div>
                              <div className="surface-muted flex h-[var(--control-height)] items-center justify-between rounded-[var(--radius-md)] px-3 py-1.5 shadow-sm">
                                <span className="text-sm font-medium">Capture Browser Diagnostics</span>
                                <Toggle
                                  checked={recipeProfile.diagnostics_profile.capture_browser_diagnostics}
                                  onChange={(checked) =>
                                    setRecipeProfile((current) => ({
                                      ...current,
                                      diagnostics_profile: {
                                        ...current.diagnostics_profile,
                                        capture_browser_diagnostics: checked,
                                      },
                                    }))
                                  }
                                />
                              </div>
                            </div>
                          </div>
                        </Card>
                      ) : (
                        <DataRegionEmpty
                          title="No run profile available"
                          description="This run did not produce a domain profile payload."
                          className="px-0"
                        />
                      )}
                    </div>
                  ) : null}
                </>
              }
            />
          </Card>
        </div>
      ) : null}
    </div>
  );
}

