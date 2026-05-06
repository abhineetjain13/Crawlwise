'use client';

import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  Copy,
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
} from 'lucide-react';
import React, { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactElement, ReactNode, RefObject } from 'react';

import {
  Badge,
  Button,
  Input,
  Textarea,
  Tooltip,
  Toggle as PrimitiveToggle,
} from '../ui/primitives';
import type {
  CrawlDomain,
  CrawlLog,
  CrawlRecord,
  CrawlRun,
  CrawlSurface,
} from '../../lib/api/types';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../ui/table';
import { formatTimeHms, parseApiDate } from '../../lib/format/date';
import { cn } from '../../lib/utils';

export type CrawlTab = 'category' | 'pdp';
export type CategoryMode = 'single' | 'sitemap' | 'bulk';
export type PdpMode = 'single' | 'batch' | 'csv';
export type ValidationState = 'idle' | 'valid' | 'invalid';
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
export type FieldRowMessageTone = 'success' | 'warning' | 'danger';
export type PendingDispatch = {
  runType: 'crawl' | 'batch' | 'csv';
  surface: CrawlSurface;
  url?: string;
  urls?: string[];
  settings: Record<string, unknown>;
  additionalFields: string[];
  csvFile: File | null;
};
export type OutputTabKey = 'table' | 'json' | 'markdown' | 'logs' | 'learning' | 'run_config';
type IconElementProps = {
  className?: string;
};

export function parseRequestedCrawlTab(value: string | null): CrawlTab | null {
  return value === 'category' || value === 'pdp' ? value : null;
}

export function parseRequestedCategoryMode(value: string | null): CategoryMode | null {
  return value === 'single' || value === 'sitemap' || value === 'bulk' ? value : null;
}

export function parseRequestedPdpMode(value: string | null): PdpMode | null {
  return value === 'single' || value === 'batch' || value === 'csv' ? value : null;
}

export function uniqueFields(values: string[]) {
  return Array.from(new Set(values.map(normalizeField).filter(Boolean)));
}

export function cleanRequestedField(value: string) {
  return String(value || '')
    .trim()
    .replace(/\s+/g, ' ');
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
    .replace(/&/g, '')
    .replace(/([a-z0-9])([A-Z])/g, '$1_$2')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/_+/g, '_')
    .replace(/^_+|_+$/g, '');
}

export function deriveSurface(domain: CrawlDomain, module: CrawlTab): CrawlSurface {
  if (domain === 'jobs') {
    return module === 'category' ? 'job_listing' : 'job_detail';
  }
  return module === 'category' ? 'ecommerce_listing' : 'ecommerce_detail';
}

export function inferDomainFromSurface(surface: string | null | undefined): CrawlDomain | null {
  const normalizedSurface = String(surface || '').toLowerCase();
  if (normalizedSurface.startsWith('job_')) {
    return 'jobs';
  }
  if (normalizedSurface.startsWith('ecommerce_')) {
    return 'commerce';
  }
  return null;
}

const SCHEMA_TYPE_FIELD_NAMES = new Set(
  [
    'AggregateRating',
    'BreadcrumbList',
    'IndividualProduct',
    'Organization',
    'PeopleAudience',
    'PostalAddress',
    'QuantitativeValue',
    'WebPage',
    'WebSite',
  ].flatMap((value) => {
    const normalized = normalizeField(value);
    return [normalized, normalized.replace(/_/g, '')];
  }),
);

const DAY_OF_WEEK_FIELD_NAMES = new Set([
  'monday',
  'tuesday',
  'wednesday',
  'thursday',
  'friday',
  'saturday',
  'sunday',
]);

export function validateAdditionalFieldName(value: string) {
  const cleaned = cleanRequestedField(value);
  const normalized = normalizeField(cleaned);
  const collapsed = normalized.replace(/_/g, '');
  if (!cleaned) {
    return 'Field name cannot be empty.';
  }
  if (cleaned.length < 2) {
    return 'Field name must be at least 2 characters.';
  }
  if (cleaned.length > 60) {
    return 'Field name must be 60 characters or fewer.';
  }
  if (!normalized) {
    return 'Field name must include letters or numbers.';
  }
  if ((cleaned.match(/\s+/g) ?? []).length >= 7 || (normalized.match(/_/g) ?? []).length >= 7) {
    return 'Field name is too sentence-like. Keep it concise.';
  }
  if (SCHEMA_TYPE_FIELD_NAMES.has(normalized) || SCHEMA_TYPE_FIELD_NAMES.has(collapsed)) {
    return 'Field name looks like a schema type. Use a business field.';
  }
  if (DAY_OF_WEEK_FIELD_NAMES.has(normalized)) {
    return 'Field name looks like a day label. Use a business field.';
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
  return inferRunModule(run) === 'category';
}

export function stringifyCell(value: unknown) {
  if (value == null) return '';
  if (typeof value === 'string') return value;
  return JSON.stringify(value);
}

export function decodeUrlForDisplay(value: string) {
  const text = String(value || '').trim();
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
  if (typeof value === 'string') {
    return decodeUrlForDisplay(value) as T;
  }
  if (Array.isArray(value)) {
    return value.map((entry) => decodeUrlsForDisplay(entry)) as T;
  }
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value).map(([key, entry]) => [key, decodeUrlsForDisplay(entry)]),
    ) as T;
  }
  return value;
}

export function humanizeFieldName(value: string) {
  const normalized = String(value || '')
    .replace(/[_-]+/g, '')
    .replace(/\s+/g, '')
    .trim();
  if (!normalized) return '';
  return normalized.charAt(0).toUpperCase() + normalized.slice(1);
}

export function presentCandidateValue(value: unknown) {
  const trimmed = stringifyCell(value).trim();
  if (!trimmed) return '';
  const schemaMatch = trimmed.match(/^https?:\/\/schema\.org\/([A-Za-z]+)$/i);
  if (!schemaMatch) return trimmed;
  const token = schemaMatch[1].replace(/([a-z])([A-Z])/g, '$1 $2');
  return token.charAt(0).toUpperCase() + token.slice(1);
}

export function isEmptyCandidateValue(value: unknown) {
  if (value === null || value === undefined) return true;
  if (typeof value === 'string') return value.trim().length === 0;
  if (Array.isArray(value)) return value.length === 0;
  if (typeof value === 'object') return Object.keys(value).length === 0;
  return false;
}

export function readRecordValue(record: CrawlRecord, field: string) {
  const data = record.data && typeof record.data === 'object' ? record.data : {};
  const raw = record.raw_data && typeof record.raw_data === 'object' ? record.raw_data : {};
  if (field in data) return data[field];
  if (field in raw) return raw[field];
  if (field === 'source_url') return record.source_url;
  return '';
}

export function formatDuration(start?: string | null, end?: string | null) {
  if (!start) return '--';
  const started = parseApiDate(start).getTime();
  const finished = end ? parseApiDate(end).getTime() : Date.now();

  if (!Number.isFinite(started) || !Number.isFinite(finished)) return '--';
  const ms = Math.max(0, finished - started);
  const totalSeconds = Math.floor(ms / 1000);
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m}m ${s}s`;
}

export function formatDurationMs(durationMs?: number | null) {
  if (typeof durationMs !== 'number' || !Number.isFinite(durationMs) || durationMs < 0) {
    return null;
  }
  const totalSeconds = Math.floor(durationMs / 1000);
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m}m ${s}s`;
}

export function progressPercent(run: CrawlRun | undefined) {
  const value = typeof run?.result_summary?.progress === 'number' ? run.result_summary.progress : 0;
  return Math.min(100, Math.max(0, value));
}

export function extractionVerdict(run: CrawlRun | undefined) {
  const verdict = String(run?.result_summary?.extraction_verdict ?? '')
    .trim()
    .toLowerCase();
  return verdict || 'unknown';
}

