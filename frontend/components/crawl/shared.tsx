"use client";

import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  CircleAlert,
  Database,
  Dot,
  Globe,
  GripVertical,
  HardDrive,
  Info,
  Layers,
  Monitor,
  Plus,
  RefreshCw,
  RotateCcw,
  ShieldAlert,
  Trash2,
  X,
  XCircle,
  Zap,
} from "lucide-react";
import React, { memo, useCallback, useEffect, useRef, useState } from "react";
import type { ReactElement, ReactNode, RefObject } from "react";

import { Badge, Button, Input, Textarea, Tooltip, Toggle as PrimitiveToggle } from "../ui/primitives";
import type { CrawlDomain, CrawlRecord, CrawlRun, CrawlSurface } from "../../lib/api/types";
import { formatTimeHms, parseApiDate } from "../../lib/format/date";
import { cn } from "../../lib/utils";

export type CrawlTab = "category" | "pdp";
export type CategoryMode = "single" | "sitemap" | "bulk";
export type PdpMode = "single" | "batch" | "csv";
export type ValidationState = "idle" | "valid" | "invalid";
export type FieldRow = {
  id: string;
  fieldName: string;
  cssSelector: string;
  xpath: string;
  regex: string;
  cssState: ValidationState;
  xpathState: ValidationState;
  regexState: ValidationState;
};
export type FieldRowMessageTone = "success" | "warning" | "danger";
export type PendingDispatch = {
  runType: "crawl" | "batch" | "csv";
  surface: CrawlSurface;
  url?: string;
  urls?: string[];
  settings: Record<string, unknown>;
  additionalFields: string[];
  csvFile: File | null;
};
export type OutputTabKey = "table" | "json" | "markdown" | "logs" | "learning" | "run_config";
type IconElementProps = {
  className?: string;
};

export function parseRequestedCrawlTab(value: string | null): CrawlTab | null {
  return value === "category" || value === "pdp" ? value : null;
}

export function parseRequestedCategoryMode(value: string | null): CategoryMode | null {
  return value === "single" || value === "sitemap" || value === "bulk" ? value : null;
}

export function parseRequestedPdpMode(value: string | null): PdpMode | null {
  return value === "single" || value === "batch" || value === "csv" ? value : null;
}

export function uniqueFields(values: string[]) {
  return Array.from(new Set(values.map(normalizeField).filter(Boolean)));
}

export function cleanRequestedField(value: string) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

export function uniqueRequestedFields(values: string[]) {
  const deduped: string[] = [];
  const seen = new Set<string>();
  for (const value of values) {
    const cleaned = cleanRequestedField(value);
    if (!cleaned) {
      continue;
    }
    const dedupeKey = cleaned.toLocaleLowerCase();
    if (seen.has(dedupeKey)) {
      continue;
    }
    seen.add(dedupeKey);
    deduped.push(cleaned);
  }
  return deduped;
}

export function uniqueNumbers(values: number[]) {
  return Array.from(new Set(values));
}

export function uniqueStrings(values: string[]) {
  return Array.from(new Set(values.map((value) => value.trim()).filter(Boolean)));
}

export function normalizeField(value: string) {
  return value
    .trim()
    .replace(/&/g, "")
    .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/_+/g, "_")
    .replace(/^_+|_+$/g, "");
}

export function deriveSurface(domain: CrawlDomain, module: CrawlTab): CrawlSurface {
  if (domain === "jobs") {
    return module === "category" ? "job_listing" : "job_detail";
  }
  return module === "category" ? "ecommerce_listing" : "ecommerce_detail";
}

export function inferDomainFromSurface(surface: string | null | undefined): CrawlDomain | null {
  const normalizedSurface = String(surface || "").toLowerCase();
  if (normalizedSurface.startsWith("job_")) {
    return "jobs";
  }
  if (normalizedSurface.startsWith("ecommerce_")) {
    return "commerce";
  }
  return null;
}

const SCHEMA_TYPE_FIELD_NAMES = new Set(
  [
    "AggregateRating",
    "BreadcrumbList",
    "IndividualProduct",
    "Organization",
    "PeopleAudience",
    "PostalAddress",
    "QuantitativeValue",
    "WebPage",
    "WebSite",
  ].flatMap((value) => {
    const normalized = normalizeField(value);
    return [normalized, normalized.replace(/_/g, "")];
  }),
);

const DAY_OF_WEEK_FIELD_NAMES = new Set([
  "monday",
  "tuesday",
  "wednesday",
  "thursday",
  "friday",
  "saturday",
  "sunday",
]);

export function validateAdditionalFieldName(value: string) {
  const cleaned = cleanRequestedField(value);
  const normalized = normalizeField(cleaned);
  const collapsed = normalized.replace(/_/g, "");
  if (!cleaned) {
    return "Field name cannot be empty.";
  }
  if (cleaned.length < 2) {
    return "Field name must be at least 2 characters.";
  }
  if (cleaned.length > 60) {
    return "Field name must be 60 characters or fewer.";
  }
  if (!normalized) {
    return "Field name must include letters or numbers.";
  }
  if ((cleaned.match(/\s+/g) ?? []).length >= 7 || (normalized.match(/_/g) ?? []).length >= 7) {
    return "Field name is too sentence-like. Keep it concise.";
  }
  if (SCHEMA_TYPE_FIELD_NAMES.has(normalized) || SCHEMA_TYPE_FIELD_NAMES.has(collapsed)) {
    return "Field name looks like a schema type. Use a business field.";
  }
  if (DAY_OF_WEEK_FIELD_NAMES.has(normalized)) {
    return "Field name looks like a day label. Use a business field.";
  }
  return null;
}

