"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRightCircle, ChevronsDown, Copy, Download } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { PageHeader, SectionHeader } from "../ui/patterns";
import { Badge, Button, Card, Input } from "../ui/primitives";
import { api } from "../../lib/api";
import type { CrawlRecord, CrawlRun } from "../../lib/api/types";
import { CRAWL_DEFAULTS } from "../../lib/constants/crawl-defaults";
import { ACTIVE_STATUSES, TERMINAL_STATUSES } from "../../lib/constants/crawl-statuses";
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
  humanizeVerdict,
  humanizeFieldName,
  isListingRun,
  LogTerminal,
  OutputTab,
  type OutputTabKey,
  PreviewRow,
  progressPercent,
  ProgressBar,
  RecordsTable,
  scrollViewportToBottom,
  stringifyCell,
  uniqueNumbers,
  uniqueStrings,
} from "./shared";

type CrawlRunScreenProps = {
  runId: number;
};

const exportLinkClassName =
  "focus-ring no-underline inline-flex h-8 items-center justify-center gap-1.5 rounded-[var(--radius-md)] bg-[var(--accent)] px-3.5 text-[13px] font-medium !text-white shadow-[var(--shadow-xs)] transition-all hover:bg-[var(--accent-hover)] hover:!text-white";

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
  const queryClient = useQueryClient();
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [outputTab, setOutputTab] = useState<OutputTabKey>("table");
  const [liveJumpAvailable, setLiveJumpAvailable] = useState(false);
  const [runActionPending, setRunActionPending] = useState<"pause" | "resume" | "kill" | null>(null);
  const [runActionError, setRunActionError] = useState("");
  const logViewportRef = useRef<HTMLDivElement | null>(null);
  const terminalSyncRef = useRef<string | null>(null);
  const runQuery = useQuery({
    queryKey: ["crawl-run", runId],
    queryFn: () => api.getCrawl(runId),
    refetchInterval: (query) =>
      query.state.data && ACTIVE_STATUSES.has(query.state.data.status) ? POLLING_INTERVALS.ACTIVE_JOB_MS : false,
  });
  const run = runQuery.data;
  const live = Boolean(run && ACTIVE_STATUSES.has(run.status));
  const terminal = run ? TERMINAL_STATUSES.has(run.status) : false;

  const runCreatedMs = run?.created_at ? new Date(run.created_at).getTime() : null;
  const [startMs] = useState(() => runCreatedMs ?? Date.now());
  const [localNow, setLocalNow] = useState(Date.now());

  useEffect(() => {
    if (!live) return;
    const interval = setInterval(() => setLocalNow(Date.now()), 1000);
    return () => clearInterval(interval);
  }, [live]);

  const relativeOffsetMs = run?.created_at ? Math.max(0, Date.now() - new Date(run.created_at).getTime()) : 0;
  // If IST shift is ~5.5h, relativeOffsetMs will be huge. We need to clamp to session relative for active jobs.
  const activeDurationMs = localNow - startMs;

  const recordsQuery = useQuery({
    queryKey: ["crawl-records", runId],
    queryFn: () => api.getRecords(runId, { limit: 1000 }),
    enabled: Boolean(run),
    refetchInterval: () => {
      const latestRun = queryClient.getQueryData<CrawlRun>(["crawl-run", runId]);
      return latestRun && (latestRun.status === "running" || latestRun.status === "paused")
        ? POLLING_INTERVALS.RECORDS_MS
        : false;
    },
  });

  const logsQuery = useQuery({
    queryKey: ["crawl-logs", runId],
    queryFn: () => api.getCrawlLogs(runId),
    refetchInterval: () => {
      const latestRun = queryClient.getQueryData<CrawlRun>(["crawl-run", runId]);
      return latestRun && (latestRun.status === "running" || latestRun.status === "paused")
        ? POLLING_INTERVALS.LOGS_MS
        : false;
    },
  });
  const markdownQuery = useQuery({
    queryKey: ["crawl-markdown", runId],
    queryFn: () => api.getMarkdown(runId),
    enabled: Boolean(run),
    refetchInterval: () => {
      const latestRun = queryClient.getQueryData<CrawlRun>(["crawl-run", runId]);
      return latestRun && (latestRun.status === "running" || latestRun.status === "paused")
        ? POLLING_INTERVALS.RECORDS_MS
        : false;
    },
  });

  const records = useMemo(() => recordsQuery.data?.items ?? [], [recordsQuery.data?.items]);
  const logs = useMemo(() => (logsQuery.data ?? []).slice(-CRAWL_DEFAULTS.MAX_LIVE_LOGS), [logsQuery.data]);
  const markdown = markdownQuery.data ?? "";
  const showRunLoadingState = runQuery.isLoading && !run;

  useEffect(() => {
    if (!run || !terminal) {
      terminalSyncRef.current = null;
      return;
    }

    const syncKey = `${run.id}:${run.status}:${run.completed_at ?? ""}:${run.updated_at}`;
    if (terminalSyncRef.current === syncKey) {
      return;
    }
    terminalSyncRef.current = syncKey;

    void Promise.allSettled([runQuery.refetch(), recordsQuery.refetch(), logsQuery.refetch(), markdownQuery.refetch()]);
  }, [logsQuery, markdownQuery, recordsQuery, run, runQuery, terminal]);

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
  const resultUrls = useMemo(() => uniqueStrings(records.map((record) => extractRecordUrl(record))), [records]);
  const selectedResultUrls = useMemo(
    () => uniqueStrings(selectedRecords.map((record) => extractRecordUrl(record))),
    [selectedRecords],
  );
  const listingRun = useMemo(() => isListingRun(run), [run]);
  const verdict = extractionVerdict(run);
  const batchFromResultsUrls = selectedResultUrls.length ? selectedResultUrls : resultUrls;
  const batchFromResultsLabel = selectedResultUrls.length
    ? `Batch Crawl Selected (${selectedResultUrls.length})`
    : `Batch Crawl Results (${resultUrls.length})`;

  const summary = {
    records: Number(run?.result_summary?.record_count ?? records.length) || 0,
    pages: Number(run?.result_summary?.processed_urls ?? run?.result_summary?.completed_urls ?? 0) || 0,
    fields: visibleColumns.length,
    duration: terminal 
      ? formatDuration(run?.created_at, run?.completed_at)
      : formatDuration(new Date(startMs).toISOString(), new Date(startMs + (Number(run?.result_summary?.elapsed_ms) || (localNow - startMs))).toISOString()),
  };

  async function runControl(action: "pause" | "resume" | "kill") {
    setRunActionPending(action);
    setRunActionError("");
    try {
      if (action === "pause") {
        await api.pauseCrawl(runId);
      } else if (action === "resume") {
        await api.resumeCrawl(runId);
      } else {
        await api.killCrawl(runId);
      }
      await Promise.all([runQuery.refetch(), logsQuery.refetch(), recordsQuery.refetch(), markdownQuery.refetch()]);
    } catch (error) {
      setRunActionError(error instanceof Error ? error.message : `Unable to ${action} crawl.`);
    } finally {
      setRunActionPending(null);
    }
  }

  function resetToConfig() {
    router.replace("/crawl?module=pdp&mode=single");
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
            <ProgressBar percent={progressPercent(run)} />
            {run?.status === "paused" ? (
              <div className="rounded-md border border-warning/30 bg-warning/10 px-3 py-2 text-sm text-foreground">
                Job paused. Output so far is preserved.
              </div>
            ) : null}
            {runActionError ? (
              <div className="rounded-md border border-danger/20 bg-danger/10 px-3 py-2 text-sm text-danger">
                {runActionError}
              </div>
            ) : null}
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
                  <RecordsTable
                    records={records}
                    visibleColumns={visibleColumns}
                    selectedIds={selectedIds}
                    onSelectAll={(checked) => setSelectedIds(checked ? records.map((record) => record.id) : [])}
                    onToggleRow={(id, checked) =>
                      setSelectedIds((current) =>
                        checked ? uniqueNumbers([...current, id]) : current.filter((value) => value !== id),
                      )
                    }
                  />
                ) : (
                  <div className="grid min-h-40 place-items-center rounded-[10px] border border-dashed border-border bg-panel/60 text-sm text-muted">
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
                <pre className="crawl-terminal crawl-terminal-json min-h-[55vh] max-h-[72vh] overflow-y-auto px-4 pb-4 pt-14 text-[12px]">
                  {JSON.stringify(records.map(cleanRecord), null, 2)}
                </pre>
              </div>
            ) : null}

            {outputTab === "markdown" ? (
              <Card className="relative overflow-hidden">
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
                  <div className="space-y-2 p-4">
                    {Array.from({ length: 8 }, (_, index) => (
                      <div key={index} className="skeleton h-5 w-full rounded-[var(--radius-md)]" />
                    ))}
                  </div>
                ) : markdown ? (
                  <div className="max-h-[72vh] overflow-y-auto px-6 pb-8 pt-14">
                    <article className="markdown-document max-w-none">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
                    </article>
                  </div>
                ) : (
                  <div className="grid min-h-40 place-items-center rounded-[10px] border border-dashed border-border bg-panel/60 text-sm text-muted">
                    No markdown is available for this run.
                  </div>
                )}
              </Card>
            ) : null}

            {outputTab === "logs" ? <LogTerminal logs={logs} viewportRef={logViewportRef} /> : null}
          </div>
        </Card>
      ) : null}
    </div>
  );
}
