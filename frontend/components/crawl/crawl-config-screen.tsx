"use client";

import "./crawl.module.css";

import { Check, Globe, Info, Plus, Shield, SlidersHorizontal, Sparkles } from "lucide-react";
import type { Route } from "next";
import { useRouter } from "next/navigation";
import { FormEvent, startTransition, useEffect, useMemo, useRef, useState } from "react";

import { cn } from "../../lib/utils";
import { InlineAlert, PageHeader, SectionHeader, TabBar } from "../ui/patterns";
import { Badge, Button, Dropdown, Card, Input, Textarea, Toggle, Tooltip } from "../ui/primitives";
import { api } from "../../lib/api";
import type {
 CrawlConfig,
 CrawlDomain,
 DomainRunProfile,
} from "../../lib/api/types";
import { CRAWL_DEFAULTS, CRAWL_LIMITS } from "../../lib/constants/crawl-defaults";
import { getNormalizedDomain } from "../../lib/format/domain";
import { STORAGE_KEYS } from "../../lib/constants/storage-keys";
import { UI_DELAYS } from "../../lib/constants/timing";
import { telemetryErrorPayload, trackEvent } from "../../lib/telemetry/events";
import {
 AdditionalFieldInput,
 clampNumber,
 type CategoryMode,
 type CrawlTab,
 deriveSurface,
 FieldEditorHeader,
 type FieldRow,
 type FieldRowMessageTone,
 ManualFieldEditor,
 type PendingDispatch,
 parseRequestedCategoryMode,
 parseRequestedCrawlTab,
 parseLines,
 parseRequestedPdpMode,
 type PdpMode,
 SettingSection,
 SliderRow,
 validateAdditionalFieldName,
 normalizeField,
 uniqueFields,
 uniqueRequestedFields,
} from "./shared";

type CrawlConfigScreenProps = {
 requestedTab: CrawlTab | null;
 requestedCategoryMode: CategoryMode | null;
 requestedPdpMode: PdpMode | null;
};

type StudioMode = "quick" | "advanced";
type FetchMode = DomainRunProfile["fetch_profile"]["fetch_mode"];
type ExtractionSource = DomainRunProfile["fetch_profile"]["extraction_source"];
type JsMode = DomainRunProfile["fetch_profile"]["js_mode"];
type TraversalMode = NonNullable<DomainRunProfile["fetch_profile"]["traversal_mode"]>;
type TraversalDropdownValue = TraversalMode | "off";
type CaptureNetworkMode = DomainRunProfile["diagnostics_profile"]["capture_network"];
type DiagnosticsPreset = "lean" | "standard" | "deep_debug";

const FETCH_MODE_OPTIONS = new Set<FetchMode>([
 "auto",
 "http_only",
 "browser_only",
 "http_then_browser",
]);
const EXTRACTION_SOURCE_OPTIONS = new Set<ExtractionSource>([
 "raw_html",
 "rendered_dom",
 "rendered_dom_visual",
 "network_payload_first",
]);
const JS_MODE_OPTIONS = new Set<JsMode>(["auto", "enabled", "disabled"]);
const TRAVERSAL_MODE_OPTIONS = new Set<TraversalMode>([
 "auto",
 "scroll",
 "load_more",
 "view_all",
 "paginate",
]);
const CAPTURE_NETWORK_OPTIONS = new Set<CaptureNetworkMode>([
 "off",
 "matched_only",
 "all_small_json",
]);
const RUN_SETUP_ROW_CLASS = "grid gap-2 md:grid-cols-[140px_minmax(0,1fr)] md:items-center md:gap-3";
const RUN_SETUP_CONTROL_CLASS = "flex md:justify-self-start";
const RUN_SETUP_LABEL_CLASS = "flex min-w-0 h-[var(--control-height)] items-center gap-3";
const RUN_SETUP_STACK_CLASS = "flex flex-col gap-3";
const ADVANCED_CONTROL_ROW_CLASS = "grid gap-1.5 md:grid-cols-[120px_minmax(0,1fr)] md:items-center md:gap-3";
const ADVANCED_COLUMN_CLASS = "flex flex-col gap-4";
const ADVANCED_SUBSECTION_CLASS = "flex flex-col gap-2.5";
const ADVANCED_SECTION_TITLE_CLASS = "flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-muted";

const DIAGNOSTICS_PRESETS: Record<
 DiagnosticsPreset,
 DomainRunProfile["diagnostics_profile"]
> = {
 lean: {
 capture_html: true,
 capture_screenshot: false,
 capture_network: "off",
 capture_response_headers: true,
 capture_browser_diagnostics: true,
 },
 standard: {
 capture_html: true,
 capture_screenshot: false,
 capture_network: "matched_only",
 capture_response_headers: true,
 capture_browser_diagnostics: true,
 },
 deep_debug: {
 capture_html: true,
 capture_screenshot: true,
 capture_network: "all_small_json",
 capture_response_headers: true,
 capture_browser_diagnostics: true,
 },
};

function defaultRunProfile(): DomainRunProfile {
 return {
 version: 1,
 fetch_profile: {
 fetch_mode: "auto",
 extraction_source: "raw_html",
 js_mode: "auto",
 include_iframes: false,
 traversal_mode: null,
 request_delay_ms: CRAWL_DEFAULTS.REQUEST_DELAY_MS,
 },
 locality_profile: {
 geo_country: "auto",
 language_hint: null,
 currency_hint: null,
 },
 diagnostics_profile: { ...DIAGNOSTICS_PRESETS.standard },
 source_run_id: null,
 saved_at: null,
 };
}

function cloneRunProfile(profile: DomainRunProfile | null | undefined): DomainRunProfile {
 const base = defaultRunProfile();
 if (!profile) {
 return base;
 }
 return {
 version: 1,
 fetch_profile: {
 ...base.fetch_profile,
 ...(profile.fetch_profile ?? {}),
 },
 locality_profile: {
 ...base.locality_profile,
 ...(profile.locality_profile ?? {}),
 },
 diagnostics_profile: {
 ...base.diagnostics_profile,
 ...(profile.diagnostics_profile ?? {}),
 },
 source_run_id: profile.source_run_id ?? null,
 saved_at: profile.saved_at ?? null,
 };
}

function diagnosticsPresetForProfile(profile: DomainRunProfile): DiagnosticsPreset {
 const current = profile.diagnostics_profile;
 for (const preset of ["lean", "standard", "deep_debug"] as const) {
 const candidate = DIAGNOSTICS_PRESETS[preset];
 if (
 current.capture_html === candidate.capture_html &&
 current.capture_screenshot === candidate.capture_screenshot &&
 current.capture_network === candidate.capture_network &&
 current.capture_response_headers === candidate.capture_response_headers &&
 current.capture_browser_diagnostics === candidate.capture_browser_diagnostics
 ) {
 return preset;
 }
 }
 return "standard";
}

function applyDiagnosticsPreset(
 profile: DomainRunProfile,
 preset: DiagnosticsPreset,
): DomainRunProfile {
 return {
 ...profile,
 diagnostics_profile: { ...DIAGNOSTICS_PRESETS[preset] },
 };
}

function isSingleUrlMode(crawlTab: CrawlTab, mode: CategoryMode | PdpMode) {
 return (
 (crawlTab === "category" && mode === "single") ||
 (crawlTab === "pdp" && mode === "single")
 );
}

function normalizeHttpLookupDomain(rawUrl: string) {
 const candidate = rawUrl.trim();
 if (!candidate) {
 return "";
 }
 try {
 const parsed = new URL(candidate);
 if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
 return "";
 }
 return parsed.hostname.replace(/^www\./, "").toLowerCase();
 } catch {
 return "";
 }
}

