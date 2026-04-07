"use client";

import {
  CheckCircle2,
  CircleAlert,
  GripVertical,
  RotateCcw,
  Trash2,
  X,
} from "lucide-react";
import { memo, useEffect, useRef } from "react";
import type { ReactNode, RefObject } from "react";

import { Badge, Button, Input, Textarea } from "../ui/primitives";
import type { CrawlRecord, CrawlRun } from "../../lib/api/types";
import { cn } from "../../lib/utils";

export type CrawlTab = "category" | "pdp";
export type CategoryMode = "single" | "sitemap" | "bulk";
export type PdpMode = "single" | "batch" | "csv";
export type ValidationState = "idle" | "valid" | "invalid";
export type FieldRow = {
  id: string;
  fieldName: string;
  xpath: string;
  regex: string;
  xpathState: ValidationState;
  regexState: ValidationState;
};
export type PendingDispatch = {
  runType: "crawl" | "batch" | "csv";
  surface: string;
  url?: string;
  urls?: string[];
  settings: Record<string, unknown>;
  additionalFields: string[];
  csvFile: File | null;
};
export type OutputTabKey = "table" | "json" | "markdown" | "logs";

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

export function uniqueNumbers(values: number[]) {
  return Array.from(new Set(values));
}

export function uniqueStrings(values: string[]) {
  return Array.from(new Set(values.map((value) => value.trim()).filter(Boolean)));
}

export function normalizeField(value: string) {
  return value.trim().toLowerCase().replace(/\s+/g, "_");
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
  return stringifyCell(record.data?.url ?? record.raw_data?.url ?? record.source_url).trim();
}

export function isListingRun(run?: CrawlRun) {
  return inferRunModule(run) === "category";
}

export function stringifyCell(value: unknown) {
  if (value == null) return "";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
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

/**
* Formats a duration between two timestamps into a compact minutes-and-seconds string.
* @example
* formatDuration("2024-01-01T10:00:00Z", "2024-01-01T10:02:15Z")
* "2m 15s"
* @param {string | null | undefined} start - Start timestamp in ISO date string format.
* @param {string | null | undefined} end - End timestamp in ISO date string format; if omitted, uses the current UTC-synced time.
* @returns {string} A formatted duration string like "Xm Ys", or "--" when input timestamps are missing or invalid.
**/
export function formatDuration(start?: string | null, end?: string | null) {
  if (!start) return "--";
  const started = new Date(start).getTime();
  // Ensure we compare apples to apples: backend created_at is UTC. 
  // If we don't have end_at, use a UTC-synced timestamp.
  const finished = end ? new Date(end).getTime() : new Date(new Date().toISOString()).getTime();

  if (!Number.isFinite(started) || !Number.isFinite(finished)) return "--";
  const ms = Math.max(0, finished - started);
  const totalSeconds = Math.floor(ms / 1000);
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

/**
 * Renders a horizontal progress bar with a percentage label.
 * @example
 * ProgressBar({ percent: 75 })
 * <div>...</div>
 * @param {{ percent: number }} props - Component props containing the completion percentage.
 * @returns {JSX.Element} A progress bar UI element showing the current progress.
 */
export function ProgressBar({ percent }: Readonly<{ percent: number }>) {
  return (
    <div className="space-y-1">
      <div className="h-1.5 rounded-full bg-border">
        <div
          className={cn("h-1.5 rounded-full bg-accent transition-all", percent > 90 && "bg-danger")}
          style={{ width: `${percent}%` }}
        />
      </div>
      <div className="text-xs text-muted">{percent}% complete</div>
    </div>
  );
}

/**
 * Renders a scrollable terminal-style log viewer for crawl output.
 * @example
 * LogTerminal({ logs, live, viewportRef })
 * <div>Waiting for log output...</div>
 * @param {{ logs: Array<{ id: number; level: string; message: string; created_at: string }>; live?: boolean; viewportRef?: RefObject<HTMLDivElement | null> }} props - Component props containing log entries, live mode flag, and an optional viewport ref.
 * @returns {JSX.Element} A terminal-like log container displaying formatted log entries or a placeholder message.
 **/
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
      aria-live={live ? "polite" : "off"}
      aria-atomic="false"
    >
      {logs.length ? (
        logs.map((log) => (
          <div key={log.id} className="font-mono text-[12px] leading-6">
            <span className="text-muted">[{formatTimestamp(log.created_at)}]</span>{" "}
            <span
              className={cn(
                "inline-flex items-center px-1.5 py-0.5 text-[10px] font-semibold tracking-[0.08em]",
                logTone(log.level),
              )}
            >
              {normalizeLogLevel(log.level)}
            </span>{" "}
            <span>{log.message}</span>
          </div>
        ))
      ) : (
        <div className="text-sm text-muted">{live ? "Waiting for log output..." : "No logs captured for this run."}</div>
      )}
    </div>
  );
});

