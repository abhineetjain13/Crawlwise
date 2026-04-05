"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRightCircle, ChevronDown, ChevronsDown, Copy, Download } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

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
  type IntelligenceCandidate,
  type IntelligenceRecordGroup,
  isEmptyCandidateValue,
  isListingRun,
  LogTerminal,
  OutputTab,
  type OutputTabKey,
  presentCandidateValue,
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
  "focus-ring no-underline inline-flex h-8 items-center justify-center gap-1.5 rounded-[var(--radius-md)] bg-[var(--accent)] px-3.5 text-[13px] font-medium !text-white shadow-[var(--shadow-xs)] transition-all hover:bg-[var(--accent-hover)] !hover:text-white";

function isSafeHref(href: string) {
  try {
    const base = typeof window === "undefined" ? "http://localhost" : window.location.origin;
    const url = new URL(href, base);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}

function normalizeIntelligenceFieldName(value: string) {
  return value.trim().toLowerCase().replace(/[\s-]+/g, "_");
}

function intelligenceValueFingerprint(value: unknown) {
  return stringifyCell(value).replace(/\s+/g, " ").trim().toLowerCase();
}

function intelligenceSourcePriority(kind: IntelligenceCandidate["sourceKind"], confidence?: number) {
  if (kind === "llm_suggestion") return 3;
  if (kind === "review_bucket") return confidence && confidence >= 8 ? 2 : 1;
  return 0;
}

function shouldHideIntelligenceValue(record: CrawlRecord, fieldName: string, value: unknown) {
  const normalizedField = normalizeIntelligenceFieldName(fieldName);
  const outputFields = new Set(
    Object.keys(record.data ?? {})
      .map((key) => normalizeIntelligenceFieldName(key))
      .filter(Boolean),
  );
  if (outputFields.has(normalizedField)) {
    return true;
  }
  const fingerprint = intelligenceValueFingerprint(value);
  if (!fingerprint) {
    return true;
  }
  const outputValues = new Set(
    Object.values(record.data ?? {})
      .map((item) => intelligenceValueFingerprint(item))
      .filter(Boolean),
  );
  return outputValues.has(fingerprint);
}

export function CrawlRunScreen({ runId }: Readonly<CrawlRunScreenProps>) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [outputTab, setOutputTab] = useState<OutputTabKey>("table");
  const [liveJumpAvailable, setLiveJumpAvailable] = useState(false);
  const [runActionPending, setRunActionPending] = useState<"pause" | "resume" | "kill" | null>(null);
  const [selectedCandidateKeys, setSelectedCandidateKeys] = useState<Record<string, boolean>>({});
  const [candidateEdits, setCandidateEdits] = useState<Record<string, { fieldName: string; value?: string }>>({});
  const [expandedIntelligenceGroups, setExpandedIntelligenceGroups] = useState<Record<string, boolean>>({});
  const [commitPending, setCommitPending] = useState(false);
  const [commitError, setCommitError] = useState("");
  const [runActionError, setRunActionError] = useState("");
  const logViewportRef = useRef<HTMLDivElement | null>(null);
  const terminalSyncRef = useRef<string | null>(null);
  const intelligenceGroupsInitializedRef = useRef(false);
  const runQuery = useQuery({
    queryKey: ["crawl-run", runId],
    queryFn: () => api.getCrawl(runId),
    refetchInterval: (query) =>
      query.state.data && ACTIVE_STATUSES.has(query.state.data.status) ? POLLING_INTERVALS.ACTIVE_JOB_MS : false,
  });
  const run = runQuery.data;
  const live = Boolean(run && ACTIVE_STATUSES.has(run.status));
  const terminal = run ? TERMINAL_STATUSES.has(run.status) : false;

  const [startMs] = useState(Date.now());
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

  const records = useMemo(() => recordsQuery.data?.items ?? [], [recordsQuery.data?.items]);
  const logs = useMemo(() => (logsQuery.data ?? []).slice(-CRAWL_DEFAULTS.MAX_LIVE_LOGS), [logsQuery.data]);
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

    void Promise.allSettled([runQuery.refetch(), recordsQuery.refetch(), logsQuery.refetch()]);
  }, [logsQuery, recordsQuery, run, runQuery, terminal]);

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

  const intelligenceCandidates = useMemo<IntelligenceCandidate[]>(() => {
    const grouped = new Map<string, IntelligenceCandidate>();

    for (const record of records) {
      const recordUrl = extractRecordUrl(record) || record.source_url;
      const recordTitle = stringifyCell(record.data?.title).trim() || recordUrl || `Record ${record.id}`;
      const fieldDiscovery = record.source_trace?.field_discovery;
      const reviewBucket = Array.isArray(record.review_bucket)
        ? record.review_bucket
        : record.review_bucket && typeof record.review_bucket === "object"
          ? [record.review_bucket]
          : [];

      if (fieldDiscovery && typeof fieldDiscovery === "object" && !Array.isArray(fieldDiscovery)) {
        for (const [fieldName, rawEntry] of Object.entries(fieldDiscovery as Record<string, unknown>)) {
          if (!rawEntry || typeof rawEntry !== "object") {
            continue;
          }
          const entry = rawEntry as Record<string, unknown>;
          if (stringifyCell(entry.status).trim() !== "found") {
            continue;
          }
          if (stringifyCell(entry.tier).trim() !== "intelligence") {
            continue;
          }
          const rawValue = entry.value;
          const displayValue = stringifyCell(rawValue).trim();
          if (!displayValue) {
            continue;
          }
          if (shouldHideIntelligenceValue(record, fieldName, rawValue)) {
            continue;
          }
          const sources = Array.isArray(entry.sources)
            ? entry.sources.map((source) => stringifyCell(source).trim()).filter(Boolean)
            : [];
          const groupLabel = sources.length ? `Discovered via ${sources.join(", ")}` : "Discovered";
          const key = `${record.id}:${normalizeIntelligenceFieldName(fieldName)}:${intelligenceValueFingerprint(rawValue)}`;
          const candidate: IntelligenceCandidate = {
            key,
            recordId: record.id,
            recordUrl,
            recordTitle,
            fieldName,
            displayLabel: humanizeFieldName(fieldName),
            groupLabel,
            value: rawValue,
            sortOrder: Number.MAX_SAFE_INTEGER - 1000,
            sourceKind: "candidate",
          };
          const existing = grouped.get(key);
          if (!existing || intelligenceSourcePriority(candidate.sourceKind) > intelligenceSourcePriority(existing.sourceKind, existing.confidenceScore)) {
            grouped.set(key, candidate);
          }
        }
      }

      for (const item of reviewBucket) {
        if (!item || typeof item !== "object") {
          continue;
        }
        const fieldName = stringifyCell(item.key).trim();
        const rawValue = item.value;
        const displayValue = stringifyCell(rawValue).trim();
        if (!fieldName || !displayValue) {
          continue;
        }
        const confidence = Number(item.confidence_score) || 0;
        if (confidence < 7) {
          continue;
        }
        if (shouldHideIntelligenceValue(record, fieldName, rawValue)) {
          continue;
        }
        const key = `${record.id}:${normalizeIntelligenceFieldName(fieldName)}:${intelligenceValueFingerprint(rawValue)}`;
        const candidate: IntelligenceCandidate = {
          key,
          recordId: record.id,
          recordUrl,
          recordTitle,
          fieldName,
          displayLabel: humanizeFieldName(fieldName),
          groupLabel: confidence > 0 ? `Review Bucket (${confidence}/10)` : "Review Bucket",
          value: rawValue,
          sortOrder: Number.MAX_SAFE_INTEGER - Math.min(Math.max(confidence, 0), 10),
          confidenceScore: confidence || undefined,
          sourceKind: "review_bucket",
        };
        const existing = grouped.get(key);
        if (!existing || intelligenceSourcePriority(candidate.sourceKind, confidence) > intelligenceSourcePriority(existing.sourceKind, existing.confidenceScore)) {
          grouped.set(key, candidate);
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
          if (shouldHideIntelligenceValue(record, fieldName, rawValue)) {
            continue;
          }
          const key = `${record.id}:${normalizeIntelligenceFieldName(fieldName)}:${intelligenceValueFingerprint(rawValue)}`;
          const candidate: IntelligenceCandidate = {
            key,
            recordId: record.id,
            recordUrl,
            recordTitle,
            fieldName,
            displayLabel: humanizeFieldName(fieldName),
            groupLabel: "Suggested",
            value: rawValue,
            sortOrder: Number.MAX_SAFE_INTEGER,
            sourceKind: "llm_suggestion",
          };
          const existing = grouped.get(key);
          if (!existing || intelligenceSourcePriority(candidate.sourceKind) > intelligenceSourcePriority(existing.sourceKind, existing.confidenceScore)) {
            grouped.set(key, candidate);
          }
        }
      }
    }

    return Array.from(grouped.values()).sort((left, right) => {
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
      intelligenceGroupsInitializedRef.current = false;
      return;
    }
    setExpandedIntelligenceGroups((current) => {
      const next: Record<string, boolean> = {};
      for (const group of intelligenceRecordGroups) {
        if (group.key in current) {
          next[group.key] = current[group.key];
        }
      }
      if (!intelligenceGroupsInitializedRef.current && !(intelligenceRecordGroups[0].key in next)) {
        next[intelligenceRecordGroups[0].key] = true;
        intelligenceGroupsInitializedRef.current = true;
      }
      return next;
    });
  }, [intelligenceRecordGroups]);

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
      await Promise.all([runQuery.refetch(), logsQuery.refetch(), recordsQuery.refetch()]);
    } catch (error) {
      setRunActionError(error instanceof Error ? error.message : `Unable to ${action} crawl.`);
    } finally {
      setRunActionPending(null);
    }
  }

  async function commitSelectedCandidates(candidateKeys?: string[]) {
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
      setCandidateEdits((current) => {
        if (!allowedKeys) {
          return {};
        }
        const next = { ...current };
        for (const key of allowedKeys) {
          delete next[key];
        }
        return next;
      });
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
    setSelectedCandidateKeys((current) => ({
      ...current,
      ...Object.fromEntries(group.items.map((item) => [item.key, true])),
    }));
    await commitSelectedCandidates(group.items.map((item) => item.key));
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
                CSV
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
                <OutputTab active={outputTab === "intelligence"} onClick={() => setOutputTab("intelligence")}>
                  Intelligence
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

            {outputTab === "intelligence" ? (
              <Card className="space-y-4 p-4">
                {commitError ? (
                  <div className="rounded-md border border-danger/20 bg-danger/10 px-3 py-2 text-sm text-danger">
                    {commitError}
                  </div>
                ) : null}
                {intelligenceCandidates.length ? (
                  <div className="space-y-4">
                    {intelligenceRecordGroups.map((group) => {
                      const selectedCount = group.items.filter((item) => selectedCandidateKeys[item.key]).length;
                      const expanded = Boolean(expandedIntelligenceGroups[group.key]);
                      return (
                        <div key={group.key} className="space-y-2">
                          <div className="flex flex-wrap items-center gap-3">
                            <button
                              type="button"
                              aria-expanded={expanded}
                              onClick={() =>
                                setExpandedIntelligenceGroups((current) => ({ ...current, [group.key]: !expanded }))
                              }
                              className="min-w-0 flex flex-1 items-center gap-3 text-left"
                            >
                              <div className="min-w-0 flex flex-1 items-center gap-3 overflow-hidden">
                                <span className="truncate text-sm font-semibold text-foreground">{group.recordTitle}</span>
                                <span className="truncate text-xs text-muted">{group.recordUrl}</span>
                              </div>
                              <ChevronDown className={cn("size-4 shrink-0 transition-transform", expanded ? "rotate-180" : "")} />
                            </button>
                            <Badge tone="neutral">{group.items.length} rows</Badge>
                            <Badge tone="neutral">{selectedCount} selected</Badge>
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
                          <div
                            className={cn(
                              "overflow-hidden transition-[opacity] duration-150 ease-out",
                              expanded ? "opacity-100" : "opacity-0",
                            )}
                          >
                            <div className={cn("pt-1", expanded ? "block" : "hidden")}>
                              <table className="compact-data-table min-w-[1080px]">
                                <thead>
                                  <tr>
                                    <th className="w-10">
                                      <input
                                        type="checkbox"
                                        aria-label={`Select all rows for ${group.recordTitle}`}
                                        checked={group.items.length > 0 && selectedCount === group.items.length}
                                        onChange={(event) => setGroupCandidateSelection(group, event.target.checked)}
                                      />
                                    </th>
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
                                            onChange={(event) =>
                                              setCandidateEdits((current) => ({
                                                ...current,
                                                [item.key]: {
                                                  fieldName: event.target.value,
                                                  value: current[item.key]?.value,
                                                },
                                              }))
                                            }
                                            className="h-8 border-0 bg-transparent px-0 text-sm shadow-none"
                                          />
                                        </td>
                                        <td className="text-xs text-muted">
                                          <div>{item.groupLabel || "General"}</div>
                                          {item.sourceKind === "review_bucket" && item.confidenceScore ? (
                                            <div className="mt-1 text-[11px] text-foreground/70">
                                              Confidence {item.confidenceScore}/10
                                            </div>
                                          ) : null}
                                        </td>
                                        <td title={editedValue}>
                                          <div className="flex items-center gap-2">
                                            <Input
                                              value={editedValue}
                                              onChange={(event) =>
                                                setCandidateEdits((current) => ({
                                                  ...current,
                                                  [item.key]: {
                                                    fieldName: current[item.key]?.fieldName ?? item.displayLabel,
                                                    value: event.target.value,
                                                  },
                                                }))
                                              }
                                              className="h-8 border-0 bg-transparent px-0 font-mono text-sm shadow-none"
                                            />
                                            {item.href && isSafeHref(item.href) ? (
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
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <div className="text-sm text-muted">No field candidates are available for this run.</div>
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