function surfaceLabel(surface: string) {
 if (surface === "ecommerce_listing") {
 return "Commerce Listing";
 }
 if (surface === "ecommerce_detail") {
 return "Commerce Detail";
 }
 if (surface === "job_listing") {
 return "Job Listing";
 }
 if (surface === "job_detail") {
 return "Job Detail";
 }
 return surface;
}

function stripDomainMemoryFieldRows(rows: FieldRow[]) {
 return rows.filter((row) => !row.id.startsWith("domain-memory-"));
}

export function CrawlConfigScreen({
 requestedTab,
 requestedCategoryMode,
 requestedPdpMode,
}: Readonly<CrawlConfigScreenProps>) {
 const router = useRouter();
 const [crawlTab, setCrawlTab] = useState<CrawlTab>(() => requestedTab ?? "category");
 const [crawlDomain, setCrawlDomain] = useState<CrawlDomain>("commerce");
 const [categoryMode, setCategoryMode] = useState<CategoryMode>(() => requestedCategoryMode ?? "single");
 const [pdpMode, setPdpMode] = useState<PdpMode>(() => requestedPdpMode ?? "single");
 const [targetUrl, setTargetUrl] = useState("");
 const [bulkUrls, setBulkUrls] = useState("");
 const [csvFile, setCsvFile] = useState<File | null>(null);
 const [smartExtraction, setSmartExtraction] = useState(false);
 const [studioMode, setStudioMode] = useState<StudioMode>("quick");
 const [runProfile, setRunProfile] = useState<DomainRunProfile>(() => defaultRunProfile());
 const [maxRecords, setMaxRecords] = useState(String(CRAWL_DEFAULTS.MAX_RECORDS));
 const [respectRobotsTxt, setRespectRobotsTxt] = useState<boolean>(CRAWL_DEFAULTS.RESPECT_ROBOTS_TXT);
 const [proxyEnabled, setProxyEnabled] = useState(false);
 const [proxyInput, setProxyInput] = useState("");
 const [savedProfileDomain, setSavedProfileDomain] = useState("");
 const [savedProfileLoaded, setSavedProfileLoaded] = useState(false);
 const [savedProfileMessage, setSavedProfileMessage] = useState("");
 const [additionalDraft, setAdditionalDraft] = useState("");
 const [additionalFields, setAdditionalFields] = useState<string[]>([]);
 const [fieldRows, setFieldRows] = useState<FieldRow[]>([]);
 const [generatingSelectors, setGeneratingSelectors] = useState(false);
 const [savingDomainMemory, setSavingDomainMemory] = useState(false);
 const [fieldConfigMessage, setFieldConfigMessage] = useState("");
 const [fieldConfigError, setFieldConfigError] = useState("");
 const [fieldRowMessages, setFieldRowMessages] = useState<Record<string, { tone: FieldRowMessageTone; message: string }>>({});
 const [activeFieldTestId, setActiveFieldTestId] = useState<string | null>(null);
 const [configError, setConfigError] = useState("");
 const [isSubmitting, setIsSubmitting] = useState(false);
 const bulkPrefillRouteSyncGuardRef = useRef(false);
 const profileLookupRequestRef = useRef(0);
 const domainMemoryLookupRequestRef = useRef(0);
 const profileLookupTargetUrlRef = useRef("");
 const profileDirtyRef = useRef(false);
 const lastProfileKeyRef = useRef("");
 const lastDomainMemoryKeyRef = useRef("");

 const activeMode = crawlTab === "category" ? categoryMode : pdpMode;
 const surface = deriveSurface(crawlDomain, crawlTab);
 const singleUrlMode = isSingleUrlMode(crawlTab, activeMode);
 const normalizedTargetDomain = normalizeHttpLookupDomain(targetUrl);
 const profileLookupKey =
 singleUrlMode && normalizedTargetDomain && surface
 ? `${normalizedTargetDomain}|${surface}`
 : "";
 const domainMemoryLookupKey =
 singleUrlMode && normalizedTargetDomain && surface
 ? `${normalizedTargetDomain}|${surface}`
 : "";
 const diagnosticsPreset = diagnosticsPresetForProfile(runProfile);

 useEffect(() => {
 profileLookupTargetUrlRef.current = profileLookupKey ? targetUrl.trim() : "";
 }, [profileLookupKey, targetUrl]);

 useEffect(() => {
 if (bulkPrefillRouteSyncGuardRef.current) {
 if (requestedTab === "pdp") {
 bulkPrefillRouteSyncGuardRef.current = false;
 } else {
 return;
 }
 }
 const nextTab = requestedTab ?? "category";
 const nextCategoryMode = requestedCategoryMode ?? "single";
 const nextPdpMode = requestedPdpMode ?? "single";
 setCrawlTab((current) => (current === nextTab ? current : nextTab));
 setCategoryMode((current) => (current === nextCategoryMode ? current : nextCategoryMode));
 setPdpMode((current) => (current === nextPdpMode ? current : nextPdpMode));
 }, [requestedCategoryMode, requestedPdpMode, requestedTab]);

 useEffect(() => {
 const routeMode = crawlTab === "category" ? requestedCategoryMode : requestedPdpMode;
 if (requestedTab === crawlTab && routeMode === activeMode) {
 return;
 }
 const nextUrl = `/crawl?module=${crawlTab}&mode=${activeMode}`;
 if (typeof window !== "undefined") {
 const currentUrl = `${window.location.pathname}${window.location.search}`;
 if (currentUrl !== nextUrl) {
 window.history.replaceState(null, "", nextUrl);
 }
 }
 }, [activeMode, crawlTab, requestedCategoryMode, requestedPdpMode, requestedTab]);

 useEffect(() => {
 const stored = window.sessionStorage.getItem(STORAGE_KEYS.BULK_PREFILL);
 if (!stored) {
 return;
 }
 try {
 const parsed = JSON.parse(stored) as {
 domain?: CrawlDomain;
 urls: string[];
 additional_fields?: string[];
 };
 if (Array.isArray(parsed.urls) && parsed.urls.length) {
 bulkPrefillRouteSyncGuardRef.current = true;
 setCrawlTab("pdp");
 setPdpMode("batch");
 if (parsed.domain === "commerce" || parsed.domain === "jobs") {
 setCrawlDomain(parsed.domain);
 }
 setBulkUrls(parsed.urls.join("\n"));
 if (Array.isArray(parsed.additional_fields)) {
 setAdditionalFields(uniqueRequestedFields(parsed.additional_fields));
 }
 router.replace("/crawl?module=pdp&mode=batch" as Route);
 }
 } catch {
 } finally {
 window.sessionStorage.removeItem(STORAGE_KEYS.BULK_PREFILL);
 }
 }, [router]);

 useEffect(() => {
 if (lastProfileKeyRef.current !== profileLookupKey) {
 profileDirtyRef.current = false;
 lastProfileKeyRef.current = profileLookupKey;
 if (!profileLookupKey) {
 setSavedProfileLoaded(false);
 setSavedProfileDomain("");
 setSavedProfileMessage("");
 setRunProfile(defaultRunProfile());
 return;
 }
 }
 if (!profileLookupKey) {
 return;
 }
 const requestId = profileLookupRequestRef.current + 1;
 profileLookupRequestRef.current = requestId;
 const timer = window.setTimeout(async () => {
 try {
 const response = await api.getDomainRunProfile({
 url: profileLookupTargetUrlRef.current,
 surface,
 });
 if (profileLookupRequestRef.current !== requestId) {
 return;
 }
 const savedProfile = response.saved_run_profile;
 setSavedProfileDomain(response.domain);
 if (savedProfile && !profileDirtyRef.current) {
 setRunProfile(cloneRunProfile(savedProfile));
 setSavedProfileLoaded(true);
 setSavedProfileMessage(
 `Saved domain profile applied for ${response.domain} on ${surfaceLabel(response.surface)}. Explicit edits below override it for this run.`,
 );
 } else {
 setSavedProfileLoaded(Boolean(savedProfile));
 setSavedProfileMessage(
 savedProfile
 ? `Saved domain profile found for ${response.domain}. Your current edits are preserved for this run.`
 : "",
 );
 if (!savedProfile && !profileDirtyRef.current) {
 setRunProfile(defaultRunProfile());
 }
 }
 } catch {
 if (profileLookupRequestRef.current === requestId) {
 setSavedProfileLoaded(false);
 setSavedProfileDomain("");
 setSavedProfileMessage("");
 }
 }
 }, UI_DELAYS.DEBOUNCE_MS);
 return () => window.clearTimeout(timer);
 }, [profileLookupKey, surface]);

 useEffect(() => {
 if (lastDomainMemoryKeyRef.current !== domainMemoryLookupKey) {
 lastDomainMemoryKeyRef.current = domainMemoryLookupKey;
 setFieldConfigError("");
 setFieldConfigMessage("");
 setFieldRowMessages({});
 setFieldRows((current) => stripDomainMemoryFieldRows(current));
 if (!domainMemoryLookupKey) {
 return;
 }
 }
 if (!domainMemoryLookupKey) {
 return;
 }
 const requestId = domainMemoryLookupRequestRef.current + 1;
 domainMemoryLookupRequestRef.current = requestId;
 const lookupDomain = normalizedTargetDomain;
 const timer = window.setTimeout(async () => {
 setFieldConfigError("");
 try {
 const records = await api.listSelectors({ domain: lookupDomain });
 if (domainMemoryLookupRequestRef.current !== requestId) {
 return;
 }
 const matchingRecords = selectRelevantSelectorRecords(records, surface);
 if (!matchingRecords.length) {
 setFieldRows((current) => stripDomainMemoryFieldRows(current));
 return;
 }
 const incomingRows = matchingRecords.map(buildFieldRowFromSelectorRecord);
 setFieldRows((current) => mergeFieldRows(stripDomainMemoryFieldRows(current), incomingRows));
 setFieldRowMessages({});
 } catch (error) {
 if (domainMemoryLookupRequestRef.current === requestId) {
 setFieldConfigError(error instanceof Error ? error.message : "Unable to load domain memory.");
 }
 }
 }, UI_DELAYS.DEBOUNCE_MS);
 return () => window.clearTimeout(timer);
 }, [domainMemoryLookupKey, normalizedTargetDomain, surface]);

 const config = useMemo<CrawlConfig>(
 () => ({
 module: crawlTab,
 domain: crawlDomain,
 mode: crawlTab === "category" ? categoryMode : pdpMode,
 target_url: targetUrl,
 bulk_urls: bulkUrls,
 csv_file: csvFile,
 smart_extraction: smartExtraction,
 max_records: clampNumber(maxRecords, CRAWL_LIMITS.MIN_RECORDS, CRAWL_LIMITS.MAX_RECORDS, CRAWL_DEFAULTS.MAX_RECORDS),
 respect_robots_txt: respectRobotsTxt,
 proxy_enabled: proxyEnabled,
 proxy_lines: proxyEnabled ? parseLines(proxyInput) : [],
 additional_fields: additionalFields,
 }),
 [
 additionalFields,
 bulkUrls,
 categoryMode,
 crawlDomain,
 crawlTab,
 csvFile,
 maxRecords,
 pdpMode,
 proxyEnabled,
 proxyInput,
 respectRobotsTxt,
 smartExtraction,
 targetUrl,
  ],
 );

 async function loadDomainMemoryForUrl(rawUrl: string) {
 const target = rawUrl.trim();
 const domain = getNormalizedDomain(target);
 if (!target || !domain) {
 return;
 }
 const requestId = domainMemoryLookupRequestRef.current + 1;
 domainMemoryLookupRequestRef.current = requestId;
 setFieldConfigError("");
 try {
 const records = await api.listSelectors({ domain });
 if (domainMemoryLookupRequestRef.current !== requestId) {
 return;
 }
 const matchingRecords = selectRelevantSelectorRecords(records, surface);
 if (!matchingRecords.length) {
 setFieldConfigMessage("No saved domain memory found for this URL.");
 setFieldRows((current) => stripDomainMemoryFieldRows(current));
 return;
 }
 const incomingRows = matchingRecords.map(buildFieldRowFromSelectorRecord);
 setFieldRows((current) => mergeFieldRows(stripDomainMemoryFieldRows(current), incomingRows));
 setFieldRowMessages({});
 setFieldConfigMessage(`Loaded ${matchingRecords.length} saved selector${matchingRecords.length === 1 ? "" : "s"} from domain memory.`);
 } catch (error) {
 if (domainMemoryLookupRequestRef.current === requestId) {
 setFieldConfigError(error instanceof Error ? error.message : "Unable to load domain memory.");
 }
 }
 }

 function markProfileDirty(updater: (current: DomainRunProfile) => DomainRunProfile) {
 profileDirtyRef.current = true;
 setRunProfile((current) => cloneRunProfile(updater(current)));
 }

 async function startCrawl(event: FormEvent) {
 event.preventDefault();
 if (isSubmitting) {
 return;
 }
 setConfigError("");
 setIsSubmitting(true);
 try {
 const dispatch = buildDispatch(config, fieldRows, {
 runProfile,
 studioMode,
 });
 if (studioMode === "advanced") {
 trackEvent("advanced_mode_selected_vs_effective", {
 module: config.module,
 selected_advanced_mode: runProfile.fetch_profile.traversal_mode,
 effective_advanced_mode: dispatch.settings.advanced_mode ?? null,
 });
 }
 let response: { run_id: number };
 if (dispatch.runType === "csv") {
 if (!dispatch.csvFile) {
 throw new Error("CSV file is missing.");
 }
 response = await api.createCsvCrawl({
 file: dispatch.csvFile,
 surface: dispatch.surface,
 additionalFields: dispatch.additionalFields,
 settings: dispatch.settings,
 });
 } else {
 response = await api.createCrawl({
 run_type: dispatch.runType,
 url: dispatch.url,
 urls: dispatch.urls,
 surface: dispatch.surface,
 settings: dispatch.settings,
 additional_fields: dispatch.additionalFields,
 });
 }
 startTransition(() => {
 router.replace((`/crawl?run_id=${response.run_id}`) as Route);
 router.refresh();
 });
 } catch (error) {
 const message = error instanceof Error ? error.message : "Unable to launch crawl.";
 trackEvent(
 "crawl_submit_error_rate",
 telemetryErrorPayload(error, {
 module: config.module,
 mode: config.mode,
 surface,
 studio_mode: studioMode,
 smart_extraction: config.smart_extraction,
 run_type_hint: inferRunTypeHint(config),
 }),
 );
 setConfigError(message);
 } finally {
 setIsSubmitting(false);
 }
 }

 function addManualField() {
 setFieldRows((current) => [
 ...current,
 {
 id: `${Date.now()}-${current.length}`,
 fieldName: "",
 cssSelector: "",
 xpath: "",
 regex: "",
 cssState: "idle",
 xpathState: "idle",
 regexState: "idle",
 },
 ]);
 }

 async function generateFieldSelectors() {
 const target = targetUrl.trim();
 if (!target) {
 setFieldConfigError("Enter a target URL before generating selectors.");
 return;
 }
 const expectedColumns = selectorGenerationFields(surface, fieldRows, additionalFields);
 if (!expectedColumns.length) {
 setFieldConfigError("Add at least one field or additional field before generating selectors.");
 return;
 }
 setGeneratingSelectors(true);
 setFieldConfigError("");
 try {
 const response = await api.suggestSelectors({
 url: target,
 expected_columns: expectedColumns,
 surface,
 });
 const incomingRows = expectedColumns.map((fieldName) =>
 buildFieldRowFromSuggestion(fieldName, response.suggestions[normalizeField(fieldName)]?.[0]),
 );
 setFieldRows((current) => mergeFieldRows(current, incomingRows));
 setFieldRowMessages({});
 setFieldConfigMessage(`Generated selector suggestions for ${expectedColumns.length} field${expectedColumns.length === 1 ? "" : "s"}.`);
 } catch (error) {
 setFieldConfigError(error instanceof Error ? error.message : "Unable to generate selectors.");
 } finally {
 setGeneratingSelectors(false);
 }
 }

 async function testFieldRow(row: FieldRow) {
 const target = targetUrl.trim();
 if (!target) {
 setFieldRowMessages((current) => ({
 ...current,
 [row.id]: { tone: "warning", message: "Enter a target URL before testing selectors." },
 }));
 return;
 }
 if (!row.cssSelector.trim() && !row.xpath.trim() && !row.regex.trim()) {
 setFieldRowMessages((current) => ({
 ...current,
 [row.id]: { tone: "warning", message: "Add a CSS selector, XPath, or regex before testing." },
 }));
 return;
 }
 setActiveFieldTestId(row.id);
 try {
 const response = await api.testSelector({
 url: target,
 css_selector: row.cssSelector.trim() || undefined,
 xpath: row.xpath.trim() || undefined,
 regex: row.regex.trim() || undefined,
 });
 setFieldRowMessages((current) => ({
 ...current,
 [row.id]: {
 tone: response.count > 0 ? "success" : "warning",
 message:
 response.count > 0
 ? `Matched ${response.count} result${response.count === 1 ? "" : "s"}${response.matched_value ? `: ${response.matched_value}` : "."}`
 : "No matches.",
 },
 }));
 } catch (error) {
 setFieldRowMessages((current) => ({
 ...current,
 [row.id]: { tone: "danger", message: error instanceof Error ? error.message : "Selector test failed." },
 }));
 } finally {
 setActiveFieldTestId(null);
 }
 }

 async function saveToDomainMemory() {
 const target = targetUrl.trim();
 const domain = getNormalizedDomain(target);
 if (!target || !domain) {
 setFieldConfigError("Enter a target URL before saving domain memory.");
 return;
 }
 const dedupedRows = Array.from(
 new Map(
 fieldRows
 .filter((row) => normalizeField(row.fieldName) && (row.cssSelector.trim() || row.xpath.trim() || row.regex.trim()))
 .map((row) => [normalizeField(row.fieldName), row] as const),
 ).values(),
 );
 if (!dedupedRows.length) {
 setFieldConfigError("Add at least one selector row before saving domain memory.");
 return;
 }
 setSavingDomainMemory(true);
 setFieldConfigError("");
 try {
 const existingRecords = selectRelevantSelectorRecords(await api.listSelectors({ domain }), surface);
 const existingByField = new Map(existingRecords.map((record) => [normalizeField(record.field_name), record] as const));
 const settled = await Promise.allSettled(
 dedupedRows.map(async (row) => {
 const fieldName = normalizeField(row.fieldName);
 const payload = {
 field_name: fieldName,
 css_selector: row.cssSelector.trim() || undefined,
 xpath: row.xpath.trim() || undefined,
 regex: row.regex.trim() || undefined,
 source: "crawl_config",
 status: "validated" as const,
 is_active: true,
 };
 const existing = existingByField.get(fieldName);
 if (existing) {
 await api.updateSelector(existing.id, payload);
 return;
 }
 await api.createSelector({
 domain,
 surface,
 ...payload,
 });
 }),
 );
 const failedCount = settled.filter((result) => result.status === "rejected").length;
 const savedCount = settled.length - failedCount;
 if (failedCount) {
 setFieldConfigError(`Saved ${savedCount} selector${savedCount === 1 ? "" : "s"}, ${failedCount} failed.`);
 } else {
 setFieldConfigMessage(`Saved ${savedCount} selector${savedCount === 1 ? "" : "s"} to domain memory.`);
 }
 if (savedCount) {
 await loadDomainMemoryForUrl(target);
 }
 } catch (error) {
 setFieldConfigError(error instanceof Error ? error.message : "Unable to save domain memory.");
 } finally {
 setSavingDomainMemory(false);
 }
 }

 const hasTarget = (singleUrlMode || categoryMode === "sitemap")
 ? targetUrl.trim().length > 0
 : (bulkUrls.trim().length > 0 || csvFile !== null);
 const canSubmit = canPreview(config, fieldRows, { runProfile, studioMode }) && !isSubmitting;

 return (
 <div className="page-stack gap-4">
 <PageHeader title="Crawl Studio" description="Configure and launch crawls across product listings and detail pages." />

 {/* Flow Stepper */}
 <div className="flex items-center gap-0 text-[11px]">
 <CsFlowStep step={1} label="Target" active={hasTarget} />
 <CsFlowConnector active={hasTarget} />
 <CsFlowStep step={2} label="Configure" active={studioMode === "advanced" || crawlDomain !== "commerce"} />
 <CsFlowConnector active={studioMode === "advanced" || crawlDomain !== "commerce"} />
 <CsFlowStep step={3} label="Launch" active={canSubmit} />
 </div>

 <form className="grid gap-5 xl:grid-cols-[minmax(0,1.45fr)_380px] xl:items-stretch" onSubmit={(event) => void startCrawl(event)}>
 <div className="page-stack">
 <Card className="section-card overflow-hidden">
 <header className="cs-panel-header">
 <span className="cs-panel-title">Target URL</span>
 <Badge tone="info" className="h-5 px-1.5 text-[10px]">{crawlTab === "category" ? "Category" : "PDP"}</Badge>
 </header>
 <div className="p-4 space-y-4">
 <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-start">
 <div className="flex flex-wrap items-center gap-2">
 <TabBar
 value={crawlTab}
 onChange={(value) => {
 const parsed = parseRequestedCrawlTab(value);
 if (parsed) {
 setCrawlTab(parsed);
 }
 }}
 options={[
 { value: "category", label: "Category Crawl" },
 { value: "pdp", label: "PDP Crawl" },
 ]}
 />
 {crawlTab === "category" ? (
 <TabBar
 value={categoryMode}
 compact
 onChange={(value) => {
 const parsed = parseRequestedCategoryMode(value);
 if (parsed) {
 setCategoryMode(parsed);
 }
 }}
 options={[
 { value: "single", label: "Single" },
 { value: "sitemap", label: "Sitemap" },
 { value: "bulk", label: "Bulk" },
 ]}
 />
 ) : (
 <TabBar
 value={pdpMode}
 compact
 onChange={(value) => {
 const parsed = parseRequestedPdpMode(value);
 if (parsed) {
 setPdpMode(parsed);
 }
 }}
 options={[
 { value: "single", label: "Single" },
 { value: "batch", label: "Batch" },
 { value: "csv", label: "CSV Upload" },
 ]}
 />
 )}
 </div>
 <Button
 variant="accent"
 size="lg"
 type="submit"
 disabled={!canSubmit}
 className="min-w-[140px] justify-self-start lg:justify-self-end shadow-[0_8px_24px_color-mix(in_srgb,var(--accent)_20%,transparent)]"
 >
 {isSubmitting ? <><span className="cs-live-dot mr-1.5" />Starting...</> : "Start Crawl"}
 </Button>
 </div>

 {(crawlTab === "category" && categoryMode === "bulk") || (crawlTab === "pdp" && pdpMode === "batch") ? (
 <label className="grid gap-1.5">
 <span className="field-label">URLs (one per line)</span>
 <div className="relative">
 <Textarea
 value={bulkUrls}
 onChange={(event) => setBulkUrls(event.target.value)}
 placeholder={"https://example.com/page-1\nhttps://example.com/page-2"}
 rows={10}
 className="min-h-[420px] text-mono-body"
 aria-label="Bulk URLs input"
 />
 {bulkUrls.trim() ? (
 <div className="absolute bottom-2 right-2 rounded bg-background/80 px-2 py-1 text-sm text-muted backdrop-blur-sm">
 {parseLines(bulkUrls).length} URLs
 </div>
 ) : null}
 </div>
 </label>
 ) : crawlTab === "pdp" && pdpMode === "csv" ? (
 <label className="grid gap-1.5">
 <span className="field-label">CSV File</span>
 <div className="flex items-center gap-3">
 <input
 key="csv-file-input"
 id="csv-file-input"
 type="file"
 accept=".csv,text/csv"
 onChange={(event) => setCsvFile(event.target.files?.[0] ?? null)}
 className="sr-only"
 aria-label="CSV file input"
 />
 <label
 htmlFor="csv-file-input"
 className="ui-on-accent-surface cursor-pointer rounded-[var(--radius-md)] bg-accent px-3 py-1.5 text-sm font-medium transition-colors hover:bg-accent-hover"
 >
 Choose file
 </label>
 <span className="text-sm text-muted">
 {csvFile ? csvFile.name : "No file chosen"}
 </span>
 </div>
 </label>
 ) : (
 <label className="grid gap-1.5">
 <span className="field-label">Target URL</span>
 <Input
 key="target-url-input"
 value={targetUrl}
 onChange={(event) => setTargetUrl(event.target.value)}
 placeholder={
 crawlTab === "category"
 ? "https://example.com/collections/chairs"
 : "https://example.com/products/oak-chair"
 }
 className="text-mono-body"
 aria-label="Target URL input"
 />
 </label>
 )}

 {savedProfileMessage ? (
 <div className="rounded-[var(--radius-md)] border border-subtle-panel-border bg-subtle-panel px-3 py-2 text-sm leading-[1.5] text-secondary">
 {savedProfileMessage}
 </div>
 ) : null}

 <AdditionalFieldInput
 value={additionalDraft}
 fields={additionalFields}
 onChange={setAdditionalDraft}
 onCommit={(value) => setAdditionalFields((current) => uniqueRequestedFields([...current, value]))}
 onRemove={(value) => setAdditionalFields((current) => current.filter((field) => field !== value))}
 />
 </div>
 </Card>

 {studioMode === "advanced" ? (
 <Card className="section-card overflow-hidden">
 <header className="cs-panel-header">
 <span className="cs-panel-title">Field Configuration</span>
 <div className="flex items-center gap-2">
 <Button
 variant="ghost"
 type="button"
 size="sm"
 onClick={() => void generateFieldSelectors()}
 disabled={generatingSelectors}
 className="h-7 rounded-lg px-2.5 text-[11px]"
 >
 <Sparkles className="size-3" />
 {generatingSelectors ? "Generating..." : "Generate"}
 </Button>
 <Button variant="ghost" type="button" size="sm" onClick={addManualField} className="h-7 rounded-lg px-2.5 text-[11px]">
 <Plus className="size-3" />
 New Field
 </Button>
 <Button
 variant="accent"
 type="button"
 size="sm"
 onClick={() => void saveToDomainMemory()}
 disabled={savingDomainMemory || !fieldRows.some((row) => normalizeField(row.fieldName) && (row.cssSelector.trim() || row.xpath.trim() || row.regex.trim()))}
 className="h-7 rounded-lg px-3 text-[11px] shadow-[0_6px_16px_color-mix(in_srgb,var(--accent)_20%,transparent)]"
 >
 {savingDomainMemory ? "Saving..." : "Save to Memory"}
 </Button>
 </div>
 </header>
 <div className="p-4 space-y-3">
 {fieldConfigMessage ? <p className="text-sm leading-[1.5] text-success">{fieldConfigMessage}</p> : null}
 {fieldConfigError ? <InlineAlert message={fieldConfigError} /> : null}
 <div className="flex flex-col gap-3">
 {fieldRows.length ? (
 <>
 <FieldEditorHeader />
 {fieldRows.map((row) => (
 <ManualFieldEditor
 key={row.id}
 row={row}
 showLabels={false}
 message={fieldRowMessages[row.id]?.message}
 messageTone={fieldRowMessages[row.id]?.tone}
 onChange={(patch) => {
 setFieldRows((current) =>
 current.map((entry) => (entry.id === row.id ? { ...entry, ...patch } : entry)),
 );
 setFieldRowMessages((current) => {
 if (!current[row.id]) {
 return current;
 }
 const next = { ...current };
 delete next[row.id];
 return next;
 });
 }}
 onDelete={() => {
 setFieldRows((current) => current.filter((entry) => entry.id !== row.id));
 setFieldRowMessages((current) => {
 if (!current[row.id]) {
 return current;
 }
 const next = { ...current };
 delete next[row.id];
 return next;
 });
 }}
 onTest={() => void testFieldRow(row)}
 testing={activeFieldTestId === row.id}
 testDisabled={!targetUrl.trim() || (!row.cssSelector.trim() && !row.xpath.trim() && !row.regex.trim())}
 />
 ))}
 </>
 ) : (
 <div className="surface-muted rounded-lg border-dashed px-4 py-6 text-sm leading-[1.55] text-secondary">
 No selector rows yet.
 </div>
 )}
 </div>
 </div>
 </Card>
 ) : null}

 {configError ? <InlineAlert message={configError} /> : null}
 </div>

 <div className="h-full xl:self-stretch">
 <div className="h-full xl:sticky xl:top-[68px]">
 <Card className="section-card overflow-hidden">
 <header className="cs-panel-header">
 <span className="cs-panel-title">Crawl Settings</span>
 <Badge tone="neutral" className="h-5 px-1.5 text-[10px]">{studioMode === "advanced" ? "Advanced" : "Quick"}</Badge>
 </header>
 <div className="p-4 page-stack">
 <div className={RUN_SETUP_ROW_CLASS}>
 <div className={RUN_SETUP_LABEL_CLASS}>
 <Globe className="size-4 shrink-0 text-accent" />
 <div className="field-label mb-0">Domain</div>
 </div>
 <TabBar
 value={crawlDomain}
 compact
 className={RUN_SETUP_CONTROL_CLASS}
 onChange={(value) => {
 if (value === "commerce" || value === "jobs") {
 setCrawlDomain(value);
 }
 }}
 options={[
 { value: "commerce", label: "Commerce" },
 { value: "jobs", label: "Jobs" },
 ]}
 />
 </div>

 <div className={RUN_SETUP_ROW_CLASS}>
 <div className={RUN_SETUP_LABEL_CLASS}>
 <SlidersHorizontal className="size-4 shrink-0 text-accent" />
 <div className="flex items-center gap-1.5">
 <div className="field-label mb-0">Mode</div>
 <Tooltip content="Advanced Mode exposes the full fetch, locality, diagnostics, and selector controls.">
 <Info className="size-3.5 cursor-help text-muted transition-colors hover:text-secondary" />
 </Tooltip>
 </div>
 </div>
 <TabBar
 value={studioMode}
 compact
 className={RUN_SETUP_CONTROL_CLASS}
 onChange={(value) => {
 if (value === "quick" || value === "advanced") {
 setStudioMode(value);
 }
 }}
 options={[
 { value: "quick", label: "Quick" },
 { value: "advanced", label: "Advanced" },
 ]}
 />
 </div>

 <div className={RUN_SETUP_ROW_CLASS}>
 <div className={RUN_SETUP_LABEL_CLASS}>
 <Sparkles className="size-4 shrink-0 text-accent" />
 <div className="flex items-center gap-1.5">
 <div className="field-label mb-0">LLM Enabled</div>
 <Tooltip content="Per-run enrichment only. This does not overwrite saved domain defaults.">
 <Info className="size-3.5 cursor-help text-muted transition-colors hover:text-secondary" />
 </Tooltip>
 </div>
 </div>
 <div className={RUN_SETUP_CONTROL_CLASS}>
 <Toggle checked={smartExtraction} onChange={setSmartExtraction} ariaLabel="LLM enabled" />
 </div>
 </div>

 <div className={RUN_SETUP_STACK_CLASS}>
 <div className={RUN_SETUP_ROW_CLASS}>
 <div className={RUN_SETUP_LABEL_CLASS}>
 <Globe className="size-4 shrink-0 text-accent" />
 <div className="min-w-0">
 <div className="flex items-center gap-1.5">
 <div className="field-label mb-0">Proxy List</div>
 <Tooltip content={"Example:\nhttp://host:port\nhttp://user:pass@host:port"}>
 <Info className="size-3.5 cursor-help text-muted transition-colors hover:text-secondary" />
 </Tooltip>
 </div>
 </div>
 </div>
 <div className={RUN_SETUP_CONTROL_CLASS}>
 <Toggle
 checked={proxyEnabled}
 onChange={setProxyEnabled}
 ariaLabel="Proxy List enabled"
 />
 </div>
 </div>
 {proxyEnabled ? (
  <div className="mt-6 ml-7 flex flex-col gap-3">
 <div className="field-label">Example Proxy List To Enter</div>
 <Textarea
 value={proxyInput}
 onChange={(event) => {
 setProxyInput(event.target.value);
 }}
 placeholder={"http://host:port\nhttp://user:pass@host:port"}
 className="min-h-[104px] text-mono-body leading-[1.55]"
 aria-label="Proxy pool input"
 />
 </div>
 ) : null}
 </div>

 {singleUrlMode && savedProfileLoaded ? (
 <div className="text-sm leading-[1.5] text-secondary">
 Saved domain profile active: <span className="font-medium text-foreground">{savedProfileDomain}</span> · {surfaceLabel(surface)}
 </div>
 ) : null}
 </div>
 </Card>
 </div>
 </div>

 {studioMode === "advanced" ? (
 <Card className="section-card xl:col-span-2 overflow-visible">
 <header className="cs-panel-header">
 <span className="cs-panel-title flex items-center gap-1.5"><SlidersHorizontal className="size-3.5" /> Advanced Settings</span>
 <Tooltip content="Fine-tune fetch, limits, locality, and diagnostics for this exploratory run.">
 <Info className="size-3.5 cursor-help text-muted transition-colors hover:text-secondary" />
 </Tooltip>
 </header>
 <div className="p-5 grid gap-0 xl:grid-cols-3 xl:divide-x xl:divide-[var(--border)]">
 <section className={cn(ADVANCED_COLUMN_CLASS, "xl:pr-6")}>
 <div className={ADVANCED_SECTION_TITLE_CLASS}>
 <h3>Execution</h3>
 <Tooltip content="Control how the crawler fetches, renders, and traverses the target.">
 <Info className="size-3 cursor-help text-muted transition-colors hover:text-secondary" />
 </Tooltip>
 </div>
 <div className={ADVANCED_SUBSECTION_CLASS}>
 <div className={ADVANCED_CONTROL_ROW_CLASS}>
 <div className="field-label">Fetch Mode</div>
 <Dropdown<FetchMode>
 ariaLabel="Fetch mode"
 value={runProfile.fetch_profile.fetch_mode}
 onChange={(next) => {
 if (FETCH_MODE_OPTIONS.has(next)) {
 markProfileDirty((current) => ({
 ...current,
 fetch_profile: {
 ...current.fetch_profile,
 fetch_mode: next,
 },
 }));
 }
 }}
 options={[
 { value: "auto", label: "Auto" },
 { value: "http_only", label: "HTTP Only" },
 { value: "browser_only", label: "Browser Only" },
 { value: "http_then_browser", label: "HTTP Then Browser" },
 ]}
 />
 </div>
 <div className={ADVANCED_CONTROL_ROW_CLASS}>
 <div className="field-label">Extraction</div>
 <Dropdown<ExtractionSource>
 ariaLabel="Extraction source"
 value={runProfile.fetch_profile.extraction_source}
 onChange={(next) => {
 if (EXTRACTION_SOURCE_OPTIONS.has(next)) {
 markProfileDirty((current) => ({
 ...current,
 fetch_profile: {
 ...current.fetch_profile,
 extraction_source: next,
 },
 }));
 }
 }}
 options={[
 { value: "raw_html", label: "Raw HTML" },
 { value: "rendered_dom", label: "Rendered DOM" },
 { value: "rendered_dom_visual", label: "Rendered + Visual" },
 { value: "network_payload_first", label: "Network Payload First" },
 ]}
 />
 </div>
 <div className={ADVANCED_CONTROL_ROW_CLASS}>
 <div className="field-label">JS Mode</div>
 <Dropdown<JsMode>
 ariaLabel="JavaScript mode"
 value={runProfile.fetch_profile.js_mode}
 onChange={(next) => {
 if (JS_MODE_OPTIONS.has(next)) {
 markProfileDirty((current) => ({
 ...current,
 fetch_profile: {
 ...current.fetch_profile,
 js_mode: next,
 },
 }));
 }
 }}
 options={[
 { value: "auto", label: "Auto" },
 { value: "enabled", label: "Enabled" },
 { value: "disabled", label: "Disabled" },
 ]}
 />
 </div>
 <div className={ADVANCED_CONTROL_ROW_CLASS}>
 <div className="field-label">Traversal</div>
 <Dropdown<TraversalDropdownValue>
 ariaLabel="Traversal mode"
 value={runProfile.fetch_profile.traversal_mode ?? "off"}
 onChange={(next) => {
 if (next === "off") {
 markProfileDirty((current) => ({
 ...current,
 fetch_profile: {
 ...current.fetch_profile,
 traversal_mode: null,
 },
 }));
 return;
 }
 if (TRAVERSAL_MODE_OPTIONS.has(next)) {
 markProfileDirty((current) => ({
 ...current,
 fetch_profile: {
 ...current.fetch_profile,
 traversal_mode: next,
 },
 }));
 }
 }}
 options={[
 { value: "off", label: "Off" },
 { value: "auto", label: "Auto" },
 { value: "paginate", label: "Paginate" },
 { value: "scroll", label: "Scroll" },
 { value: "load_more", label: "Load More" },
 { value: "view_all", label: "View All" },
 ]}
 />
 </div>
 </div>
 <div className={ADVANCED_SUBSECTION_CLASS}>
 <SettingSection
 label="Include iframes"
 description="Allow iframe content to participate in extraction and selector recovery."
 checked={runProfile.fetch_profile.include_iframes}
 onChange={(next) =>
 markProfileDirty((current) => ({
 ...current,
 fetch_profile: {
 ...current.fetch_profile,
 include_iframes: next,
 },
 }))
 }
 />
 <SettingSection
 label="Respect robots.txt"
 description="Skip disallowed paths and honor crawl-delay."
 checked={respectRobotsTxt}
 onChange={setRespectRobotsTxt}
 />
 </div>
 </section>

 <section className={cn(ADVANCED_COLUMN_CLASS, "xl:px-6")}>
 <div className={ADVANCED_SECTION_TITLE_CLASS}>
 <h3>Limits &amp; Locales</h3>
 <Tooltip content="Set repeat-run bounds and regional hints before dispatch.">
 <Info className="size-3 cursor-help text-muted transition-colors hover:text-secondary" />
 </Tooltip>
 </div>
 <div className={ADVANCED_SUBSECTION_CLASS}>
 <SliderRow
 label="Request Delay"
 description="Wait time between requests to the same target."
 value={String(runProfile.fetch_profile.request_delay_ms)}
 min={CRAWL_LIMITS.MIN_REQUEST_DELAY_MS}
 max={CRAWL_LIMITS.MAX_REQUEST_DELAY_MS}
 step={100}

 onChange={(next) =>
 markProfileDirty((current) => ({
 ...current,
 fetch_profile: {
 ...current.fetch_profile,
 request_delay_ms: clampNumber(
 next,
 CRAWL_LIMITS.MIN_REQUEST_DELAY_MS,
 CRAWL_LIMITS.MAX_REQUEST_DELAY_MS,
 CRAWL_DEFAULTS.REQUEST_DELAY_MS,
 ),
 },
 }))
 }
 onReset={() =>
 markProfileDirty((current) => ({
 ...current,
 fetch_profile: {
 ...current.fetch_profile,
 request_delay_ms: CRAWL_DEFAULTS.REQUEST_DELAY_MS,
 },
 }))
 }
 />
 <SliderRow
 label="Max Records"
 description="Target record count. The crawler stops after a page reaches this target; it does not trim extra rows from that page."
 value={maxRecords}
 min={CRAWL_LIMITS.MIN_RECORDS}
 max={CRAWL_LIMITS.MAX_RECORDS}
 step={10}
 onChange={setMaxRecords}
 onReset={() => setMaxRecords(String(CRAWL_DEFAULTS.MAX_RECORDS))}
 />
 </div>
 <div className={ADVANCED_SUBSECTION_CLASS}>
 <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-muted">
 <span>Locale Hints</span>
 <Tooltip content="Keep country, language, and currency aligned with the market you want to simulate.">
 <Info className="size-3 cursor-help text-muted transition-colors hover:text-secondary" />
 </Tooltip>
 </div>
 <div className={ADVANCED_CONTROL_ROW_CLASS}>
 <div className="field-label mb-0">Geo Country</div>
 <Input
 value={runProfile.locality_profile.geo_country}
 onChange={(event) =>
 markProfileDirty((current) => ({
 ...current,
 locality_profile: {
 ...current.locality_profile,
 geo_country: event.target.value.trim() || "auto",
 },
 }))
 }
 aria-label="Geo country"
 />
 </div>
 <div className={ADVANCED_CONTROL_ROW_CLASS}>
 <div className="field-label mb-0">Language Hint</div>
 <Input
 value={runProfile.locality_profile.language_hint ?? ""}
 onChange={(event) =>
 markProfileDirty((current) => ({
 ...current,
 locality_profile: {
 ...current.locality_profile,
 language_hint: event.target.value.trim() || null,
 },
 }))
 }
 aria-label="Language hint"
 />
 </div>
 <div className={ADVANCED_CONTROL_ROW_CLASS}>
 <div className="field-label mb-0">Currency Hint</div>
 <Input
 value={runProfile.locality_profile.currency_hint ?? ""}
 onChange={(event) =>
 markProfileDirty((current) => ({
 ...current,
 locality_profile: {
 ...current.locality_profile,
 currency_hint: event.target.value.trim() || null,
 },
 }))
 }
 aria-label="Currency hint"
 />
 </div>
 </div>
 </section>

 <section className={cn(ADVANCED_COLUMN_CLASS, "xl:pl-6")}>
 <div className={ADVANCED_SECTION_TITLE_CLASS}>
 <h3>Output &amp; Diagnostics</h3>
 <Tooltip content="Choose what evidence and artifacts stay attached to this run.">
 <Info className="size-3 cursor-help text-muted transition-colors hover:text-secondary" />
 </Tooltip>
 </div>
 <div className={ADVANCED_SUBSECTION_CLASS}>
 <div className={ADVANCED_CONTROL_ROW_CLASS}>
 <div className="field-label">Diagnostics</div>
 <Dropdown<DiagnosticsPreset>
 ariaLabel="Diagnostics preset"
 value={diagnosticsPreset}
 onChange={(next) => {
 if (next === "lean" || next === "standard" || next === "deep_debug") {
 markProfileDirty((current) => applyDiagnosticsPreset(current, next));
 }
 }}
 options={[
 { value: "lean", label: "Lean" },
 { value: "standard", label: "Standard" },
 { value: "deep_debug", label: "Deep Debug" },
 ]}
 />
 </div>
 <div className={ADVANCED_CONTROL_ROW_CLASS}>
 <div className="field-label">Network Capture</div>
 <Dropdown<CaptureNetworkMode>
 ariaLabel="Network capture"
 value={runProfile.diagnostics_profile.capture_network}
 onChange={(next) => {
 if (CAPTURE_NETWORK_OPTIONS.has(next)) {
 markProfileDirty((current) => ({
 ...current,
 diagnostics_profile: {
 ...current.diagnostics_profile,
 capture_network: next,
 },
 }));
 }
 }}
 options={[
 { value: "off", label: "Off" },
 { value: "matched_only", label: "Matched Only" },
 { value: "all_small_json", label: "All Small JSON" },
 ]}
 />
 </div>
 </div>
 <div className={ADVANCED_SUBSECTION_CLASS}>
 <SettingSection
 label="Capture HTML"
 description="Persist the page HTML artifact for this run."
 checked={runProfile.diagnostics_profile.capture_html}
 onChange={(next) =>
 markProfileDirty((current) => ({
 ...current,
 diagnostics_profile: {
 ...current.diagnostics_profile,
 capture_html: next,
 },
 }))
 }
 />
 <SettingSection
 label="Capture Screenshot"
 description="Store browser screenshots when available."
 checked={runProfile.diagnostics_profile.capture_screenshot}
 onChange={(next) =>
 markProfileDirty((current) => ({
 ...current,
 diagnostics_profile: {
 ...current.diagnostics_profile,
 capture_screenshot: next,
 },
 }))
 }
 />
 <SettingSection
 label="Capture Response Headers"
 description="Preserve response-header diagnostics."
 checked={runProfile.diagnostics_profile.capture_response_headers}
 onChange={(next) =>
 markProfileDirty((current) => ({
 ...current,
 diagnostics_profile: {
 ...current.diagnostics_profile,
 capture_response_headers: next,
 },
 }))
 }
 />
 <SettingSection
 label="Capture Browser Diagnostics"
 description="Keep detailed browser-attempt diagnostics for debugging."
 checked={runProfile.diagnostics_profile.capture_browser_diagnostics}
 onChange={(next) =>
 markProfileDirty((current) => ({
 ...current,
 diagnostics_profile: {
 ...current.diagnostics_profile,
 capture_browser_diagnostics: next,
 },
 }))
 }
 />
 </div>
 </section>
 </div>
 </Card>
 ) : null}
 </form>
 </div>
 );
}

