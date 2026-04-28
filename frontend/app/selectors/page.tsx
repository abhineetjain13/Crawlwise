"use client";

import { AlertCircle, Check, CheckCircle2, Plus, Search, Sparkles, Trash2 } from"lucide-react";
import { useState } from"react";

import { EmptyPanel, InlineAlert, PageHeader, SectionCard } from"../../components/ui/patterns";
import { Badge, Button, Dropdown, Input, Textarea } from"../../components/ui/primitives";
import { api } from"../../lib/api";
import { httpErrorStatus } from"../../lib/api/client";
import type {
 SelectorCreatePayload,
 SelectorRecord,
 SelectorSuggestion,
} from"../../lib/api/types";
import { getNormalizedDomain } from"../../lib/format/domain";
import { cn } from"../../lib/utils";

type SelectorKind ="xpath"|"css_selector"|"regex";
type RowState ="idle"|"accepted"|"saved";
type StatusTone ="success"|"warning"|"danger";

type SelectorRow = {
 key: string;
 selectorId: number | null;
 surface: string | null;
 fieldName: string;
 kind: SelectorKind;
 selectorValue: string;
 extractedValue: string;
 source: string;
 state: RowState;
};

type RowMessage = {
 tone: StatusTone;
 message: string;
};

export default function SelectorsPage() {
 const [url, setUrl] = useState("");
 const [loadedUrl, setLoadedUrl] = useState("");
 const [previewUrl, setPreviewUrl] = useState("");
 const [resolvedSurface, setResolvedSurface] = useState("generic");
 const [iframePromoted, setIframePromoted] = useState(false);
 const [expectedColumns, setExpectedColumns] = useState("");
 const [rows, setRows] = useState<SelectorRow[]>([]);
 const [rowMessages, setRowMessages] = useState<Record<string, RowMessage>>({});
 const [loadError, setLoadError] = useState("");
 const [loadingSuggestions, setLoadingSuggestions] = useState(false);
 const [savingAccepted, setSavingAccepted] = useState(false);
 const [activeTestKey, setActiveTestKey] = useState<string | null>(null);
 const [activeDetectKey, setActiveDetectKey] = useState<string | null>(null);

 const parsedColumns = parseExpectedColumns(expectedColumns);
 const domain = getNormalizedDomain(loadedUrl);

 async function loadPageAndSuggestions() {
 const targetUrl = url.trim();
 if (!targetUrl) {
 setLoadError("Enter a page URL.");
 return;
 }
 if (!parsedColumns.length) {
 setLoadError("Enter at least one expected column.");
 return;
 }
 setLoadError("");
 setLoadingSuggestions(true);
 try {
 const response = await api.suggestSelectors({
 url: targetUrl,
 expected_columns: parsedColumns,
 });
 const previewTargetUrl = response.preview_url || targetUrl;
 const nextSurface = response.surface || inferSelectorSurface(parsedColumns, targetUrl);
 const selectorDomain =
 getNormalizedDomain(previewTargetUrl) || getNormalizedDomain(targetUrl);
 const savedRecords = selectorDomain
 ? await api.listSelectors({ domain: selectorDomain, surface: nextSurface })
 : [];
 const savedRows = selectRelevantSelectorRecords(savedRecords, nextSurface).map(
 buildRowFromSelectorRecord,
 );
 const suggestedRows = parsedColumns.map((field) => {
 const suggestion = response.suggestions[field]?.[0];
 return buildRowFromSuggestion(field, suggestion, nextSurface);
 });
 setLoadedUrl(previewTargetUrl);
 setPreviewUrl(api.selectorPreviewHtml(previewTargetUrl));
 setResolvedSurface(nextSurface);
 setIframePromoted(Boolean(response.iframe_promoted));
 setRows(mergeSelectorRows(savedRows, suggestedRows));
 setRowMessages({});
 } catch (error) {
 setLoadError(error instanceof Error ? error.message :"Unable to load selector suggestions.");
 } finally {
 setLoadingSuggestions(false);
 }
 }

 function updateRow(key: string, patch: Partial<SelectorRow>) {
 setRows((current) => current.map((row) => (row.key === key ? { ...row, ...patch } : row)));
 }

 function addFieldRow() {
 setRows((current) => [...current, createEmptyRow()]);
 }

 function removeFieldRow(key: string) {
 setRows((current) => current.filter((row) => row.key !== key));
 setRowMessages((current) => {
 const next = { ...current };
 delete next[key];
 return next;
 });
 }

 async function redetectRow(row: SelectorRow) {
 if (!loadedUrl || !row.fieldName.trim()) {
 setRowMessages((current) => ({
 ...current,
 [row.key]: { tone:"warning", message:"Load a URL and enter a field name first."},
 }));
 return;
 }
 setActiveDetectKey(row.key);
 try {
 const response = await api.suggestSelectors({
 url: loadedUrl,
 expected_columns: [normalizeField(row.fieldName)],
 });
 const suggestion = response.suggestions[normalizeField(row.fieldName)]?.[0];
 if (!suggestion) {
 setRowMessages((current) => ({
 ...current,
 [row.key]: { tone:"warning", message:"No selector suggestion found for this field."},
 }));
 return;
 }
 const next = buildRowFromSuggestion(row.fieldName, suggestion, row.surface ?? resolvedSurface);
 updateRow(row.key, {
 kind: next.kind,
 selectorValue: next.selectorValue,
 extractedValue: next.extractedValue,
 source: next.source,
 state:"idle",
 });
 setRowMessages((current) => ({ ...current,
 [row.key]: { tone:"success", message:"Suggested selector refreshed."},
 }));
 } catch (error) {
 setRowMessages((current) => ({
 ...current,
 [row.key]: { tone:"danger", message: error instanceof Error ? error.message :"Auto-detect failed."},
 }));
 } finally {
 setActiveDetectKey(null);
 }
 }

 async function testRow(row: SelectorRow) {
 if (!loadedUrl || !row.selectorValue.trim()) {
 setRowMessages((current) => ({
 ...current,
 [row.key]: { tone:"warning", message:"Load a URL and enter a selector to test."},
 }));
 return;
 }
 setActiveTestKey(row.key);
 try {
 const response = await api.testSelector({
 url: loadedUrl,
 xpath: row.kind ==="xpath"? row.selectorValue.trim() : undefined,
 css_selector: row.kind ==="css_selector"? row.selectorValue.trim() : undefined,
 regex: row.kind ==="regex"? row.selectorValue.trim() : undefined,
 });
 updateRow(row.key, {
 extractedValue: response.matched_value ??"",
 });
 setRowMessages((current) => ({
 ...current,
 [row.key]: {
 tone: response.count > 0 ?"success":"warning",
 message: formatSelectorMatchMessage(response.count),
 },
 }));
 } catch (error) {
 setRowMessages((current) => ({
 ...current,
 [row.key]: { tone:"danger", message: error instanceof Error ? error.message :"Selector test failed."},
 }));
 } finally {
 setActiveTestKey(null);
 }
 }

 async function saveAcceptedRows() {
 const acceptedRows = rows.filter((row) => row.state ==="accepted"&& row.fieldName.trim() && row.selectorValue.trim());
 if (!acceptedRows.length || !domain) {
 setLoadError("Accept at least one selector row before saving.");
 return;
 }
 setSavingAccepted(true);
 setLoadError("");
 const failedFields: string[] = [];
 try {
 const existingRecords = selectRelevantSelectorRecords(
 await api.listSelectors({ domain, surface: resolvedSurface }),
 resolvedSurface,
 );
 const existingByField = new Map(
 existingRecords.map((record) => [normalizeField(record.field_name), record] as const),
 );
 const settled = await Promise.allSettled(
 acceptedRows.map(async (row) => {
 const fieldName = normalizeField(row.fieldName);
 const payload: SelectorCreatePayload = {
 domain,
 surface: resolvedSurface,
 field_name: fieldName,
 xpath: row.kind ==="xpath"? row.selectorValue.trim() : undefined,
 css_selector: row.kind ==="css_selector"? row.selectorValue.trim() : undefined,
 regex: row.kind ==="regex"? row.selectorValue.trim() : undefined,
 sample_value: row.extractedValue.trim() || undefined,
 source: row.source || selectorSource(row.kind),
 status:"validated",
 is_active: true,
 };
 const existing = row.selectorId ? { id: row.selectorId } : existingByField.get(fieldName);
 if (existing) {
 const updated = await api.updateSelector(existing.id, payload);
 return { key: row.key, selectorId: updated.id };
 }
 try {
 const created = await api.createSelector(payload);
 existingByField.set(fieldName, created);
 return { key: row.key, selectorId: created.id };
 } catch (error) {
 if (!isDuplicateSelectorError(error)) {
 throw error;
 }
 const duplicateRecord =
 existingByField.get(fieldName)
 ?? selectRelevantSelectorRecords(
 await api.listSelectors({ domain, surface: resolvedSurface }),
 resolvedSurface,
 ).find((record) => normalizeField(record.field_name) === fieldName);
 if (!duplicateRecord) {
 throw error;
 }
 existingByField.set(fieldName, duplicateRecord);
 const updated = await api.updateSelector(duplicateRecord.id, payload);
 return { key: row.key, selectorId: updated.id };
 }
 }),
 );
 const savedRows = new Map<string, number>();
 const nextMessages: Record<string, RowMessage> = {};
 settled.forEach((result, index) => {
 const row = acceptedRows[index];
 if (result.status ==="fulfilled") {
 savedRows.set(result.value.key, result.value.selectorId);
 return;
 }
 failedFields.push(row.fieldName.trim() || row.key);
 nextMessages[row.key] = {
 tone:"danger",
 message: result.reason instanceof Error ? result.reason.message :"Unable to save selector.",
 };
 });
 if (savedRows.size) {
 setRows((current) =>
 current.map((entry) =>
 savedRows.has(entry.key)
 ? {
 ...entry,
 selectorId: savedRows.get(entry.key) ?? entry.selectorId,
 surface: resolvedSurface,
 state:"saved",
 }
 : entry,
 ),
 );
 }
 setRowMessages((current) => {
 const remainingMessages = Object.fromEntries(
 Object.entries(current).filter(([key]) => !savedRows.has(key)),
 ) as Record<string, RowMessage>;
 return {
 ...remainingMessages,
 ...nextMessages,
 };
 });
 } finally {
 setSavingAccepted(false);
 }
 if (failedFields.length) {
 setLoadError(`Unable to save ${failedFields.join(", ")}. Saved rows stay marked as saved; failed rows remain accepted for retry.`);
 } }

 return (
 <div className="page-stack">
 <PageHeader title="CSS / XPath Selector"/>

 <SectionCard title="Selector Inputs"description="Enter a page URL and expected column names, then let the LLM suggest selectors for each field.">
 <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(280px,0.8fr)_auto] xl:items-end">
 <label className="grid gap-1.5">
 <span className="field-label">Page URL</span>
 <Input
 value={url}
 onChange={(event) => setUrl(event.target.value)}
 placeholder="https://example.com/products/oak-chair"
 className="font-mono text-sm leading-[var(--leading-relaxed)]"
 />
 </label>
 <label className="grid gap-1.5">
 <span className="field-label">Expected Columns</span>
 <Textarea
 value={expectedColumns}
 onChange={(event) => setExpectedColumns(event.target.value)}
 placeholder="price, sku, availability, brand"
 className="min-h-[80px] text-sm leading-[var(--leading-relaxed)]"
 />
 </label>
 <Button type="button"variant="accent"onClick={() => void loadPageAndSuggestions()} disabled={loadingSuggestions}>
 <Sparkles className="size-3.5"/>
 {loadingSuggestions ?"Loading...":"Load Page"}
 </Button>
 </div>
 {loadError ? <InlineAlert message={loadError} /> : null}
 </SectionCard>

 <div className="grid gap-4 xl:grid-cols-[minmax(0,1.05fr)_minmax(420px,0.95fr)]">
 <SectionCard title="Page Preview"description={loadedUrl ||"Load a page to preview its DOM context."}action={loadedUrl ? <div className="flex items-center gap-2"><Badge tone="info">{resolvedSurface}</Badge>{iframePromoted ? <Badge tone="warning">iframe promoted</Badge> : null}</div> : null}>
 <div className="bg-panel rounded-xl shadow-card backdrop-blur-md overflow-hidden p-0">
 {previewUrl ? (
 <iframe
 key={previewUrl}
 src={previewUrl}
 title="Selector page preview"
 className="h-[760px] w-full bg-panel"
 loading="lazy"
 referrerPolicy="no-referrer"
 sandbox="allow-same-origin"
 />
 ) : (
 <div className="grid h-[760px] place-items-center text-sm leading-[var(--leading-relaxed)] text-muted">
 No page loaded.
 </div>
 )}
 </div>
 </SectionCard>

 <SectionCard title="Field Rows"description="Review LLM suggestions, edit selectors manually, test arbitrary XPath/CSS/regex, then accept the rows you want to save."action={<Button type="button"variant="ghost"onClick={addFieldRow}><Plus className="size-3.5"/>Add Field</Button>}>

 {rows.length ? (
 <div className="space-y-3">
 {rows.map((row) => {
 const message = rowMessages[row.key];
 const selectorInputId = `selector-value-${row.key}`;
 return (
 <div key={row.key} className="rounded-[var(--radius-lg)] border border-border bg-background-elevated p-4">
 <div className="grid gap-3">
 <div className="grid gap-3 xl:grid-cols-[150px_120px_minmax(0,1fr)_auto]">
 <label className="grid gap-1">
 <span className="field-label">Field Name</span>
 <Input
 value={row.fieldName}
 onChange={(event) => updateRow(row.key, { fieldName: event.target.value, state: nextEditedState(row.state) })}
 placeholder="price"
 />
 </label>

 <label className="grid gap-1">
 <span className="field-label">Type</span>
 <Dropdown<SelectorKind>
 value={row.kind}
 onChange={(kind) => updateRow(row.key, { kind, state: nextEditedState(row.state) })}
 options={[
 { value:"xpath", label:"XPath"},
 { value:"css_selector", label:"CSS"},
 { value:"regex", label:"Regex"},
 ]}
 />
 </label>

 <label className="grid gap-1"htmlFor={selectorInputId}>
 <span className="field-label">XPath / CSS / Regex</span>
 <div className="relative">
 <Input
 id={selectorInputId}
 value={row.selectorValue}
 onChange={(event) => updateRow(row.key, { selectorValue: event.target.value, state: nextEditedState(row.state) })}
 placeholder={selectorPlaceholder(row.kind)}
 className="pr-10 font-mono text-sm leading-[var(--leading-relaxed)]"
 />
 <div className="pointer-events-none absolute inset-y-0 right-3 flex items-center">
 {row.selectorValue.trim() ? <CheckCircle2 className="size-4 text-success"/> : <AlertCircle className="size-4 text-muted"/>}
 </div>
 </div>
 </label>

 <div className="flex items-end justify-end">
 <Button
 type="button"
 variant="danger"
 size="icon"
 onClick={() => removeFieldRow(row.key)}
 className="size-8"
 aria-label="Delete field row"
 >
 <Trash2 className="size-3.5"/>
 </Button>
 </div>
 </div>

 <label className="grid gap-1">
 <span className="field-label">Extracted Value Preview</span>
 <Input
 value={row.extractedValue}
 onChange={(event) => updateRow(row.key, { extractedValue: event.target.value })}
 placeholder="Extracted value"
 className="font-mono text-sm leading-[var(--leading-relaxed)]"
 />
 </label>

 <div className="flex flex-wrap items-center gap-2">
 <Button type="button"variant="secondary"onClick={() => void redetectRow(row)} disabled={activeDetectKey === row.key}>
 <Sparkles className="size-3.5"/>
 {activeDetectKey === row.key ?"Detecting...":"Auto-detect"}
 </Button>
 <Button type="button"variant="secondary"onClick={() => void testRow(row)} disabled={activeTestKey === row.key}>
 <Search className="size-3.5"/>
 {activeTestKey === row.key ?"Testing...":"Test"}
 </Button>
 <Button
 type="button"
 variant={row.state ==="accepted"|| row.state ==="saved"?"secondary":"ghost"}
 onClick={() => updateRow(row.key, { state: nextSelectorRowState(row.state) })}
 disabled={row.state ==="saved"}
 >
 <Check className="size-3.5"/>
 {selectorStateLabel(row.state)}
 </Button>
 <Badge tone={selectorStateTone(row.state)}>
 {row.state}
 </Badge>
 </div>

 {message ? (
 <div
 className={cn(
"alert-surface",
 message.tone ==="success"&&"alert-success",
 message.tone ==="warning"&&"alert-warning",
 message.tone ==="danger"&&"alert-danger",
 )}
 >
 {message.message}
 </div>
 ) : null}
 </div>
 </div>
 );
 })}
 </div>
 ) : (
 <EmptyPanel title="No field rows yet"description="Load a page with expected columns to generate LLM suggestions."/>
 )}

 <div className="flex justify-end border-t border-border pt-4">
 <Button type="button"variant="accent"onClick={() => void saveAcceptedRows()} disabled={savingAccepted || !rows.some((row) => row.state ==="accepted")}>
 <Check className="size-3.5"/>
 {savingAccepted ?"Saving...":"Save Accepted Selectors"}
 </Button>
 </div>
 </SectionCard>
 </div>
 </div>
 );
}

