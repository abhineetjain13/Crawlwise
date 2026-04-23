"use client";

import {
 RefreshCcw,
 Pencil,
 Save,
 Search,
 Trash2,
 X,
 Database,
 SlidersHorizontal,
 Cookie,
 Activity,
} from "lucide-react";
import { useDeferredValue, useEffect, useMemo, useState } from "react";

import { EmptyPanel, InlineAlert, PageHeader, SectionCard } from "../../../components/ui/patterns";
import { Badge, Button, Card, Dropdown, Input } from "../../../components/ui/primitives";
import { api } from "../../../lib/api";
import type {
 CrawlRun,
 DomainCookieMemoryRecord,
 DomainFieldFeedbackRecord,
 DomainRunProfileRecord,
 SelectorRecord,
 SelectorUpdatePayload,
} from "../../../lib/api/types";
import { getNormalizedDomain } from "../../../lib/format/domain";
import { cn } from "../../../lib/utils";

type LocalRecord = SelectorRecord & { _uid: string };

type EditDraft = {
 field_name: string;
 kind: "xpath" | "css_selector" | "regex";
 selectorValue: string;
 source: string;
 is_active: boolean;
};

type SurfaceWorkspace = {
 surface: string;
 selectors: LocalRecord[];
 profile: DomainRunProfileRecord | null;
 learning: DomainFieldFeedbackRecord[];
 completedRuns: CrawlRun[];
};

type DomainWorkspace = {
 domain: string;
 surfaces: SurfaceWorkspace[];
 cookieMemory: DomainCookieMemoryRecord | null;
 learning: DomainFieldFeedbackRecord[];
 completedRunCount: number;
 latestCompletedAt: string | null;
};

function surfaceLabel(surface: string) {
 if (surface === "ecommerce_listing") return "Commerce Listing";
 if (surface === "ecommerce_detail") return "Commerce Detail";
 if (surface === "job_listing") return "Job Listing";
 if (surface === "job_detail") return "Job Detail";
 return surface.replace(/_/g, " ");
}

function titleCaseToken(value: string | null | undefined) {
 return String(value || "")
 .split(/[_\s]+/)
 .filter(Boolean)
 .map((token) => token.charAt(0).toUpperCase() + token.slice(1))
 .join(" ");
}

function selectorValue(record: Pick<SelectorRecord, "xpath" | "css_selector" | "regex">) {
 return record.xpath ?? record.css_selector ?? record.regex ?? "";
}

function profileSearchText(profile: DomainRunProfileRecord) {
 return [
 profile.domain,
 profile.surface,
 profile.profile.fetch_profile.fetch_mode,
 profile.profile.fetch_profile.extraction_source,
 profile.profile.fetch_profile.js_mode,
 profile.profile.fetch_profile.traversal_mode,
 profile.profile.locality_profile.geo_country,
 profile.profile.locality_profile.language_hint ?? "",
 profile.profile.locality_profile.currency_hint ?? "",
 ]
 .join(" ")
 .toLowerCase();
}

function feedbackSearchText(feedback: DomainFieldFeedbackRecord) {
 return [
 feedback.domain,
 feedback.surface,
 feedback.field_name,
 feedback.action,
 feedback.source_kind,
 feedback.source_value ?? "",
 feedback.selector_kind ?? "",
 feedback.selector_value ?? "",
 ]
 .join(" ")
 .toLowerCase();
}

function formatTimestamp(value: string | null | undefined) {
 if (!value) {
 return "—";
 }
 const parsed = new Date(value);
 if (Number.isNaN(parsed.getTime())) {
 return "—";
 }
 return parsed.toLocaleString();
}

function runProfileSummary(profile: DomainRunProfileRecord) {
 return [
 { label: "Fetch", value: titleCaseToken(profile.profile.fetch_profile.fetch_mode) },
 { label: "JS", value: titleCaseToken(profile.profile.fetch_profile.js_mode) },
 { label: "Traversal", value: titleCaseToken(profile.profile.fetch_profile.traversal_mode ?? "off") },
 { label: "Network", value: titleCaseToken(profile.profile.diagnostics_profile.capture_network) },
 ];
}