function inferRunTypeHint(config: CrawlConfig) {
 if (config.module === "category") {
 return config.mode === "bulk" ? "batch" : "crawl";
 }
 if (config.mode === "csv") {
 return "csv";
 }
 if (config.mode === "batch") {
 return "batch";
 }
 return "crawl";
}

function buildExtractionContract(fieldRows: FieldRow[]) {
 const extractionContract = fieldRows
 .map((row) => {
 const fieldName = normalizeField(row.fieldName);
 const cssSelector = row.cssSelector.trim();
 const xpath = row.xpath.trim();
 const regex = row.regex.trim();
 if (!fieldName || (!cssSelector && !xpath && !regex)) {
 return null;
 }
 const reason = validateAdditionalFieldName(fieldName);
 if (reason) {
 throw new Error(`Invalid manual field "${row.fieldName || fieldName}": ${reason}`);
 }
 return {
 field_name: fieldName,
 css_selector: cssSelector || undefined,
 xpath: xpath || undefined,
 regex: regex || undefined,
 };
 })
 .filter((row): row is NonNullable<typeof row> => Boolean(row));
 return extractionContract;
}

export function buildDispatch(
 config: CrawlConfig,
 fieldRows: FieldRow[] = [],
 options?: {
 runProfile?: DomainRunProfile;
 studioMode?: StudioMode;
 },
): PendingDispatch {
 const additionalFields = uniqueRequestedFields(config.additional_fields);
 const invalidAdditionalField = additionalFields.find((field) => validateAdditionalFieldName(field));
 if (invalidAdditionalField) {
 const reason = validateAdditionalFieldName(invalidAdditionalField);
 throw new Error(`Invalid additional field "${invalidAdditionalField}": ${reason}`);
 }
 const surface = deriveSurface(config.domain, config.module);
 const runProfile = cloneRunProfile(options?.runProfile);
 const studioMode = options?.studioMode ?? "quick";
 const traversalMode = studioMode === "advanced" ? runProfile.fetch_profile.traversal_mode : null;
 const commonSettings = {
 llm_enabled: config.smart_extraction,
 advanced_enabled: studioMode === "advanced",
 advanced_mode: traversalMode,
 max_records: config.max_records,
 respect_robots_txt: config.respect_robots_txt,
 proxy_enabled: config.proxy_enabled,
 proxy_list: config.proxy_enabled ? config.proxy_lines : [],
 proxy_profile: {
 enabled: config.proxy_enabled,
 proxy_list: config.proxy_enabled ? config.proxy_lines : [],
 },
 additional_fields: additionalFields,
 crawl_module: config.module,
 crawl_mode: config.mode,
 fetch_profile: {
 ...runProfile.fetch_profile,
 traversal_mode: traversalMode,
 request_delay_ms: clampNumber(
 runProfile.fetch_profile.request_delay_ms,
 CRAWL_LIMITS.MIN_REQUEST_DELAY_MS,
 CRAWL_LIMITS.MAX_REQUEST_DELAY_MS,
 CRAWL_DEFAULTS.REQUEST_DELAY_MS,
 ),
 },
 locality_profile: { ...runProfile.locality_profile },
 diagnostics_profile: { ...runProfile.diagnostics_profile },
 extraction_contract: buildExtractionContract(fieldRows),
 };

 if (config.module === "category") {
 if (config.mode === "bulk") {
 const urls = parseLines(config.bulk_urls);
 if (!urls.length) throw new Error("Bulk crawl needs at least one URL.");
 return {
 runType: "batch",
 surface,
 url: urls[0],
 urls,
 settings: { ...commonSettings, urls },
 additionalFields,
 csvFile: null,
 };
 }
 if (!config.target_url.trim()) throw new Error("Enter a target URL.");
 return {
 runType: "crawl",
 surface,
 url: config.target_url.trim(),
 settings: commonSettings,
 additionalFields,
 csvFile: null,
 };
 }

 if (config.mode === "csv") {
 if (!config.csv_file) throw new Error("Select a CSV file.");
 return {
 runType: "csv",
 surface,
 url: config.target_url.trim() || undefined,
 settings: commonSettings,
 additionalFields,
 csvFile: config.csv_file,
 };
 }

 if (config.mode === "batch") {
 const urls = parseLines(config.bulk_urls);
 if (!urls.length) throw new Error("Batch crawl needs at least one URL.");
 return {
 runType: "batch",
 surface,
 url: urls[0],
 urls,
 settings: { ...commonSettings, urls },
 additionalFields,
 csvFile: null,
 };
 }

 if (!config.target_url.trim()) throw new Error("Enter a target URL.");
 return {
 runType: "crawl",
 surface,
 url: config.target_url.trim(),
 settings: commonSettings,
 additionalFields,
 csvFile: null,
 };
}

