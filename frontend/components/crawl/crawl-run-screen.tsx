"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowRightCircle, ChevronsDown, Copy, Download } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import {
  DataRegionEmpty,
  DataRegionLoading,
  InlineAlert,
  PageHeader,
  ProgressBar,
  RunSummaryChips,
  RunWorkspaceShell,
  SectionHeader,
  StatusDot,
  TabBar,
} from "../ui/patterns";
import { Badge, Button, Card, Input } from "../ui/primitives";
import { api } from "../../lib/api";
import { getApiWebSocketBaseUrl } from "../../lib/api/client";
import type { CrawlLog, CrawlRecord, CrawlRun } from "../../lib/api/types";
import { CRAWL_DEFAULTS } from "../../lib/constants/crawl-defaults";
import { ACTIVE_STATUSES } from "../../lib/constants/crawl-statuses";
import { STORAGE_KEYS } from "../../lib/constants/storage-keys";
import { POLLING_INTERVALS } from "../../lib/constants/timing";
import { telemetryErrorPayload, trackEvent } from "../../lib/telemetry/events";
import { parseApiDate } from "../../lib/format/date";
import { humanizeStatus, runsStatusTone as statusTone } from "../../lib/ui/status";
import {
  ActionButton,
  cleanRecord,
  copyJson,
  extractRecordUrl,
  extractionVerdict,
  extractionVerdictTone,
  formatDuration,
  estimateDataQuality,
  humanizeVerdict,
  humanizeFieldName,
  humanizeQuality,
  isListingRun,
  LogTerminal,
  type OutputTabKey,
  PreviewRow,
  progressPercent,
  qualityTone,
  RecordsTable,
  scrollViewportToBottom,
  stringifyCell,
  uniqueNumbers,
  uniqueStrings,
} from "./shared";
import { useRunStatusFlags, useTerminalSync } from "./use-run-polling";

type CrawlRunScreenProps = {
  runId: number;
};

