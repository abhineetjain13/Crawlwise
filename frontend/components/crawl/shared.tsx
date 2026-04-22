"use client";

import {
 CheckCircle2,
 CircleAlert,
 GripVertical,
 Info,
 RotateCcw,
 Trash2,
 X,
} from"lucide-react";
import React, { memo, useCallback, useEffect, useRef, useState } from"react";
import type { ReactElement, ReactNode, RefObject } from"react";

import { Badge, Button, Input, Textarea, Tooltip, Toggle as PrimitiveToggle } from"../ui/primitives";
import type { CrawlDomain, CrawlRecord, CrawlRun, CrawlSurface } from"../../lib/api/types";
import { formatTimeHms, parseApiDate } from"../../lib/format/date";
import { cn } from"../../lib/utils";

export type CrawlTab ="category"|"pdp";
export type CategoryMode ="single"|"sitemap"|"bulk";
export type PdpMode ="single"|"batch"|"csv";
export type ValidationState ="idle"|"valid"|"invalid";
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
export type FieldRowMessageTone ="success"|"warning"|"danger";
export type PendingDispatch = {
 runType:"crawl"|"batch"|"csv";
 surface: CrawlSurface;
 url?: string;
 urls?: string[];
 settings: Record<string, unknown>;
 additionalFields: string[];
 csvFile: File | null;
};
export type OutputTabKey ="table"|"json"|"markdown"|"logs";
type IconElementProps = {
 className?: string;
};

export function parseRequestedCrawlTab(value: string | null): CrawlTab | null {
 return value ==="category"|| value ==="pdp"? value : null;
}

export function parseRequestedCategoryMode(value: string | null): CategoryMode | null {
 return value ==="single"|| value ==="sitemap"|| value ==="bulk"? value : null;
}

export function parseRequestedPdpMode(value: string | null): PdpMode | null {
 return value ==="single"|| value ==="batch"|| value ==="csv"? value : null;
}

export function uniqueFields(values: string[]) {
 return Array.from(new Set(values.map(normalizeField).filter(Boolean)));
}

export function cleanRequestedField(value: string) {
 return String(value ||"").replace(/\s+/g,"").trim();
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
 .replace(/&/g,"")
 .replace(/([a-z0-9])([A-Z])/g,"$1_$2")
 .toLowerCase()
 .replace(/[^a-z0-9]+/g,"_")
 .replace(/_+/g,"_")
 .replace(/^_+|_+$/g,"");
}

export function deriveSurface(domain: CrawlDomain, module: CrawlTab): CrawlSurface {
 if (domain ==="jobs") {
 return module ==="category"?"job_listing":"job_detail";
 }
 return module ==="category"?"ecommerce_listing":"ecommerce_detail";
}

export function inferDomainFromSurface(surface: string | null | undefined): CrawlDomain | null {
 const normalizedSurface = String(surface ||"").toLowerCase();
 if (normalizedSurface.startsWith("job_")) {
 return"jobs";
 }
 if (normalizedSurface.startsWith("ecommerce_")) {
 return"commerce";
 }
 return null;
}

const SCHEMA_TYPE_FIELD_NAMES = new Set([
"aggregaterating",
"breadcrumblist",
"individualproduct",
"organization",
"peopleaudience",
"postaladdress",
"quantitativevalue",
"webpage",
"website",
]);

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
 if (!cleaned) {
 return"Field name cannot be empty.";
 }
 if (cleaned.length < 2) {
 return"Field name must be at least 2 characters.";
 }
 if (cleaned.length > 60) {
 return"Field name must be 60 characters or fewer.";
 }
 if (!normalized) {
 return"Field name must include letters or numbers.";
 }
 if ((cleaned.match(/\s+/g) ?? []).length >= 7 || (normalized.match(/_/g) ?? []).length >= 7) {
 return"Field name is too sentence-like. Keep it concise.";
 }
 if (SCHEMA_TYPE_FIELD_NAMES.has(normalized)) {
 return"Field name looks like a schema type. Use a business field.";
 }
 if (DAY_OF_WEEK_FIELD_NAMES.has(normalized)) {
 return"Field name looks like a day label. Use a business field.";
 }
 return null;
}