function parseExpectedColumns(value: string) {
 return Array.from(
 new Set(
 value
 .split(/[\n,]/)
 .map((item) => normalizeField(item))
 .filter(Boolean),
 ),
 );
}

function selectorPlaceholder(kind: SelectorKind) {
 if (kind ==="xpath") return"//span[@class='price']";
 if (kind ==="css_selector") return".price";
 return"\\$[\\d,.]+";
}

function selectorSource(kind: SelectorKind) {
 if (kind ==="xpath") return"llm_xpath";
 if (kind ==="css_selector") return"llm_css";
 return"llm_regex";
}

function formatSelectorMatchMessage(count: number) {
 if (count <= 0) {
 return"No matches.";
 }
 const suffix = count === 1 ?"":"s";
 return `Matched ${count} result${suffix}.`;
}

function nextSelectorRowState(state: RowState): RowState {
 if (state ==="saved") return"saved";
 if (state ==="accepted") return"idle";
 return"accepted";
}

function selectorStateLabel(state: RowState) {
 if (state ==="saved") return"Saved";
 if (state ==="accepted") return"Accepted";
 return"Accept";
}

function selectorStateTone(state: RowState) {
 if (state ==="saved") return"success"as const;
 if (state ==="accepted") return"warning"as const;
 return"neutral"as const;
}