function canPreview(
 config: CrawlConfig,
 fieldRows: FieldRow[],
 options?: {
 runProfile?: DomainRunProfile;
 studioMode?: StudioMode;
 },
) {
 try {
 buildDispatch(config, fieldRows, options);
 return true;
 } catch {
 return false;
 }
}

function selectorGenerationFields(surface: string, fieldRows: FieldRow[], additionalFields: string[]) {
 return uniqueFields([
 ...defaultFieldsForSurface(surface),
 ...additionalFields,
 ...fieldRows.map((row) => row.fieldName),
 ]);
}

function defaultFieldsForSurface(surface: string) {
 if (surface === "job_detail") {
 return ["title", "company", "location", "salary", "apply_url"];
 }
 if (surface === "job_listing") {
 return ["title", "company", "location", "url"];
 }
 if (surface === "ecommerce_listing") {
 return ["title", "price", "image_url", "url"];
 }
 return ["title", "price", "brand", "sku", "availability", "image_url"];
}

function selectRelevantSelectorRecords(
 records: Array<{
 id: number;
 field_name: string;
 surface: string;
 is_active: boolean;
 css_selector?: string | null;
 xpath?: string | null;
 regex?: string | null;
 }>,
 surface: string,
) {
 return records
 .filter((record) => record.is_active && (record.surface === surface || record.surface === "generic"))
 .sort((left, right) => {
 const leftPriority = left.surface === surface ? 0 : 1;
 const rightPriority = right.surface === surface ? 0 : 1;
 if (leftPriority !== rightPriority) {
 return leftPriority - rightPriority;
 }
 return left.field_name.localeCompare(right.field_name);
 });
}