export function parseLines(value: string) {
  return value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

export function clampNumber(value: string | number, min: number, max: number, fallback: number) {
  const parsed = Number.parseInt(String(value), 10);
  if (Number.isNaN(parsed)) return fallback;
  return Math.min(max, Math.max(min, parsed));
}

export function extractRecordUrl(record: CrawlRecord) {
  const value = record.data?.url ?? record.raw_data?.url ?? record.source_url;
  return stringifyCell(value).trim();
}

export function isListingRun(run?: CrawlRun) {
  return inferRunModule(run) === "category";
}

export function stringifyCell(value: unknown) {
  if (value == null) return "";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

export function decodeUrlForDisplay(value: string) {
  const text = String(value || "").trim();
  if (!/^https?:\/\//i.test(text)) return text;
  try {
    return decodeURI(text);
  } catch {
    return text;
  }
}

export function formatCellDisplay(value: unknown) {
  return decodeUrlForDisplay(stringifyCell(value));
}

export function decodeUrlsForDisplay<T>(value: T): T {
  if (typeof value === "string") {
    return decodeUrlForDisplay(value) as T;
  }
  if (Array.isArray(value)) {
    return value.map((entry) => decodeUrlsForDisplay(entry)) as T;
  }
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([key, entry]) => [key, decodeUrlsForDisplay(entry)]),
    ) as T;
  }
  return value;
}

export function humanizeFieldName(value: string) {
  const normalized = String(value || "")
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (!normalized) return "";
  return normalized.charAt(0).toUpperCase() + normalized.slice(1);
}

export function presentCandidateValue(value: unknown) {
  const trimmed = stringifyCell(value).trim();
  if (!trimmed) return "";
  const schemaMatch = trimmed.match(/^https?:\/\/schema\.org\/([A-Za-z]+)$/i);
  if (!schemaMatch) return trimmed;
  const token = schemaMatch[1].replace(/([a-z])([A-Z])/g, "$1 $2");
  return token.charAt(0).toUpperCase() + token.slice(1);
}

export function isEmptyCandidateValue(value: unknown) {
  if (value === null || value === undefined) return true;
  if (typeof value === "string") return value.trim().length === 0;
  if (Array.isArray(value)) return value.length === 0;
  if (typeof value === "object") return Object.keys(value).length === 0;
  return false;
}

export function readRecordValue(record: CrawlRecord, field: string) {
  const data = record.data && typeof record.data === "object" ? record.data : {};
  const raw = record.raw_data && typeof record.raw_data === "object" ? record.raw_data : {};
  if (field in data) return data[field];
  if (field in raw) return raw[field];
  if (field === "source_url") return record.source_url;
  return "";
}

export function formatDuration(start?: string | null, end?: string | null) {
  if (!start) return "--";
  const started = parseApiDate(start).getTime();
  const finished = end ? parseApiDate(end).getTime() : Date.now();

  if (!Number.isFinite(started) || !Number.isFinite(finished)) return "--";
  const ms = Math.max(0, finished - started);
  const totalSeconds = Math.floor(ms / 1000);
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m}m ${s}s`;
}

export function formatDurationMs(durationMs?: number | null) {
  if (typeof durationMs !== "number" || !Number.isFinite(durationMs) || durationMs < 0) {
    return null;
  }
  const totalSeconds = Math.floor(durationMs / 1000);
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m}m ${s}s`;
}

export function progressPercent(run: CrawlRun | undefined) {
  const value = typeof run?.result_summary?.progress === "number" ? run.result_summary.progress : 0;
  return Math.min(100, Math.max(0, value));
}

export function extractionVerdict(run: CrawlRun | undefined) {
  const verdict = String(run?.result_summary?.extraction_verdict ?? "").trim().toLowerCase();
  return verdict || "unknown";
}

export function extractionVerdictTone(verdict: string) {
  if (verdict === "success") return "success";
  if (verdict === "partial") return "warning";
  if (verdict === "schema_miss" || verdict === "listing_detection_failed" || verdict === "empty") return "warning";
  if (verdict === "blocked" || verdict === "proxy_exhausted" || verdict === "error") return "danger";
  return "neutral";
}

export function humanizeVerdict(verdict: string) {
  return verdict.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}
export type QualityLevel = "high" | "medium" | "low" | "unknown";

export type QualitySnapshot = {
  level: QualityLevel;
  score: number;
  populatedCells: number;
  totalCells: number;
};

const QUALITY_IDENTITY_FIELD_PATTERNS = [
  /^title$/,
  /^name$/,
  /_title$/,
  /_name$/,
  /^url$/,
  /_url$/,
  /^price$/,
  /_price$/,
  /^brand$/,
  /^company$/,
  /^location$/,
  /^sku$/,
  /^id$/,
];

const LOW_SIGNAL_VALUE_TOKENS = new Set([
  "n/a",
  "na",
  "none",
  "null",
  "undefined",
  "unknown",
  "tbd",
  "--",
  "-",
]);

function isIdentityField(field: string) {
  const normalized = normalizeField(field);
  return QUALITY_IDENTITY_FIELD_PATTERNS.some((pattern) => pattern.test(normalized));
}

function isInformativeValue(value: unknown): boolean {
  if (isEmptyCandidateValue(value)) {
    return false;
  }

  const rendered = stringifyCell(value).trim();
  if (!rendered) {
    return false;
  }

  if (LOW_SIGNAL_VALUE_TOKENS.has(rendered.toLowerCase())) {
    return false;
  }

  if (Array.isArray(value)) {
    return value.some((entry) => isInformativeValue(entry));
  }

  if (typeof value === "object") {
    return Object.values(value as Record<string, unknown>).some((entry) => isInformativeValue(entry));
  }

  return rendered.length >= 2;
}

