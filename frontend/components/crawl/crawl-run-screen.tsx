"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowRightCircle, ChevronsDown, Copy, Download } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { InlineAlert, PageHeader, SectionHeader } from "../ui/patterns";
import { Badge, Button, Card, Input } from "../ui/primitives";
import { api } from "../../lib/api";
import type { CrawlLog, CrawlRecord, CrawlRun } from "../../lib/api/types";
import { CRAWL_DEFAULTS } from "../../lib/constants/crawl-defaults";
import { ACTIVE_STATUSES } from "../../lib/constants/crawl-statuses";
import { STORAGE_KEYS } from "../../lib/constants/storage-keys";
import { POLLING_INTERVALS } from "../../lib/constants/timing";
import { cn } from "../../lib/utils";
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
  OutputTab,
  type OutputTabKey,
  PreviewRow,
  progressPercent,
  ProgressBar,
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

const exportLinkClassName =
  "focus-ring no-underline inline-flex h-8 items-center justify-center gap-1.5 rounded-[var(--radius-md)] bg-[var(--accent)] px-3.5 text-sm font-medium !text-white shadow-[var(--shadow-xs)] transition-all hover:bg-[var(--accent-hover)] hover:!text-white";

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
  const [tableVisibleCount, setTableVisibleCount] = useState(CRAWL_DEFAULTS.TABLE_PAGE_SIZE * 4);
  const [jsonVisibleCount, setJsonVisibleCount] = useState(CRAWL_DEFAULTS.TABLE_PAGE_SIZE * 4);
  const logViewportRef = useRef<HTMLDivElement | null>(null);
  const sessionStartMsRef = useRef<number>(Date.now());
  
  const runQuery = useQuery({
    queryKey: ["crawl-run", runId],
    queryFn: () => api.getCrawl(runId),
    refetchInterval: (query) =>
      query.state.data && ACTIVE_STATUSES.has(query.state.data.status)
        ? POLLING_INTERVALS.ACTIVE_JOB_MS
        : false,
  });
  const run = runQuery.data;
  const { live, terminal } = useRunStatusFlags(run);
  const shouldFetchRecords = Boolean(run) && (outputTab === "table" || outputTab === "json");
  const shouldFetchLogs = Boolean(run) && (live || outputTab === "logs");
  const shouldFetchMarkdown = Boolean(run) && terminal && outputTab === "markdown";

  const runCreatedMs = run?.created_at ? new Date(run.created_at).getTime() : null;
  const effectiveStartMs = runCreatedMs ?? sessionStartMsRef.current;
  const [localNow, setLocalNow] = useState(Date.now());
  const recordsFetchLimit = Math.min(
    800,
    Math.max(CRAWL_DEFAULTS.TABLE_PAGE_SIZE * 2, outputTab === "json" ? jsonVisibleCount : tableVisibleCount),
  );

  useEffect(() => {
    if (!live) return;
    const interval = setInterval(() => setLocalNow(Date.now()), 1000);
    return () => clearInterval(interval);
  }, [live]);

  const recordsQuery = useQuery({
    queryKey: ["crawl-records", runId, recordsFetchLimit],
    queryFn: () => api.getRecords(runId, { limit: recordsFetchLimit }),
    enabled: shouldFetchRecords,
    refetchInterval: live && shouldFetchRecords ? POLLING_INTERVALS.RECORDS_MS : false,
  });

  const logsQuery = useQuery({
    queryKey: ["crawl-logs", runId],
    queryFn: () => api.getCrawlLogs(runId),
    enabled: shouldFetchLogs,
    refetchInterval: live && shouldFetchLogs ? POLLING_INTERVALS.LOGS_MS : false,
  });
  const markdownQuery = useQuery({
    queryKey: ["crawl-markdown", runId],
    queryFn: () => api.getMarkdown(runId),
    enabled: shouldFetchMarkdown,
    refetchInterval: false,
  });

  const records = useMemo(() => recordsQuery.data?.items ?? [], [recordsQuery.data?.items]);
  const recordsFetchCapReached = useMemo(
    () => records.length >= recordsFetchLimit && recordsFetchLimit >= 800,
    [records, recordsFetchLimit],
  );
  const recordsTotal = recordsQuery.data?.meta?.total ?? records.length;
  const tableRecords = useMemo(
    () => records.slice(0, Math.min(records.length, tableVisibleCount)),
    [records, tableVisibleCount],
  );
  const jsonRecords = useMemo(
    () => records.slice(0, Math.min(records.length, jsonVisibleCount)),
    [records, jsonVisibleCount],
  );
  const hasMoreTableRecords =
    tableRecords.length < records.length || (records.length < recordsTotal && !recordsFetchCapReached);
  const hasMoreJsonRecords =
    jsonRecords.length < records.length || (records.length < recordsTotal && !recordsFetchCapReached);
  const logs = useMemo(
    () => (logsQuery.data ?? []).slice(-CRAWL_DEFAULTS.MAX_LIVE_LOGS),
    [logsQuery.data],
  );
  const markdown = markdownQuery.data ?? "";
  const recordsJson = useMemo(
    () => (outputTab === "json" ? JSON.stringify(jsonRecords.map(cleanRecord), null, 2) : ""),
    [outputTab, jsonRecords],
  );
  const showRunLoadingState = runQuery.isLoading && !run;
  const panelRefreshErrors = [
    {
      key: "records",
      label: "records",
      error: recordsQuery.error,
      refetch: recordsQuery.refetch,
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

  useTerminalSync(run, terminal, [runQuery, recordsQuery, logsQuery, markdownQuery]);

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
    setTableVisibleCount(CRAWL_DEFAULTS.TABLE_PAGE_SIZE * 4);
    setJsonVisibleCount(CRAWL_DEFAULTS.TABLE_PAGE_SIZE * 4);
  }, [runId]);

  useEffect(() => {
    const availableRecordIds = new Set(records.map((record) => record.id));
    setSelectedIds((current) => current.filter((id) => availableRecordIds.has(id)));
  }, [records]);

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
    () => records.filter((record) => selectedIds.includes(record.id)),
    [records, selectedIds],
  );
  const resultUrls = useMemo(() => uniqueStrings(records.map((record) => extractRecordUrl(record))), [records]);
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

  const summary = {
    records: Number(run?.result_summary?.record_count ?? records.length) || 0,
    pages: Number(run?.result_summary?.processed_urls ?? run?.result_summary?.completed_urls ?? 0) || 0,
    fields: visibleColumns.length,
    duration: formatDuration(
      new Date(effectiveStartMs).toISOString(),
      terminal ? run?.completed_at : new Date(localNow).toISOString(),
    ),
  };
  const lastRunUpdateMs = run?.updated_at
    ? new Date(run.updated_at).getTime()
    : run?.created_at
      ? new Date(run.created_at).getTime()
      : null;
  const showStuckRunWarning =
    live &&
    Boolean(lastRunUpdateMs) &&
    localNow - (lastRunUpdateMs ?? localNow) > POLLING_INTERVALS.STUCK_RUN_WARNING_MS;

  async function runControl() {
    setRunActionPending("kill");
    setRunActionError("");
    try {
      await api.killCrawl(runId);
      await Promise.all([runQuery.refetch(), logsQuery.refetch(), recordsQuery.refetch(), markdownQuery.refetch()]);
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
      {showStuckRunWarning ? (
        <InlineAlert
          tone="warning"
          message="This run appears to be active but has not updated for a while. Check logs, or use Hard Kill if it is stuck."
        />
      ) : null}

      {!showRunLoadingState && !terminal ? (
        <div className="grid gap-4 xl:grid-cols-[minmax(320px,0.32fr)_minmax(0,0.68fr)]">
          <Card className="space-y-4">
            <SectionHeader title="Progress" description={run ? `Run ${run.id} is ${run.status.replace(/_/g, " ")}.` : "Loading run state..."} />
            <PreviewRow label="Run ID" value={run ? `#${run.id}` : "--"} mono />
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
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius-lg)] border border-border bg-[var(--bg-elevated)] px-4 py-3">
            <div className="min-w-0 flex-1">
              {run?.url ? (
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
              )}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {listingRun && batchFromResultsUrls.length ? (
                <Button variant="accent" type="button" onClick={triggerBatchCrawlFromResults}>
                  <ArrowRightCircle className="size-3.5" />
                  {batchFromResultsLabel}
                </Button>
              ) : null}
              <a
                href={api.exportCsv(runId)}
                target="_blank"
                rel="noreferrer"
                className={cn(exportLinkClassName, "shadow-[var(--shadow-sm)]")}
              >
                <Download className="size-3.5" />
                Excel (CSV)
              </a>
              <a
                href={api.exportJson(runId)}
                target="_blank"
                rel="noreferrer"
                className={cn(exportLinkClassName, "shadow-[var(--shadow-sm)]")}
              >
                <Download className="size-3.5" />
                JSON
              </a>
              <a
                href={api.exportMarkdown(runId)}
                target="_blank"
                rel="noreferrer"
                className={cn(exportLinkClassName, "shadow-[var(--shadow-sm)]")}
              >
                <Download className="size-3.5" />
                Markdown
              </a>
            </div>
          </div>

          <div className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border">
              <div className="flex items-center gap-0">
                <OutputTab active={outputTab === "table"} onClick={() => setOutputTab("table")}>
                  {`Table (${summary.fields})`}
                </OutputTab>
                <OutputTab active={outputTab === "json"} onClick={() => setOutputTab("json")}>
                  JSON
                </OutputTab>
                <OutputTab active={outputTab === "markdown"} onClick={() => setOutputTab("markdown")}>
                  Markdown
                </OutputTab>
                <OutputTab active={outputTab === "logs"} onClick={() => setOutputTab("logs")}>
                  Logs
                </OutputTab>
              </div>
              <div className="pb-2 text-sm text-muted">
                Time Taken: <span className="font-semibold text-foreground">{summary.duration}</span>
                {" • "}
                Verdict:{" "}
                <span className="font-semibold text-foreground">{humanizeVerdict(verdict)}</span>
                {" • "}
                Data Quality:{" "}
                <span className="font-semibold text-foreground">{humanizeQuality(quality.level)}</span>
              </div>
            </div>

            {outputTab === "table" ? (
              <div className="space-y-3">
                {recordsQuery.isLoading && !records.length ? (
                  <div className="space-y-2">
                    {Array.from({ length: 5 }, (_, index) => (
                      <div key={index} className="skeleton h-9 w-full rounded-[var(--radius-md)]" />
                    ))}
                  </div>
                ) : records.length ? (
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
                          Showing {tableRecords.length} of {recordsTotal} records
                        </span>
                        <Button
                          variant="secondary"
                          type="button"
                          onClick={() => setTableVisibleCount((current) => current + CRAWL_DEFAULTS.TABLE_PAGE_SIZE * 4)}
                        >
                          Load More
                        </Button>
                      </div>
                    ) : null}
                    {records.length < recordsTotal && recordsFetchCapReached ? (
                      <InlineAlert
                        tone="warning"
                        message={`Preview capped at ${records.length} records for performance. Export JSON/CSV for the full ${recordsTotal} records.`}
                      />
                    ) : null}
                  </div>
                ) : (
                  <div className="grid min-h-40 place-items-center rounded-[var(--radius-lg)] border border-dashed border-border bg-panel text-sm text-muted">
                    No records captured yet.
                  </div>
                )}
              </div>
            ) : null}

            {outputTab === "json" ? (
              <div className="relative">
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
              <div className="relative">
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
                  <div className="max-h-[72vh] overflow-y-auto rounded-[var(--radius-lg)] border border-border bg-[var(--surface-card)] px-3 pb-3 pt-12">
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

            {outputTab === "logs" ? <LogTerminal logs={logs} viewportRef={logViewportRef} /> : null}
          </div>
        </Card>
      ) : null}
    </div>
  );
}
