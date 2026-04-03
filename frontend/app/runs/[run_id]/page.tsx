"use client";

import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Circle, LoaderCircle, XCircle } from "lucide-react";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { Badge, Button, Card, Input } from "../../../components/ui/primitives";
import { PageHeader, SectionHeader } from "../../../components/ui/patterns";
import { api } from "../../../lib/api";
import type { CrawlLog, CrawlRecord, CrawlRun, ReviewPayload, ReviewSelection } from "../../../lib/api/types";
import { cn } from "../../../lib/utils";

const TERMINAL_STATUSES = new Set(["completed", "failed", "cancelled"]);
const STAGES = ["ACQUIRE", "DISCOVER", "EXTRACT", "UNIFY", "PUBLISH"] as const;

type ResultTab = "csv" | "json" | "evidence" | "logs";
type StageState = "idle" | "active" | "done" | "interrupted";

export default function RunDetailPage() {
  const params = useParams<{ run_id: string }>();
  const runId = Number(params.run_id);
  const [resultTab, setResultTab] = useState<ResultTab>("csv");
  const [extraFieldInput, setExtraFieldInput] = useState("");
  const [localSelections, setLocalSelections] = useState<Record<string, ReviewSelection>>({});
  const [extraFields, setExtraFields] = useState<string[]>([]);
  const [saveError, setSaveError] = useState("");
  const [isSaving, setIsSaving] = useState(false);

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
    queryFn: () => api.getRecords(runId, { limit: 1000 }),
    enabled: Boolean(run),
    refetchInterval: pollInterval,
  });
  const reviewQuery = useQuery({
    queryKey: ["review", runId],
    queryFn: () => api.getReview(runId),
    enabled: Boolean(run && TERMINAL_STATUSES.has(run.status)),
  });

  const logs = logsQuery.data ?? [];
  const records = recordsQuery.data?.items ?? [];
  const review = reviewQuery.data;
  const runError = typeof run?.result_summary?.error === "string" ? run.result_summary.error : "";
  const stageItems = useMemo(() => deriveStages(logs, run?.status), [logs, run?.status]);

  useEffect(() => {
    if (!review) {
      return;
    }
    const selectedOutputs = new Set(buildDefaultSelections(review).filter((item) => item.selected).map((item) => item.output_field));
    const nextExtraFields = review.canonical_fields.filter((field) => !selectedOutputs.has(field));
    setExtraFields((current) => (current.length ? current : nextExtraFields));
  }, [review]);

  const fieldSelections = useMemo(() => {
    const defaults = buildDefaultSelections(review);
    return defaults.map((selection) => localSelections[selection.source_field] ?? selection);
  }, [localSelections, review]);

  const csvColumns = useMemo(() => {
    const selected = fieldSelections.filter((item) => item.selected).map((item) => item.output_field.trim()).filter(Boolean);
    return [...new Set([...selected, ...extraFields])];
  }, [extraFields, fieldSelections]);

  const csvRows = useMemo(
    () => buildCsvRows(records, fieldSelections, extraFields),
    [records, extraFields, fieldSelections],
  );

  async function savePromotion() {
    setSaveError("");
    setIsSaving(true);
    try {
      await api.saveReview(runId, {
        selections: fieldSelections,
        extra_fields: extraFields,
      });
      setExtraFieldInput("");
      await reviewQuery.refetch();
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to save promoted fields.";
      setSaveError(message);
      window.alert(message);
    } finally {
      setIsSaving(false);
    }
  }

  function addExtraField() {
    const value = normalizeFieldName(extraFieldInput);
    if (!value) {
      return;
    }
    setExtraFields((current) => (current.includes(value) ? current : [...current, value]));
    setExtraFieldInput("");
  }

  function removeExtraField(value: string) {
    setExtraFields((current) => current.filter((item) => item !== value));
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title={live ? "Extraction Running" : run?.status === "completed" ? "Extraction Complete" : `Run #${runId}`}
        description={run?.url ?? "Loading run details..."}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            {run ? <StatusChip status={run.status} /> : null}
            {!live ? (
              <>
                <a href={api.exportCsv(runId)} target="_blank" rel="noreferrer" className="inline-flex h-9 items-center justify-center rounded-lg border border-border bg-panel px-3.5 text-sm font-semibold text-foreground transition hover:bg-panel-strong">
                  CSV
                </a>
                <a href={api.exportJson(runId)} target="_blank" rel="noreferrer" className="inline-flex h-9 items-center justify-center rounded-lg border border-border bg-panel px-3.5 text-sm font-semibold text-foreground transition hover:bg-panel-strong">
                  JSON
                </a>
              </>
            ) : null}
            <Button variant="secondary" onClick={() => void Promise.all([runQuery.refetch(), logsQuery.refetch(), recordsQuery.refetch(), reviewQuery.refetch()])}>
              Refresh
            </Button>
          </div>
        }
      />

      <Card className="space-y-3">
        <div className="grid gap-2 text-sm text-muted sm:grid-cols-2 xl:grid-cols-4">
          <MetaLine label="Mode" value={formatRunType(run?.run_type)} />
          <MetaLine label="Page Type" value={formatPageType(readString(run?.settings?.page_type) ?? "-")} />
          <MetaLine label="Records" value={String(records.length)} />
          <MetaLine label="Domain" value={readString(run?.result_summary?.domain) ?? getDomain(run?.url)} />
        </div>
      </Card>

      {live ? (
        <Card className="space-y-4">
          <SectionHeader title="Pipeline Progress" description="Current crawl stages for this run." />
          <div className="space-y-2">
            {stageItems.map((stage) => (
              <div
                key={stage.label}
                className={cn(
                  "flex items-start gap-3 rounded-lg border px-3 py-3 transition",
                  stage.state === "active" && "border-brand/40 bg-brand/6",
                  stage.state === "done" && "border-emerald-500/20 bg-emerald-500/6",
                  stage.state === "interrupted" && "border-amber-500/30 bg-amber-500/10",
                  stage.state === "idle" && "border-border/60 bg-panel-strong/30",
                )}
              >
                <div className="mt-0.5 shrink-0">{renderStageIcon(stage.state)}</div>
                <div className="min-w-0">
                  <div className="text-sm font-semibold text-foreground">{stage.label}</div>
                  <div className="text-sm text-muted">{stage.description}</div>
                </div>
              </div>
            ))}
          </div>
        </Card>
      ) : (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1.55fr)_360px]">
          <Card className="space-y-4">
            <div className="flex flex-wrap gap-2 border-b border-border/70 pb-3">
              <ResultTabButton active={resultTab === "csv"} onClick={() => setResultTab("csv")}>CSV View</ResultTabButton>
              <ResultTabButton active={resultTab === "json"} onClick={() => setResultTab("json")}>JSON</ResultTabButton>
              <ResultTabButton active={resultTab === "evidence"} onClick={() => setResultTab("evidence")}>Evidence</ResultTabButton>
              <ResultTabButton active={resultTab === "logs"} onClick={() => setResultTab("logs")}>Logs</ResultTabButton>
            </div>

            {runError ? (
              <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-foreground">
                {runError}
              </div>
            ) : null}

            {resultTab === "csv" ? (
              csvColumns.length ? (
                <div className="overflow-auto rounded-lg border border-border/70">
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
                          <td>{index + 1}</td>
                          {csvColumns.map((column) => (
                            <td key={column} title={stringifyCell(row[column])}>
                              <span className="block max-w-[280px] truncate text-foreground">
                                {stringifyCell(row[column]) || "—"}
                              </span>
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="text-sm text-muted">No normalized fields available yet.</p>
              )
            ) : null}

            {resultTab === "json" ? (
              <pre className="max-h-[40rem] overflow-auto rounded-lg bg-panel-strong/60 p-4 text-[11px] text-foreground">
                {JSON.stringify(records.map((record) => record.data), null, 2)}
              </pre>
            ) : null}

            {resultTab === "evidence" ? (
              <pre className="max-h-[40rem] overflow-auto rounded-lg bg-panel-strong/60 p-4 text-[11px] text-foreground">
                {JSON.stringify(records.map((record) => ({
                  source_url: record.source_url,
                  raw_data: record.raw_data,
                  discovered_data: record.discovered_data,
                  source_trace: record.source_trace,
                  raw_html_path: record.raw_html_path,
                })), null, 2)}
              </pre>
            ) : null}

            {resultTab === "logs" ? <MessagesOnlyLogs logs={logs} /> : null}
          </Card>

          <Card className="space-y-4">
            <SectionHeader
              title="Canonical Fields"
              description="Select, rename, and promote fields for this domain and surface."
            />

            <div className="grid gap-2">
              {fieldSelections.map((selection) => (
                <div key={selection.source_field} className="grid gap-2 rounded-lg border border-border/60 bg-panel-strong/25 p-3">
                  <div className="flex items-center justify-between gap-3">
                    <label className="inline-flex items-center gap-2 text-sm font-medium text-foreground">
                      <input
                        type="checkbox"
                        checked={selection.selected}
                        onChange={(event) =>
                          setLocalSelections((current) => ({
                            ...current,
                            [selection.source_field]: { ...selection, selected: event.target.checked },
                          }))
                        }
                      />
                      {selection.source_field}
                    </label>
                    <span className="text-[11px] uppercase tracking-[0.18em] text-muted">Source</span>
                  </div>
                  <Input
                    value={selection.output_field}
                    onChange={(event) =>
                      setLocalSelections((current) => ({
                        ...current,
                        [selection.source_field]: {
                          ...selection,
                          output_field: normalizeFieldName(event.target.value),
                        },
                      }))
                    }
                    placeholder="canonical_field_name"
                  />
                </div>
              ))}
            </div>

            <div className="grid gap-2">
              <div className="text-sm font-medium text-foreground">Extra Canonical Fields</div>
              <div className="flex gap-2">
                <Input
                  value={extraFieldInput}
                  onChange={(event) => setExtraFieldInput(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      addExtraField();
                    }
                  }}
                  placeholder="add field like material or trim"
                />
                <Button type="button" variant="secondary" onClick={addExtraField}>Add</Button>
              </div>
              <div className="flex flex-wrap gap-2">
                {extraFields.map((field) => (
                  <button
                    key={field}
                    type="button"
                    onClick={() => removeExtraField(field)}
                    className="rounded-full border border-border px-3 py-1 text-xs text-foreground"
                  >
                    {field} ×
                  </button>
                ))}
              </div>
            </div>

            <div className="rounded-lg border border-border/60 bg-panel-strong/25 p-3 text-sm text-muted">
              Current canonical set: {(review?.canonical_fields ?? []).join(", ") || "No saved fields yet."}
            </div>

            {saveError ? (
              <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-700 dark:text-red-300">
                {saveError}
              </div>
            ) : null}

            <Button onClick={() => void savePromotion()} disabled={reviewQuery.isFetching || isSaving}>
              {isSaving ? "Saving..." : "Save promoted fields"}
            </Button>
          </Card>
        </div>
      )}
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
        "inline-flex h-8 items-center rounded-lg border px-3 text-sm font-semibold transition",
        active ? "border-brand bg-brand text-brand-foreground" : "border-border bg-panel-strong/40 text-foreground hover:bg-panel-strong",
      )}
    >
      {children}
    </button>
  );
}