function isSafeHref(href: string) {
  try {
    const base = typeof window === "undefined" ? "http://localhost" : window.location.origin;
    const url = new URL(href, base);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}

export function CrawlRunScreen({ runId }: Readonly<CrawlRunScreenProps>) {
  const router = useRouter();
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [outputTab, setOutputTab] = useState<OutputTabKey>("table");
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
  
  const runQuery = useQuery({
    queryKey: ["crawl-run", runId],
    queryFn: () => api.getCrawl(runId),
    refetchInterval: false,
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
  });

  const jsonRecordsQuery = useQuery({
    queryKey: ["crawl-records-json", runId, recordsFetchLimit],
    queryFn: () => api.getRecords(runId, { limit: recordsFetchLimit }),
    enabled: shouldFetchJsonRecords,
    refetchInterval: false,
  });

  const logsQuery = useQuery({
    queryKey: ["crawl-logs", runId, logCursorAfterId],
    queryFn: () => api.getCrawlLogs(runId, { afterId: logCursorAfterId, limit: CRAWL_DEFAULTS.MAX_LIVE_LOGS }),
    enabled: shouldFetchLogs,
    refetchInterval: false,
  });
  const markdownQuery = useQuery({
    queryKey: ["crawl-markdown", runId],
    queryFn: () => api.getMarkdown(runId),
    enabled: shouldFetchMarkdown,
    refetchInterval: false,
  });

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
  const hasMoreTableRecords = tableRecords.length < tableTotal;
  const hasMoreJsonRecords =
    jsonRecords.length < records.length || (records.length < recordsTotal && !recordsFetchCapReached);
  const logs = useMemo(() => logItems.slice(-CRAWL_DEFAULTS.MAX_LIVE_LOGS), [logItems]);
  const markdown = markdownQuery.data ?? "";
  const recordsJson = useMemo(
    () => (outputTab === "json" ? JSON.stringify(jsonRecords.map(cleanRecord), null, 2) : ""),
    [outputTab, jsonRecords],
  );
  const showRunLoadingState = runQuery.isLoading && !run;
  const panelRefreshErrors = [
    {
      key: "run",
      label: "run",
      error: runQuery.error,
      refetch: runQuery.refetch,
    },
    {
      key: "records",
      label: "records",
      error: tableRecordsQuery.error ?? jsonRecordsQuery.error,
      refetch: async () => {
        const tasks: Array<Promise<unknown>> = [];
        if (tableRecordsQuery.error) {
          tasks.push(tableRecordsQuery.refetch());
        }
        if (jsonRecordsQuery.error) {
          tasks.push(jsonRecordsQuery.refetch());
        }
        if (!tasks.length) {
          tasks.push(tableRecordsQuery.refetch(), jsonRecordsQuery.refetch());
        }
        await Promise.allSettled(tasks);
      },
    },
    {
      key: "logs",
      label: "logs",
      error: logsQuery.error,
      refetch: logsQuery.refetch,
    },
    {
      key: "markdown",
      label: "markdown",
      error: markdownQuery.error,
      refetch: markdownQuery.refetch,
    },
  ].filter((panel) => panel.error);

  useTerminalSync(run, terminal, [runQuery, tableRecordsQuery, jsonRecordsQuery, logsQuery, markdownQuery]);

  useEffect(() => {
    if (!tableRecordsQuery.data) {
      return;
    }
    const nextItems = tableRecordsQuery.data.items ?? [];
    const nextTotal = tableRecordsQuery.data.meta?.total ?? nextItems.length;
    setTableTotal(nextTotal);
    setTableRecords((current) => {
      const byId = new Map<number, CrawlRecord>();
      for (const row of current) byId.set(row.id, row);
      for (const row of nextItems) byId.set(row.id, row);
      return Array.from(byId.values()).sort((a, b) => a.id - b.id);
    });
  }, [tableRecordsQuery.data]);

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
    if (!shouldFetchLogs || typeof window === "undefined" || typeof WebSocket === "undefined") {
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
  }, [refetchRunQuery, runId, shouldFetchLogs]);

  useEffect(() => {
    if (!live) {
      return;
    }

    const refetchPanels = () => {
      const tasks: Array<Promise<unknown>> = [runQuery.refetch()];
      if (shouldFetchTableRecords) {
        tasks.push(tableRecordsQuery.refetch());
      }
      if (shouldFetchJsonRecords) {
        tasks.push(jsonRecordsQuery.refetch());
      }
      if (shouldFetchLogs && !logSocketConnected) {
        tasks.push(logsQuery.refetch());
      }
      if (shouldFetchMarkdown) {
        tasks.push(markdownQuery.refetch());
      }
      void Promise.allSettled(tasks);
    };

    const intervalId = window.setInterval(refetchPanels, POLLING_INTERVALS.ACTIVE_JOB_MS);
    return () => window.clearInterval(intervalId);
  }, [
    live,
    jsonRecordsQuery,
    logSocketConnected,
    logsQuery,
    markdownQuery,
    runQuery,
    shouldFetchLogs,
    shouldFetchJsonRecords,
    shouldFetchMarkdown,
    shouldFetchTableRecords,
    tableRecordsQuery,
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

  useEffect(() => {
    setTablePage(1);
    setTableRecords([]);
    setTableTotal(0);
    setJsonVisibleCount(CRAWL_DEFAULTS.TABLE_PAGE_SIZE * 4);
    setLogItems([]);
    setLogCursorAfterId(undefined);
    setLogSocketConnected(false);
  }, [runId]);

  useEffect(() => {
    const availableRecordIds = new Set(
      (outputTab === "table" ? tableRecords : records).map((record) => record.id),
    );
    setSelectedIds((current) => current.filter((id) => availableRecordIds.has(id)));
  }, [outputTab, records, tableRecords]);

  const recordsForAnalysis = outputTab === "table" ? tableRecords : records.slice(0, CRAWL_DEFAULTS.TABLE_PAGE_SIZE * 4);
  const visibleColumns = useMemo(() => {
    const columns = new Set<string>();
    for (const record of recordsForAnalysis) {
      Object.keys(record.data ?? {}).forEach((key) => {
        if (!key.startsWith("_")) {
          columns.add(key);
        }
      });
    }
    return Array.from(columns);
  }, [recordsForAnalysis]);
  const fieldQualityScores = useMemo(() => {
    const scores: Record<string, number> = {};
    if (!recordsForAnalysis.length || !visibleColumns.length) {
      return scores;
    }
    for (const column of visibleColumns) {
      let populated = 0;
      for (const record of recordsForAnalysis) {
        const value = record.data?.[column] ?? record.raw_data?.[column];
        if (value !== null && value !== undefined && String(value).trim() !== "") {
          populated += 1;
        }
      }
      scores[column] = populated / recordsForAnalysis.length;
    }
    return scores;
  }, [recordsForAnalysis, visibleColumns]);

  const selectedRecords = useMemo(
    () => (outputTab === "table" ? tableRecords : records).filter((record) => selectedIds.includes(record.id)),
    [outputTab, records, selectedIds, tableRecords],
  );
  const resultUrls = useMemo(
    () => uniqueStrings((outputTab === "table" ? tableRecords : records).map((record) => extractRecordUrl(record))),
    [outputTab, records, tableRecords],
  );
  const selectedResultUrls = useMemo(
    () => uniqueStrings(selectedRecords.map((record) => extractRecordUrl(record))),
    [selectedRecords],
  );
  const listingRun = useMemo(() => isListingRun(run), [run]);
  const verdict = extractionVerdict(run);
  const quality = useMemo(
    () => estimateDataQuality(recordsForAnalysis, visibleColumns),
    [recordsForAnalysis, visibleColumns],
  );
  const batchFromResultsUrls = selectedResultUrls.length ? selectedResultUrls : resultUrls;
  const batchFromResultsLabel = selectedResultUrls.length
    ? `Batch Crawl Selected (${selectedResultUrls.length})`
    : `Batch Crawl Results (${resultUrls.length})`;

  const summaryRecordsFromRun = Number(run?.result_summary?.record_count ?? 0) || 0;
  const summaryPagesFromRun =
    Number(run?.result_summary?.processed_urls ?? run?.result_summary?.completed_urls ?? 0) || 0;
  const summary = {
    records: Math.max(summaryRecordsFromRun, recordsTotal),
    pages: Math.max(
      summaryPagesFromRun,
      Number(run?.result_summary?.progress ?? 0) > 0 ? 1 : 0,
    ),
    fields: visibleColumns.length,
    duration: formatDuration(
      new Date(effectiveStartMs).toISOString(),
      terminal ? run?.completed_at : new Date(localNow).toISOString(),
    ),
  };

  async function downloadExport(kind: "csv" | "json" | "markdown") {
    const filename = `run-${runId}.${kind === "markdown" ? "md" : kind}`;
    try {
      const blob =
        kind === "csv"
          ? await api.downloadCsv(runId)
          : kind === "json"
            ? await api.downloadJson(runId)
            : await api.downloadMarkdown(runId);
      const objectUrl = window.URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = filename;
      anchor.style.display = "none";
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
      window.URL.revokeObjectURL(objectUrl);
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
    window.sessionStorage.setItem(
      STORAGE_KEYS.BULK_PREFILL,
      JSON.stringify({
        urls,
      }),
    );
    router.replace("/crawl?module=pdp&mode=batch");
  }

  if (runQuery.error) {
    return (
      <div className="space-y-4">
        <PageHeader
          title="Crawl Studio"
          actions={
            <Button variant="accent" type="button" onClick={resetToConfig}>
              New Crawl
            </Button>
          }
        />
        <Card className="space-y-3 px-6 py-8">
          <SectionHeader title="Unable to Load Crawl" description="The run workspace could not be restored." />
          <div className="text-sm text-danger">
            {runQuery.error instanceof Error ? runQuery.error.message : "Unknown crawl loading error."}
          </div>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title="Crawl Studio"
        actions={
          <Button variant="accent" type="button" onClick={resetToConfig}>
            New Crawl
          </Button>
        }
      />

      {showRunLoadingState ? (
        <Card className="space-y-3 px-6 py-8">
          <SectionHeader title="Loading Crawl" description="Fetching run details and restoring the workspace." />
          <div className="text-sm text-muted">Run #{runId} is loading.</div>
        </Card>
      ) : null}

      {panelRefreshErrors.length ? (
        <Card className="space-y-3 border-danger/30 bg-danger/5">
          <SectionHeader
            title="Some live panels failed to refresh"
            description="Data may be stale until these requests recover."
          />
          <div className="space-y-1 text-sm text-danger">
            {panelRefreshErrors.map((panel) => (
              <div key={panel.key}>
                Unable to refresh {panel.label}:{" "}
                {panel.error instanceof Error ? panel.error.message : "Unknown error."}
              </div>
            ))}
          </div>
          <div>
            <Button variant="secondary" type="button" onClick={() => void retryFailedPanels()}>
              Retry failed panels
            </Button>
          </div>
        </Card>
      ) : null}
      {!showRunLoadingState && !terminal ? (
        <div className="grid gap-4 xl:grid-cols-[minmax(320px,0.32fr)_minmax(0,0.68fr)]">
          <Card className="space-y-4">
            <SectionHeader title="Progress" description={run ? `Run ${run.id} is ${humanizeStatus(run.status)}.` : "Loading run state..."} />
            <PreviewRow label="Run ID" value={run ? `#${run.id}` : "--"} mono />
            <PreviewRow
              label="Status"
              value={
                run ? (
                  <span className="inline-flex items-center gap-1.5">
                    <StatusDot tone={statusTone(run.status)} />
                    {humanizeStatus(run.status)}
                  </span>
                ) : (
                  "--"
                )
              }
            />
            <PreviewRow label="Crawl Type" value={run?.run_type ?? "--"} />
            <PreviewRow label="Target" value={run?.url ?? "--"} mono />
            <PreviewRow label="Records" value={String(summary.records)} />
            <PreviewRow label="Pages" value={String(summary.pages)} />
            <PreviewRow label="Elapsed" value={summary.duration} />
            <PreviewRow
              label="Verdict"
              value={
                <Badge tone={extractionVerdictTone(verdict)}>
                  {humanizeVerdict(verdict)}
                </Badge>
              }
            />
            <PreviewRow
              label="Data Quality"
              value={
                <Badge tone={qualityTone(quality.level)}>
                  {humanizeQuality(quality.level)} ({Math.round(quality.score * 100)}%)
                </Badge>
              }
            />
            <ProgressBar percent={progressPercent(run)} />
            {runActionError ? <InlineAlert message={runActionError} /> : null}
            <div className="flex flex-wrap gap-2">
              <ActionButton
                label={runActionPending === "kill" ? "Killing..." : "Hard Kill"}
                onClick={() => void runControl()}
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
                liveJumpAvailable ? (
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
                ) : null
              }
            />
            <LogTerminal logs={logs} live viewportRef={logViewportRef} />
          </Card>
        </div>
      ) : null}

      {!showRunLoadingState && terminal ? (
        <Card className="space-y-4">
          <RunWorkspaceShell
            header={
              run?.url ? (
                <a
                  href={run.url}
                  target="_blank"
                  rel="noreferrer"
                  className="block truncate text-sm font-medium text-accent underline-offset-2 hover:underline"
                >
                  {run.url}
                </a>
              ) : (
                <p className="text-sm text-muted">Waiting for completed run data.</p>
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
                <Button variant="accent" type="button" onClick={() => void downloadExport("csv")}>
                  <Download className="size-3.5" />
                  Excel (CSV)
                </Button>
                <Button variant="accent" type="button" onClick={() => void downloadExport("json")}>
                  <Download className="size-3.5" />
                  JSON
                </Button>
                <Button variant="accent" type="button" onClick={() => void downloadExport("markdown")}>
                  <Download className="size-3.5" />
                  Markdown
                </Button>
              </>
            }
            tabs={
              <TabBar
                value={outputTab}
                onChange={(value) => setOutputTab(value as OutputTabKey)}
                options={[
                  { value: "table", label: `Table (${summary.fields})` },
                  { value: "json", label: "JSON" },
                  { value: "markdown", label: "Markdown" },
                  { value: "logs", label: "Logs" },
                ]}
              />
            }
            summary={
              <RunSummaryChips
                duration={summary.duration}
                verdict={humanizeVerdict(verdict)}
                quality={humanizeQuality(quality.level)}
              />
            }
            content={
              <>
                {outputTab === "table" ? (
                  <div className="space-y-3 min-h-[55vh]">
                    {tableRecordsQuery.isLoading && !tableRecords.length ? (
                      <DataRegionLoading count={5} className="px-0" />
                    ) : tableRecords.length ? (
                      <div className="space-y-3">
                        <RecordsTable
                          records={tableRecords}
                          visibleColumns={visibleColumns}
                          fieldQualityScores={fieldQualityScores}
                          selectedIds={selectedIds}
                          onSelectAll={(checked) => setSelectedIds(checked ? tableRecords.map((record) => record.id) : [])}
                          onToggleRow={(id, checked) =>
                            setSelectedIds((current) =>
                              checked ? uniqueNumbers([...current, id]) : current.filter((value) => value !== id),
                            )
                          }
                        />
                        {hasMoreTableRecords ? (
                          <div className="flex items-center justify-between rounded-[var(--radius-md)] border border-border bg-panel px-3 py-2 text-xs text-muted">
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
                      <DataRegionEmpty title="No records captured yet" description="Records will appear here once extraction returns rows." className="px-0" />
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
                    <pre className="crawl-terminal crawl-terminal-json min-h-[55vh] max-h-[72vh] overflow-y-auto px-4 pb-4 pt-14 text-xs">
                      {recordsJson}
                    </pre>
                    {hasMoreJsonRecords ? (
                      <div className="mt-2 flex items-center justify-between rounded-[var(--radius-md)] border border-border bg-panel px-3 py-2 text-xs text-muted">
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
                      <div className="space-y-2 rounded-[var(--radius-lg)] border border-border bg-[var(--surface-card)] px-3 pb-3 pt-12">
                        {Array.from({ length: 8 }, (_, index) => (
                          <div key={index} className="skeleton h-5 w-full rounded-[var(--radius-md)]" />
                        ))}
                      </div>
                    ) : markdown ? (
                      <div className="min-h-[55vh] max-h-[72vh] overflow-y-auto rounded-[var(--radius-lg)] border border-border bg-[var(--surface-card)] px-3 pb-3 pt-12">
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
                      <div className="grid min-h-40 place-items-center rounded-[var(--radius-lg)] border border-dashed border-border bg-panel text-sm text-muted">
                        No markdown is available for this run.
                      </div>
                    )}
                  </div>
                ) : null}

                {outputTab === "logs" ? (
                  <div className="min-h-[55vh]">
                    <LogTerminal logs={logs} viewportRef={logViewportRef} />
                  </div>
                ) : null}
              </>
            }
          />
        </Card>
      ) : null}
    </div>
  );
}