/**
 * Renders a segmented tab bar for selecting one of several options.
 * @example
 * TabBar({
 *   value: "daily",
 *   onChange: (nextValue) => console.log(nextValue),
 *   options: [
 *     { value: "daily", label: "Daily" },
 *     { value: "weekly", label: "Weekly" },
 *   ],
 * })
 * // "weekly"
 * @param {{ value: string, onChange: (value: string) => void, options: Array<{ value: string, label: string }> }} props - Tab bar configuration including the current value, change handler, and available options.
 * @returns {JSX.Element} A tab bar element containing selectable buttons for each option.
 **/
export function TabBar({
  value,
  onChange,
  options,
}: Readonly<{
  value: string;
  onChange: (value: string) => void;
  options: Array<{ value: string; label: string }>;
}>) {
  return (
    <div className="inline-flex min-h-[38px] items-center rounded-[var(--radius-lg)] border border-border bg-[var(--segmented-bg)] p-1 shadow-[var(--segmented-shadow)]">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          onClick={() => onChange(option.value)}
          className={cn(
            "rounded-[8px] px-3 py-1.5 text-sm font-medium transition-all",
            value === option.value
              ? "segmented-active"
              : "text-muted hover:bg-[var(--segmented-item-hover-bg)] hover:text-foreground",
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

/**
* Renders a segmented button control for selecting one option from a list.
* @example
* SegmentedMode({ value: "list", onChange: (v) => console.log(v), options: [{ value: "list", label: "List" }] })
* "list"
* @param {Readonly<{ value: string; onChange: (value: string) => void; options: Array<{ value: string; label: string }> }>} props - Component props containing the selected value, change handler, and available options.
* @returns {JSX.Element} A segmented control UI element.
**/
export function SegmentedMode({
  value,
  onChange,
  options,
}: Readonly<{
  value: string;
  onChange: (value: string) => void;
  options: Array<{ value: string; label: string }>;
}>) {
  return (
    <div className="inline-flex min-h-[38px] flex-wrap items-center rounded-[var(--radius-lg)] border border-border bg-[var(--segmented-bg)] p-1 shadow-[var(--segmented-shadow)]">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          onClick={() => onChange(option.value)}
          className={cn(
            "rounded-[8px] px-3 py-1.5 text-sm font-medium transition-all",
            value === option.value
              ? "segmented-active"
              : "text-muted hover:bg-[var(--segmented-item-hover-bg)] hover:text-foreground",
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

/**
 * Renders a two-column mode picker with selectable options and an active state.
 * @example
 * AdvancedModePicker({ value: "mode1", onChange: setMode, options: [{ value: "mode1", label: "Mode 1", description: "Description" }] })
 * undefined
 * @param {Readonly<{ value: string; onChange: (value: string) => void; options: Array<{ value: string; label: string; description: string }> }>} props - Component props containing the current value, change handler, and available options.
 * @returns {JSX.Element} The rendered mode picker UI.
 */
export function AdvancedModePicker({
  value,
  onChange,
  options,
}: Readonly<{
  value: string;
  onChange: (value: string) => void;
  options: Array<{ value: string; label: string; description: string }>;
}>) {
  return (
    <div className="grid grid-cols-2 gap-2">
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            onClick={() => onChange(option.value)}
            className={cn(
              "rounded-[var(--radius-lg)] border px-3 py-2.5 text-left transition-all",
              active
                ? "advanced-picker-active border-[color:var(--accent)] shadow-[var(--shadow-sm)]"
                : "border-border bg-[var(--advanced-picker-bg)] hover:border-[var(--border-strong)] hover:bg-[var(--advanced-picker-hover-bg)]",
            )}
          >
            <div className="flex items-center justify-between gap-3">
              <span className={cn("text-sm font-semibold leading-none", active ? "text-foreground" : "text-[var(--text-secondary)]")}>
                {option.label}
              </span>
              <span
                className={cn(
                  "rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em]",
                  active ? "bg-accent text-[var(--accent-fg)]" : "bg-[var(--bg-elevated)] text-muted",
                )}
              >
                {active ? "Active" : "Mode"}
              </span>
            </div>
            <p className="mt-1.5 text-[11px] leading-4 text-muted">{option.description}</p>
          </button>
        );
      })}
    </div>
  );
}

/**
 * Renders a collapsible settings section with an icon, label, description, and toggle.
 * @example
 * SettingSection({
 *   label: "Notifications",
 *   description: "Enable or disable alerts",
 *   icon: <BellIcon />,
 *   checked: true,
 *   onChange: (value) => console.log(value),
 *   children: <div>Additional settings</div>
 * })
 * returns a settings section UI element
 * @param {object} props - Component props for the settings section.
 * @param {string} props.label - Title text displayed for the setting.
 * @param {string} props.description - Supporting description shown under the label.
 * @param {ReactNode} props.icon - Icon displayed in the section header.
 * @param {boolean} props.checked - Whether the section is enabled and expanded.
 * @param {(value: boolean) => void} props.onChange - Callback invoked when the toggle changes.
 * @param {ReactNode} [props.children] - Optional content shown when the section is expanded.
 * @returns {JSX.Element} The rendered settings section component.
 **/
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
  icon: ReactNode;
  checked: boolean;
  onChange: (value: boolean) => void;
  children?: ReactNode;
}>) {
  return (
    <div
      className={cn(
        "overflow-hidden rounded-[var(--radius-xl)] border backdrop-blur-sm transition-all",
        checked
          ? "border-[color:color-mix(in_srgb,var(--accent)_28%,var(--border))] bg-[var(--setting-surface-active-bg)] shadow-[var(--shadow-sm)]"
          : "border-[var(--border-strong)] bg-[var(--setting-surface-bg)]",
      )}
    >
      <div className="flex min-h-[68px] items-center justify-between gap-3 px-4 py-3">
        <div className="flex min-w-0 items-start gap-3">
          <div
            className={cn(
              "mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-[12px] border transition-colors",
              checked
                ? "border-[color:color-mix(in_srgb,var(--accent)_22%,transparent)] bg-[var(--setting-icon-active-bg)] text-[var(--accent)]"
                : "border-border bg-[var(--setting-icon-bg)] text-[var(--text-secondary)]",
            )}
          >
            {icon}
          </div>
          <div className="min-w-0">
            <div className="text-[12px] font-semibold uppercase tracking-[0.08em] text-[var(--text-primary)]">{label}</div>
            <div className="text-[13px] leading-5 text-[var(--text-secondary)]">{description}</div>
          </div>
        </div>
        <Toggle checked={checked} onChange={onChange} ariaLabel={label} />
      </div>
      {children ? (
        <div
          className={cn(
            "overflow-hidden transition-[max-height] duration-200 ease-out",
            checked ? "max-h-[420px]" : "max-h-0",
          )}
        >
          <div className="border-t border-border/80 bg-[var(--setting-body-bg)] p-2 space-y-2">{children}</div>
        </div>
      ) : null}
    </div>
  );
}

/**
 * Renders a labeled slider input row with a numeric text field, reset control, and optional suffix.
 * @example
 * SliderRow({ label: "Speed", value: "5", min: 0, max: 10, step: 1, onChange: handleChange, onReset: handleReset, suffix: "px" })
 * // returns a slider row UI for editing the speed value
 * @param {Readonly<{ label: string; value: string; min: number; max: number; step: number; onChange: (value: string) => void; onReset: () => void; suffix?: string; }>} props - Component props for configuring the slider row.
 * @returns {JSX.Element} The rendered slider row component.
 **/
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
    <div className="rounded-[var(--radius-lg)] border border-border bg-[var(--slider-row-bg)] px-3 py-1.5 shadow-[var(--slider-row-highlight)]">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <div className="text-[12px] font-semibold text-[var(--text-secondary)]">{label}</div>
          <button type="button" onClick={onReset} aria-label={`Reset ${label}`} className="text-muted hover:text-foreground">
            <RotateCcw className="size-3" />
          </button>
        </div>
        <div className="flex items-center gap-3">
          <input
            type="range"
            min={min}
            max={max}
            step={step}
            value={clampNumber(value, min, max, min)}
            onChange={(event) => onChange(event.target.value)}
            className="slider-control w-28"
          />
          <div className="relative">
            <Input
              value={value}
              onChange={(event) => onChange(event.target.value.replace(/[^\d]/g, ""))}
              onBlur={() => onChange(String(clampNumber(value, min, max, min)))}
              className="h-7 w-16 rounded-[var(--radius-md)] border-none bg-transparent pr-5 text-right font-mono text-[12px] tabular-nums text-[var(--accent)] focus:ring-0"
            />
            <span className="pointer-events-none absolute right-0 top-1/2 -translate-y-1/2 text-[10px] lowercase text-[var(--accent)] opacity-60">
              {suffix ?? ""}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * Renders an input for managing a comma-separated list of additional fields, with removable field chips and commit-on-blur behavior.
 * @example
 * AdditionalFieldInput({
 *   value: "price, sku",
 *   fields: ["brand"],
 *   onChange: (value) => console.log(value),
 *   onCommit: (value) => console.log("commit", value),
 *   onRemove: (value) => console.log("remove", value),
 * })
 * @param {Readonly<{ value: string; fields: string[]; onChange: (value: string) => void; onCommit: (value: string) => void; onRemove: (value: string) => void; }>} props - Component props containing the current input value, existing fields, and change/commit/remove handlers.
 * @returns {JSX.Element} The rendered additional fields input UI.
 */
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
  const chips = uniqueFields([...fields, ...parseLines(value.replace(/,/g, "\n"))]);

  function handleChange(next: string) {
    const parts = next.split(",");
    parts
      .slice(0, -1)
      .map((part) => normalizeField(part))
      .filter(Boolean)
      .forEach(onCommit);
    onChange(parts.at(-1) ?? "");
  }

  function handleBlur() {
    parseLines(value).map(normalizeField).filter(Boolean).forEach(onCommit);
    onChange("");
  }

  return (
    <label className="grid gap-1.5">
      <span className="label-caps">Additional Fields</span>
      <Input
        value={value}
        onChange={(event) => handleChange(event.target.value)}
        onBlur={handleBlur}
        placeholder="price, sku, availability, brand"
        className="font-mono text-sm"
      />
      {chips.length ? (
        <div className="flex flex-wrap gap-1.5">
          {chips.map((field) => (
            <button
              key={field}
              type="button"
              onClick={() => onRemove(field)}
              aria-label={`Remove ${field}`}
              className="inline-flex items-center gap-1 rounded-md border border-border bg-panel px-2 py-1 text-xs"
            >
              <span>{field}</span>
              <X className="size-3.5" aria-hidden="true" />
            </button>
          ))}
        </div>
      ) : null}
    </label>
  );
}

/**
 * Renders an editable manual field row with inputs for field name, XPath, and regex, plus delete action.
 * @example
 * ManualFieldEditor({ row, onChange, onDelete })
 * undefined
 * @param {{ row: FieldRow; onChange: (patch: Partial<FieldRow>) => void; onDelete: () => void; }} props - Component props containing the field row data and callbacks for updates and deletion.
 * @returns {JSX.Element} The rendered manual field editor UI.
 */
export function ManualFieldEditor({
  row,
  onChange,
  onDelete,
}: Readonly<{
  row: FieldRow;
  onChange: (patch: Partial<FieldRow>) => void;
  onDelete: () => void;
}>) {
  return (
    <div className="grid gap-2 rounded-md border border-border bg-background p-3 xl:grid-cols-[24px_minmax(160px,0.8fr)_minmax(240px,1fr)_minmax(200px,1fr)_auto]">
      <div className="flex items-center justify-center text-muted">
        <GripVertical className="size-4" />
      </div>
      <label className="grid gap-1">
        <span className="label-caps">Field</span>
        <Input value={row.fieldName} onChange={(event) => onChange({ fieldName: event.target.value })} placeholder="price" className="font-mono text-sm" />
      </label>
      <ValidatedField
        label="XPath"
        value={row.xpath}
        state={row.xpathState}
        placeholder="//span[@class='price']"
        onChange={(value) => onChange({ xpath: value })}
        onBlur={(value) => onChange({ xpathState: validateXPath(value) })}
      />
      <ValidatedField
        label="Regex"
        value={row.regex}
        state={row.regexState}
        placeholder="\\$[\\d,.]+"
        onChange={(value) => onChange({ regex: value })}
        onBlur={(value) => onChange({ regexState: validateRegex(value) })}
      />
      <div className="flex items-end justify-end">
        <button
          type="button"
          onClick={onDelete}
          aria-label={`Delete ${row.fieldName || "manual field"}`}
          className="inline-flex size-8 items-center justify-center rounded-[var(--radius-md)] border border-border text-danger hover:bg-danger/10"
        >
          <Trash2 className="size-3.5" aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}

/**
 * Renders a selectable table of crawl records with dynamically visible columns.
 * @example
 * RecordsTable({
 *   records: [],
 *   visibleColumns: ['id', 'url'],
 *   selectedIds: [],
 *   onSelectAll: (checked) => {},
 *   onToggleRow: (id, checked) => {},
 * })
 * undefined
 * @param {Readonly<{records: CrawlRecord[], visibleColumns: string[], selectedIds: number[], onSelectAll: (checked: boolean) => void, onToggleRow: (id: number, checked: boolean) => void}>} props - Table data, column visibility, selection state, and selection handlers.
 * @returns {JSX.Element} A table element displaying the provided records with row and select-all checkboxes.
 **/
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
  return (
    <div className="overflow-auto rounded-[10px] border border-border">
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
            {visibleColumns.map((col) => (
              <th key={col}>{col}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {records.map((record) => (
            <tr key={record.id}>
              <td>
                <input
                  type="checkbox"
                  checked={selectedIds.includes(record.id)}
                  onChange={(event) => onToggleRow(record.id, event.target.checked)}
                />
              </td>
              {visibleColumns.map((col) => (
                <td key={col} title={stringifyCell(readRecordValue(record, col))}>
                  <span className="block max-w-[260px] truncate">
                    {stringifyCell(readRecordValue(record, col)) || <span className="text-muted/50">--</span>}
                  </span>
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
});

/**
 * Renders a small action button with optional danger and disabled states.
 * @example
 * ActionButton({ label: "Delete", danger: true, onClick: () => {} })
 * <Button />
 * @param {{ label: string; danger?: boolean; disabled?: boolean; onClick?: () => void }} props - Button configuration and click handler.
 * @returns {JSX.Element} The rendered button element.
 */
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
      disabled={disabled}
      onClick={onClick}
      className="h-8 px-3 text-xs"
    >
      {label}
    </Button>
  );
}

/**
 * Renders a clickable tab button with active and inactive visual states.
 * @example
 * OutputTab({ active: true, children: "Output", onClick: () => {} })
 * <button>Output</button>
 * @param {{ active?: boolean; children: ReactNode; onClick: () => void }} props - Tab properties including active state, content, and click handler.
 * @returns {JSX.Element} A button element representing the output tab.
 **/
export function OutputTab({
  active = false,
  children,
  onClick,
}: Readonly<{ active?: boolean; children: ReactNode; onClick: () => void }>) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "relative px-4 py-2 text-sm font-medium transition-colors",
        active ? "text-[var(--text-primary)] after:absolute after:inset-x-0 after:bottom-0 after:h-0.5 after:bg-accent" : "text-[var(--text-muted)] hover:text-[var(--text-secondary)]",
      )}
    >
      {children}
    </button>
  );
}

export function PreviewRow({ label, value, mono }: Readonly<{ label: string; value: ReactNode; mono?: boolean }>) {
  return (
    <div className="flex items-start justify-between gap-4 rounded-[var(--radius-md)] border border-border bg-panel px-3 py-2">
      <div className="shrink-0 label-caps">{label}</div>
      <div className={cn("min-w-0 max-w-[65%] overflow-hidden break-all text-right text-sm text-[var(--text-secondary)]", mono && "font-mono text-xs")}>
        {value || "--"}
      </div>
    </div>
  );
}

/**
* Infers the crawl tab/module from a run's settings, mode, or surface.
* @example
* inferRunModule(run)
* "category"
* @param {CrawlRun | undefined} run - Crawl run data used to determine the module.
* @returns {CrawlTab | null} The inferred crawl tab, or null if it cannot be determined.
**/
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
    document.evaluate(value, document, null, XPathResult.ANY_TYPE, null);
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
  if (normalized === "WARN") return "border-transparent bg-transparent text-warning";
  if (normalized === "ERROR") return "border-transparent bg-transparent text-danger";
  if (normalized === "PROXY") return "border-transparent bg-transparent text-accent";
  return "border-transparent bg-transparent text-[var(--text-secondary)]";
}

function normalizeLogLevel(level: string) {
  return String(level || "").trim().toUpperCase();
}

function useLogViewport(_logCount: number, ref?: RefObject<HTMLDivElement | null>) {
  const internalRef = useRef<HTMLDivElement | null>(null);
  const targetRef = ref ?? internalRef;

  useEffect(() => {
    scrollViewportToBottom(targetRef);
  }, [_logCount, targetRef]);

  return targetRef;
}

function getFocusableElements(container: HTMLDivElement | null) {
  if (!container) {
    return [] as HTMLElement[];
  }
  return Array.from(
    container.querySelectorAll<HTMLElement>(
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ),
  ).filter((element) => !element.hasAttribute("hidden") && element.getAttribute("aria-hidden") !== "true");
}

/**
* Renders an accessible toggle button that switches between checked and unchecked states.
* @example
* Toggle({ checked: true, onChange: (value) => console.log(value), ariaLabel: "Enable feature" })
* void
* @param {{ checked: boolean; onChange: (value: boolean) => void; ariaLabel?: string }} Argument - Toggle props including current state, change handler, and optional aria label.
* @returns {JSX.Element} A button element representing the toggle control.
**/
function Toggle({
  checked,
  onChange,
  ariaLabel,
}: Readonly<{ checked: boolean; onChange: (value: boolean) => void; ariaLabel?: string }>) {
  return (
    <button
      type="button"
      aria-label={ariaLabel}
      aria-pressed={checked}
      onClick={() => onChange(!checked)}
      className={cn("relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors", checked ? "bg-accent" : "bg-border")}
    >
      <span
        className={cn(
          "inline-block size-4 rounded-full shadow-sm transition-transform",
          checked ? "translate-x-4 bg-[var(--accent-fg)]" : "translate-x-0.5 bg-[var(--bg-panel-strong)]",
        )}
      />
    </button>
  );
}

/**
 * Renders a labeled input field with validation state feedback.
 * @example
 * ValidatedField({
 *   label: "Email",
 *   value: "user@example.com",
 *   state: "valid",
 *   placeholder: "Enter your email",
 *   onChange: (value) => console.log(value),
 *   onBlur: (value) => console.log(value),
 * })
 * @param {{ label: string, value: string, state: ValidationState, placeholder: string, onChange: (value: string) => void, onBlur: (value: string) => void }} props - Props for configuring the validated field input.
 * @returns {JSX.Element} A labeled input element that displays validation icons based on the current state.
 **/
function ValidatedField({
  label,
  value,
  state,
  placeholder,
  onChange,
  onBlur,
}: Readonly<{
  label: string;
  value: string;
  state: ValidationState;
  placeholder: string;
  onChange: (value: string) => void;
  onBlur: (value: string) => void;
}>) {
  return (
    <label className="grid gap-1">
      <span className="label-caps">{label}</span>
      <div className="relative">
        <Input
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onBlur={(event) => onBlur(event.target.value)}
          placeholder={placeholder}
          className="pr-10 font-mono text-sm"
        />
        <div className="pointer-events-none absolute inset-y-0 right-3 flex items-center">
          {state === "valid" ? <CheckCircle2 className="size-4 text-success" /> : null}
          {state === "invalid" ? <CircleAlert className="size-4 text-danger" /> : null}
        </div>
      </div>
    </label>
  );
}

function formatTimestamp(value: string) {
  try {
    return new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return value;
  }
}