function MessagesOnlyLogs({ logs }: Readonly<{ logs: CrawlLog[] }>) {
  if (!logs.length) {
    return <p className="text-sm text-muted">No logs yet.</p>;
  }
  return (
    <div className="max-h-[40rem] space-y-1 overflow-auto rounded-lg border border-border/70 bg-panel-strong/25 p-3">
      {logs.map((log) => (
        <div key={log.id} className="rounded-md px-2 py-1.5 text-sm text-foreground">
          {log.message}
        </div>
      ))}
    </div>
  );
}

function StatusChip({ status }: Readonly<{ status: string }>) {
  const tone = status === "completed" ? "success" : status === "failed" || status === "cancelled" ? "warning" : "neutral";
  return <Badge tone={tone}>{status}</Badge>;
}

function MetaLine({ label, value }: Readonly<{ label: string; value: string }>) {
  return (
    <div>
      <div className="text-[10px] font-semibold uppercase tracking-[0.16em]">{label}</div>
      <div className="mt-1 text-sm text-foreground">{value || "—"}</div>
    </div>
  );
}

function renderStageIcon(state: StageState) {
  if (state === "done") {
    return <CheckCircle2 className="size-4 text-emerald-500" />;
  }
  if (state === "active") {
    return <LoaderCircle className="size-4 animate-spin text-brand" />;
  }
  if (state === "interrupted") {
    return <XCircle className="size-4 text-amber-500" />;
  }
  return <Circle className="size-4 text-muted" />;
}

