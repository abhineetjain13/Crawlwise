"use client";

import { ChevronDown, ChevronUp, Pencil, RefreshCcw, Save, Search, Trash2, X } from"lucide-react";
import { useDeferredValue, useEffect, useMemo, useState } from"react";

import { EmptyPanel, InlineAlert, PageHeader, SectionCard } from"../../../components/ui/patterns";
import { Badge, Button, Card, Dropdown, Input } from"../../../components/ui/primitives";
import { api } from"../../../lib/api";
import type { SelectorRecord, SelectorUpdatePayload } from"../../../lib/api/types";
import { cn } from"../../../lib/utils";

type LocalRecord = SelectorRecord & { _uid: string };

type EditDraft = {
 field_name: string;
 surface: string;
 kind:"xpath"|"css_selector"|"regex";
 selectorValue: string;
 source: string;
 is_active: boolean;
};

export default function DomainMemoryManagePage() {
 const [records, setRecords] = useState<LocalRecord[]>([]);
 const [loading, setLoading] = useState(true);
 const [error, setError] = useState("");
 const [editingId, setEditingId] = useState<string | null>(null);
 const [draft, setDraft] = useState<EditDraft | null>(null);
 const [searchQuery, setSearchQuery] = useState("");
 const [surfaceFilter, setSurfaceFilter] = useState("all");
 const [collapsedDomains, setCollapsedDomains] = useState<Record<string, boolean>>({});
 const deferredSearchQuery = useDeferredValue(searchQuery);

 async function loadRecords() {
 setLoading(true);
 setError("");
 try {
 const data = await api.listSelectors();
 setRecords(data.map((r, i) => ({ ...r, _uid: `${r.id}-${i}-${Date.now()}` })));
 } catch (nextError) {
 setError(nextError instanceof Error ? nextError.message :"Unable to load domain memory.");
 } finally {
 setLoading(false);
 }
 }

 useEffect(() => {
 void loadRecords();
 }, []);

 const availableSurfaces = useMemo(() => {
 return Array.from(new Set(records.map((record) => record.surface))).sort();
 }, [records]);

 const filteredRecords = useMemo(() => {
 const query = deferredSearchQuery.trim().toLowerCase();
 return records.filter((record) => {
 if (surfaceFilter !== "all" && record.surface !== surfaceFilter) {
 return false;
 }
 if (!query) {
 return true;
 }
 const selectorValue = record.xpath ?? record.css_selector ?? record.regex ?? "";
 return [
 record.domain,
 record.surface,
 record.field_name,
 record.source,
 selectorValue,
 ]
 .join(" ")
 .toLowerCase()
 .includes(query);
 });
 }, [deferredSearchQuery, records, surfaceFilter]);

 const summary = useMemo(() => {
 const surfaces = new Set(filteredRecords.map((record) => record.surface));
 const domains = new Set(filteredRecords.map((record) => record.domain));
 const activeCount = filteredRecords.filter((record) => record.is_active).length;
 return {
 domains: domains.size,
 selectors: filteredRecords.length,
 active: activeCount,
 surfaces: surfaces.size,
 };
 }, [filteredRecords]);

 const groupedRecords = useMemo(() => {
 const grouped = new Map<string, LocalRecord[]>();
 for (const record of filteredRecords) {
 const key = record.domain;
 grouped.set(key, [...(grouped.get(key) ?? []), record]);
 }
 return Array.from(grouped.entries()).sort(([left], [right]) => left.localeCompare(right));
 }, [filteredRecords]);

 useEffect(() => {
 setCollapsedDomains((current) => {
 const next = { ...current };
 for (const record of records) {
 if (!(record.domain in next)) {
 next[record.domain] = true;
 }
 }
 return next;
 });
 }, [records]);

 function toggleDomain(domain: string) {
 setCollapsedDomains((current) => ({ ...current, [domain]: !current[domain] }));
 }

 function expandVisibleDomains() {
 setCollapsedDomains((current) => ({
 ...current,
 ...Object.fromEntries(groupedRecords.map(([domain]) => [domain, false])),
 }));
 }

 function collapseVisibleDomains() {
 setCollapsedDomains((current) => ({
 ...current,
 ...Object.fromEntries(groupedRecords.map(([domain]) => [domain, true])),
 }));
 }

 function startEdit(record: LocalRecord) {
 setEditingId(record._uid);
 setDraft({
 field_name: record.field_name,
 surface: record.surface,
 kind: record.xpath ?"xpath": record.css_selector ?"css_selector":"regex",
 selectorValue: record.xpath ?? record.css_selector ?? record.regex ??"",
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
 xpath: draft.kind ==="xpath"? draft.selectorValue : null,
 css_selector: draft.kind ==="css_selector"? draft.selectorValue : null,
 regex: draft.kind ==="regex"? draft.selectorValue : null,
 source: draft.source,
 is_active: draft.is_active,
 };
 try {
 const updated = await api.updateSelector(record.id, payload);
 setRecords((current) => current.map((entry) => (entry._uid === record._uid ? { ...updated, _uid: record._uid } : entry)));
 cancelEdit();
 } catch (nextError) {
 setError(nextError instanceof Error ? nextError.message :"Unable to save selector.");
 }
 }

 async function toggleActive(record: LocalRecord) {
 try {
 const updated = await api.updateSelector(record.id, { is_active: !record.is_active });
 setRecords((current) => current.map((entry) => (entry._uid === record._uid ? { ...updated, _uid: record._uid } : entry)));
 } catch (nextError) {
 setError(nextError instanceof Error ? nextError.message :"Unable to update selector state.");
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
 setError(nextError instanceof Error ? nextError.message :"Unable to delete selector.");
 }
 }

 async function deleteDomain(domain: string) {
 try {
 await api.deleteSelectorsByDomain(domain);
 setRecords((current) => current.filter((entry) => entry.domain !== domain));
 if (draft && records.find((record) => record._uid === editingId)?.domain === domain) {
 cancelEdit();
 }
 } catch (nextError) {
 setError(nextError instanceof Error ? nextError.message :"Unable to clear domain memory.");
 }
 }

 return (
 <div className="page-stack">
 <PageHeader title="Domain Memory"/>

 <SectionCard
 title="Saved Selectors"
 description="Search, filter, and compress selector memory by domain so large selector sets stay manageable."
 action={
 <Button type="button"variant="secondary"onClick={() => void loadRecords()} disabled={loading}>
 <RefreshCcw className="size-3.5"/>
 {loading ?"Refreshing...":"Refresh"}
 </Button>
 }
 >
 {error ? <InlineAlert message={error} /> : null}
 <div className="grid gap-3 pt-4 xl:grid-cols-[minmax(0,1.2fr)_220px_auto]">
 <label className="grid gap-1.5">
 <span className="field-label">Search domains, fields, or selectors</span>
 <div className="relative">
 <Input
 value={searchQuery}
 onChange={(event) => setSearchQuery(event.target.value)}
 placeholder="Search domain, field, source, or selector text"
 className="pl-9"
 />
 <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted"/>
 </div>
 </label>
 <label className="grid gap-1.5">
 <span className="field-label">Surface</span>
 <Dropdown<string>
 value={surfaceFilter}
 onChange={setSurfaceFilter}
 options={[
 { value: "all", label: "All surfaces" },
 ...availableSurfaces.map((surface) => ({ value: surface, label: surface })),
 ]}
 />
 </label>
 <div className="flex flex-wrap items-end justify-end gap-2">
 <Button type="button" variant="ghost" onClick={expandVisibleDomains} disabled={!groupedRecords.length}>
 <ChevronDown className="size-3.5"/>
 Expand all
 </Button>
 <Button type="button" variant="ghost" onClick={collapseVisibleDomains} disabled={!groupedRecords.length}>
 <ChevronUp className="size-3.5"/>
 Collapse all
 </Button>
 </div>
 </div>
 <div className="grid gap-2 pt-4 sm:grid-cols-2 xl:grid-cols-4">
 {[
 { label: "Domains", value: summary.domains },
 { label: "Selectors", value: summary.selectors },
 { label: "Active", value: summary.active },
 { label: "Surfaces", value: summary.surfaces },
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
 <p className="text-sm text-muted">Loading selector memory…</p>
 </Card>
 ) : groupedRecords.length ? (
 groupedRecords.map(([domain, domainRecords]) => (
 <Card key={domain} className="section-card">
 <div className="space-y-4">
 <div className="flex flex-wrap items-start justify-between gap-3">
 <div className="min-w-0 flex-1 space-y-3">
 <div className="flex flex-wrap items-center gap-2">
 <button
 type="button"
 onClick={() => toggleDomain(domain)}
 className="inline-flex items-center gap-2 text-left"
 >
 <span className="text-base font-semibold text-foreground">{domain}</span>
 {collapsedDomains[domain] ? (
 <ChevronDown className="size-4 text-muted"/>
 ) : (
 <ChevronUp className="size-4 text-muted"/>
 )}
 </button>
 <Badge tone="neutral">{domainRecords.length} selector{domainRecords.length === 1 ? "" : "s"}</Badge>
 <Badge tone="info">
 {new Set(domainRecords.map((record) => record.surface)).size} surface{new Set(domainRecords.map((record) => record.surface)).size === 1 ? "" : "s"}
 </Badge>
 <Badge tone="success">
 {domainRecords.filter((record) => record.is_active).length} active
 </Badge>
 </div>
 <div className="flex flex-wrap gap-2">
 {Array.from(new Set(domainRecords.map((record) => record.surface)))
 .sort()
 .map((surface) => (
 <Badge key={surface} tone="neutral" className="font-mono">
 {surface}
 </Badge>
 ))}
 </div>
 </div>
 <div className="flex flex-wrap gap-2">
 <Button type="button" variant="ghost" onClick={() => toggleDomain(domain)}>
 {collapsedDomains[domain] ? "Show selectors" : "Hide selectors"}
 </Button>
 <Button type="button"variant="danger"onClick={() => void deleteDomain(domain)}>
 <Trash2 className="size-3.5"/>
 Delete Domain
 </Button>
 </div>
 </div>
 {!collapsedDomains[domain] ? (
 <div className="space-y-2">
 {domainRecords
 .slice()
 .sort((left, right) =>
 `${left.surface}:${left.field_name}`.localeCompare(`${right.surface}:${right.field_name}`),
 )
 .map((record) => {
 const isEditing = editingId === record._uid && draft;
 return (
 <div
 key={record._uid}
 className={cn(
 "rounded-[var(--radius-lg)] border border-border bg-background-elevated px-3 py-3",
 isEditing && "ring-1 ring-[var(--accent)]/35",
 )}
 >
 {isEditing ? (
 <div className="grid gap-3">
 <div className="grid gap-3 xl:grid-cols-[minmax(0,0.8fr)_160px_140px_auto]">
 <label className="grid gap-1">
 <span className="field-label">Field Name</span>
 <Input value={draft.field_name} onChange={(event) => setDraft({ ...draft, field_name: event.target.value })} />
 </label>
 <label className="grid gap-1">
 <span className="field-label">Surface</span>
 <Input value={draft.surface} disabled />
 </label>
 <label className="grid gap-1">
 <span className="field-label">Type</span>
 <Dropdown<EditDraft["kind"]>
 value={draft.kind}
 onChange={(kind) => setDraft({ ...draft, kind })}
 options={[
 { value:"xpath", label:"XPath"},
 { value:"css_selector", label:"CSS"},
 { value:"regex", label:"Regex"},
 ]}
 />
 </label>
 <div className="flex items-end justify-end gap-2">
 <Button type="button"variant="secondary"onClick={cancelEdit}>
 <X className="size-3.5"/>
 Cancel
 </Button>
 <Button type="button"variant="accent"onClick={() => void saveEdit(record)}>
 <Save className="size-3.5"/>
 Save
 </Button>
 </div>
 </div>
 <label className="grid gap-1">
 <span className="field-label">Selector Value</span>
 <Input
 value={draft.selectorValue}
 onChange={(event) => setDraft({ ...draft, selectorValue: event.target.value })}
 className="font-mono text-sm"
 />
 </label>
 <div className="flex flex-wrap items-center gap-2">
 <Badge tone={draft.is_active ?"success":"warning"}>{draft.is_active ?"active":"inactive"}</Badge>
 <Badge tone="neutral">{draft.source}</Badge>
 <Button type="button"variant="secondary"onClick={() => setDraft({ ...draft, is_active: !draft.is_active })}>
 {draft.is_active ?"Deactivate":"Activate"}
 </Button>
 </div>
 </div>
 ) : (
 <div className="grid gap-3 xl:grid-cols-[minmax(0,220px)_minmax(0,1fr)_auto] xl:items-center">
 <div className="min-w-0 space-y-2">
 <div className="truncate text-sm font-semibold text-foreground">{record.field_name}</div>
 <div className="flex flex-wrap items-center gap-2">
 <Badge tone="info">{record.surface}</Badge>
 <Badge tone={record.is_active ?"success":"warning"}>{record.is_active ?"active":"inactive"}</Badge>
 <Badge tone="neutral">{record.xpath ?"XPath": record.css_selector ?"CSS":"Regex"}</Badge>
 </div>
 </div>
 <div className="min-w-0 space-y-2">
 <div
 className="rounded-[var(--radius-md)] border border-[var(--divider)] bg-[var(--bg-panel)] px-3 py-2 font-mono text-xs leading-5 text-muted"
 title={record.xpath ?? record.css_selector ?? record.regex ??""}
 >
 <div className="flex items-center justify-between gap-3">
 <span className="field-label">Selector</span>
 <span className="truncate text-[11px] uppercase tracking-[0.08em] text-muted">{record.source}</span>
 </div>
 <div className="pt-1 break-all text-[13px] text-foreground">
 {record.xpath ?? record.css_selector ?? record.regex ??""}
 </div>
 </div>
 </div>
 <div className="flex flex-wrap items-center justify-end gap-2 xl:flex-col xl:items-end">
 <Button type="button"variant="ghost"size="sm"onClick={() => void toggleActive(record)}>
 {record.is_active ?"Deactivate":"Activate"}
 </Button>
 <Button type="button"variant="secondary"size="sm"onClick={() => startEdit(record)}>
 <Pencil className="size-3.5"/>
 Edit
 </Button>
 <Button type="button"variant="danger"size="sm"onClick={() => void deleteRecord(record)}>
 <Trash2 className="size-3.5"/>
 Delete
 </Button>
 </div>
 </div>
 )}
 </div>
 );
})}
 </div>
 ) : null}
 </div>
 </Card>
 ))
 ) : (
 <EmptyPanel
 title={records.length ? "No matching selectors" : "No saved selectors"}
 description={
 records.length
 ? "Adjust the search or surface filter to see more domain memory records."
 : "Domain memory is empty. Save selectors from Crawl Studio or the Selector Tool to manage them here."
 }
 />
 )}
 </div>
 );
}