export function scoreRecordQuality(record: CrawlRecord, visibleColumns: string[]) {
  if (!visibleColumns.length) {
    return 0;
  }

  let populatedCount = 0;
  let informativeCount = 0;
  let identityCount = 0;

  for (const column of visibleColumns) {
    const value = readRecordValue(record, column);
    if (isEmptyCandidateValue(value)) {
      continue;
    }

    populatedCount += 1;
    if (isInformativeValue(value)) {
      informativeCount += 1;
      if (isIdentityField(column)) {
        identityCount += 1;
      }
    }
  }

  const coverage = populatedCount / visibleColumns.length;
  const richness = Math.min(1, informativeCount / 4);
  const identity = Math.min(1, identityCount / 2);
  let score = coverage * 0.45 + richness * 0.35 + identity * 0.2;

  if (informativeCount <= 1) {
    score = Math.min(score, 0.34);
  } else if (informativeCount === 2) {
    score = Math.min(score, identityCount >= 1 ? 0.68 : 0.54);
  } else if (informativeCount < 4) {
    score = Math.min(score, 0.84);
  }

  return score;
}


export function estimateDataQuality(records: CrawlRecord[], visibleColumns: string[]): QualitySnapshot {
  if (!records.length || !visibleColumns.length) {
    return {
      level: "unknown",
      score: 0,
      populatedCells: 0,
      totalCells: records.length * visibleColumns.length,
    };
  }

  const totalCells = records.length * visibleColumns.length;
  let populatedCells = 0;
  let aggregateRecordScore = 0;
  let broadlyUsefulRows = 0;

  for (const record of records) {
    let populatedForRecord = 0;
    for (const column of visibleColumns) {
      const value = readRecordValue(record, column);
      if (!isEmptyCandidateValue(value)) {
        populatedCells += 1;
        populatedForRecord += 1;
      }
    }
    const recordScore = scoreRecordQuality(record, visibleColumns);
    aggregateRecordScore += recordScore;
    if (recordScore >= 0.55 || populatedForRecord >= 3) {
      broadlyUsefulRows += 1;
    }
  }

  const completenessRatio = populatedCells / totalCells;
  const averageRecordScore = aggregateRecordScore / records.length;
  const usefulRowRatio = broadlyUsefulRows / records.length;
  const score = completenessRatio * 0.2 + averageRecordScore * 0.6 + usefulRowRatio * 0.2;

  if (score >= 0.8) {
    return { level: "high", score, populatedCells, totalCells };
  }
  if (score >= 0.5) {
    return { level: "medium", score, populatedCells, totalCells };
  }
  return { level: "low", score, populatedCells, totalCells };
}

export function qualityTone(level: QualityLevel) {
  if (level === "high") return "success";
  if (level === "medium") return "warning";
  if (level === "low") return "danger";
  return "neutral";
}

export function humanizeQuality(level: QualityLevel) {
  if (level === "unknown") return "Unknown";
  return level.charAt(0).toUpperCase() + level.slice(1);
}

export function qualityLevelFromScore(score: number): QualityLevel {
  if (!Number.isFinite(score)) return "unknown";
  if (score >= 0.8) return "high";
  if (score >= 0.5) return "medium";
  return "low";
}

export function copyJson(records: CrawlRecord[]) {
  void navigator.clipboard.writeText(JSON.stringify(records.map(cleanRecord), null, 2));
}

export function cleanRecord(record: CrawlRecord) {
  return Object.fromEntries(
    Object.entries(record.data ?? {}).filter(
      ([key, value]) => !key.startsWith("_") && value !== null && value !== "" && !(Array.isArray(value) && value.length === 0),
    ),
  );
}

export function scrollViewportToBottom(ref: RefObject<HTMLDivElement | null>) {
  window.requestAnimationFrame(() => {
    const node = ref.current;
    if (!node) {
      return;
    }
    node.scrollTop = node.scrollHeight;
  });
}

function getLogIcon(level: string, message: string) {
  const msg = message.toLowerCase();
  const isWarn = level === "warning" || level === "warn";
  const isError = logMessageIsError(level, message);
  const hasUrl = /https?:\/\//i.test(message);

  if (isError) return XCircle;
  if (isWarn) return AlertTriangle;

  if (msg.includes("starting crawl")) return Activity;
  if (msg.includes("ignoring robots.txt")) return ShieldAlert;
  if (msg.includes("extracted")) return Database;
  if (msg.includes("normalized") || msg.includes("normalised")) return Layers;
  if (msg.includes("persisted")) return HardDrive;
  if (
    msg.includes("acquiring") ||
    msg.includes("fetching")
  ) return Globe;
  if (
    msg.includes("browser") ||
    msg.includes("playwright") ||
    msg.includes("patchright") ||
    msg.includes("headless")
  ) return Monitor;
  if (msg.includes("record")) return Database;
  if (
    msg.includes("page loaded") ||
    msg.includes("page load")
  ) return Zap;
  if (
    msg.includes("challenge") ||
    msg.includes("blocked") ||
    msg.includes("captcha") ||
    msg.includes("bot check")
  ) return ShieldAlert;
  if (hasUrl) return Globe;
  if (
    msg.includes("retry") ||
    msg.includes("retrying") ||
    msg.includes("refresh")
  ) return RefreshCw;
  if (
    msg.includes("complete") ||
    msg.includes("success") ||
    msg.includes("done") ||
    msg.includes("finished")
  ) return CheckCircle2;
  return Dot;
}