function shouldPoll(run: CrawlRun | undefined) {
  return !run || !TERMINAL_STATUSES.has(run.status);
}

function deriveStages(logs: CrawlLog[], status: string | undefined) {
  const startedIndex = STAGES.reduce((index, stage, stageIndex) => (
    logs.some((log) => log.message.includes(`[${stage}]`)) ? stageIndex : index
  ), -1);

  return STAGES.map((stage, index) => {
    let state: StageState = "idle";
    if (status === "completed") {
      state = "done";
    } else if (status === "failed" || status === "cancelled") {
      if (index < startedIndex) {
        state = "done";
      } else if (index === startedIndex) {
        state = "interrupted";
      }
    } else if (startedIndex === -1) {
      state = index === 0 ? "active" : "idle";
    } else if (index < startedIndex) {
      state = "done";
    } else if (index === startedIndex) {
      state = "active";
    }

    return {
      label: stageTitle(stage),
      state,
      description: stageDescription(stage),
    };
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
  if (stage === "ACQUIRE") return "Fetching the page and loading rendered content.";
  if (stage === "DISCOVER") return "Inspecting sources and reusable evidence.";
  if (stage === "EXTRACT") return "Extracting candidate fields.";
  if (stage === "UNIFY") return "Normalizing values into the target record shape.";
  return "Saving records and memory.";
}

function buildDefaultSelections(review: ReviewPayload | undefined): ReviewSelection[] {
  if (!review) {
    return [];
  }
  const fields = [...new Set([...review.normalized_fields, ...review.discovered_fields])];
  return fields.map((field) => ({
    source_field: field,
    output_field: review.domain_mapping[field] ?? review.suggested_mapping[field] ?? field,
    selected: review.normalized_fields.includes(field) || review.canonical_fields.includes(field),
  }));
}

function buildCsvRows(records: CrawlRecord[], selections: ReviewSelection[], extraFields: string[]) {
  const selected = selections.filter((item) => item.selected);
  return records.map((record) => {
    const row: Record<string, unknown> = {};
    for (const selection of selected) {
      row[selection.output_field] = readRecordValue(record, selection.source_field);
    }
    for (const field of extraFields) {
      row[field] = row[field] ?? "";
    }
    return row;
  });
}

function readRecordValue(record: CrawlRecord, field: string) {
  if (field in record.data) return record.data[field];
  if (field in record.raw_data) return record.raw_data[field];
  if (field in record.discovered_data) return record.discovered_data[field];
  return "";
}

function normalizeFieldName(value: string) {
  return value.trim().toLowerCase().replace(/\s+/g, "_");
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
  return value ?? "-";
}

function formatPageType(value: string | undefined) {
  if (!value || value === "-") return "-";
  return value === "pdp" ? "PDP" : value.charAt(0).toUpperCase() + value.slice(1);
}

function readString(value: unknown) {
  return typeof value === "string" ? value : undefined;
}

function getDomain(url: string | undefined) {
  if (!url) return "-";
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}