export function extractionVerdictTone(verdict: string) {
  if (verdict === 'success') return 'success';
  if (verdict === 'partial') return 'warning';
  if (verdict === 'schema_miss' || verdict === 'listing_detection_failed' || verdict === 'empty')
    return 'warning';
  if (verdict === 'blocked' || verdict === 'proxy_exhausted' || verdict === 'error')
    return 'danger';
  return 'neutral';
}

export function humanizeVerdict(verdict: string) {
  return verdict.replace(/_/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase());
}
export type QualityLevel = 'high' | 'medium' | 'low' | 'unknown';

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
  'n/a',
  'na',
  'none',
  'null',
  'undefined',
  'unknown',
  'tbd',
  '--',
  '-',
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

  if (typeof value === 'object') {
    return Object.values(value as Record<string, unknown>).some((entry) =>
      isInformativeValue(entry),
    );
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

export function scoreFieldQuality(records: CrawlRecord[], field: string) {
  if (!records.length) {
    return 0;
  }
  const informativeValues = records
    .map((record) => readRecordValue(record, field))
    .filter((value) => isInformativeValue(value));
  if (!informativeValues.length) {
    return 0;
  }
  const coverage = informativeValues.length / records.length;
  const uniqueValues = new Set(
    informativeValues.map((value) => stringifyCell(value).trim().toLowerCase()).filter(Boolean),
  ).size;
  const diversity = Math.min(1, uniqueValues / Math.min(3, informativeValues.length));
  return coverage * 0.75 + diversity * 0.25;
}

export function estimateDataQuality(
  records: CrawlRecord[],
  visibleColumns: string[],
): QualitySnapshot {
  if (!records.length || !visibleColumns.length) {
    return {
      level: 'unknown',
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
    return { level: 'high', score, populatedCells, totalCells };
  }
  if (score >= 0.5) {
    return { level: 'medium', score, populatedCells, totalCells };
  }
  return { level: 'low', score, populatedCells, totalCells };
}

export function qualityTone(level: QualityLevel) {
  if (level === 'high') return 'success';
  if (level === 'medium') return 'warning';
  if (level === 'low') return 'danger';
  return 'neutral';
}

export function humanizeQuality(level: QualityLevel) {
  if (level === 'unknown') return 'Unknown';
  return level.charAt(0).toUpperCase() + level.slice(1);
}

export function qualityLevelFromScore(score: number): QualityLevel {
  if (!Number.isFinite(score)) return 'unknown';
  if (score >= 0.8) return 'high';
  if (score >= 0.5) return 'medium';
  return 'low';
}

export function copyJson(records: CrawlRecord[]) {
  void navigator.clipboard.writeText(JSON.stringify(records.map(cleanRecordForDisplay), null, 2));
}

export function cleanRecord(record: CrawlRecord) {
  return Object.fromEntries(
    Object.entries(record.data ?? {}).filter(
      ([key, value]) =>
        !key.startsWith('_') &&
        value !== null &&
        value !== '' &&
        !(Array.isArray(value) && value.length === 0),
    ),
  );
}

export function cleanRecordForDisplay(record: CrawlRecord) {
  return decodeUrlsForDisplay(cleanRecord(record));
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
  const isWarn = level === 'warning' || level === 'warn';
  const isError = logMessageIsError(level, message);
  const hasUrl = /https?:\/\//i.test(message);

  if (isError) return XCircle;
  if (isWarn) return AlertTriangle;

  if (msg.includes('starting crawl')) return Activity;
  if (msg.includes('ignoring robots.txt')) return ShieldAlert;
  if (msg.includes('extracted')) return Database;
  if (msg.includes('normalized') || msg.includes('normalised')) return Layers;
  if (msg.includes('persisted')) return HardDrive;
  if (msg.includes('acquiring') || msg.includes('fetching')) return Globe;
  if (
    msg.includes('browser') ||
    msg.includes('playwright') ||
    msg.includes('patchright') ||
    msg.includes('headless')
  )
    return Monitor;
  if (msg.includes('record')) return Database;
  if (msg.includes('page loaded') || msg.includes('page load')) return Zap;
  if (
    msg.includes('challenge') ||
    msg.includes('blocked') ||
    msg.includes('captcha') ||
    msg.includes('bot check')
  )
    return ShieldAlert;
  if (hasUrl) return Globe;
  if (msg.includes('retry') || msg.includes('retrying') || msg.includes('refresh'))
    return RefreshCw;
  if (
    msg.includes('complete') ||
    msg.includes('success') ||
    msg.includes('done') ||
    msg.includes('finished')
  )
    return CheckCircle2;
  return Dot;
}

function getLogIconStyle(level: string, message: string): { iconCls: string; bgCls: string } {
  const msg = message.toLowerCase();
  const isError = logMessageIsError(level, message);
  const hasUrl = /https?:\/\//i.test(message);

  if (isError) return { iconCls: 'text-danger', bgCls: 'bg-danger-bg' };
  if (level === 'warning' || level === 'warn')
    return { iconCls: 'text-warning', bgCls: 'bg-warning-bg' };

  if (msg.includes('starting crawl')) return { iconCls: 'text-info', bgCls: 'bg-info-bg' };
  if (msg.includes('ignoring robots.txt'))
    return { iconCls: 'text-warning', bgCls: 'bg-warning-bg' };
  if (msg.includes('resolved')) return { iconCls: 'text-muted ', bgCls: 'bg-zinc-500/10' };
  if (msg.includes('acquired')) return { iconCls: 'text-info', bgCls: 'bg-indigo-500/10' };
  if (msg.includes('extracted')) return { iconCls: 'text-success', bgCls: 'bg-success-bg' };
  if (msg.includes('normalized') || msg.includes('normalised'))
    return { iconCls: 'text-warning', bgCls: 'bg-warning-bg' };
  if (msg.includes('persisted')) return { iconCls: 'text-success', bgCls: 'bg-success-bg' };
  if (msg.includes('page loaded') || msg.includes('page load'))
    return { iconCls: 'text-warning', bgCls: 'bg-warning-bg' };
  if (
    msg.includes('challenge') ||
    msg.includes('blocked') ||
    msg.includes('captcha') ||
    msg.includes('bot check')
  )
    return { iconCls: 'text-danger', bgCls: 'bg-danger-bg' };
  if (msg.includes('acquiring') || msg.includes('fetching'))
    return { iconCls: 'text-info', bgCls: 'bg-info-bg' };
  if (
    msg.includes('browser') ||
    msg.includes('patchright') ||
    msg.includes('playwright') ||
    msg.includes('headless')
  )
    return { iconCls: 'text-violet-600', bgCls: 'bg-violet-500/12' };
  if (msg.includes('record')) return { iconCls: 'text-success', bgCls: 'bg-success-bg' };
  if (hasUrl) return { iconCls: 'text-info', bgCls: 'bg-info-bg' };
  if (
    msg.includes('complete') ||
    msg.includes('success') ||
    msg.includes('done') ||
    msg.includes('finished')
  )
    return { iconCls: 'text-success', bgCls: 'bg-success-bg' };
  if (msg.includes('retry') || msg.includes('retrying'))
    return { iconCls: 'text-info', bgCls: 'bg-info-bg' };
  if (level === 'debug') return { iconCls: 'text-muted', bgCls: 'bg-transparent' };
  return {
    iconCls: 'text-secondary',
    bgCls: 'bg-[color-mix(in_srgb,var(--bg-alt)_50%,transparent)]',
  };
}

function logMessageIsError(level: string, message: string): boolean {
  const normalizedLevel = String(level || '').toLowerCase();
  if (normalizedLevel === 'error') return true;
  if (normalizedLevel) return false;
  const text = String(message || '');
  const lowered = text.toLowerCase();
  if (
    /\b(no|not|none|no longer)\s+(error|errors|failed)\b/i.test(text) ||
    lowered.includes('no errors found') ||
    lowered.includes('validation failed check passed')
  ) {
    return false;
  }
  return /^\s*(error|failed)\b/i.test(text);
}

export type LogStage = 'acquisition' | 'extraction' | 'normalize' | 'persistence' | 'system';

export interface LogStageConfig {
  label: string;
  borderClass: string;
  chipClass: string;
  textOnlyClass: string;
  panelClass: string;
}

const DISPLAY_LOG_STAGES: LogStage[] = ['acquisition', 'extraction', 'normalize', 'persistence'];

export const STAGE_CONFIG: Record<LogStage, LogStageConfig> = {
  acquisition: {
    label: 'Acquire',
    borderClass: 'border-info/30',
    chipClass: 'bg-info text-white font-medium',
    textOnlyClass: 'text-info font-medium',
    panelClass: 'border-info/20 bg-info-bg',
  },
  extraction: {
    label: 'Extract',
    borderClass: 'border-accent/30',
    chipClass: 'bg-accent text-accent-fg font-medium',
    textOnlyClass: 'text-accent font-medium',
    panelClass: 'border-accent/20 bg-accent-subtle',
  },
  normalize: {
    label: 'Normalize',
    borderClass: 'border-orange-400/30',
    chipClass: 'bg-orange-500 text-white font-bold',
    textOnlyClass: 'text-orange-500 font-bold',
    panelClass: 'border-orange-400/20 bg-orange-500/10',
  },
  persistence: {
    label: 'Persist',
    borderClass: 'border-indigo-400/30',
    chipClass: 'bg-indigo-500 text-white font-bold',
    textOnlyClass: 'text-indigo-500 font-bold',
    panelClass: 'border-indigo-400/20 bg-indigo-500/10',
  },
  system: {
    label: 'Run',
    borderClass: 'border-border-strong',
    chipClass: 'bg-zinc-700 text-white font-medium',
    textOnlyClass: 'text-muted font-medium',
    panelClass: 'border-border bg-subtle-panel-bg',
  },
};

export const TERMINAL_STRINGS = {
  FIELDS: 'Fields',
  CONFIDENCE: 'Confidence',
  RUN_EVENTS: 'Run Events',
  PENDING: 'Pending...',
  SITE_PAYLOAD: 'Site payload',
  PAYLOAD_PEEK: 'Payload Peek',
  NO_LOGS: 'No logs.',
  NO_PAYLOAD: 'No persisted payload for this site yet.',
} as const;

export const LOG_PATTERNS = {
  STARTING_CRAWL: /^Starting crawl run for (https?:\/\/\S+?)(?: \((\d+)\/(\d+)\))?$/i,
  ROBOTS_IGNORE: /ignoring robots\.txt/i,
  PERSISTENCE_SUMMARY: /\bpersisted\s+\d+\s+record/i,
  ROBOTS_PREFIX: /^\[ROBOTS\]\s*/i,
  HEADLESS_BROWSER: /launched headless browser \(([^,]+),[^)]+\)/i,
  URL: /https?:\/\/[^\s]+/g,
  COUNTER: /\(\d+\/\d+\)/,
} as const;

export function getLogStage(message: string): LogStage {
  const text = message.toLowerCase();
  if (text.includes('persisted') || text.includes('persisting') || text.includes('committed')) {
    return 'persistence';
  }
  if (
    text.includes('normalized') ||
    text.includes('normalised') ||
    text.includes('schema validation cleaned')
  ) {
    return 'normalize';
  }
  if (
    text.includes('extracted') ||
    text.includes('extraction yielded') ||
    text.includes('rejected detail extraction') ||
    text.includes('traversal yielded') ||
    text.includes('selector self-heal')
  ) {
    return 'extraction';
  }
  if (
    text.includes('acquiring') ||
    text.includes('robots') ||
    text.includes('proxy') ||
    text.includes('browser') ||
    text.includes('navigation') ||
    text.includes('page loaded') ||
    text.includes('acquired payload')
  ) {
    return 'acquisition';
  }
  if (
    text.includes('starting crawl') ||
    text.includes('resolved') ||
    text.includes('pipeline finished') ||
    text.includes('stopped after reaching') ||
    text.includes('run paused') ||
    text.includes('run killed')
  ) {
    return 'system';
  }
  return 'system';
}

type LogSiteGroup = {
  key: string;
  label: string;
  url: string;
  index: number | null;
  total: number | null;
  logs: CrawlLog[];
  stageLogs: Record<LogStage, CrawlLog[]>;
  records: CrawlRecord[];
  hasError: boolean;
  hasWarning: boolean;
  lastStage: LogStage;
  recordCount: number;
};

function parseStartingLog(message: string) {
  const match = sanitizeLogMessage(message).match(LOG_PATTERNS.STARTING_CRAWL);
  if (!match) {
    return null;
  }
  const [, url, indexValue, totalValue] = match;
  return {
    url,
    index: indexValue ? Number.parseInt(indexValue, 10) : null,
    total: totalValue ? Number.parseInt(totalValue, 10) : null,
  };
}

function isWarningLog(log: CrawlLog) {
  const level = String(log.level || '').toLowerCase();
  if (level === 'warn' || level === 'warning') {
    return true;
  }
  const text = log.message.toLowerCase();
  return (
    text.includes('partial') ||
    text.includes('yielded 0 records') ||
    text.includes('retrying') ||
    text.includes('rejected detail extraction')
  );
}

function isHiddenLogMessage(message: string) {
  return LOG_PATTERNS.ROBOTS_IGNORE.test(String(message || ''));
}

function isPersistenceSummaryLog(message: string) {
  return LOG_PATTERNS.PERSISTENCE_SUMMARY.test(String(message || ''));
}

function matchesSiteUrl(record: CrawlRecord, siteUrl: string) {
  const candidates = new Set<string>();
  for (const value of [
    record.source_url,
    record.data?.url,
    record.raw_data?.url,
    record.source_trace?.acquisition && typeof record.source_trace.acquisition === 'object'
      ? (record.source_trace.acquisition as Record<string, unknown>).final_url
      : null,
  ]) {
    const text = typeof value === 'string' ? value.trim() : '';
    if (text) {
      candidates.add(text);
    }
  }
  return candidates.has(siteUrl);
}

function siteLabel(url: string, index: number | null, total: number | null) {
  const prefix = index && total ? `${index}/${total}` : index ? String(index) : null;
  return prefix ? `${prefix} ${url}` : url;
}

function siteDomId(groupKey: string) {
  return `site-log-${groupKey.replace(/[^a-z0-9_-]+/gi, '-')}`;
}

export function buildLogSiteGroups(logs: CrawlLog[], records: CrawlRecord[] = []): LogSiteGroup[] {
  const groups: Array<
    Omit<LogSiteGroup, 'records' | 'hasError' | 'hasWarning' | 'lastStage' | 'recordCount'>
  > = [];
  let currentGroup: (typeof groups)[number] | null = null;
  let untitledCounter = 0;

  for (const log of logs) {
    if (isHiddenLogMessage(log.message)) {
      continue;
    }
    const start = parseStartingLog(log.message);
    if (start) {
      currentGroup = {
        key: `site:${start.index ?? logs.indexOf(log)}:${start.url}`,
        label: siteLabel(start.url, start.index, start.total),
        url: start.url,
        index: start.index,
        total: start.total,
        logs: [],
        stageLogs: {
          acquisition: [],
          extraction: [],
          normalize: [],
          persistence: [],
          system: [],
        },
      };
      groups.push(currentGroup);
    }

    if (!currentGroup) {
      untitledCounter += 1;
      currentGroup = {
        key: `run:${untitledCounter}`,
        label: TERMINAL_STRINGS.RUN_EVENTS,
        url: '',
        index: null,
        total: null,
        logs: [],
        stageLogs: {
          acquisition: [],
          extraction: [],
          normalize: [],
          persistence: [],
          system: [],
        },
      };
      groups.push(currentGroup);
    }

    const stage = start ? 'system' : getLogStage(log.message);
    currentGroup.logs.push(log);
    currentGroup.stageLogs[stage].push(log);
  }

  return groups.map((group) => {
    const matchedRecords = group.url
      ? records.filter((record) => matchesSiteUrl(record, group.url))
      : [];
    let lastStage: LogStage = 'system';
    for (const stage of [...DISPLAY_LOG_STAGES, 'system'] as LogStage[]) {
      if (group.stageLogs[stage].length > 0) {
        lastStage = stage;
      }
    }
    const hasError = group.logs.some((log) => logMessageIsError(log.level, log.message));
    const hasWarning = !hasError && group.logs.some(isWarningLog);
    return {
      ...group,
      records: matchedRecords,
      hasError,
      hasWarning,
      lastStage,
      recordCount: matchedRecords.length,
    };
  });
}

function severityTone(group: LogSiteGroup, index: number) {
  // REMOVED ALL BACKGROUND COLORS AS PER USER REQUEST - TERMINAL IS NOW MONOCHROMATIC
  if (group.hasError) {
    return 'bg-transparent border-l-2 border-l-danger';
  }
  if (group.hasWarning) {
    return 'bg-transparent border-l-2 border-l-warning';
  }
  if (group.recordCount > 0 || group.stageLogs.persistence.length > 0) {
    return 'bg-transparent border-l-2 border-l-success';
  }
  return index % 2 === 0
    ? 'bg-[color-mix(in_srgb,var(--bg-alt)_40%,transparent)]'
    : 'bg-transparent';
}

function severityLabel(group: LogSiteGroup) {
  if (group.hasError) {
    return 'Error';
  }
  if (group.hasWarning) {
    return 'Warning';
  }
  if (group.recordCount > 0 || group.stageLogs.persistence.length > 0) {
    return 'Persisted';
  }
  return 'Running';
}

function payloadSnapshot(group: LogSiteGroup) {
  if (!group.records.length) {
    return '';
  }
  const payload =
    group.records.length === 1
      ? cleanRecordForDisplay(group.records[0])
      : group.records.map(cleanRecordForDisplay);
  return JSON.stringify(payload, null, 2);
}

function publicFieldNames(record: CrawlRecord) {
  return Object.entries(record.data ?? {})
    .filter(([key, value]) => !key.startsWith('_') && isInformativeValue(value))
    .map(([key]) => key);
}

function recordConfidence(record: CrawlRecord): { score: number; level: string } | null {
  const rawConfidence =
    (record.raw_data && typeof record.raw_data === 'object'
      ? (record.raw_data as Record<string, unknown>)._confidence
      : null) ||
    (record.discovered_data && typeof record.discovered_data === 'object'
      ? (record.discovered_data as Record<string, unknown>).confidence
      : null);
  if (!rawConfidence || typeof rawConfidence !== 'object') {
    return null;
  }
  const payload = rawConfidence as Record<string, unknown>;
  const score = Number(payload.score);
  if (!Number.isFinite(score)) {
    return null;
  }
  return {
    score,
    level:
      String(payload.level || qualityLevelFromScore(score))
        .trim()
        .toLowerCase() || 'unknown',
  };
}

function groupConfidence(group: LogSiteGroup): { score: number; level: string } | null {
  const scores = group.records
    .map(recordConfidence)
    .filter((value): value is { score: number; level: string } => value !== null);
  if (!scores.length) {
    return null;
  }
  const average = scores.reduce((total, item) => total + item.score, 0) / scores.length;
  return {
    score: average,
    level: String(qualityLevelFromScore(average)),
  };
}

function groupFieldCoverage(group: LogSiteGroup, requestedFields: string[]) {
  const requested = uniqueRequestedFields(requestedFields);
  const normalizedRequested = requested.map(normalizeField);
  const foundNormalized = new Set<string>();
  const foundOriginal = new Map<string, string>();

  for (const record of group.records) {
    for (const field of publicFieldNames(record)) {
      const normalized = normalizeField(field);
      foundNormalized.add(normalized);
      if (!foundOriginal.has(normalized)) {
        foundOriginal.set(normalized, field);
      }
    }
  }

  if (requested.length) {
    const covered = requested.filter(
      (field, index) =>
        foundNormalized.has(normalizedRequested[index]) || foundNormalized.has(field),
    );
    return {
      foundCount: covered.length,
      totalCount: requested.length,
      labels: covered,
    };
  }

  const labels = Array.from(foundOriginal.values());
  return {
    foundCount: labels.length,
    totalCount: labels.length,
    labels,
  };
}

function toneForConfidence(level: string) {
  if (level === 'high') return 'text-success';
  if (level === 'medium') return 'text-warning';
  if (level === 'low') return 'text-danger';
  return 'text-muted';
}

type ExpandedLogRow = {
  key: string;
  stage: LogStage;
  level: string;
  message: string;
  createdAt?: string | null;
  payloadAction?: boolean;
};

function buildExpandedRows(
  group: LogSiteGroup,
  coverage: ReturnType<typeof groupFieldCoverage>,
  confidence: ReturnType<typeof groupConfidence>,
): ExpandedLogRow[] {
  const rows: ExpandedLogRow[] = group.logs.map((log) => ({
    key: `log-${log.id}`,
    stage: parseStartingLog(log.message) ? 'system' : getLogStage(log.message),
    level: log.level,
    message: log.message,
    createdAt: log.created_at,
  }));

  if (coverage.totalCount > 0 || coverage.labels.length > 0 || confidence) {
    const parts: string[] = [];
    if (coverage.totalCount > 0) {
      const labels = coverage.labels.length
        ? coverage.labels.map(humanizeFieldName).join(', ')
        : 'none';
      parts.push(
        `${TERMINAL_STRINGS.FIELDS} ${coverage.foundCount}/${coverage.totalCount}: ${labels}`,
      );
    }
    if (confidence) {
      parts.push(`${TERMINAL_STRINGS.CONFIDENCE} ${Math.round(confidence.score * 100)}%`);
    }
    rows.push({
      key: `${group.key}-fields`,
      stage: 'persistence',
      level: 'info',
      message: parts.join(' | '),
      payloadAction: group.records.length > 0,
    });
  }

  return rows;
}

function formatShortUrlLabel(url: string) {
  try {
    const parsed = new URL(url);
    const domain = parsed.hostname.replace(/^www\./, '');
    const parts = parsed.pathname.split('/').filter(Boolean);
    const lastPart = parts.at(-1) || '';
    if (parts.length > 1) {
      return `${domain}/.../${lastPart}`;
    }
    return domain + (lastPart ? `/${lastPart}` : '');
  } catch {
    return url.length > 40 ? url.slice(0, 40) + '…' : url;
  }
}

function sanitizeLogMessage(message: string) {
  return String(message || '')
    .replace(/\s*\[corr=[^\]]+\]/gi, '')
    .replace(/\s{2,}/g, ' ')
    .trim();
}