function getLogIconStyle(level: string, message: string): { iconCls: string; bgCls: string } {
  const msg = message.toLowerCase();
  const isError = logMessageIsError(level, message);
  const hasUrl = /https?:\/\//i.test(message);

  if (isError) return { iconCls: "text-danger", bgCls: "bg-danger/10" };
  if (level === "warning" || level === "warn") return { iconCls: "text-warning", bgCls: "bg-warning/10" };

  if (msg.includes("starting crawl")) return { iconCls: "text-sky-500", bgCls: "bg-sky-500/10" };
  if (msg.includes("ignoring robots.txt")) return { iconCls: "text-orange-400", bgCls: "bg-orange-400/10" };
  if (msg.includes("resolved")) return { iconCls: "text-slate-400", bgCls: "bg-slate-400/10" };
  if (msg.includes("acquired")) return { iconCls: "text-indigo-400", bgCls: "bg-indigo-400/10" };
  if (msg.includes("extracted")) return { iconCls: "text-emerald-400", bgCls: "bg-emerald-400/12" };
  if (msg.includes("normalized") || msg.includes("normalised")) return { iconCls: "text-amber-400", bgCls: "bg-amber-400/12" };
  if (msg.includes("persisted")) return { iconCls: "text-fuchsia-400", bgCls: "bg-fuchsia-400/12" };
  if (msg.includes("page loaded") || msg.includes("page load"))
    return { iconCls: "text-amber-400", bgCls: "bg-amber-400/12" };
  if (msg.includes("challenge") || msg.includes("blocked") || msg.includes("captcha") || msg.includes("bot check"))
    return { iconCls: "text-orange-400", bgCls: "bg-orange-400/12" };
  if (msg.includes("acquiring") || msg.includes("fetching"))
    return { iconCls: "text-indigo-400", bgCls: "bg-indigo-400/12" };
  if (msg.includes("browser") || msg.includes("patchright") || msg.includes("playwright") || msg.includes("headless"))
    return { iconCls: "text-violet-400", bgCls: "bg-violet-400/12" };
  if (msg.includes("record")) return { iconCls: "text-emerald-400", bgCls: "bg-emerald-400/12" };
  if (hasUrl) return { iconCls: "text-indigo-400", bgCls: "bg-indigo-400/12" };
  if (msg.includes("complete") || msg.includes("success") || msg.includes("done") || msg.includes("finished"))
    return { iconCls: "text-emerald-500", bgCls: "bg-emerald-500/10" };
  if (msg.includes("retry") || msg.includes("retrying"))
    return { iconCls: "text-sky-400", bgCls: "bg-sky-400/12" };
  if (level === "debug") return { iconCls: "text-white/20", bgCls: "bg-transparent" };
  return { iconCls: "text-white/40", bgCls: "bg-white/5" };
}

function logMessageIsError(level: string, message: string): boolean {
  const normalizedLevel = String(level || "").toLowerCase();
  if (normalizedLevel === "error") return true;
  if (normalizedLevel) return false;
  const text = String(message || "");
  const lowered = text.toLowerCase();
  if (
    /\b(no|not|none|no longer)\s+(error|errors|failed)\b/i.test(text) ||
    lowered.includes("no errors found") ||
    lowered.includes("validation failed check passed")
  ) {
    return false;
  }
  return /^\s*(error|failed)\b/i.test(text);
}

function sanitizeLogMessage(message: string) {
  return String(message || "")
    .replace(/\s*\[corr=[^\]]+\]/gi, "")
    .replace(/\s{2,}/g, " ")
    .trim();
}

function ShortenedUrl({ url }: { url: string }) {
  let display = url;
  try {
    const parsed = new URL(url);
    const domain = parsed.hostname.replace(/^www\./, "");
    const parts = parsed.pathname.split("/").filter(Boolean);
    const lastPart = parts.at(-1) || "";
    if (parts.length > 1) {
      display = `${domain}/.../${lastPart}`;
    } else {
      display = domain + (lastPart ? `/${lastPart}` : "");
    }
  } catch {
    display = url.length > 40 ? url.slice(0, 40) + "…" : url;
  }

  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      className="text-blue-400/60 hover:text-blue-400 underline underline-offset-2 decoration-blue-400/20 transition-colors"
      title={url}
      onClick={(e) => e.stopPropagation()}
    >
      {display}
    </a>
  );
}

function renderLogContent(message: string, isStartingCrawl: boolean): React.ReactNode {
  let text = sanitizeLogMessage(message).replace(/^\[ROBOTS\]\s*/i, "");
  text = text.replace(
    /launched headless browser \(([^,]+),[^)]+\)/i,
    (_, engine) => `Launched ${engine.trim()} browser`,
  );

  const urlRegex = /https?:\/\/[^\s]+/g;
  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  let match;

  while ((match = urlRegex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }
    parts.push(<ShortenedUrl key={match.index} url={match[0]} />);
    lastIndex = urlRegex.lastIndex;
  }
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }

  const baseContent = parts.length > 0 ? parts : [text];

  if (isStartingCrawl) {
    return baseContent.map((part, i) => {
      if (typeof part === "string") {
        const counterMatch = part.match(/\(\d+\/\d+\)/);
        if (counterMatch && counterMatch.index !== undefined) {
          const before = part.slice(0, counterMatch.index);
          const after = part.slice(counterMatch.index + counterMatch[0].length);
          return (
            <React.Fragment key={i}>
              {before}
              <span className="text-blue-400/70 font-extrabold">{counterMatch[0]}</span>
              {after}
            </React.Fragment>
          );
        }
      }
      return part;
    });
  }

  return baseContent;
}