export default function DomainMemoryManagePage() {
 const [records, setRecords] = useState<LocalRecord[]>([]);
 const [profiles, setProfiles] = useState<DomainRunProfileRecord[]>([]);
 const [cookies, setCookies] = useState<DomainCookieMemoryRecord[]>([]);
 const [feedback, setFeedback] = useState<DomainFieldFeedbackRecord[]>([]);
 const [completedRuns, setCompletedRuns] = useState<CrawlRun[]>([]);
 const [loading, setLoading] = useState(true);
 const [error, setError] = useState("");
 const [selectedDomain, setSelectedDomain] = useState("");
 const [editingId, setEditingId] = useState<string | null>(null);
 const [draft, setDraft] = useState<EditDraft | null>(null);
 const [searchQuery, setSearchQuery] = useState("");
 const [surfaceFilter, setSurfaceFilter] = useState("all");
 const deferredSearchQuery = useDeferredValue(searchQuery);

 async function loadWorkspace() {
 setLoading(true);
 setError("");
 try {
 const [selectorData, profileData, cookieData, feedbackData, crawlData] = await Promise.all([
 api.listSelectors(),
 api.listDomainRunProfiles(),
 api.listDomainCookieMemory(),
 api.listDomainFieldFeedback({ limit: 100 }),
 api.listCrawls({ status: "completed", limit: 100 }),
 ]);
 setRecords(selectorData.map((record, index) => ({ ...record, _uid: `${record.id}-${index}-${Date.now()}` })));
 setProfiles(profileData);
 setCookies(cookieData);
 setFeedback(feedbackData);
 setCompletedRuns(crawlData.items);
 } catch (nextError) {
 setError(nextError instanceof Error ? nextError.message : "Unable to load domain memory.");
 } finally {
 setLoading(false);
 }
 }

 useEffect(() => {
 void loadWorkspace();
 }, []);

 const availableSurfaces = useMemo(() => {
 return Array.from(
 new Set([
 ...records.map((record) => record.surface),
 ...profiles.map((profile) => profile.surface),
 ...feedback.map((entry) => entry.surface),
 ...completedRuns.map((run) => run.surface),
 ]),
 ).sort();
 }, [completedRuns, feedback, profiles, records]);

 const groupedWorkspaces = useMemo<DomainWorkspace[]>(() => {
 const query = deferredSearchQuery.trim().toLowerCase();
 const byDomain = new Map<string, Map<string, SurfaceWorkspace>>();
 const cookiesByDomain = new Map(cookies.map((row) => [row.domain, row] as const));
 const runsByDomain = new Map<string, Map<string, CrawlRun[]>>();

 function ensureSurfaceWorkspace(domain: string, surface: string): SurfaceWorkspace {
 const domainEntry = byDomain.get(domain) ?? new Map<string, SurfaceWorkspace>();
 if (!byDomain.has(domain)) {
 byDomain.set(domain, domainEntry);
 }
 const existing = domainEntry.get(surface);
 if (existing) {
 return existing;
 }
 const created: SurfaceWorkspace = {
 surface,
 selectors: [],
 profile: null,
 learning: [],
 completedRuns: [],
 };
 domainEntry.set(surface, created);
 return created;
 }

 function ensureDomainRuns(domain: string, surface: string) {
 const domainEntry = runsByDomain.get(domain) ?? new Map<string, CrawlRun[]>();
 if (!runsByDomain.has(domain)) {
 runsByDomain.set(domain, domainEntry);
 }
 const existing = domainEntry.get(surface);
 if (existing) {
 return existing;
 }
 const created: CrawlRun[] = [];
 domainEntry.set(surface, created);
 return created;
 }

 for (const record of records) {
 if (surfaceFilter !== "all" && record.surface !== surfaceFilter) {
 continue;
 }
 const searchable = [
 record.domain,
 record.surface,
 record.field_name,
 record.source,
 selectorValue(record),
 ]
 .join(" ")
 .toLowerCase();
 if (query && !searchable.includes(query) && !record.domain.toLowerCase().includes(query)) {
 continue;
 }
 ensureSurfaceWorkspace(record.domain, record.surface).selectors.push(record);
 }

 for (const profile of profiles) {
 if (surfaceFilter !== "all" && profile.surface !== surfaceFilter) {
 continue;
 }
 if (query && !profileSearchText(profile).includes(query) && !profile.domain.toLowerCase().includes(query)) {
 continue;
 }
 ensureSurfaceWorkspace(profile.domain, profile.surface).profile = profile;
 }

 for (const row of feedback) {
 if (surfaceFilter !== "all" && row.surface !== surfaceFilter) {
 continue;
 }
 if (query && !feedbackSearchText(row).includes(query) && !row.domain.toLowerCase().includes(query)) {
 continue;
 }
 ensureSurfaceWorkspace(row.domain, row.surface).learning.push(row);
 }

 for (const run of completedRuns) {
 const domain = String(run.result_summary?.domain || "").trim() || getNormalizedDomain(run.url);
 if (!domain) {
 continue;
 }
 if (surfaceFilter !== "all" && run.surface !== surfaceFilter) {
 continue;
 }
 const searchable = [
 domain,
 run.surface,
 run.url,
 run.status,
 ]
 .join(" ")
 .toLowerCase();
 if (query && !searchable.includes(query) && !domain.toLowerCase().includes(query)) {
 continue;
 }
 ensureDomainRuns(domain, run.surface).push(run);
 ensureSurfaceWorkspace(domain, run.surface).completedRuns.push(run);
 }

 const visibleDomains = new Set<string>([
 ...byDomain.keys(),
 ...runsByDomain.keys(),
 ...cookies
 .filter((row) => {
 if (!query) {
 return surfaceFilter === "all";
 }
 return row.domain.toLowerCase().includes(query);
 })
 .map((row) => row.domain),
 ]);

 return Array.from(visibleDomains)
 .map((domain) => {
 const surfaces = Array.from((byDomain.get(domain) ?? new Map<string, SurfaceWorkspace>()).values())
 .sort((left, right) => left.surface.localeCompare(right.surface));
 const completedRunCount = surfaces.reduce((count, surface) => count + surface.completedRuns.length, 0);
 const latestCompletedAt =
 surfaces
 .flatMap((surface) => surface.completedRuns)
 .map((run) => run.completed_at ?? run.updated_at ?? run.created_at)
 .filter(Boolean)
 .sort((left, right) => new Date(right).getTime() - new Date(left).getTime())[0] ?? null;
 return {
 domain,
 surfaces,
 cookieMemory: cookiesByDomain.get(domain) ?? null,
 learning: surfaces.flatMap((surface) => surface.learning),
 completedRunCount,
 latestCompletedAt,
 };
 })
 .filter((entry) => entry.surfaces.length || entry.cookieMemory)
 .sort((left, right) => {
 const completedDelta = right.completedRunCount - left.completedRunCount;
 if (completedDelta !== 0) {
 return completedDelta;
 }
 const leftTime = left.latestCompletedAt ? new Date(left.latestCompletedAt).getTime() : 0;
 const rightTime = right.latestCompletedAt ? new Date(right.latestCompletedAt).getTime() : 0;
 if (rightTime !== leftTime) {
 return rightTime - leftTime;
 }
 const leftMemoryScore =
 left.surfaces.reduce((count, surface) => count + surface.selectors.length, 0) +
 left.surfaces.filter((surface) => surface.profile).length +
 left.learning.length +
 (left.cookieMemory ? 1 : 0);
 const rightMemoryScore =
 right.surfaces.reduce((count, surface) => count + surface.selectors.length, 0) +
 right.surfaces.filter((surface) => surface.profile).length +
 right.learning.length +
 (right.cookieMemory ? 1 : 0);
 if (rightMemoryScore !== leftMemoryScore) {
 return rightMemoryScore - leftMemoryScore;
 }
 return left.domain.localeCompare(right.domain);
 });
 }, [completedRuns, cookies, deferredSearchQuery, feedback, profiles, records, surfaceFilter]);

 useEffect(() => {
 if (!groupedWorkspaces.length) {
 setSelectedDomain("");
 return;
 }
 if (!selectedDomain || !groupedWorkspaces.some((entry) => entry.domain === selectedDomain)) {
 setSelectedDomain(groupedWorkspaces[0].domain);
 }
 }, [groupedWorkspaces, selectedDomain]);

 const selectedWorkspace = useMemo(
 () => groupedWorkspaces.find((entry) => entry.domain === selectedDomain) ?? groupedWorkspaces[0] ?? null,
 [groupedWorkspaces, selectedDomain],
 );

 const summary = useMemo(() => {
 const visibleDomains = groupedWorkspaces.length;
 const visibleSurfaces = groupedWorkspaces.reduce((count, entry) => count + entry.surfaces.length, 0);
 const visibleSelectors = groupedWorkspaces.reduce(
 (count, entry) => count + entry.surfaces.reduce((surfaceCount, surface) => surfaceCount + surface.selectors.length, 0),
 0,
 );
 const visibleProfiles = groupedWorkspaces.reduce(
 (count, entry) => count + entry.surfaces.filter((surface) => surface.profile).length,
 0,
 );
 const visibleLearning = groupedWorkspaces.reduce((count, entry) => count + entry.learning.length, 0);
 const visibleCookieDomains = groupedWorkspaces.filter((entry) => entry.cookieMemory).length;
 return {
 domains: visibleDomains,
 surfaces: visibleSurfaces,
 selectors: visibleSelectors,
 profiles: visibleProfiles,
 learning: visibleLearning,
 cookies: visibleCookieDomains,
 };
 }, [groupedWorkspaces]);

 function startEdit(record: LocalRecord) {
 setEditingId(record._uid);
 setDraft({
 field_name: record.field_name,
 kind: record.xpath ? "xpath" : record.css_selector ? "css_selector" : "regex",
 selectorValue: selectorValue(record),
 source: record.source,
 is_active: record.is_active,
 });
 }

 function cancelEdit() {
 setEditingId(null);
 setDraft(null);
 }

 async function saveEdit(record: LocalRecord) {
 if (!draft) {
 return;
 }
 const payload: SelectorUpdatePayload = {
 field_name: draft.field_name,
 xpath: draft.kind === "xpath" ? draft.selectorValue : null,
 css_selector: draft.kind === "css_selector" ? draft.selectorValue : null,
 regex: draft.kind === "regex" ? draft.selectorValue : null,
 source: draft.source,
 is_active: draft.is_active,
 };
 try {
 const updated = await api.updateSelector(record.id, payload);
 setRecords((current) =>
 current.map((entry) => (entry._uid === record._uid ? { ...updated, _uid: record._uid } : entry)),
 );
 cancelEdit();
 } catch (nextError) {
 setError(nextError instanceof Error ? nextError.message : "Unable to save selector.");
 }
 }

 async function toggleActive(record: LocalRecord) {
 try {
 const updated = await api.updateSelector(record.id, { is_active: !record.is_active });
 setRecords((current) =>
 current.map((entry) => (entry._uid === record._uid ? { ...updated, _uid: record._uid } : entry)),
 );
 } catch (nextError) {
 setError(nextError instanceof Error ? nextError.message : "Unable to update selector state.");
 }
 }

 async function deleteRecord(record: LocalRecord) {
 try {
 await api.deleteSelector(record.id);
 setRecords((current) => current.filter((entry) => entry._uid !== record._uid));
 if (editingId === record._uid) {
 cancelEdit();
 }
 } catch (nextError) {
 setError(nextError instanceof Error ? nextError.message : "Unable to delete selector.");
 }
 }

 async function deleteDomainSelectors(domain: string) {
 try {
 await api.deleteSelectorsByDomain(domain);
 setRecords((current) => current.filter((entry) => entry.domain !== domain));
 if (records.find((record) => record._uid === editingId)?.domain === domain) {
 cancelEdit();
 }
 } catch (nextError) {
 setError(nextError instanceof Error ? nextError.message : "Unable to clear domain selectors.");
 }
 }

 return (
 <div className="page-stack">
 <PageHeader
 title="Domain Memory"
 description="Manage learned selectors, run profiles, cookies, and recent learning by domain."
 actions={
 <Button type="button" variant="secondary" onClick={() => void loadWorkspace()} disabled={loading}>
 <RefreshCcw className="size-3.5" />
 {loading ? "Refreshing..." : "Refresh"}
 </Button>
 }
 />

 <SectionCard
 title="Memory Workspace"
 description="Search across selector memory, saved defaults, cookies, and field feedback, then inspect one domain at a time."
 >
 {error ? <InlineAlert message={error} /> : null}
 <div className="grid gap-3 pt-4 xl:grid-cols-[minmax(0,1.2fr)_220px]">
 <label className="grid gap-1.5">
 <span className="field-label">Search domains, selectors, run defaults, or learning</span>
 <div className="relative">
 <Input
 value={searchQuery}
 onChange={(event) => setSearchQuery(event.target.value)}
 placeholder="Search domain, field, selector text, fetch mode, or feedback"
 className="h-[var(--control-height)] pl-10 leading-normal"
 />
 <Search className="pointer-events-none absolute left-3 top-1/2 z-10 size-4 -translate-y-1/2 text-muted" />
 </div>
 </label>
 <label className="grid gap-1.5">
 <span className="field-label">Surface</span>
 <Dropdown<string>
 value={surfaceFilter}
 onChange={setSurfaceFilter}
 options={[
 { value: "all", label: "All surfaces" },
 ...availableSurfaces.map((surface) => ({ value: surface, label: surfaceLabel(surface) })),
 ]}
 />
 </label>
 </div>

 <div className="grid gap-2 pt-4 sm:grid-cols-2 xl:grid-cols-6">
 {[
 { label: "Domains", value: summary.domains },
 { label: "Surfaces", value: summary.surfaces },
 { label: "Selectors", value: summary.selectors },
 { label: "Saved Profiles", value: summary.profiles },
 { label: "Recent Learning", value: summary.learning },
 { label: "Cookie Domains", value: summary.cookies },
 ].map((item) => (
 <div
 key={item.label}
 className="rounded-[var(--radius-lg)] border border-border bg-background-elevated px-3 py-2"
 >
 <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">{item.label}</div>
 <div className="pt-1 text-lg font-semibold text-foreground">{item.value}</div>
 </div>
 ))}
 </div>
 </SectionCard>

 {loading ? (
 <Card className="section-card">
 <p className="text-sm text-muted">Loading domain memory workspace…</p>
 </Card>
 ) : !groupedWorkspaces.length ? (
 <EmptyPanel
 title="No domain memory found"
 description="Run a crawl, save selectors, or keep learning signals to populate this workspace."
 />
 ) : (
 <div className="grid gap-4 xl:grid-cols-[280px_minmax(0,1fr)]">
 <Card className="section-card">
 <div className="space-y-4">
 <div>
 <div className="text-sm font-semibold text-foreground">Domains</div>
 <p className="mt-1 text-sm leading-[1.5] text-secondary">Choose a domain to inspect persisted memory and recent learning.</p>
 </div>
 <div className="space-y-2">
 {groupedWorkspaces.map((workspace) => {
 const selectorCount = workspace.surfaces.reduce((count, surface) => count + surface.selectors.length, 0);
 const profileCount = workspace.surfaces.filter((surface) => surface.profile).length;
 const learningCount = workspace.learning.length;
 const isActive = workspace.domain === selectedWorkspace?.domain;
 return (
 <button
 key={workspace.domain}
 type="button"
 onClick={() => setSelectedDomain(workspace.domain)}
 className={cn(
 "w-full rounded-[var(--radius-xl)] border px-3 py-3 text-left transition-colors",
 isActive
 ? "border-[var(--accent)] bg-[var(--subtle-panel-bg)] shadow-card"
 : "border-[var(--divider)] bg-background hover:bg-background-elevated",
 )}
 >
 <div className="flex items-center justify-between gap-3">
 <div className="min-w-0">
 <div className="truncate text-sm font-semibold text-foreground">{workspace.domain}</div>
 <div className="mt-2 flex flex-wrap gap-2 text-xs text-muted">
 <span>{workspace.completedRunCount} runs</span>
 <span>{selectorCount} selectors</span>
 <span>{profileCount} profiles</span>
 <span>{learningCount} learning</span>
 </div>
 </div>
 {workspace.cookieMemory ? <Badge tone="accent">{workspace.cookieMemory.cookie_count} cookies</Badge> : null}
 </div>
 </button>
 );
 })}
 </div>
 </div>
 </Card>

 <div className="space-y-4">
 {selectedWorkspace ? (
 <>
 <Card className="section-card">
 <div className="flex flex-wrap items-start justify-between gap-3">
 <div className="space-y-2">
 <div className="text-lg font-semibold text-foreground">{selectedWorkspace.domain}</div>
 <p className="text-sm leading-[1.5] text-secondary">
 Surface-scoped selectors and run defaults live together here, while cookie memory remains domain-scoped because acquisition reuse is host-level.
 </p>
 <div className="flex flex-wrap gap-2">
 <Badge tone="neutral">
 {selectedWorkspace.surfaces.reduce((count, surface) => count + surface.selectors.length, 0)} selectors
 </Badge>
 <Badge tone="info">
 {selectedWorkspace.surfaces.filter((surface) => surface.profile).length} profiles
 </Badge>
 <Badge tone="success">{selectedWorkspace.learning.length} learning events</Badge>
 {selectedWorkspace.cookieMemory ? <Badge tone="accent">{selectedWorkspace.cookieMemory.cookie_count} cookies</Badge> : null}
 </div>
 </div>
 <Button
 type="button"
 variant="danger"
 onClick={() => void deleteDomainSelectors(selectedWorkspace.domain)}
 disabled={!selectedWorkspace.surfaces.some((surface) => surface.selectors.length)}
 >
 <Trash2 className="size-3.5" />
 Clear Selectors
 </Button>
 </div>
 </Card>

 <div className="grid gap-4 xl:grid-cols-[minmax(0,1.45fr)_minmax(300px,0.9fr)]">
 <Card className="section-card">
 <div className="space-y-4">
 <div className="flex items-center gap-2">
 <Database className="size-4 text-muted" />
 <div>
 <div className="text-base font-semibold text-foreground">Selector Memory</div>
 <p className="text-sm leading-[1.5] text-secondary">Review and edit the selectors currently saved for this domain.</p>
 </div>
 </div>

 {selectedWorkspace.surfaces.length ? (
 <div className="space-y-4">
 {selectedWorkspace.surfaces.map((surfaceWorkspace) => (
 <div
 key={`${selectedWorkspace.domain}:${surfaceWorkspace.surface}`}
 className="rounded-[var(--radius-xl)] border border-[var(--subtle-panel-border)] bg-[var(--subtle-panel-bg)] p-4"
 >
 <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
 <div>
 <div className="text-sm font-semibold text-foreground">{surfaceLabel(surfaceWorkspace.surface)}</div>
 <div className="text-xs text-muted">
 {surfaceWorkspace.selectors.length} selector{surfaceWorkspace.selectors.length === 1 ? "" : "s"}
 </div>
 </div>
 {surfaceWorkspace.profile ? <Badge tone="info">profile saved</Badge> : <Badge tone="neutral">no saved profile</Badge>}
 </div>

 {surfaceWorkspace.selectors.length ? (
 <div className="space-y-3">
 {surfaceWorkspace.selectors.map((record) => {
 const isEditing = editingId === record._uid && draft !== null;
 return (
 <div key={record._uid} className="rounded-lg border border-[var(--divider)] bg-background px-3 py-3">
 {isEditing ? (
 <div className="space-y-3">
 <div className="grid gap-3 md:grid-cols-2">
 <label className="grid gap-1.5">
 <span className="field-label">Field</span>
 <Input
 value={draft.field_name}
 onChange={(event) => setDraft((current) => (current ? { ...current, field_name: event.target.value } : current))}
 />
 </label>
 <label className="grid gap-1.5">
 <span className="field-label">Source</span>
 <Input
 value={draft.source}
 onChange={(event) => setDraft((current) => (current ? { ...current, source: event.target.value } : current))}
 />
 </label>
 </div>
 <label className="grid gap-1.5">
 <span className="field-label">Selector Kind</span>
 <select
 value={draft.kind}
 onChange={(event) =>
 setDraft((current) =>
 current ? { ...current, kind: event.target.value as EditDraft["kind"] } : current,
 )
 }
 className="rounded-[var(--radius-md)] border border-[var(--divider)] bg-background px-3 py-2 text-sm"
 >
 <option value="css_selector">CSS Selector</option>
 <option value="xpath">XPath</option>
 <option value="regex">Regex</option>
 </select>
 </label>
 <label className="grid gap-1.5">
 <span className="field-label">Selector</span>
 <Input
 value={draft.selectorValue}
 onChange={(event) =>
 setDraft((current) => (current ? { ...current, selectorValue: event.target.value } : current))
 }
 />
 </label>
 <label className="flex items-center gap-2 text-sm text-secondary">
 <input
 type="checkbox"
 checked={draft.is_active}
 onChange={(event) =>
 setDraft((current) => (current ? { ...current, is_active: event.target.checked } : current))
 }
 />
 Active selector
 </label>
 <div className="flex flex-wrap gap-2">
 <Button type="button" variant="accent" onClick={() => void saveEdit(record)}>
 <Save className="size-3.5" />
 Save
 </Button>
 <Button type="button" variant="ghost" onClick={cancelEdit}>
 <X className="size-3.5" />
 Cancel
 </Button>
 </div>
 </div>
 ) : (
 <div className="flex flex-wrap items-start justify-between gap-3">
 <div className="min-w-0 flex-1">
 <div className="flex flex-wrap items-center gap-2">
 <span className="font-medium text-foreground">{record.field_name}</span>
 <Badge tone={record.is_active ? "success" : "warning"}>
 {record.is_active ? "active" : "inactive"}
 </Badge>
 <Badge tone="neutral">{titleCaseToken(record.source)}</Badge>
 </div>
 <code className="mt-2 block break-all text-xs text-secondary">{selectorValue(record)}</code>
 {record.sample_value ? <div className="mt-2 text-xs text-muted">Sample: {record.sample_value}</div> : null}
 </div>
 <div className="flex flex-wrap gap-2">
 <Button type="button" variant="ghost" onClick={() => startEdit(record)}>
 <Pencil className="size-3.5" />
 Edit
 </Button>
 <Button type="button" variant="ghost" onClick={() => void toggleActive(record)}>
 {record.is_active ? "Disable" : "Enable"}
 </Button>
 <Button type="button" variant="danger" onClick={() => void deleteRecord(record)}>
 <Trash2 className="size-3.5" />
 Delete
 </Button>
 </div>
 </div>
 )}
 </div>
 );
 })}
 </div>
 ) : (
 <div className="rounded-lg border border-dashed border-[var(--divider)] px-3 py-3 text-sm text-muted">
 No selectors saved for this surface yet.
 </div>
 )}
 </div>
 ))}
 </div>
 ) : (
 <EmptyPanel
 title="No saved selector memory"
 description="Selectors promoted from completed runs will appear here once they are saved."
 />
 )}
 </div>
 </Card>

 <div className="space-y-4">
 <Card className="section-card">
 <div className="space-y-4">
 <div className="flex items-center gap-2">
 <SlidersHorizontal className="size-4 text-muted" />
 <div>
 <div className="text-base font-semibold text-foreground">Run Profile Defaults</div>
 <p className="text-sm leading-[1.5] text-secondary">Saved fetch and diagnostics defaults that will be reused for future runs on this domain.</p>
 </div>
 </div>
 {selectedWorkspace.surfaces.some((surface) => surface.profile) ? (
 <div className="space-y-3">
 {selectedWorkspace.surfaces
 .filter((surface) => surface.profile)
 .map((surface) => (
 <div key={`${selectedWorkspace.domain}:${surface.surface}:profile`} className="rounded-lg border border-[var(--divider)] bg-background px-3 py-3">
 <div className="flex items-center justify-between gap-2">
 <div className="text-sm font-semibold text-foreground">{surfaceLabel(surface.surface)}</div>
 <div className="text-xs text-muted">Saved {formatTimestamp(surface.profile?.updated_at ?? null)}</div>
 </div>
 <div className="mt-3 grid gap-2 sm:grid-cols-2">
 {runProfileSummary(surface.profile!).map((item) => (
 <div key={`${surface.surface}:${item.label}`} className="rounded-[var(--radius-md)] bg-background-elevated px-2.5 py-2">
 <div className="text-[11px] uppercase tracking-[0.08em] text-muted">{item.label}</div>
 <div className="pt-1 text-sm font-medium text-foreground">{item.value}</div>
 </div>
 ))}
 </div>
 <div className="mt-3 text-xs text-muted">
 Geo: {surface.profile?.profile.locality_profile.geo_country || "auto"} · Language: {surface.profile?.profile.locality_profile.language_hint || "—"} · Currency: {surface.profile?.profile.locality_profile.currency_hint || "—"}
 </div>
 </div>
 ))}
 </div>
 ) : (
 <EmptyPanel
 title="No saved run profiles"
 description="Use the Run Config tab on a completed crawl to save reusable defaults for this domain."
 />
 )}
 </div>
 </Card>

 <Card className="section-card">
 <div className="space-y-4">
 <div className="flex items-center gap-2">
 <Cookie className="size-4 text-muted" />
 <div>
 <div className="text-base font-semibold text-foreground">Saved Domain Cookies</div>
 <p className="text-sm leading-[1.5] text-secondary">Cookie memory is stored at the domain level so acquisition can reuse known session context.</p>
 </div>
 </div>
 {selectedWorkspace.cookieMemory ? (
 <div className="rounded-lg border border-[var(--divider)] bg-background px-3 py-3">
 <div className="grid gap-3 sm:grid-cols-2">
 <div>
 <div className="text-[11px] uppercase tracking-[0.08em] text-muted">Cookies</div>
 <div className="pt-1 text-lg font-semibold text-foreground">{selectedWorkspace.cookieMemory.cookie_count}</div>
 </div>
 <div>
 <div className="text-[11px] uppercase tracking-[0.08em] text-muted">Origins</div>
 <div className="pt-1 text-lg font-semibold text-foreground">{selectedWorkspace.cookieMemory.origin_count}</div>
 </div>
 </div>
 <div className="mt-3 text-xs text-muted">Updated {formatTimestamp(selectedWorkspace.cookieMemory.updated_at)}</div>
 </div>
 ) : (
 <EmptyPanel
 title="No cookie memory saved"
 description="A successful authenticated or protected acquisition run will populate cookie memory here."
 />
 )}
 </div>
 </Card>

 <Card className="section-card">
 <div className="space-y-4">
 <div className="flex items-center gap-2">
 <Activity className="size-4 text-muted" />
 <div>
 <div className="text-base font-semibold text-foreground">Recent Learning</div>
 <p className="text-sm leading-[1.5] text-secondary">Latest keep and reject decisions captured for this domain across all surfaces.</p>
 </div>
 </div>
 {selectedWorkspace.learning.length ? (
 <div className="space-y-2">
 {selectedWorkspace.learning.slice(0, 8).map((row) => (
 <div key={row.id} className="rounded-lg border border-[var(--divider)] bg-background px-3 py-3">
 <div className="flex flex-wrap items-center gap-2">
 <Badge tone={row.action === "reject" ? "warning" : "success"}>{row.action}</Badge>
 <span className="text-sm font-medium text-foreground">{row.field_name}</span>
 <Badge tone="neutral">{surfaceLabel(row.surface)}</Badge>
 </div>
 <div className="mt-2 text-xs text-secondary">
 Source: {row.source_kind}
 {row.source_value ? ` · Value: ${row.source_value}` : ""}
 </div>
 {row.selector_value ? <code className="mt-2 block break-all text-xs text-muted">{row.selector_value}</code> : null}
 <div className="mt-2 text-xs text-muted">{formatTimestamp(row.created_at)}</div>
 </div>
 ))}
 </div>
 ) : (
 <EmptyPanel
 title="No recent learning"
 description="Use the Learning tab on a completed run to keep or reject field evidence and populate this history."
 />
 )}
 </div>
 </Card>
 </div>
 </div>
 </>
 ) : null}
 </div>
 </div>
 )}
 </div>
 );
}