function ShortenedUrl({ url }: { url: string }) {
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      className="text-info decoration-info/20 hover:text-accent type-body underline underline-offset-4 transition-colors"
      title={url}
      onClick={(e) => e.stopPropagation()}
    >
      {formatShortUrlLabel(url)}
    </a>
  );
}

function renderLogContent(message: string, isStartingCrawl: boolean): React.ReactNode {
  let text = sanitizeLogMessage(message).replace(LOG_PATTERNS.ROBOTS_PREFIX, '');
  text = text.replace(
    LOG_PATTERNS.HEADLESS_BROWSER,
    (_, engine) => `Launched ${engine.trim()} browser`,
  );

  const urlRegex = LOG_PATTERNS.URL;
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
      if (typeof part === 'string') {
        const counterMatch = part.match(LOG_PATTERNS.COUNTER);
        if (counterMatch && counterMatch.index !== undefined) {
          const before = part.slice(0, counterMatch.index);
          const after = part.slice(counterMatch.index + counterMatch[0].length);
          return (
            <React.Fragment key={i}>
              {before}
              <span className="text-blue-400/70">{counterMatch[0]}</span>
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
  records = [],
  requestedFields = [],
  live = false,
  viewportRef,
}: Readonly<{
  logs: CrawlLog[];
  records?: CrawlRecord[];
  requestedFields?: string[];
  live?: boolean;
  viewportRef?: RefObject<HTMLDivElement | null>;
}>) {
  const ref = useLogViewport(logs.length, viewportRef);
  const peekPanelRef = useRef<HTMLDivElement | null>(null);
  const [peekedGroupKey, setPeekedGroupKey] = useState<string | null>(null);
  const [peekedRecordIndex, setPeekedRecordIndex] = useState(0);
  const [expandedGroupPreference, setExpandedGroupPreference] = useState<
    string | null | '__auto__'
  >('__auto__');
  const [triageCursor, setTriageCursor] = useState(0);
  const groups = useMemo(() => buildLogSiteGroups(logs, records), [logs, records]);
  const issueGroups = useMemo(
    () => groups.filter((group) => group.hasError || group.hasWarning),
    [groups],
  );
  const activePeekedGroupKey = useMemo(
    () =>
      peekedGroupKey && groups.some((group) => group.key === peekedGroupKey)
        ? peekedGroupKey
        : null,
    [groups, peekedGroupKey],
  );
  const peekedGroup = useMemo(
    () => groups.find((group) => group.key === activePeekedGroupKey) ?? null,
    [activePeekedGroupKey, groups],
  );
  const expandedGroupKey = useMemo(() => {
    if (
      expandedGroupPreference &&
      expandedGroupPreference !== '__auto__' &&
      groups.some((group) => group.key === expandedGroupPreference)
    ) {
      return expandedGroupPreference;
    }
    if (expandedGroupPreference === null) {
      return null;
    }
    if (live && groups.length > 0) {
      return groups[groups.length - 1].key;
    }
    return issueGroups[0]?.key ?? groups[0]?.key ?? null;
  }, [expandedGroupPreference, groups, issueGroups, live]);
  const safePeekedRecordIndex = peekedGroup
    ? Math.min(peekedRecordIndex, Math.max(peekedGroup.records.length - 1, 0))
    : 0;
  const safeTriageCursor = issueGroups.length ? Math.min(triageCursor, issueGroups.length - 1) : 0;

  useEffect(() => {
    if (!activePeekedGroupKey) {
      return;
    }
    const handlePointerDown = (event: MouseEvent) => {
      const panel = peekPanelRef.current;
      if (!panel) {
        return;
      }
      if (!panel.contains(event.target as Node)) {
        setPeekedGroupKey(null);
      }
    };
    document.addEventListener('mousedown', handlePointerDown);
    return () => document.removeEventListener('mousedown', handlePointerDown);
  }, [activePeekedGroupKey]);

  const timelineTicks = useMemo(() => {
    if (!groups.length) {
      return [];
    }
    const start = parseApiDate(groups[0].logs[0]?.created_at ?? new Date().toISOString()).getTime();
    const end = parseApiDate(
      groups[groups.length - 1].logs.at(-1)?.created_at ??
        groups[0].logs[0]?.created_at ??
        new Date().toISOString(),
    ).getTime();
    const range = Math.max(1, end - start);
    return groups.map((group) => {
      const createdAt = group.logs[0]?.created_at ?? new Date().toISOString();
      const percent = ((parseApiDate(createdAt).getTime() - start) / range) * 100;
      return {
        key: group.key,
        percent,
        tone: group.hasError
          ? 'bg-danger'
          : group.hasWarning
            ? 'bg-warning'
            : group.recordCount > 0
              ? 'bg-emerald-400'
              : 'bg-white/15',
      };
    });
  }, [groups]);

  const jumpToGroup = (groupKey: string) => {
    const el = document.getElementById(siteDomId(groupKey));
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      el.classList.add('log-entry-highlight');
      setTimeout(() => el.classList.remove('log-entry-highlight'), 2000);
    }
    setExpandedGroupPreference(groupKey);
  };

  const toggleGroup = (groupKey: string) => {
    if (live && groups.length > 0 && groupKey === groups[groups.length - 1].key) {
      return;
    }
    setExpandedGroupPreference((current) => (current === groupKey ? null : groupKey));
  };

  const navigateTriage = (dir: 'next' | 'prev') => {
    if (!issueGroups.length) {
      return;
    }
    const delta = dir === 'next' ? 1 : -1;
    const nextIndex = (safeTriageCursor + delta + issueGroups.length) % issueGroups.length;
    setTriageCursor(nextIndex);
    jumpToGroup(issueGroups[nextIndex].key);
  };

  return (
    <div
      className="group/terminal relative flex flex-col overflow-hidden rounded-xl border"
      style={{
        borderColor: 'var(--terminal-border)',
        backgroundColor: 'var(--terminal-bg)',
        color: 'var(--terminal-fg)',
        boxShadow: 'var(--terminal-shadow)',
      }}
    >
      <div
        className="flex h-9 items-center justify-between border-b bg-[color-mix(in_srgb,var(--text-primary)_5%,transparent)] px-4"
        style={{ borderColor: 'var(--terminal-border)' }}
      >
        <span className="text-muted type-label-mono tracking-[0.25em] uppercase">
          activity_stream.log
        </span>
        <div className="flex items-center gap-3">
          <div className="group/scrubber relative flex h-2 w-32 cursor-crosshair items-center rounded-sm bg-[color-mix(in_srgb,var(--text-primary)_8%,transparent)]">
            {timelineTicks.map((tick) => (
              <div
                key={tick.key}
                role="button"
                tabIndex={0}
                aria-label={`Jump to ${tick.key}`}
                onClick={() => jumpToGroup(tick.key)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ' || e.code === 'Space') {
                    e.preventDefault();
                    jumpToGroup(tick.key);
                  }
                }}
                className={cn(
                  'focus-visible:ring-accent absolute h-full w-0.5 cursor-pointer transition-transform hover:scale-y-125 focus-visible:scale-y-125 focus-visible:ring-1 focus-visible:outline-none',
                  tick.tone,
                )}
                style={{ left: `${tick.percent}%` }}
              />
            ))}
          </div>
          <div className="flex items-center gap-3 opacity-60 transition-opacity group-focus-within/terminal:opacity-100 group-hover/terminal:opacity-100">
            <button
              onClick={() => navigateTriage('prev')}
              className="type-label-mono hover:text-accent focus-visible:text-accent focus-visible:outline-none"
            >
              Prev
            </button>
            <span className="bg-muted h-3 w-px opacity-20" />
            <button
              onClick={() => navigateTriage('next')}
              className="type-label-mono hover:text-accent focus-visible:text-accent focus-visible:outline-none"
            >
              Next
            </button>
          </div>
        </div>
      </div>

      <div
        ref={ref}
        className="crawl-activity-log max-h-[72vh] min-h-[50vh] overflow-y-auto"
        role="log"
        aria-live={live ? 'polite' : 'off'}
        aria-atomic="false"
      >
        {groups.length ? (
          groups.map((group, index) => {
            const activeKey = live && groups.length > 0 ? groups[groups.length - 1].key : null;
            const expanded = expandedGroupKey === group.key || group.key === activeKey;
            const payload = payloadSnapshot(group);
            const confidence = groupConfidence(group);
            const coverage = groupFieldCoverage(group, requestedFields);
            const lastLog = group.logs.at(-1);
            const summaryLog =
              [...group.logs].reverse().find((log) => !isPersistenceSummaryLog(log.message)) ??
              lastLog;
            const expandedRows = buildExpandedRows(group, coverage, confidence);
            return (
              <section key={group.key} id={siteDomId(group.key)} className="overflow-hidden">
                <div
                  role="button"
                  tabIndex={0}
                  aria-expanded={expanded}
                  aria-label={`${expanded ? 'Collapse' : 'Expand'} logs for ${group.url || group.label}`}
                  onClick={() => toggleGroup(group.key)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === '') {
                      e.preventDefault();
                      toggleGroup(group.key);
                    }
                  }}
                  className={cn(
                    'group/row grid w-full cursor-pointer grid-cols-[32px_minmax(280px,2fr)_80px_100px_auto_minmax(200px,1.2fr)_80px_60px] items-center gap-3 px-4 py-2.5 text-left transition-colors outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-inset',
                    severityTone(group, index),
                  )}
                >
                  <div className="type-body text-muted font-medium opacity-60">
                    {(index + 1).toString().padStart(2, '0')}
                  </div>
                  <div className="min-w-0">
                    {group.url ? (
                      <a
                        href={group.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        onClick={(e) => e.stopPropagation()}
                        className="text-info block truncate text-sm font-normal underline-offset-4 hover:underline"
                        title={group.url}
                      >
                        {formatShortUrlLabel(group.url)}
                      </a>
                    ) : (
                      <span
                        className="text-secondary block truncate text-sm font-normal"
                        title={group.label}
                        onClick={(e) => e.stopPropagation()}
                      >
                        {group.label}
                      </span>
                    )}
                  </div>
                  <div className="type-body text-secondary font-medium whitespace-nowrap">
                    <span className="text-muted mr-1.5 font-sans text-sm font-bold tracking-wider uppercase">
                      F:
                    </span>
                    {coverage.foundCount}/{coverage.totalCount || 0}
                  </div>
                  <div className="type-body font-medium whitespace-nowrap">
                    <span className="text-muted mr-1.5 font-sans text-sm font-bold tracking-wider uppercase">
                      C:
                    </span>
                    <span
                      className={cn(
                        confidence ? toneForConfidence(confidence.level) : 'text-muted',
                      )}
                    >
                      {confidence ? `${Math.round(confidence.score * 100)}%` : '--'}
                    </span>
                  </div>
                  <div className="flex items-center justify-center">
                    {group.lastStage !== 'system' && (
                      <div
                        className={cn(
                          'rounded px-1.5 py-0.5 text-sm font-bold tracking-wider uppercase',
                          STAGE_CONFIG[group.lastStage].chipClass,
                        )}
                      >
                        {STAGE_CONFIG[group.lastStage].label}
                      </div>
                    )}
                  </div>
                  <div className="min-w-0">
                    <div
                      className="type-control text-secondary truncate"
                      title={summaryLog?.message || ''}
                    >
                      {summaryLog
                        ? sanitizeLogMessage(summaryLog.message)
                        : TERMINAL_STRINGS.PENDING}
                    </div>
                  </div>
                  <div className="flex items-center justify-end">
                    {payload ? (
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="type-control h-7 px-2"
                        onClick={(event) => {
                          event.stopPropagation();
                          setPeekedGroupKey(group.key);
                          setPeekedRecordIndex(0);
                        }}
                      >
                        Peek
                      </Button>
                    ) : (
                      <span className="type-caption opacity-25">--</span>
                    )}
                  </div>
                  <div className="pr-2 text-right">
                    <div className="text-muted group-hover/row:text-secondary type-label-mono uppercase transition-colors">
                      {live && groups.length > 0 && group.key === groups[groups.length - 1].key
                        ? 'Active'
                        : expanded
                          ? 'Less'
                          : 'More'}
                    </div>
                  </div>
                </div>

                {expanded ? (
                  <div className="bg-[color-mix(in_srgb,var(--bg-alt)_60%,transparent)]">
                    <div className="overflow-hidden">
                      {expandedRows.length ? (
                        expandedRows.map((row, expandedIndex) => {
                          return (
                            <div
                              key={row.key}
                              className={cn(
                                'grid grid-cols-[64px_84px_minmax(0,1fr)_auto] items-center gap-4 px-4 py-2 text-xs',
                                expandedIndex % 2 === 0
                                  ? 'bg-[color-mix(in_srgb,var(--bg-alt)_35%,transparent)]'
                                  : 'bg-transparent',
                              )}
                            >
                              <span className="text-muted font-mono text-xs font-medium tabular-nums">
                                {row.createdAt ? formatTimeHms(row.createdAt) : '--'}
                              </span>
                              <span
                                className={cn(
                                  'inline-flex text-xs font-semibold tracking-wider uppercase',
                                  STAGE_CONFIG[row.stage].textOnlyClass,
                                )}
                              >
                                {STAGE_CONFIG[row.stage].label}
                              </span>
                              <span className="type-body text-secondary min-w-0 font-medium break-words">
                                {!row.createdAt
                                  ? row.message
                                  : renderLogContent(row.message, row.stage === 'system')}
                              </span>
                              <span className="flex items-center gap-2">
                                {row.payloadAction ? (
                                  <Button
                                    type="button"
                                    variant="ghost"
                                    size="sm"
                                    className="h-auto px-0 py-0 text-xs font-normal"
                                    onClick={() => {
                                      setPeekedGroupKey(group.key);
                                      setPeekedRecordIndex(0);
                                    }}
                                  >
                                    Peek payload
                                  </Button>
                                ) : null}
                              </span>
                            </div>
                          );
                        })
                      ) : (
                        <div className="px-3 py-2 text-xs opacity-40">
                          {TERMINAL_STRINGS.NO_LOGS}
                        </div>
                      )}
                    </div>
                  </div>
                ) : null}
              </section>
            );
          })
        ) : (
          <div className="px-4 py-8 text-center text-[14px] italic opacity-55">
            {live ? 'Waiting for log stream...' : 'No log activity recorded'}
          </div>
        )}
      </div>

      {activePeekedGroupKey ? (
        <div className="absolute inset-0 z-40 bg-[color-mix(in_srgb,var(--bg-base)_60%,transparent)] backdrop-blur-sm">
          <div
            ref={peekPanelRef}
            className="animate-in slide-in-from-right absolute inset-y-0 right-0 z-50 w-[32rem] max-w-full border-l duration-300"
            style={{
              borderColor: 'var(--terminal-border)',
              backgroundColor: 'var(--terminal-code-bg)',
              color: 'var(--terminal-fg)',
              boxShadow: 'var(--terminal-shadow)',
            }}
          >
            <div
              className="flex items-center justify-between border-b px-4 py-3"
              style={{
                borderColor: 'var(--terminal-border)',
                backgroundColor: 'var(--terminal-bg)',
              }}
            >
              <div className="min-w-0 flex-1">
                <div className="text-accent type-label-mono text-[10px] font-bold tracking-wider uppercase">
                  {TERMINAL_STRINGS.PAYLOAD_PEEK}
                </div>
                <div
                  className="mt-0.5 truncate pr-4 text-xs font-medium tabular-nums"
                  style={{ color: 'var(--text-muted)' }}
                  title={peekedGroup?.label ?? ''}
                >
                  {peekedGroup?.label ?? TERMINAL_STRINGS.SITE_PAYLOAD}
                </div>
              </div>
              <button
                onClick={() => setPeekedGroupKey(null)}
                className="hover:text-foreground text-xs font-medium transition-colors"
                style={{ color: 'var(--text-muted)' }}
              >
                Close
              </button>
            </div>
            <div className="relative h-[calc(100%-60px)] overflow-hidden p-4">
              <div className="group relative h-full">
                <div className="absolute top-3 right-3 z-10 opacity-0 transition-all group-hover:opacity-100">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-7 bg-[#1e1e1e]/80 text-[10px] text-white backdrop-blur-sm hover:bg-white/10 hover:text-white"
                    onClick={() => {
                      if (!peekedGroup) return;
                      const currentRecord =
                        peekedGroup.records[safePeekedRecordIndex] ?? peekedGroup.records[0];
                      if (!currentRecord) return;
                      void navigator.clipboard.writeText(
                        JSON.stringify(cleanRecordForDisplay(currentRecord), null, 2),
                      );
                    }}
                  >
                    <Copy className="mr-1.5 size-3" />
                    Copy
                  </Button>
                </div>
                <pre
                  className="crawl-terminal crawl-terminal-json h-full max-h-full overflow-auto"
                >
                  {peekedGroup && peekedGroup.records[safePeekedRecordIndex]
                    ? JSON.stringify(
                        cleanRecordForDisplay(peekedGroup.records[safePeekedRecordIndex]),
                        null,
                        2,
                      )
                    : TERMINAL_STRINGS.NO_PAYLOAD}
                </pre>
              </div>
            </div>
          </div>
        </div>
      ) : null}
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
        className: cn(icon.props.className, 'size-4'),
      })
    : null;

  return (
    // Outer wrapper is flex-col so the children panel is a sibling of the control row,
    // not a child inside the h-9 constraint that would clip it.
    <div className="w-full">
      <div className="grid h-9 w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-3">
        <div className="flex min-w-0 items-center gap-1.5">
          {renderedIcon ? (
            <div
              className={cn(
                'flex size-8 shrink-0 items-center justify-center rounded-[var(--radius-md)] border transition-colors',
                checked
                  ? 'bg-setting-icon-active-bg text-accent shadow-setting-icon-active border-[color:color-mix(in_srgb,var(--accent)_22%,transparent)]'
                  : 'border-border bg-setting-icon-bg text-secondary',
              )}
            >
              {renderedIcon}
            </div>
          ) : null}
          <div className="type-control min-w-0">{label}</div>
          <Tooltip content={description}>
            <Info className="text-muted hover:text-secondary size-3.5 cursor-help transition-colors" />
          </Tooltip>
        </div>
        <div className="flex justify-start">
          <PrimitiveToggle checked={checked} onChange={onChange} ariaLabel={label} />
        </div>
      </div>
      {/* Children panel as sibling — can animate height freely */}
      {children ? (
        <div
          className={cn(
            'transition-[max-height] duration-200 ease-out',
            checked ? 'max-h-[500px] overflow-visible' : 'max-h-0 overflow-hidden',
          )}
        >
          <div className="border-divider bg-setting-body-bg space-y-3 border-t px-5 py-4">
            {children}
          </div>
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
      className={cn('grid w-full gap-2.5 md:grid-cols-[140px_minmax(0,1fr)_112px] md:items-center')}
    >
      <div className="flex min-w-0 items-center gap-1.5">
        <span className="type-control">{label}</span>
        {description ? (
          <Tooltip content={description}>
            <Info className="text-muted hover:text-secondary size-3.5 cursor-help transition-colors" />
          </Tooltip>
        ) : null}
        <button
          type="button"
          onClick={onReset}
          aria-label={`Reset ${label}`}
          className="text-muted hover:text-primary transition-colors"
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
          onChange={(event) => onChange(event.target.value.replace(/[^\d]/g, ''))}
          onBlur={() => onChange(String(clampNumber(value, min, max, min)))}
          className="pr-8 text-right font-mono tabular-nums"
        />
        {suffix ? (
          <span className="text-muted type-caption pointer-events-none absolute top-1/2 right-1.5 -translate-y-1/2 lowercase">
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
  const chips = uniqueRequestedFields([...fields, ...parseLines(value.replace(/,/g, '\n'))]);
  const [validationHint, setValidationHint] = useState<string | null>(null);

  function commitField(candidate: string) {
    const cleaned = cleanRequestedField(candidate);
    if (!cleaned) {
      return;
    }
    const validationError = validateAdditionalFieldName(cleaned);
    if (validationError) {
      setValidationHint(`Skipped "${cleaned}": ${validationError}`);
      return;
    }
    onCommit(cleaned);
  }

  function handleChange(next: string) {
    const parts = next.split(',');
    parts.slice(0, -1).forEach(commitField);
    setValidationHint(null);
    onChange(parts.at(-1) ?? '');
  }

  function handleBlur() {
    parseLines(value).forEach(commitField);
    onChange('');
  }

  return (
    <label className="grid gap-1.5">
      <span className="type-control">Additional Fields</span>
      <Input
        value={value}
        onChange={(event) => handleChange(event.target.value)}
        onBlur={handleBlur}
        placeholder="price, sku, Features & Benefits, Product Story"
        className="font-mono"
      />
      {validationHint ? <p className="text-danger type-caption">{validationHint}</p> : null}
      {chips.length ? (
        <div className="flex flex-wrap gap-1.5">
          {chips.map((field) => (
            <button
              key={field}
              type="button"
              onClick={() => onRemove(field)}
              aria-label={`Remove ${field}`}
              className="border-subtle-panel-border bg-subtle-panel text-secondary type-body inline-flex items-center gap-1 rounded-[var(--radius-sm)] border px-2 py-1"
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
  messageTone = 'warning',
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
    <div className="border-border card-gradient space-y-1.5 rounded-[var(--radius-md)] border p-2.5">
      <div className="grid gap-2 xl:grid-cols-[24px_minmax(140px,0.8fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,0.8fr)_auto]">
        <div className="text-muted/50 hidden items-center justify-center xl:flex">
          <GripVertical className="size-3.5" />
        </div>
        <label className="grid gap-1">
          <span className={cn('field-label', !showLabels && 'sr-only')}>Field</span>
          <Input
            aria-label="Field"
            value={row.fieldName}
            onChange={(event) => onChange({ fieldName: event.target.value })}
            placeholder="price"
            className="type-body h-8"
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
                className="type-control h-8 min-w-[64px]"
              >
                {testing ? '...' : 'Test'}
              </Button>
            ) : null}
            <button
              type="button"
              onClick={onDelete}
              aria-label={`Delete ${row.fieldName || 'manual field'}`}
              className="surface-muted text-danger/70 hover:bg-danger/10 hover:text-danger inline-flex size-8 items-center justify-center rounded-[var(--radius-md)]"
            >
              <Trash2 className="size-3.5" />
            </button>
          </div>
        </div>
      </div>
      {message ? (
        <div
          className={cn(
            'alert-surface type-caption px-2.5 py-1.5',
            messageTone === 'success' && 'alert-success',
            messageTone === 'warning' && 'alert-warning',
            messageTone === 'danger' && 'alert-danger',
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
        <span className="type-label-mono text-accent">Field</span>
        <Info className="text-accent/60 size-3" />
      </div>
      <div className="flex items-center gap-1.5">
        <span className="type-label-mono text-accent">CSS</span>
        <Info className="text-accent/60 size-3" />
      </div>
      <div className="flex items-center gap-1.5">
        <span className="type-label-mono text-accent">XPath</span>
        <Info className="text-accent/60 size-3" />
      </div>
      <div className="flex items-center gap-1.5">
        <span className="type-label-mono text-accent">Regex</span>
        <Info className="text-accent/60 size-3" />
      </div>
      <span className="type-label-mono text-accent text-right">Actions</span>
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
      <span className={cn('field-label', !showLabel && 'sr-only')}>{label}</span>
      <div className="relative">
        <Input
          aria-label={label}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onBlur={(event) => onBlur(event.target.value)}
          placeholder={placeholder}
          className="type-body h-8 pr-9"
        />
        <div className="pointer-events-none absolute inset-y-0 right-2.5 flex items-center">
          {state === 'valid' ? <CheckCircle2 className="text-success/80 size-3.5" /> : null}
          {state === 'invalid' ? <CircleAlert className="text-danger/80 size-3.5" /> : null}
        </div>
      </div>
    </label>
  );
}

const BROKEN_THUMBNAIL_STORAGE_KEY = 'crawlerai-broken-thumb-urls-v1';
const BROKEN_THUMBNAIL_HOSTS_KEY = 'crawlerai-broken-thumb-hosts-v1';
const BROKEN_THUMBNAIL_URLS = new Set<string>();
const BROKEN_THUMBNAIL_HOSTS = new Set<string>();

function loadBrokenThumbnailCache() {
  if (typeof window === 'undefined') return;
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
  if (typeof window === 'undefined') return;
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
    return '';
  }
}

function RecordThumbnail({ src }: Readonly<{ src: string }>) {
  const host = thumbnailHost(src);
  const initiallyBroken =
    BROKEN_THUMBNAIL_URLS.has(src) || (host !== '' && BROKEN_THUMBNAIL_HOSTS.has(host));
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
  const IMAGE_KEYS = new Set(['image_url', 'image', 'thumbnail', 'img']);
  const TITLE_KEYS = new Set(['title', 'name', 'product_name', 'product title']);
  const PRICE_KEYS = new Set([
    'price',
    'sale_price',
    'offer_price',
    'current_price',
    'final_price',
    'our_price',
    'deal_price',
  ]);
  const URL_KEYS = new Set(['url', 'source_url', 'product_url', 'canonical_url']);

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
    if (!containerNode || typeof ResizeObserver === 'undefined') {
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
    if (!raw || raw === '--') return <span className="text-muted/40 type-body">--</span>;

    if (TITLE_KEYS.has(col)) {
      return <span className="type-body block max-w-[320px] truncate font-medium">{raw}</span>;
    }
    if (PRICE_KEYS.has(col)) {
      return <span className="text-foreground type-body font-bold tabular-nums">{raw}</span>;
    }
    if (URL_KEYS.has(col)) {
      const isSafe = raw.startsWith('http://') || raw.startsWith('https://');
      if (isSafe) {
        return (
          <a
            href={raw}
            target="_blank"
            rel="noreferrer"
            className="link-accent block max-w-[200px] truncate text-sm transition-colors"
            title={raw}
          >
            {raw}
          </a>
        );
      }
    }
    return <span className="text-secondary block max-w-[260px] truncate text-sm">{raw}</span>;
  }

  return (
    <div className="surface-muted max-h-[calc(100vh-272px)] overflow-hidden rounded-[var(--radius-md)] border">
      <Table
        className="compact-data-table min-w-max"
        wrapperClassName="max-h-[calc(100vh-276px)] scrollbar-stable"
      >
        <TableHeader className="bg-background sticky top-0 z-40">
          <TableRow>
            <TableHead className="bg-background sticky left-0 z-50 w-10">
              <input
                type="checkbox"
                checked={selectedIds.length === records.length && records.length > 0}
                onChange={(event) => onSelectAll(event.target.checked)}
              />
            </TableHead>
            {hasImageCol ? (
              <TableHead className="bg-background sticky left-10 z-50 w-16 text-center">
                IMG
              </TableHead>
            ) : null}
            {dataColumns.map((col, idx) => {
              const isFirstData = idx === 0;
              const isUrl = URL_KEYS.has(col.toLowerCase());
              const leftOffset = isFirstData ? (hasImageCol ? 104 : 40) : undefined;
              return (
                <TableHead
                  key={col}
                  style={
                    leftOffset !== undefined
                      ? { left: leftOffset, width: isUrl ? 280 : 180 }
                      : undefined
                  }
                  className={cn(
                    'bg-background whitespace-nowrap',
                    PRICE_KEYS.has(col) && 'text-right',
                    isFirstData && 'sticky z-50',
                    isUrl && 'min-w-[280px]',
                  )}
                >
                  {humanizeFieldName(col)}
                </TableHead>
              );
            })}
          </TableRow>
        </TableHeader>
        <TableBody>
          {records.map((record) => {
            const isSelected = selectedIds.includes(record.id);
            const imageSrc = imageCol ? stringifyCell(readRecordValue(record, imageCol)) : '';

            return (
              <TableRow key={record.id} className={cn(isSelected && 'bg-accent/[0.04]')}>
                <TableCell className="bg-background sticky left-0 z-30">
                  <input
                    type="checkbox"
                    checked={isSelected}
                    onChange={(event) => onToggleRow(record.id, event.target.checked)}
                  />
                </TableCell>
                {hasImageCol ? (
                  <TableCell className="bg-background sticky left-10 z-30 text-center">
                    {imageSrc ? (
                      <RecordThumbnail src={imageSrc} />
                    ) : (
                      <span className="text-muted/40 type-body">--</span>
                    )}
                  </TableCell>
                ) : null}
                {dataColumns.map((col, idx) => {
                  const isFirstData = idx === 0;
                  const isUrl = URL_KEYS.has(col.toLowerCase());
                  const leftOffset = isFirstData ? (hasImageCol ? 104 : 40) : undefined;
                  return (
                    <TableCell
                      key={col}
                      style={
                        leftOffset !== undefined
                          ? { left: leftOffset, width: isUrl ? 280 : 180 }
                          : undefined
                      }
                      className={cn(
                        PRICE_KEYS.has(col) && 'text-right',
                        isFirstData && 'bg-background sticky z-30',
                        isUrl && 'min-w-[280px]',
                      )}
                    >
                      {renderCell(col, record)}
                    </TableCell>
                  );
                })}
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
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
      variant={danger ? 'danger' : 'secondary'}
      size="sm"
      disabled={disabled}
      onClick={onClick}
      className="type-control h-8 min-w-0 px-3"
    >
      {label}
    </Button>
  );
}

export function PreviewRow({
  label,
  value,
  mono,
}: Readonly<{ label: string; value: ReactNode; mono?: boolean }>) {
  return (
    <div className="surface-muted flex items-start justify-between gap-4 rounded-[var(--radius-md)] px-3 py-2">
      <div className="field-label shrink-0">{label}</div>
      <div
        className={cn(
          'text-foreground type-body min-w-0 flex-1 text-right',
          mono && 'type-label-mono',
        )}
      >
        {value || '--'}
      </div>
    </div>
  );
}

function inferRunModule(run?: CrawlRun): CrawlTab | null {
  if (!run) {
    return null;
  }
  const settings = run.settings && typeof run.settings === 'object' ? run.settings : {};
  const configuredModule = typeof settings.crawl_module === 'string' ? settings.crawl_module : '';
  if (configuredModule === 'category' || configuredModule === 'pdp') {
    return configuredModule;
  }

  const configuredMode = typeof settings.crawl_mode === 'string' ? settings.crawl_mode : '';
  if (configuredMode === 'bulk' || configuredMode === 'sitemap') {
    return 'category';
  }
  if (configuredMode === 'batch' || configuredMode === 'csv') {
    return 'pdp';
  }

  const surface = String(run.surface || '').toLowerCase();
  if (surface.includes('listing')) {
    return 'category';
  }
  if (surface.includes('detail')) {
    return 'pdp';
  }

  return null;
}

function validateXPath(value: string): ValidationState {
  if (!value.trim()) return 'idle';
  try {
    globalThis.document?.evaluate(value, globalThis.document, null, XPathResult.ANY_TYPE, null);
    return 'valid';
  } catch {
    return 'invalid';
  }
}

function validateCssSelector(value: string): ValidationState {
  if (!value.trim()) return 'idle';
  try {
    globalThis.document?.querySelector(value);
    return 'valid';
  } catch {
    return 'invalid';
  }
}

function validateRegex(value: string): ValidationState {
  if (!value.trim()) return 'idle';
  try {
    new RegExp(value);
    return 'valid';
  } catch {
    return 'invalid';
  }
}

function logTone(level: string) {
  const normalized = normalizeLogLevel(level);
  if (normalized === 'WARN' || normalized === 'WARNING')
    return 'border-transparent bg-transparent text-warning';
  if (normalized === 'ERROR') return 'border-transparent bg-transparent text-danger';
  return 'border-transparent bg-transparent text-terminal-fg';
}

function logLineTone(level: string) {
  const normalized = normalizeLogLevel(level);
  if (normalized === 'WARN' || normalized === 'WARNING') return 'text-warning';
  if (normalized === 'ERROR') return 'text-danger';
  return 'text-terminal-fg';
}

function normalizeLogLevel(level: string) {
  return String(level || '')
    .trim()
    .toUpperCase();
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