export const LogTerminal = memo(function LogTerminal({
  logs,
  live = false,
  viewportRef,
}: Readonly<{
  logs: Array<{ id: number; level: string; message: string; created_at: string }>;
  live?: boolean;
  viewportRef?: RefObject<HTMLDivElement | null>;
}>) {
  const ref = useLogViewport(logs.length, viewportRef);
  const lastId = logs.length > 0 ? logs[logs.length - 1].id : null;

  return (
    <div className="flex flex-col rounded-xl border border-white/5 bg-[var(--terminal-code-bg)] shadow-2xl overflow-hidden">
      {/* Terminal Header */}
      <div className="flex items-center gap-1.5 px-4 py-2 border-b border-white/5 bg-white/5">
        <div className="size-2.5 rounded-full bg-red-500/20 border border-red-500/40" />
        <div className="size-2.5 rounded-full bg-amber-500/20 border border-amber-500/40" />
        <div className="size-2.5 rounded-full bg-emerald-500/20 border border-emerald-500/40" />
        <span className="ml-2 text-[10px] font-bold uppercase tracking-widest text-[var(--terminal-fg)] opacity-40 font-mono">activity_stream.log</span>
      </div>

      <div
        ref={ref}
        className="crawl-activity-log min-h-[50vh] max-h-[72vh] overflow-y-auto p-2"
        role="log"
        aria-live={live ? "polite" : "off"}
        aria-atomic="false"
      >
        {logs.length
          ? logs.map((log) => {
              const Icon = getLogIcon(log.level, log.message);
              const { iconCls, bgCls } = getLogIconStyle(log.level, log.message);
              const isStartingCrawl = log.message.toLowerCase().includes("starting crawl");
              const isNewest = log.id === lastId;
              const displayMessage = renderLogContent(log.message, isStartingCrawl);

              return (
                <div
                  key={log.id}
                  className={cn(
                    "group flex items-start gap-3 px-3 py-1 font-mono transition-colors rounded-md",
                    "hover:bg-white/5",
                    isStartingCrawl && "bg-white/[0.04] my-1",
                    isNewest && live && "log-entry-animate",
                  )}
                  title={log.message}
                >
                  <span className="w-[72px] shrink-0 text-[11px] tabular-nums text-[var(--terminal-fg)] opacity-40 mt-0.5">
                    {formatTimeHms(log.created_at)}
                  </span>
                  <div className={cn(
                    "flex size-4 shrink-0 items-center justify-center rounded-sm mt-0.5",
                    bgCls,
                  )}>
                    <Icon className={cn("size-2.5", iconCls)} aria-hidden="true" />
                  </div>
                  <span className={cn(
                    "min-w-0 flex-1 text-[13px] leading-relaxed break-words",
                    isStartingCrawl ? "text-[var(--terminal-fg)] opacity-100" : "text-[var(--terminal-fg)] opacity-85"
                  )}>
                    {displayMessage}
                  </span>
                </div>
              );
            })
          : (
            <div className="px-4 py-8 text-center text-sm text-muted font-mono italic">
              {live ? "Waiting for log stream..." : "No log activity recorded"}
            </div>
          )}
      </div>
    </div>
  );
});

export function SettingSection({
  label,
  description,
  icon,
  checked,
  onChange,
  children,
}: Readonly<{
  label: string;
  description: string;
  icon?: ReactElement<IconElementProps>;
  checked: boolean;
  onChange: (value: boolean) => void;
  children?: ReactNode;
}>) {
  const renderedIcon = React.isValidElement<IconElementProps>(icon)
    ? React.cloneElement(icon, {
      className: cn(icon.props.className, "size-4"),
    })
    : null;

  return (
    <div className="transition-all h-9 flex items-center w-full">
      <div className="grid w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-3">
        <div className="flex items-center gap-1.5 min-w-0">
          {renderedIcon ? (
            <div
              className={cn(
                "flex size-8 shrink-0 items-center justify-center rounded-[var(--radius-md)] border transition-colors",
                checked
                  ? "border-[color:color-mix(in_srgb,var(--accent)_22%,transparent)] bg-setting-icon-active-bg text-accent shadow-setting-icon-active"
                  : "border-border bg-setting-icon-bg text-secondary",
              )}
            >
              {renderedIcon}
            </div>
          ) : null}
          <div className="field-label mb-0 min-w-0">{label}</div>
          <Tooltip content={description}>
            <Info className="size-3.5 text-muted hover:text-secondary cursor-help transition-colors" />
          </Tooltip>
        </div>
        <div className="flex justify-start">
          <PrimitiveToggle checked={checked} onChange={onChange} ariaLabel={label} />
        </div>
      </div>
      {children ? (
        <div
          className={cn(
            "transition-[max-height] duration-200 ease-out",
            checked ? "max-h-[500px] overflow-visible" : "max-h-0 overflow-hidden",
          )}
        >
          <div className="border-t border-divider bg-setting-body-bg px-5 py-4 space-y-3">{children}</div>
        </div>
      ) : null}
    </div>
  );
}

export function SliderRow({
  label,
  description,
  value,
  min,
  max,
  step,
  onChange,
  onReset,
  suffix,
}: Readonly<{
  label: string;
  description?: string;
  value: string;
  min: number;
  max: number;
  step: number;
  onChange: (value: string) => void;
  onReset: () => void;
  suffix?: string;
}>) {
  return (
    <div
      className={cn(
        "grid gap-2.5 md:grid-cols-[140px_minmax(0,1fr)_112px] md:items-center w-full",
      )}
    >
      <div className="flex items-center gap-1.5 min-w-0">
        <span className="field-label mb-0">{label}</span>
        {description ? (
          <Tooltip content={description}>
            <Info className="size-3.5 cursor-help text-muted transition-colors hover:text-secondary" />
          </Tooltip>
        ) : null}
        <button
          type="button"
          onClick={onReset}
          aria-label={`Reset ${label}`}
          className="text-muted transition-colors hover:text-primary"
        >
          <RotateCcw className="size-3" aria-hidden="true" />
        </button>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={clampNumber(value, min, max, min)}
        onChange={(event) => onChange(event.target.value)}
        className="slider-control w-full"
      />
      <div className="relative">
        <Input
          type="text"
          inputMode="numeric"
          value={value}
          onChange={(event) => onChange(event.target.value.replace(/[^\d]/g, ""))}
          onBlur={() => onChange(String(clampNumber(value, min, max, min)))}
          className="pr-8 text-right font-mono tabular-nums"
        />
        {suffix ? (
          <span className="pointer-events-none absolute right-1.5 top-1/2 -translate-y-1/2 text-sm leading-normal lowercase text-muted">
            {suffix}
          </span>
        ) : null}
      </div>
    </div>
  );
}