function nextEditedState(state: RowState): RowState {
 if (state ==="saved") return"accepted";
 if (state ==="idle") return"idle";
 return state;
}

export function selectRelevantSelectorRecords(
 records: SelectorRecord[],
 surface: string,
) {
 return records
 .filter(
 (record) =>
 record.is_active &&
 (record.surface === surface || record.surface ==="generic"),
 )
 .sort((left, right) => {
 const leftPriority = left.surface === surface ? 0 : 1;
 const rightPriority = right.surface === surface ? 0 : 1;
 if (leftPriority !== rightPriority) {
 return leftPriority - rightPriority;
 }
 return `${left.field_name}:${left.id}`.localeCompare(
 `${right.field_name}:${right.id}`,
 );
 });
}

function buildRowFromSelectorRecord(record: SelectorRecord): SelectorRow {
 if (record.xpath) {
 return {
 key: `selector:${record.id}`,
 selectorId: record.id,
 surface: record.surface,
 fieldName: record.field_name,
 kind:"xpath",
 selectorValue: record.xpath,
 extractedValue: record.sample_value ||"",
 source: record.source ||"domain_memory",
 state:"saved",
 };
 }
 if (record.css_selector) {
 return {
 key: `selector:${record.id}`,
 selectorId: record.id,
 surface: record.surface,
 fieldName: record.field_name,
 kind:"css_selector",
 selectorValue: record.css_selector,
 extractedValue: record.sample_value ||"",
 source: record.source ||"domain_memory",
 state:"saved",
 };
 }
 return {
 key: `selector:${record.id}`,
 selectorId: record.id,
 surface: record.surface,
 fieldName: record.field_name,
 kind:"regex",
 selectorValue: record.regex ||"",
 extractedValue: record.sample_value ||"",
 source: record.source ||"domain_memory",
 state:"saved",
 };
}