export function parseLines(value: string) {
 return value
 .split(/\r?\n/)
 .map((line) => line.trim())
 .filter(Boolean);
}

export function clampNumber(value: string, min: number, max: number, fallback: number) {
 const parsed = Number.parseInt(value, 10);
 if (Number.isNaN(parsed)) return fallback;
 return Math.min(max, Math.max(min, parsed));
}

export function extractRecordUrl(record: CrawlRecord) {
 const value = record.data?.url ?? record.raw_data?.url ?? record.source_url;
 return stringifyCell(value).trim();
}

export function isListingRun(run?: CrawlRun) {
 return inferRunModule(run) ==="category";
}

export function stringifyCell(value: unknown) {
 if (value == null) return"";
 if (typeof value ==="string") return value;
 return JSON.stringify(value);
}

export function decodeUrlForDisplay(value: string) {
 const text = String(value ||"").trim();
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
 if (typeof value ==="string") {
 return decodeUrlForDisplay(value) as T;
 }
 if (Array.isArray(value)) {
 return value.map((entry) => decodeUrlsForDisplay(entry)) as T;
 }
 if (value && typeof value ==="object") {
 return Object.fromEntries(
 Object.entries(value).map(([key, entry]) => [key, decodeUrlsForDisplay(entry)]),
 ) as T;
 }
 return value;
}

export function humanizeFieldName(value: string) {
 const normalized = String(value ||"")
 .replace(/[_-]+/g,"")
 .replace(/\s+/g,"")
 .trim();
 if (!normalized) return"";
 return normalized.charAt(0).toUpperCase() + normalized.slice(1);
}

export function presentCandidateValue(value: unknown) {
 const trimmed = stringifyCell(value).trim();
 if (!trimmed) return"";
 const schemaMatch = trimmed.match(/^https?:\/\/schema\.org\/([A-Za-z]+)$/i);
 if (!schemaMatch) return trimmed;
 const token = schemaMatch[1].replace(/([a-z])([A-Z])/g,"$1 $2");
 return token.charAt(0).toUpperCase() + token.slice(1);
}

export function isEmptyCandidateValue(value: unknown) {
 if (value === null || value === undefined) return true;
 if (typeof value ==="string") return value.trim().length === 0;
 if (Array.isArray(value)) return value.length === 0;
 if (typeof value ==="object") return Object.keys(value).length === 0;
 return false;
}

export function readRecordValue(record: CrawlRecord, field: string) {
 const data = record.data && typeof record.data ==="object"? record.data : {};
 const raw = record.raw_data && typeof record.raw_data ==="object"? record.raw_data : {};
 if (field in data) return data[field];
 if (field in raw) return raw[field];
 if (field ==="source_url") return record.source_url;
 return"";
}

export function formatDuration(start?: string | null, end?: string | null) {
 if (!start) return"--";
 const started = parseApiDate(start).getTime();
 const finished = end ? parseApiDate(end).getTime() : Date.now();

 if (!Number.isFinite(started) || !Number.isFinite(finished)) return"--";
 const ms = Math.max(0, finished - started);
 const totalSeconds = Math.floor(ms / 1000);
 const m = Math.floor(totalSeconds / 60);
 const s = totalSeconds % 60;
 return `${m}m ${s}s`;
}

export function formatDurationMs(durationMs?: number | null) {
 if (typeof durationMs !=="number"|| !Number.isFinite(durationMs) || durationMs < 0) {
 return null;
 }
 const totalSeconds = Math.floor(durationMs / 1000);
 const m = Math.floor(totalSeconds / 60);
 const s = totalSeconds % 60;
 return `${m}m ${s}s`;
}

export function progressPercent(run: CrawlRun | undefined) {
 const value = typeof run?.result_summary?.progress ==="number"? run.result_summary.progress : 0;
 return Math.min(100, Math.max(0, value));
}

export function extractionVerdict(run: CrawlRun | undefined) {
 const verdict = String(run?.result_summary?.extraction_verdict ??"").trim().toLowerCase();
 return verdict ||"unknown";
}