export function AdditionalFieldInput({
  value,
  fields,
  onChange,
  onCommit,
  onRemove,
}: Readonly<{
  value: string;
  fields: string[];
  onChange: (value: string) => void;
  onCommit: (value: string) => void;
  onRemove: (value: string) => void;
}>) {
  const chips = uniqueRequestedFields([...fields, ...parseLines(value.replace(/,/g, "\n"))]);
  const [validationHint, setValidationHint] = useState<string | null>(null);

  function commitField(candidate: string) {
    const cleaned = cleanRequestedField(candidate);
    if (!cleaned) {
      return;
    }
    const validationError = validateAdditionalFieldName(cleaned);
    if (validationError) {
      setValidationHint(`Skipped "${cleaned}": ${validationError}`);      return;
    }
    onCommit(cleaned);
  }

  function handleChange(next: string) {
    const parts = next.split(",");
    parts
      .slice(0, -1)
      .forEach(commitField);
    setValidationHint(null);
    onChange(parts.at(-1) ?? "");
  }

  function handleBlur() {
    parseLines(value).forEach(commitField);
    onChange("");
  }

  return (
    <label className="grid gap-1.5">
      <span className="field-label">Additional Fields</span>
      <Input
        value={value}
        onChange={(event) => handleChange(event.target.value)}
        onBlur={handleBlur}
        placeholder="price, sku, Features & Benefits, Product Story"
        className="font-mono"
      />
      {validationHint ? <p className="text-sm leading-[var(--leading-normal)] text-danger">{validationHint}</p> : null}
      {chips.length ? (
        <div className="flex flex-wrap gap-1.5">
          {chips.map((field) => (
            <button
              key={field}
              type="button"
              onClick={() => onRemove(field)}
              aria-label={`Remove ${field}`}
              className="inline-flex items-center gap-1 rounded-md border border-subtle-panel-border bg-subtle-panel px-2 py-1 text-sm leading-[var(--leading-normal)] text-secondary"
            >
              <X className="size-3.5 shrink-0" aria-hidden="true" />
              <span className="truncate">{field}</span>
            </button>
          ))}
        </div>
      ) : null}
    </label>
  );
}

export function ManualFieldEditor({
  row,
  onChange,
  onDelete,
  onTest,
  testing = false,
  testDisabled = false,
  message,
  messageTone = "warning",
  showLabels = true,
}: Readonly<{
  row: FieldRow;
  onChange: (patch: Partial<FieldRow>) => void;
  onDelete: () => void;
  onTest?: () => void;
  testing?: boolean;
  testDisabled?: boolean;
  message?: string;
  messageTone?: FieldRowMessageTone;
  showLabels?: boolean;
}>) {
  return (
    <div className="space-y-1.5 rounded-md border border-border/60 bg-background/50 p-2.5">
      <div className="grid gap-2 xl:grid-cols-[24px_minmax(140px,0.8fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,0.8fr)_auto]">
        <div className="hidden items-center justify-center text-muted/50 xl:flex">
          <GripVertical className="size-3.5" />
        </div>
        <label className="grid gap-1">
          <span className={cn("field-label", !showLabels && "sr-only")}>Field</span>
          <Input
            aria-label="Field"
            value={row.fieldName}
            onChange={(event) => onChange({ fieldName: event.target.value })}
            placeholder="price"
            className="font-mono h-8 text-xs"
          />
        </label>
        <ValidatedField
          label="CSS"
          value={row.cssSelector}
          state={row.cssState}
          placeholder=".price"
          showLabel={showLabels}
          onChange={(value) => onChange({ cssSelector: value })}
          onBlur={(value) => onChange({ cssState: validateCssSelector(value) })}
        />
        <ValidatedField
          label="XPath"
          value={row.xpath}
          state={row.xpathState}
          placeholder="//span[@class='price']"
          showLabel={showLabels}
          onChange={(value) => onChange({ xpath: value })}
          onBlur={(value) => onChange({ xpathState: validateXPath(value) })}
        />
        <ValidatedField
          label="Regex"
          value={row.regex}
          state={row.regexState}
          placeholder="\\$[\\d,.]+"
          showLabel={showLabels}
          onChange={(value) => onChange({ regex: value })}
          onBlur={(value) => onChange({ regexState: validateRegex(value) })}
        />
        <div className="flex items-end justify-end">
          <div className="flex flex-wrap items-center justify-end gap-1.5">
            {onTest ? (
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={onTest}
                disabled={testing || testDisabled}
                className="h-8 min-w-[64px] text-xs"
              >
                {testing ? "..." : "Test"}
              </Button>
            ) : null}
            <button
              type="button"
              onClick={onDelete}
              aria-label={`Delete ${row.fieldName || "manual field"}`}
              className="surface-muted inline-flex size-8 items-center justify-center rounded-[var(--radius-md)] text-danger/70 hover:bg-danger/10 hover:text-danger"
            >
              <Trash2 className="size-3.5" />
            </button>
          </div>
        </div>
      </div>
      {message ? (
        <div
          className={cn(
            "alert-surface px-2.5 py-1.5 text-xs leading-[var(--leading-normal)]",
            messageTone === "success" && "alert-success",
            messageTone === "warning" && "alert-warning",
            messageTone === "danger" && "alert-danger",
          )}
        >
          {message}
        </div>
      ) : null}
    </div>
  );
}