function buildRowFromSuggestion(
 fieldName: string,
 suggestion?: SelectorSuggestion,
 surface?: string | null,
): SelectorRow {
 if (suggestion?.xpath) {
 return {
 key: createRowKey(),
 selectorId: null,
 surface: surface ?? null,
 fieldName,
 kind:"xpath",
 selectorValue: suggestion.xpath,
 extractedValue: suggestion.sample_value ||"",
 source: suggestion.source ||"llm_xpath",
 state:"idle",
 };
 }
 if (suggestion?.css_selector) {
 return {
 key: createRowKey(),
 selectorId: null,
 surface: surface ?? null,
 fieldName,
 kind:"css_selector",
 selectorValue: suggestion.css_selector,
 extractedValue: suggestion.sample_value ||"",
 source: suggestion.source ||"llm_css",
 state:"idle",
 };
 }
 if (suggestion?.regex) {
 return {
 key: createRowKey(),
 selectorId: null,
 surface: surface ?? null,
 fieldName,
 kind:"regex",
 selectorValue: suggestion.regex,
 extractedValue: suggestion.sample_value ||"",
 source: suggestion.source ||"llm_regex",
 state:"idle",
 };
 }
 return {
 key: createRowKey(),
 selectorId: null,
 surface: surface ?? null,
 fieldName,
 kind:"xpath",
 selectorValue:"",
 extractedValue:"",
 source:"manual",
 state:"idle",
 };
}