function buildFieldRowFromSelectorRecord(record: {
 id: number;
 field_name: string;
 css_selector?: string | null;
 xpath?: string | null;
 regex?: string | null;
}) {
 return {
 id: `domain-memory-${record.id}`,
 fieldName: record.field_name,
 cssSelector: record.css_selector ?? "",
 xpath: record.xpath ?? "",
 regex: record.regex ?? "",
 cssState: record.css_selector ? "valid" : "idle",
 xpathState: record.xpath ? "valid" : "idle",
 regexState: record.regex ? "valid" : "idle",
 } satisfies FieldRow;
}

function buildFieldRowFromSuggestion(
 fieldName: string,
 suggestion?: {
 css_selector?: string | null;
 xpath?: string | null;
 regex?: string | null;
 },
) {
 return {
 id: `generated-${fieldName}`,
 fieldName,
 cssSelector: suggestion?.css_selector ?? "",
 xpath: suggestion?.xpath ?? "",
 regex: suggestion?.regex ?? "",
 cssState: suggestion?.css_selector ? "valid" : "idle",
 xpathState: suggestion?.xpath ? "valid" : "idle",
 regexState: suggestion?.regex ? "valid" : "idle",
 } satisfies FieldRow;
}

function mergeFieldRows(currentRows: FieldRow[], incomingRows: FieldRow[]) {
 const merged = new Map<string, FieldRow>();
 for (const row of currentRows) {
 merged.set(normalizeField(row.fieldName || row.id), row);
 }
 for (const row of incomingRows) {
 const key = normalizeField(row.fieldName || row.id);
 const existing = merged.get(key);
 if (!existing) {
 merged.set(key, row);
 continue;
 }
 merged.set(key, {
 ...existing,
 fieldName: existing.fieldName || row.fieldName,
 cssSelector: existing.cssSelector || row.cssSelector,
 xpath: existing.xpath || row.xpath,
 regex: existing.regex || row.regex,
 cssState: existing.cssSelector ? existing.cssState : row.cssState,
 xpathState: existing.xpath ? existing.xpathState : row.xpathState,
 regexState: existing.regex ? existing.regexState : row.regexState,
 });
 }
 return Array.from(merged.values());
}

function CsFlowStep({ step, label, active }: Readonly<{ step: number; label: string; active: boolean }>) {
 return (
  <span className={cn(
   "inline-flex items-center gap-1.5 rounded-[var(--radius-md)] px-2.5 py-1 text-[11px] font-semibold tracking-wide transition-all",
   active
    ? "bg-accent-subtle text-accent"
    : "text-muted",
  )}>
   <span className={cn(
    "inline-flex size-4 items-center justify-center rounded-full text-[9px] font-bold",
    active
     ? "ui-on-accent-surface bg-accent"
     : "bg-border text-muted",
   )}>
    {active ? <Check className="size-2.5" /> : step}
   </span>
   {label}
  </span>
 );
}

function CsFlowConnector({ active }: Readonly<{ active: boolean }>) {
 return (
  <div className={cn("mx-0.5 h-px w-4", active ? "bg-accent" : "bg-border")} />
 );
}