export function FieldEditorHeader() {
  return (
    <div className="hidden items-center gap-2 px-3 py-1.5 xl:grid xl:grid-cols-[24px_minmax(140px,0.8fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,0.8fr)_auto]">
      <div />
      <div className="flex items-center gap-1.5">
        <span className="text-[11px] font-bold uppercase tracking-wider text-[#005a9e]">Field</span>
        <Info className="size-3 text-[#005a9e]/60" />
      </div>
      <div className="flex items-center gap-1.5">
        <span className="text-[11px] font-bold uppercase tracking-wider text-[#005a9e]">CSS</span>
        <Info className="size-3 text-[#005a9e]/60" />
      </div>
      <div className="flex items-center gap-1.5">
        <span className="text-[11px] font-bold uppercase tracking-wider text-[#005a9e]">XPath</span>
        <Info className="size-3 text-[#005a9e]/60" />
      </div>
      <div className="flex items-center gap-1.5">
        <span className="text-[11px] font-bold uppercase tracking-wider text-[#005a9e]">Regex</span>
        <Info className="size-3 text-[#005a9e]/60" />
      </div>
      <span className="text-[11px] font-bold uppercase tracking-wider text-[#005a9e] text-right">Actions</span>
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
  showLabel = true,
}: Readonly<{
  label: string;
  value: string;
  state: ValidationState;
  placeholder: string;
  onChange: (value: string) => void;
  onBlur: (value: string) => void;
  showLabel?: boolean;
}>) {
  return (
    <label className="grid gap-1">
      <span className={cn("field-label", !showLabel && "sr-only")}>{label}</span>
      <div className="relative">
        <Input
          aria-label={label}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onBlur={(event) => onBlur(event.target.value)}
          placeholder={placeholder}
          className="pr-9 font-mono h-8 text-xs"
        />
        <div className="pointer-events-none absolute inset-y-0 right-2.5 flex items-center">
          {state === "valid" ? <CheckCircle2 className="size-3.5 text-success/80" /> : null}
          {state === "invalid" ? <CircleAlert className="size-3.5 text-danger/80" /> : null}
        </div>
      </div>
    </label>
  );
}

const BROKEN_THUMBNAIL_STORAGE_KEY = "crawlerai-broken-thumb-urls-v1";
const BROKEN_THUMBNAIL_HOSTS_KEY = "crawlerai-broken-thumb-hosts-v1";
const BROKEN_THUMBNAIL_URLS = new Set<string>();
const BROKEN_THUMBNAIL_HOSTS = new Set<string>();

function loadBrokenThumbnailCache() {
  if (typeof window === "undefined") return;
  try {
    const urls = window.sessionStorage.getItem(BROKEN_THUMBNAIL_STORAGE_KEY);
    if (urls) (JSON.parse(urls) as string[]).forEach((u) => BROKEN_THUMBNAIL_URLS.add(u));
    const hosts = window.sessionStorage.getItem(BROKEN_THUMBNAIL_HOSTS_KEY);
    if (hosts) (JSON.parse(hosts) as string[]).forEach((h) => BROKEN_THUMBNAIL_HOSTS.add(h));
  } catch {
    /* ignore */
  }
}
loadBrokenThumbnailCache();

function persistBrokenThumbnailCache() {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(
      BROKEN_THUMBNAIL_STORAGE_KEY,
      JSON.stringify(Array.from(BROKEN_THUMBNAIL_URLS).slice(-500)),
    );
    window.sessionStorage.setItem(
      BROKEN_THUMBNAIL_HOSTS_KEY,
      JSON.stringify(Array.from(BROKEN_THUMBNAIL_HOSTS)),
    );
  } catch {
    /* ignore */
  }
}

function thumbnailHost(src: string): string {
  try {
    return new URL(src).host;
  } catch {
    return "";
  }
}

function RecordThumbnail({ src }: Readonly<{ src: string }>) {
  const host = thumbnailHost(src);
  const initiallyBroken = BROKEN_THUMBNAIL_URLS.has(src) || (host !== "" && BROKEN_THUMBNAIL_HOSTS.has(host));
  const [broken, setBroken] = useState(initiallyBroken);
  if (broken) {
    return <span className="ct-muted">--</span>;
  }
  return (
    <div className="ct-image-wrap">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={src}
        alt=""
        loading="lazy"
        decoding="async"
        referrerPolicy="no-referrer"
        onError={() => {
          BROKEN_THUMBNAIL_URLS.add(src);
          if (host) BROKEN_THUMBNAIL_HOSTS.add(host);
          persistBrokenThumbnailCache();
          setBroken(true);
        }}
      />
    </div>
  );
}