function createEmptyRow(): SelectorRow {
 return {
 key: createRowKey(),
 selectorId: null,
 surface: null,
 fieldName:"",
 kind:"xpath",
 selectorValue:"",
 extractedValue:"",
 source:"manual",
 state:"idle",
 };
}

function createRowKey() {
 return `selector:${Date.now()}:${Math.random().toString(36).slice(2, 8)}`;
}

function normalizeField(value: string) {
 return value.trim().toLowerCase().replace(/\s+/g,"_");
}

export function inferSelectorSurface(fields: string[], url: string) {
 const normalized = new Set(fields.map((field) => normalizeField(field)));
 if (["company","location","apply_url","salary","remote"].some((field) => normalized.has(field))) {
 return"job_detail";
 }
 if (String(url).toLowerCase().includes("jobs")) {
 return"job_detail";
 }
 return"ecommerce_detail";
}

export function mergeSelectorRows(
 currentRows: SelectorRow[],
 incomingRows: SelectorRow[],
 options?: { preferIncoming?: boolean },
) {
 const merged = new Map<string, SelectorRow>();
 const preferIncoming = Boolean(options?.preferIncoming);
 for (const row of currentRows) {
 merged.set(normalizeField(row.fieldName || row.key), row);
 }
 for (const row of incomingRows) {
 const key = normalizeField(row.fieldName || row.key);
 const existing = merged.get(key);
 if (!existing) {
 merged.set(key, row);
 continue;
 }
 merged.set(key, {
 ...existing,
 selectorId: existing.selectorId ?? row.selectorId,
 surface: existing.surface ?? row.surface,
 fieldName: existing.fieldName || row.fieldName,
 kind: preferIncoming
 ? row.kind
 : existing.selectorValue
 ? existing.kind
 : row.kind,
 selectorValue: preferIncoming
 ? row.selectorValue
 : existing.selectorValue || row.selectorValue,
 extractedValue: preferIncoming
 ? row.extractedValue
 : existing.extractedValue || row.extractedValue,
 source: preferIncoming ? row.source : existing.source || row.source,
 state: preferIncoming
 ? row.state
 : existing.state ==="saved"
 ?"saved"
 : row.state,
 });
 }
 return Array.from(merged.values());
}