export function extractionVerdictTone(verdict: string) {
 if (verdict ==="success") return"success";
 if (verdict ==="partial") return"warning";
 if (verdict ==="schema_miss"|| verdict ==="listing_detection_failed"|| verdict ==="empty") return"warning";
 if (verdict ==="blocked"|| verdict ==="proxy_exhausted"|| verdict ==="error") return"danger";
 return"neutral";
}

export function humanizeVerdict(verdict: string) {
 return verdict.replace(/_/g,"").replace(/\b\w/g, (char) => char.toUpperCase());
}

export type QualityLevel ="high"|"medium"|"low"|"unknown";

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

 if (typeof value ==="object") {
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

export function scoreFieldQuality(records: CrawlRecord[], field: string) {
 if (!records.length) {
 return 0;
 }

 let populatedCount = 0;
 let informativeCount = 0;
 for (const record of records) {
 const value = readRecordValue(record, field);
 if (isEmptyCandidateValue(value)) {
 continue;
 }
 populatedCount += 1;
 if (isInformativeValue(value)) {
 informativeCount += 1;
 }
 }

 const populatedRatio = populatedCount / records.length;
 const informativeRatio = informativeCount / records.length;
 let score = populatedRatio * 0.65 + informativeRatio * 0.35;
 if (informativeRatio < 0.2) {
 score = Math.min(score, 0.34);
 }
 return score;
}

export function estimateDataQuality(records: CrawlRecord[], visibleColumns: string[]): QualitySnapshot {
 if (!records.length || !visibleColumns.length) {
 return {
 level:"unknown",
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
 return { level:"high", score, populatedCells, totalCells };
 }
 if (score >= 0.5) {
 return { level:"medium", score, populatedCells, totalCells };
 }
 return { level:"low", score, populatedCells, totalCells };
}

export function qualityTone(level: QualityLevel) {
 if (level ==="high") return"success";
 if (level ==="medium") return"warning";
 if (level ==="low") return"danger";
 return"neutral";
}

export function humanizeQuality(level: QualityLevel) {
 if (level ==="unknown") return"Unknown";
 return level.charAt(0).toUpperCase() + level.slice(1);
}

export function qualityLevelFromScore(score: number): QualityLevel {
 if (!Number.isFinite(score)) return"unknown";
 if (score >= 0.8) return"high";
 if (score >= 0.5) return"medium";
 return"low";
}

export function copyJson(records: CrawlRecord[]) {
 void navigator.clipboard.writeText(JSON.stringify(records.map(cleanRecord), null, 2));
}

export function cleanRecord(record: CrawlRecord) {
 return Object.fromEntries(
 Object.entries(record.data ?? {}).filter(
 ([key, value]) => !key.startsWith("_") && value !== null && value !==""&& !(Array.isArray(value) && value.length === 0),
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
 return (
 <div
 ref={ref}
 className="crawl-terminal min-h-[50vh] max-h-[72vh] space-y-1.5 overflow-y-auto"
 role="log"
 aria-live={live ?"polite":"off"}
 aria-atomic="false"
 >
 {logs.length ? (
 logs.map((log) => (
 <div key={log.id} className="font-mono text-sm leading-6">
 <span className="text-muted">[{formatTimeHms(log.created_at)}]</span>{""}
 <span
 className={cn(
"text-sm font-semibold text-muted uppercase inline-flex items-center px-1.5 py-0.5",
 logTone(log.level),
 )}
 >
 {normalizeLogLevel(log.level)}
 </span>{""}
 <span>{sanitizeLogMessage(log.message)}</span>
 </div>
 ))
 ) : (
 <div className="text-sm leading-[1.55] text-muted">{live ?"Waiting for log output...":"No logs captured for this run."}</div>
 )}
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
 icon: ReactElement<IconElementProps>;
 checked: boolean;
 onChange: (value: boolean) => void;
 children?: ReactNode;
}>) {
 const renderedIcon = React.isValidElement<IconElementProps>(icon)
 ? React.cloneElement(icon, {
 className: cn(icon.props.className,"size-4"),
 })
 : null;

 return (
 <div
 className={cn(
"transition-all",
 checked
 ?"bg-[var(--setting-surface-active-bg)]"
 :"hover:bg-[var(--bg-alt)]/50",
 )}
 >
 <div className="flex items-center justify-between gap-4 px-5 py-3.5">
 <div className="flex min-w-0 items-center gap-3">
 <div
 className={cn(
"flex size-8 shrink-0 items-center justify-center rounded-[var(--radius-md)] border transition-colors",
 checked
 ?"border-[color:color-mix(in_srgb,var(--accent)_22%,transparent)] bg-[var(--setting-icon-active-bg)] text-[var(--accent)] shadow-[var(--setting-icon-active-shadow)]"
 :"border-[var(--border)] bg-[var(--setting-icon-bg)] text-[var(--text-secondary)]",
 )}
 >
 {renderedIcon}
 </div>
 <div className="flex items-center gap-1.5 min-w-0">
 <div className="text-sm font-semibold tracking-[-0.01em] text-primary leading-normal">{label}</div>
 <Tooltip content={description}>
 <Info className="size-3.5 text-muted hover:text-secondary cursor-help transition-colors"/>
 </Tooltip>
 </div>
 </div>
 <PrimitiveToggle checked={checked} onChange={onChange} ariaLabel={label} />
 </div>
 {children ? (
 <div
 className={cn(
"transition-[max-height] duration-200 ease-out",
 checked ?"max-h-[500px] overflow-visible":"max-h-0 overflow-hidden",
 )}
 >
 <div className="border-t border-[var(--divider)] bg-[var(--setting-body-bg)] px-5 py-4 space-y-3">{children}</div>
 </div>
 ) : null}
 </div>
 );
}

export function SliderRow({
 label,
 value,
 min,
 max,
 step,
 onChange,
 onReset,
 suffix,
}: Readonly<{
 label: string;
 value: string;
 min: number;
 max: number;
 step: number;
 onChange: (value: string) => void;
 onReset: () => void;
 suffix?: string;
}>) {
 return (
 <div className="grid grid-cols-[110px_1fr_88px] items-center gap-x-3 py-1">
 <div className="flex items-center gap-1.5 min-w-0">
 <span className="text-sm font-medium text-secondary whitespace-nowrap leading-normal">{label}</span>
 <button
 type="button"
 onClick={onReset}
 aria-label={`Reset ${label}`}
 className="text-muted transition-colors hover:text-primary"
 >
 <RotateCcw className="size-3"aria-hidden="true"/>
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
 <input
 type="text"
 inputMode="numeric"
 value={value}
 onChange={(event) => onChange(event.target.value.replace(/[^\d]/g,""))}
 onBlur={() => onChange(String(clampNumber(value, min, max, min)))}
 className="h-7 w-full rounded-[var(--radius-md)] border border-border bg-[var(--slider-value-bg)] py-0 pl-2.5 pr-8 text-right font-mono text-sm leading-normal tabular-nums text-[var(--text-primary)] focus:ring-0 focus:border-[var(--border-focus)] focus:shadow-[0_0_0_3px_color-mix(in_srgb,var(--accent)_22%,transparent)]"
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
 const chips = uniqueRequestedFields([...fields, ...parseLines(value.replace(/,/g,"\n"))]);
 const [validationHint, setValidationHint] = useState<string | null>(null);

 function commitField(candidate: string) {
 const cleaned = cleanRequestedField(candidate);
 if (!cleaned) {
 return;
 }
 const validationError = validateAdditionalFieldName(cleaned);
 if (validationError) {
 setValidationHint(`Skipped"${cleaned}": ${validationError}`);
 return;
 }
 onCommit(cleaned);
 }

 function handleChange(next: string) {
 const parts = next.split(",");
 parts
 .slice(0, -1)
 .forEach(commitField);
 setValidationHint(null);
 onChange(parts.at(-1) ??"");
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
 className="text-mono-body"
 />
 {validationHint ? <p className="text-sm leading-[1.45] text-danger">{validationHint}</p> : null}
 {chips.length ? (
 <div className="flex flex-wrap gap-1.5">
 {chips.map((field) => (
 <button
 key={field}
 type="button"
 onClick={() => onRemove(field)}
 aria-label={`Remove ${field}`}
 className="inline-flex items-center gap-1 rounded-md border border-[var(--subtle-panel-border)] bg-[var(--subtle-panel-bg)] px-2 py-1 text-sm leading-[1.45] text-[var(--text-secondary)]"
 >
 <X className="size-3.5 shrink-0"aria-hidden="true"/>
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
 messageTone ="warning",
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
 <div className="space-y-2 rounded-md border border-border bg-background p-3">
 <div className="grid gap-2 xl:grid-cols-[24px_minmax(140px,0.8fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,0.8fr)_auto]">
 <div className="hidden items-center justify-center text-muted xl:flex">
 <GripVertical className="size-4"/>
 </div>
 <label className="grid gap-1">
 <span className={cn("field-label", !showLabels &&"sr-only")}>Field</span>
 <Input
 aria-label="Field"
 value={row.fieldName}
 onChange={(event) => onChange({ fieldName: event.target.value })}
 placeholder="price"
 className="text-mono-body"
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
 <div className="flex flex-wrap items-center justify-end gap-2">
 {onTest ? (
 <Button
 type="button"
 variant="secondary"
 size="sm"
 onClick={onTest}
 disabled={testing || testDisabled}
 className="min-w-[72px]"
 >
 {testing ?"Testing...":"Test"}
 </Button>
 ) : null}
 <button
 type="button"
 onClick={onDelete}
 aria-label={`Delete ${row.fieldName ||"manual field"}`}
 className="surface-muted inline-flex size-8 items-center justify-center rounded-[var(--radius-md)] text-danger hover:bg-danger/10"
 >
 <Trash2 className="size-4"/>
 </button>
 </div>
 </div>
 </div>
 {message ? (
 <div
 className={cn(
"alert-surface px-3 py-2 text-sm leading-[1.45]",
 messageTone ==="success"&&"alert-success",
 messageTone ==="warning"&&"alert-warning",
 messageTone ==="danger"&&"alert-danger",
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
 <div className="hidden items-center gap-2 rounded-md border border-border/70 bg-background-elevated px-3 py-2 xl:grid xl:grid-cols-[24px_minmax(140px,0.8fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,0.8fr)_auto]">
 <div />
 <span className="field-label">Field</span>
 <span className="field-label">CSS</span>
 <span className="field-label">XPath</span>
 <span className="field-label">Regex</span>
 <span className="field-label text-right">Actions</span>
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
 <span className={cn("field-label", !showLabel &&"sr-only")}>{label}</span>
 <div className="relative">
 <Input
 aria-label={label}
 value={value}
 onChange={(event) => onChange(event.target.value)}
 onBlur={(event) => onBlur(event.target.value)}
 placeholder={placeholder}
 className="pr-10 text-mono-body"
 />
 <div className="pointer-events-none absolute inset-y-0 right-3 flex items-center">
 {state ==="valid"? <CheckCircle2 className="size-4 text-success"/> : null}
 {state ==="invalid"? <CircleAlert className="size-4 text-danger"/> : null}
 </div>
 </div>
 </label>
 );
}

export const RecordsTable = memo(function RecordsTable({
 records,
 visibleColumns,
 fieldQualityScores,
 selectedIds,
 onSelectAll,
 onToggleRow,
}: Readonly<{
 records: CrawlRecord[];
 visibleColumns: string[];
 fieldQualityScores?: Record<string, number>;
 selectedIds: number[];
 onSelectAll: (checked: boolean) => void;
 onToggleRow: (id: number, checked: boolean) => void;
}>) {
 const rowHeightPx = 40;
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
 if (!containerNode || typeof ResizeObserver ==="undefined") {
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

 return (
 <div
 ref={setContainerRef}
 onScroll={(event) => setScrollTop(event.currentTarget.scrollTop)}
 className="surface-muted max-h-[70vh] rounded-lg overflow-auto"
 >
 <table className="compact-data-table min-w-[960px]">
 <thead>
 <tr>
 <th className="w-10">
 <input
 type="checkbox"
 checked={selectedIds.length === records.length && records.length > 0}
 onChange={(event) => onSelectAll(event.target.checked)}
 />
 </th>
 {visibleColumns.map((col) => {
 const score = fieldQualityScores?.[col];
 const level = qualityLevelFromScore(score ?? Number.NaN);
 return (
 <th key={col}>
 <div className="flex items-center gap-2">
 <span>{col}</span>
 {Number.isFinite(score) ? (
 <Badge tone={qualityTone(level)}>{humanizeQuality(level)}</Badge>
 ) : null}
 </div>
 </th>
 );
 })}
 </tr>
 </thead>
 <tbody>
 {topSpacerPx > 0 ? (
 <tr aria-hidden="true">
 <td colSpan={visibleColumns.length + 1} style={{ height: `${topSpacerPx}px`, padding: 0 }} />
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
 {visibleColumns.map((col) => (
 <td key={col} title={formatCellDisplay(readRecordValue(record, col))}>
 <span className="block max-w-[260px] truncate">
 {formatCellDisplay(readRecordValue(record, col)) || <span className="text-muted/50">--</span>}
 </span>
 </td>
 ))}
 </tr>
 ))}
 {bottomSpacerPx > 0 ? (
 <tr aria-hidden="true">
 <td colSpan={visibleColumns.length + 1} style={{ height: `${bottomSpacerPx}px`, padding: 0 }} />
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
 variant={danger ?"danger":"secondary"}
 size="sm"
 disabled={disabled}
 onClick={onClick}
 className={cn("h-8 min-w-0 px-3", !danger &&"text-sm leading-[1.45]")}
 >
 {label}
 </Button>
 );
}

export function PreviewRow({ label, value, mono }: Readonly<{ label: string; value: ReactNode; mono?: boolean }>) {
 return (
 <div className="surface-muted flex items-start justify-between gap-4 rounded-[var(--radius-md)] px-3 py-2">
 <div className="field-label shrink-0">{label}</div>
 <div className={cn("min-w-0 flex-1 text-right text-sm leading-[1.45] text-foreground", mono &&"font-mono")}>
 {value ||"--"}
 </div>
 </div>
 );
}

function inferRunModule(run?: CrawlRun): CrawlTab | null {
 if (!run) {
 return null;
 }
 const settings = run.settings && typeof run.settings ==="object"? run.settings : {};
 const configuredModule = typeof settings.crawl_module ==="string"? settings.crawl_module :"";
 if (configuredModule ==="category"|| configuredModule ==="pdp") {
 return configuredModule;
 }

 const configuredMode = typeof settings.crawl_mode ==="string"? settings.crawl_mode :"";
 if (configuredMode ==="bulk"|| configuredMode ==="sitemap") {
 return"category";
 }
 if (configuredMode ==="batch"|| configuredMode ==="csv") {
 return"pdp";
 }

 const surface = String(run.surface ||"").toLowerCase();
 if (surface.includes("listing")) {
 return"category";
 }
 if (surface.includes("detail")) {
 return"pdp";
 }

 return null;
}

function validateXPath(value: string): ValidationState {
 if (!value.trim()) return"idle";
 try {
 globalThis.document?.evaluate(value, globalThis.document, null, XPathResult.ANY_TYPE, null);
 return"valid";
 } catch {
 return"invalid";
 }
}

function validateCssSelector(value: string): ValidationState {
 if (!value.trim()) return"idle";
 try {
 globalThis.document?.querySelector(value);
 return"valid";
 } catch {
 return"invalid";
 }
}

function validateRegex(value: string): ValidationState {
 if (!value.trim()) return"idle";
 try {
 new RegExp(value);
 return"valid";
 } catch {
 return"invalid";
 }
}

function logTone(level: string) {
 const normalized = normalizeLogLevel(level);
 if (normalized ==="WARN") return"border-transparent bg-transparent text-warning";
 if (normalized ==="ERROR") return"border-transparent bg-transparent text-danger";
 if (normalized ==="PROXY") return"border-transparent bg-transparent text-accent";
 return"border-transparent bg-transparent text-[var(--text-secondary)]";
}

function normalizeLogLevel(level: string) {
 return String(level ||"").trim().toUpperCase();
}

function sanitizeLogMessage(message: string) {
 return String(message ||"")
 .replace(/\s*\[corr=[^\]]+\]/gi,"")
 .replace(/\s{2,}/g,"")
 .trim();
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