export const RecordsTable = memo(function RecordsTable({
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
  const IMAGE_KEYS = new Set(["image_url", "image", "thumbnail", "img"]);
  const TITLE_KEYS = new Set(["title", "name", "product_name", "product title"]);
  const PRICE_KEYS = new Set(["price", "sale_price", "offer_price", "current_price", "final_price", "our_price", "deal_price"]);
  const URL_KEYS = new Set(["url", "source_url", "product_url", "canonical_url"]);

  const imageCol = visibleColumns.find((col) => IMAGE_KEYS.has(col));
  const dataColumns = visibleColumns.filter((col) => !IMAGE_KEYS.has(col));
  const hasImageCol = !!imageCol;
  const totalCols = dataColumns.length + (hasImageCol ? 1 : 0) + 1;
  const rowHeightPx = 48;
  const overscanRows = 8;
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportHeight, setViewportHeight] = useState(560);
  const [containerNode, setContainerNode] = useState<HTMLDivElement | null>(null);
  const setContainerRef = useCallback((node: HTMLDivElement | null) => {
    setContainerNode(node);
    if (node) {
      setViewportHeight(node.clientHeight || 560);
    }
  }, []);
  const totalCount = records.length;
  const startIndex = Math.max(0, Math.floor(scrollTop / rowHeightPx) - overscanRows);
  const visibleCount = Math.ceil(viewportHeight / rowHeightPx) + overscanRows * 2;
  const endIndex = Math.min(totalCount, startIndex + visibleCount);
  const windowedRecords = records.slice(startIndex, endIndex);
  const topSpacerPx = startIndex * rowHeightPx;
  const bottomSpacerPx = Math.max(0, (totalCount - endIndex) * rowHeightPx);

  useEffect(() => {
    if (!containerNode || typeof ResizeObserver === "undefined") {
      return;
    }
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) {
        return;
      }
      setViewportHeight(entry.contentRect.height || 560);
    });
    observer.observe(containerNode);
    return () => observer.disconnect();
  }, [containerNode]);

  function renderCell(col: string, record: CrawlRecord) {
    const raw = formatCellDisplay(readRecordValue(record, col));
    if (!raw || raw === "--") return <span className="ct-muted">--</span>;

    if (TITLE_KEYS.has(col)) {
      return <span className="ct-title block max-w-[320px] truncate">{raw}</span>;
    }
    if (PRICE_KEYS.has(col)) {
      return <span className="ct-price">{raw}</span>;
    }
    if (URL_KEYS.has(col)) {
      const isSafe = raw.startsWith("http://") || raw.startsWith("https://");
      if (isSafe) {
        return (
          <a href={raw} target="_blank" rel="noreferrer" className="ct-url block max-w-[200px] truncate" title={raw}>
            {raw}
          </a>
        );
      }
    }
    return <span className="block max-w-[260px] truncate text-[var(--table-font-size)] leading-[var(--leading-snug)] text-secondary font-normal">{raw}</span>;
  }

  return (
    <div
      ref={setContainerRef}
      onScroll={(event) => setScrollTop(event.currentTarget.scrollTop)}
      className="commerce-table surface-muted max-h-[70vh] rounded-lg overflow-auto"
    >
      <table className="compact-data-table min-w-[960px]">
        <colgroup>
          <col style={{ width: 32 }} />
          {hasImageCol ? <col style={{ width: 64 }} /> : null}
          {dataColumns.map((col) => {
            let width: string | number = "auto";
            if (URL_KEYS.has(col)) width = "22%";
            else if (TITLE_KEYS.has(col)) width = "18%";
            else if (PRICE_KEYS.has(col)) width = "10%";
            return <col key={col} style={{ width }} />;
          })}
        </colgroup>
        <thead>
          <tr>
            <th className="w-10">
              <input
                type="checkbox"
                checked={selectedIds.length === records.length && records.length > 0}
                onChange={(event) => onSelectAll(event.target.checked)}
              />
            </th>
            {hasImageCol ? <th>IMG</th> : null}
            {dataColumns.map((col) => (
              <th key={col}>
                <div className="flex items-center gap-1 min-w-0">
                  <span className="flex-1 truncate">{humanizeFieldName(col)}</span>
                </div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {topSpacerPx > 0 ? (
            <tr aria-hidden="true">
              <td colSpan={totalCols} style={{ height: `${topSpacerPx}px`, padding: 0 }} />
            </tr>
          ) : null}
          {windowedRecords.map((record) => (
            <tr key={record.id}>
              <td>
                <input
                  type="checkbox"
                  checked={selectedIds.includes(record.id)}
                  onChange={(event) => onToggleRow(record.id, event.target.checked)}
                />
              </td>
              {hasImageCol ? (
                <td className="ct-image-cell">
                  {(() => {
                    const src = formatCellDisplay(readRecordValue(record, imageCol!));
                    if (!src || src === "--") return <span className="ct-muted">--</span>;
                    return <RecordThumbnail src={src} />;
                  })()}
                </td>
              ) : null}
              {dataColumns.map((col) => (
                <td key={col} title={formatCellDisplay(readRecordValue(record, col))}>
                  {renderCell(col, record)}
                </td>
              ))}
            </tr>
          ))}
          {bottomSpacerPx > 0 ? (
            <tr aria-hidden="true">
              <td colSpan={totalCols} style={{ height: `${bottomSpacerPx}px`, padding: 0 }} />
            </tr>
          ) : null}
        </tbody>
      </table>
    </div>
  );
});

export function ActionButton({
  label,
  danger,
  disabled,
  onClick,
}: Readonly<{ label: string; danger?: boolean; disabled?: boolean; onClick?: () => void }>) {
  return (
    <Button
      type="button"
      variant={danger ? "danger" : "secondary"}
      size="sm"
      disabled={disabled}
      onClick={onClick}
      className={cn("h-8 min-w-0 px-3", !danger && "text-sm leading-[var(--leading-normal)]")}
    >
      {label}
    </Button>
  );
}

export function PreviewRow({ label, value, mono }: Readonly<{ label: string; value: ReactNode; mono?: boolean }>) {
  return (
    <div className="surface-muted flex items-start justify-between gap-4 rounded-[var(--radius-md)] px-3 py-2">
      <div className="field-label shrink-0">{label}</div>
      <div className={cn("min-w-0 flex-1 text-right text-sm leading-[var(--leading-normal)] text-foreground", mono && "type-mono-standard")}>
        {value || "--"}
      </div>
    </div>
  );
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

function validateXPath(value: string): ValidationState {
  if (!value.trim()) return "idle";
  try {
    globalThis.document?.evaluate(value, globalThis.document, null, XPathResult.ANY_TYPE, null);
    return "valid";
  } catch {
    return "invalid";
  }
}

function validateCssSelector(value: string): ValidationState {
  if (!value.trim()) return "idle";
  try {
    globalThis.document?.querySelector(value);
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

function logTone(level: string) {
  const normalized = normalizeLogLevel(level);
  if (normalized === "WARN" || normalized === "WARNING") return "border-transparent bg-transparent text-warning";
  if (normalized === "ERROR") return "border-transparent bg-transparent text-danger";
  return "border-transparent bg-transparent text-terminal-fg";
}

function logLineTone(level: string) {
  const normalized = normalizeLogLevel(level);
  if (normalized === "WARN" || normalized === "WARNING") return "text-warning";
  if (normalized === "ERROR") return "text-danger";
  return "text-terminal-fg";
}

function normalizeLogLevel(level: string) {
  return String(level || "").trim().toUpperCase();
}

function useLogViewport(_logCount: number, ref?: RefObject<HTMLDivElement | null>) {
  const internalRef = useRef<HTMLDivElement | null>(null);
  const targetRef = ref ?? internalRef;

  useEffect(() => {
    if (!ref) {
      scrollViewportToBottom(internalRef);
    }
  }, [_logCount, ref]);

  return targetRef;
}