export function buildXPathForElement(element: Element): string {
 const segments: string[] = [];
 let current: Element | null = element;
 while (current && current.nodeType === Node.ELEMENT_NODE) {
 const tagName = current.tagName.toLowerCase();
 const testId = current.getAttribute("data-testid");
 if (testId) {
 segments.unshift(`//${tagName}[@data-testid=${xpathLiteral(testId)}]`);
 return segments.join("");
 }
 const id = current.getAttribute("id");
 if (id) {
 segments.unshift(`//${tagName}[@id=${xpathLiteral(id)}]`);
 return segments.join("");
 }
 const siblings = current.parentElement
 ? Array.from(current.parentElement.children).filter(
 (sibling) => sibling.tagName.toLowerCase() === tagName,
 )
 : [current];
 const index = siblings.indexOf(current) + 1;
 segments.unshift(`/${tagName}[${index}]`);
 current = current.parentElement;
 }
 return segments.join("") ||"//*";
}

export function xpathLiteral(value: string): string {
 if (!value.includes("'")) {
 return `'${value}'`;
 }
 if (!value.includes('"')) {
 return `"${value}"`;
 }
 const parts = value.split("'");
 const args: string[] = [];
 for (let index = 0; index < parts.length; index += 1) {
 args.push(`'${parts[index]}'`);
 if (index < parts.length - 1) {
 args.push(`"'"`);
 }
 }
 return `concat(${args.join(",")})`;
}

function isDuplicateSelectorError(error: unknown): boolean {
 if (httpErrorStatus(error) === 409) {
 return true;
 }
 const fragments = [];
 if (error instanceof Error) {
 fragments.push(error.message);
 }
 if (typeof error ==="object"&& error !== null &&"body"in error) {
 const body = (error as { body?: unknown }).body;
 if (typeof body ==="string") {
 fragments.push(body);
 }
 }
 const message = fragments.join("").toLowerCase();
 return message.includes("already exists") || message.includes("duplicate");
}
