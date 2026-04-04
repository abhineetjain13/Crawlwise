"use client";

import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Circle, LoaderCircle, XCircle } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { Badge, Button, Card } from "../../../components/ui/primitives";
import { PageHeader, SectionHeader } from "../../../components/ui/patterns";
import { api } from "../../../lib/api";
import type { CrawlLog, CrawlRecord, CrawlRun } from "../../../lib/api/types";
import { cn } from "../../../lib/utils";

const TERMINAL_STATUSES = new Set(["completed", "killed", "failed", "proxy_exhausted"]);
const STAGES = ["ACQUIRE", "DISCOVER", "EXTRACT", "UNIFY", "PUBLISH"] as const;
const RECORDS_PAGE_LIMIT = 1000;

type ResultTab = "csv" | "json" | "logs";
type StageState = "idle" | "active" | "done" | "interrupted";

export default function RunDetailPage() {
  const params = useParams<{ run_id: string }>();
  const router = useRouter();
  const runId = Number(params.run_id);
  const [resultTab, setResultTab] = useState<ResultTab>("csv");

  const runQuery = useQuery({
    queryKey: ["run", runId],
    queryFn: () => api.getCrawl(runId),
    refetchInterval: (query) => shouldPoll(query.state.data as CrawlRun | undefined) ? 3000 : false,
  });

  const run = runQuery.data;
  const live = shouldPoll(run);
  const pollInterval = live ? 3000 : false;

  const logsQuery = useQuery({
    queryKey: ["run-logs", runId],
    queryFn: () => api.getCrawlLogs(runId),
    enabled: Boolean(run),
    retry: 2,
    refetchInterval: (query) => (shouldPoll(runQuery.data) || (!query.state.data && !query.state.error) ? 3000 : false),
  });
  const recordsQuery = useQuery({
    queryKey: ["run-records", runId],
    queryFn: () => api.getRecords(runId, { limit: RECORDS_PAGE_LIMIT }),
    enabled: Boolean(run),
    refetchInterval: pollInterval,
  });
  const logs = useMemo(() => logsQuery.data ?? [], [logsQuery.data]);
  const records = useMemo(() => recordsQuery.data?.items ?? [], [recordsQuery.data?.items]);
  const displayedRecords = records;
  const runError = typeof run?.result_summary?.error === "string" ? run.result_summary.error : "";
  const stageItems = useMemo(
    () => deriveStages(logs, run?.status, readString(run?.result_summary?.current_stage)),
    [logs, run?.status, run?.result_summary?.current_stage],
  );

  const logicalColumns = useMemo(() => {
    const cols = new Set<string>();
    for (const record of displayedRecords) {
      for (const key of Object.keys(record.data ?? {})) {
        if (!key.startsWith("_")) cols.add(key);
      }
    }
    return [...cols];
  }, [displayedRecords]);

  const csvColumns = useMemo(() => {
    return [...new Set(logicalColumns)];
  }, [logicalColumns]);

  const bulkUrls = useMemo(() => extractBulkUrls(records, csvColumns), [csvColumns, records]);

  const csvRows = useMemo(
    () => buildCsvRows(displayedRecords, csvColumns),
    [displayedRecords, csvColumns],
  );

  return (
    <div className="space-y-4">
      <PageHeader
        title={getRunTitle(run, live, runId)}
        description={run?.url ?? "Loading run details..."}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            {run ? <StatusChip status={run.status} /> : null}
            {run ? <ExtractionVerdictChip verdict={run.result_summary?.extraction_verdict} /> : null}
            {!live ? (
              <>
                {bulkUrls.length ? (
                  <Button
                    variant="secondary"
                    type="button"
                    onClick={() => {
                      window.sessionStorage.setItem(
                        "bulk-crawl-prefill-v1",
                        JSON.stringify({
                          urls: bulkUrls,
                          tab: "batch",
                          vertical: inferVertical(run?.surface),
                          pageType: "pdp",
                          additional_fields: [],
                          sourceRunId: runId,
                          sourceUrl: run?.url ?? "",
                        }),
                      );
                      router.push("/crawl/bulk");
                    }}
                  >
                    Bulk Crawl
                  </Button>
                ) : null}
                <a href={api.exportCsv(runId)} target="_blank" rel="noreferrer">
                  <Button variant="secondary" type="button">CSV</Button>
                </a>
                <a href={api.exportJson(runId)} target="_blank" rel="noreferrer">
                  <Button variant="secondary" type="button">JSON</Button>
                </a>
              </>
            ) : null}
            <Button variant="ghost" onClick={() => void Promise.all([runQuery.refetch(), logsQuery.refetch(), recordsQuery.refetch()])}>
              Refresh
            </Button>
          </div>
        }
      />

      <div className="stagger-children grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <MetaCard label="Mode" value={formatRunType(run?.run_type)} />
        <MetaCard label="Page Type" value={formatPageType(readString(run?.settings?.page_type) ?? "-")} />
        <MetaCard label="Records" value={String(displayedRecords.length)} />
        <MetaCard label="Domain" value={readString(run?.result_summary?.domain) ?? getDomain(run?.url)} />
      </div>

      {live ? (
        <Card className="space-y-3">
          <SectionHeader title="Pipeline Progress" description="Current crawl stages for this run." />
          {run?.run_type === "batch" || run?.run_type === "csv" ? (
            <div className="grid gap-3 sm:grid-cols-3">
              <LiveMetaCard
                label="Processed URLs"
                value={`${readNumber(run?.result_summary?.processed_urls) ?? 0} / ${readNumber(run?.result_summary?.total_urls) ?? readNumber(run?.result_summary?.url_count) ?? 0}`}
              />
              <LiveMetaCard
                label="Records"
                value={String(readNumber(run?.result_summary?.record_count) ?? 0)}
              />
              <LiveMetaCard
                label="Progress"
                value={`${readNumber(run?.result_summary?.progress) ?? 0}%`}
              />
            </div>
          ) : null}
          {readString(run?.result_summary?.current_url) ? (
            <div className="rounded-md bg-panel-strong px-3 py-2 text-[12px] text-muted">
              {run?.result_summary?.current_url_index ? `URL ${run.result_summary.current_url_index}` : "URL"}
              {run?.result_summary?.total_urls ? ` / ${run.result_summary.total_urls}` : ""}
              : {readString(run?.result_summary?.current_url)}
            </div>
          ) : null}
          <div className="stagger-children space-y-1">
            {stageItems.map((stage) => (
              <div
                key={stage.label}
                className={cn(
                  "flex items-center gap-3 rounded-md px-3 py-2.5 transition-all",
                  stage.state === "active" && "bg-accent/5",
                  stage.state === "done" && "bg-success/5",
                  stage.state === "interrupted" && "bg-warning/5",
                  stage.state === "idle" && "opacity-40",
                )}
              >
                <div className="shrink-0">{renderStageIcon(stage.state)}</div>
                <div className="min-w-0 flex-1">
                  <div className="text-[13px] font-medium text-foreground">{stage.label}</div>
                </div>
                <div className="text-[11px] text-muted">{stage.description}</div>
              </div>
            ))}
          </div>
        </Card>
      ) : (
        <Card className="space-y-4">
          <div className="flex items-center gap-0.5 border-b border-border pb-2">
            <ResultTabButton active={resultTab === "csv"} onClick={() => setResultTab("csv")}>Data</ResultTabButton>
            <ResultTabButton active={resultTab === "json"} onClick={() => setResultTab("json")}>JSON</ResultTabButton>
            <ResultTabButton active={resultTab === "logs"} onClick={() => setResultTab("logs")}>Logs</ResultTabButton>
          </div>

          {runError ? (
            <div className="rounded-md border border-warning/20 bg-warning/5 px-3 py-2.5 text-[13px] text-foreground">
              {runError}
            </div>
          ) : null}

          {resultTab === "csv" ? (
            csvColumns.length ? (
              <div className="overflow-auto rounded-md border border-border">
                <table className="compact-data-table">
                  <thead>
                    <tr>
                      <th>#</th>
                      {csvColumns.map((column) => (
                        <th key={column}>{column}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {csvRows.map((row, index) => (
                      <tr key={index}>
                        <td className="text-muted tabular-nums">{index + 1}</td>
                        {csvColumns.map((column) => (
                          <td key={column} title={stringifyCell(row[column])}>
                            <span className="block max-w-[260px] truncate">
                              {stringifyCell(row[column]) || <span className="text-muted/40">--</span>}
                            </span>
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="text-[13px] text-muted">No fields extracted yet.</p>
            )
          ) : null}

          {resultTab === "json" ? (
            <pre className="max-h-[40rem] overflow-auto rounded-md border border-border bg-panel-strong p-4 font-mono text-[12px] leading-[1.6] text-foreground">
              {JSON.stringify(displayedRecords.map((record) => cleanRecordForDisplay(record)), null, 2)}
            </pre>
          ) : null}

          {resultTab === "logs" ? <MessagesOnlyLogs logs={logs} /> : null}
        </Card>
      )}
    </div>
  );
}

function MetaCard({ label, value }: Readonly<{ label: string; value: string }>) {
  return (
    <div className="rounded-md border border-border bg-panel px-3 py-2.5 shadow-card">
      <div className="text-[10px] font-medium uppercase tracking-[0.06em] text-muted">{label}</div>
      <div className="mt-0.5 text-[14px] font-medium text-foreground">{value || "--"}</div>
    </div>
  );
}

function LiveMetaCard({ label, value }: Readonly<{ label: string; value: string }>) {
  return (
    <div className="rounded-md border border-border bg-panel-strong/60 px-3 py-2.5">
      <div className="text-[10px] font-medium uppercase tracking-[0.06em] text-muted">{label}</div>
      <div className="mt-0.5 text-[16px] font-semibold text-foreground">{value || "--"}</div>
    </div>
  );
}

function ResultTabButton({
  active,
  onClick,
  children,
}: Readonly<{ active: boolean; onClick: () => void; children: string }>) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex h-7 items-center rounded-md px-2.5 text-[13px] font-medium transition-all",
        active
          ? "bg-panel-strong text-foreground"
          : "text-muted hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

function MessagesOnlyLogs({ logs }: Readonly<{ logs: CrawlLog[] }>) {
  if (!logs.length) {
    return <p className="text-[13px] text-muted">No logs yet.</p>;
  }
  return (
    <div className="max-h-[40rem] space-y-0.5 overflow-auto rounded-md border border-border bg-panel-strong p-2">
      {logs.map((log) => (
        <div key={log.id} className="rounded px-2 py-1 font-mono text-[12px] text-foreground hover:bg-background/50">
          {log.message}
        </div>
      ))}
    </div>
  );
}

function StatusChip({ status }: Readonly<{ status: string }>) {
  return <Badge tone={getStatusTone(status)}>{status}</Badge>;
}

function ExtractionVerdictChip({ verdict }: Readonly<{ verdict: string | undefined }>) {
  if (!verdict) {
    return null;
  }
  const { tone, label } = getExtractionVerdictMeta(verdict);
  return <Badge tone={tone}>{label}</Badge>;
}

function renderStageIcon(state: StageState) {
  if (state === "done") return <CheckCircle2 className="size-4 text-success" />;
  if (state === "active") return <LoaderCircle className="size-4 animate-spin text-accent" />;
  if (state === "interrupted") return <XCircle className="size-4 text-warning" />;
  return <Circle className="size-4 text-muted/40" />;
}

function cleanRecordForDisplay(record: CrawlRecord): Record<string, unknown> {
  const clean: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(record.data ?? {})) {
    if (key.startsWith("_")) continue;
    if (value === null || value === "" || (Array.isArray(value) && value.length === 0)) continue;
    if (typeof value === "object" && value !== null && !Array.isArray(value) && Object.keys(value).length === 0) continue;
    clean[key] = value;
  }
  return clean;
}

function shouldPoll(run: CrawlRun | undefined) {
  if (!run) return true;
  if (TERMINAL_STATUSES.has(run.status)) return false;
  if (run.completed_at) return false;
  if (typeof run.result_summary?.progress === "number" && run.result_summary.progress >= 100) return false;
  if (typeof run.result_summary?.record_count === "number" && run.result_summary.record_count > 0) {
    const stage = normalizeStage(run.result_summary?.current_stage);
    if (stage === "UNIFY" || stage === "PUBLISH") {
      return false;
    }
  }
  return true;
}

function deriveStages(logs: CrawlLog[], status: string | undefined, currentStage: string | undefined) {
  const explicitStage = normalizeStage(currentStage);
  const explicitStageIndex = explicitStage ? STAGES.indexOf(explicitStage) : -1;
  const startedIndex = STAGES.reduce((index, stage, stageIndex) => (
    logs.some((log) => normalizeStageLog(log.message) === stage || log.message.includes(`[${stage}]`) || log.message.includes(stageTitle(stage))) ? stageIndex : index
  ), -1);
  const furthestIndex = Math.max(explicitStageIndex, startedIndex);
  const activeIndex = explicitStageIndex >= 0 ? explicitStageIndex : startedIndex;

  return STAGES.map((stage, index) => {
    let state: StageState = "idle";
    if (status === "completed") {
      state = "done";
    } else if (status === "failed" || status === "killed" || status === "proxy_exhausted") {
      if (index < activeIndex) {
        state = "done";
      } else if (index === activeIndex) {
        state = "interrupted";
      }
    } else if (activeIndex === -1) {
      state = index === 0 ? "active" : "idle";
    } else if (index < activeIndex || index <= furthestIndex - 1) {
      state = "done";
    } else if (index === activeIndex) {
      state = "active";
    }

    return { label: stageTitle(stage), state, description: stageDescription(stage) };
  });
}

function stageTitle(stage: (typeof STAGES)[number]) {
  if (stage === "ACQUIRE") return "Acquire";
  if (stage === "DISCOVER") return "Discover";
  if (stage === "EXTRACT") return "Extract";
  if (stage === "UNIFY") return "Unify";
  return "Publish";
}

function stageDescription(stage: (typeof STAGES)[number]) {
  if (stage === "ACQUIRE") return "Fetching page content";
  if (stage === "DISCOVER") return "Inspecting data sources";
  if (stage === "EXTRACT") return "Extracting fields";
  if (stage === "UNIFY") return "Normalizing records";
  return "Saving results";
}

function buildCsvRows(records: CrawlRecord[], columns: string[]) {
  return records.map((record) => {
    const row: Record<string, unknown> = {};
    for (const column of columns) {
      row[column] = readRecordValue(record, column);
    }
    return row;
  });
}

function readRecordValue(record: CrawlRecord, field: string) {
  const data = record.data && typeof record.data === "object" ? record.data : undefined;
  const rawData = record.raw_data && typeof record.raw_data === "object" ? record.raw_data : undefined;
  if (data && field in data) return data[field];
  if (rawData && field in rawData) return rawData[field];
  return "";
}

function getRunTitle(run: CrawlRun | undefined, live: boolean, runId: number) {
  if (live) return "Extraction Running";
  if (run?.status === "completed") return "Extraction Complete";
  if (run?.status === "killed") return "Extraction Killed";
  if (run?.status === "proxy_exhausted") return "Proxy Exhausted";
  if (run?.status === "failed") return "Extraction Failed";
  return `Run #${runId}`;
}

function getStatusTone(status: string) {
  if (status === "completed") return "success" as const;
  if (status === "running") return "success" as const;
  if (status === "paused") return "warning" as const;
  if (status === "failed" || status === "killed" || status === "proxy_exhausted") return "danger" as const;
  return "neutral" as const;
}

function getExtractionVerdictMeta(verdict: string) {
  if (verdict === "success") return { tone: "success" as const, label: "Success" };
  if (verdict === "partial") return { tone: "warning" as const, label: "Partial" };
  if (verdict === "blocked") return { tone: "danger" as const, label: "Blocked" };
  if (verdict === "listing_detection_failed") return { tone: "warning" as const, label: "No Listings" };
  if (verdict === "schema_miss") return { tone: "warning" as const, label: "Schema Miss" };
  if (verdict === "empty") return { tone: "danger" as const, label: "Empty" };
  if (verdict === "error") return { tone: "danger" as const, label: "Error" };
  return { tone: "neutral" as const, label: verdict };
}

function stringifyCell(value: unknown) {
  if (value == null) return "";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

function formatRunType(value: string | undefined) {
  if (value === "crawl") return "Single";
  if (value === "batch") return "Batch";
  if (value === "csv") return "CSV";
  return value ?? "--";
}

function formatPageType(value: string | undefined) {
  if (!value || value === "-") return "--";
  return value === "pdp" ? "PDP" : value.charAt(0).toUpperCase() + value.slice(1);
}

function readString(value: unknown) {
  return typeof value === "string" ? value : undefined;
}

function readNumber(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : undefined;
  }
  return undefined;
}

function normalizeStage(value: unknown) {
  const stage = readString(value)?.trim().toUpperCase();
  if (!stage) return undefined;
  if ((STAGES as readonly string[]).includes(stage)) {
    return stage as (typeof STAGES)[number];
  }
  return undefined;
}

function normalizeStageLog(message: string) {
  const upper = message.toUpperCase();
  if (upper.includes("ACQUIRE")) return "ACQUIRE";
  if (upper.includes("DISCOVER")) return "DISCOVER";
  if (upper.includes("EXTRACT")) return "EXTRACT";
  if (upper.includes("UNIFY")) return "UNIFY";
  if (upper.includes("PUBLISH")) return "PUBLISH";
  return "";
}

function extractBulkUrls(records: CrawlRecord[], columns: string[]) {
  const preferred = ["product_url", "job_url", "detail_url", "listing_url", "url", "source_url"];
  const columnMap = new Map<string, string>();
  for (const column of columns) {
    const normalized = column.toLowerCase();
    if (!columnMap.has(normalized)) {
      columnMap.set(normalized, column);
    }
  }
  const available = [...columnMap.keys()];
  const urlField = preferred.find((field) => columnMap.has(field));
  const urls: string[] = [];
  const seen = new Set<string>();

  for (const record of records) {
    const candidateFields = urlField
      ? [columnMap.get(urlField) ?? urlField]
      : available.map((field) => columnMap.get(field) ?? field);
    for (const field of candidateFields) {
      const value = readCaseInsensitiveRecordValue(record.data, field)
        ?? readCaseInsensitiveRecordValue(record.raw_data, field)
        ?? readCaseInsensitiveRecordValue(record.source_trace, field);
      if (!value || !value.startsWith("http")) continue;
      if (seen.has(value)) continue;
      seen.add(value);
      urls.push(value);
    }
  }

  return urls;
}

function readCaseInsensitiveRecordValue(source: unknown, field: string) {
  if (!source || typeof source !== "object") {
    return undefined;
  }
  const directValue = readString((source as Record<string, unknown>)[field]);
  if (directValue) {
    return directValue;
  }
  const normalizedField = field.toLowerCase();
  for (const [key, value] of Object.entries(source as Record<string, unknown>)) {
    if (key.toLowerCase() === normalizedField) {
      return readString(value);
    }
  }
  return undefined;
}

function inferVertical(surface: string | undefined) {
  if (!surface) return "ecommerce";
  if (surface.startsWith("job_")) return "jobs";
  if (surface.startsWith("automobile_")) return "automobile";
  return "ecommerce";
}

function getDomain(url: string | undefined) {
  if (!url) return "--";
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}
