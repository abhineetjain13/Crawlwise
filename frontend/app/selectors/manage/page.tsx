"use client";

import { Pencil, RefreshCcw, Save, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { EmptyPanel, InlineAlert, PageHeader, SectionHeader } from "../../../components/ui/patterns";
import { Badge, Button, Card, Dropdown, Input } from "../../../components/ui/primitives";
import { api } from "../../../lib/api";
import type { SelectorRecord, SelectorUpdatePayload } from "../../../lib/api/types";

type LocalRecord = SelectorRecord & { _uid: string };

type EditDraft = {
  field_name: string;
  surface: string;
  kind: "xpath" | "css_selector" | "regex";
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

  async function loadRecords() {
    setLoading(true);
    setError("");
    try {
      const data = await api.listSelectors();
      setRecords(data.map((r, i) => ({ ...r, _uid: `${r.id}-${i}-${Date.now()}` })));
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Unable to load domain memory.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadRecords();
  }, []);

  const groupedRecords = useMemo(() => {
    const grouped = new Map<string, LocalRecord[]>();
    for (const record of records) {
      const key = record.domain;
      grouped.set(key, [...(grouped.get(key) ?? []), record]);
    }
    return Array.from(grouped.entries()).sort(([left], [right]) => left.localeCompare(right));
  }, [records]);

  function startEdit(record: LocalRecord) {
    setEditingId(record._uid);
    setDraft({
      field_name: record.field_name,
      surface: record.surface,
      kind: record.xpath ? "xpath" : record.css_selector ? "css_selector" : "regex",
      selectorValue: record.xpath ?? record.css_selector ?? record.regex ?? "",
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
      setRecords((current) => current.map((entry) => (entry._uid === record._uid ? { ...updated, _uid: record._uid } : entry)));
      cancelEdit();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Unable to save selector.");
    }
  }

  async function toggleActive(record: LocalRecord) {
    try {
      const updated = await api.updateSelector(record.id, { is_active: !record.is_active });
      setRecords((current) => current.map((entry) => (entry._uid === record._uid ? { ...updated, _uid: record._uid } : entry)));
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

  async function deleteDomain(domain: string) {
    try {
      await api.deleteSelectorsByDomain(domain);
      setRecords((current) => current.filter((entry) => entry.domain !== domain));
      if (draft && records.find((record) => record._uid === editingId)?.domain === domain) {
        cancelEdit();
      }
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Unable to clear domain memory.");
    }
  }

  return (
    <div className="page-stack">
      <PageHeader title="Domain Memory" />

      <Card className="section-card">
        <SectionHeader
          title="Saved Selectors"
          description="Review selector memory across domains and surfaces, edit values inline, or remove stale mappings."
          action={
            <Button type="button" variant="secondary" onClick={() => void loadRecords()} disabled={loading}>
              <RefreshCcw className="size-3.5" />
              {loading ? "Refreshing..." : "Refresh"}
            </Button>
          }
        />
        {error ? <InlineAlert message={error} /> : null}
      </Card>

      {loading ? (
        <Card className="section-card">
          <p className="text-sm text-muted">Loading selector memory…</p>
        </Card>
      ) : groupedRecords.length ? (
        groupedRecords.map(([domain, domainRecords]) => (
          <Card key={domain} className="section-card">
            <SectionHeader
              title={domain}
              description={`${domainRecords.length} selector${domainRecords.length === 1 ? "" : "s"} across ${new Set(domainRecords.map((record) => record.surface)).size} surface${new Set(domainRecords.map((record) => record.surface)).size === 1 ? "" : "s"}.`}
              action={
                <Button type="button" variant="danger" onClick={() => void deleteDomain(domain)}>
                  <Trash2 className="size-3.5" />
                  Delete Domain
                </Button>
              }
            />
            <div className="space-y-3">
              {domainRecords
                .slice()
                .sort((left, right) =>
                  `${left.surface}:${left.field_name}`.localeCompare(`${right.surface}:${right.field_name}`),
                )
                .map((record) => {
                  const isEditing = editingId === record._uid && draft;
                  return (
                    <div key={record._uid} className="rounded-[var(--radius-lg)] border border-border bg-background-elevated p-4">
                      {isEditing ? (
                        <div className="grid gap-3">
                          <div className="grid gap-3 xl:grid-cols-[minmax(0,0.7fr)_160px_140px_auto]">
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
                                  { value: "xpath", label: "XPath" },
                                  { value: "css_selector", label: "CSS" },
                                  { value: "regex", label: "Regex" },
                                ]}
                              />
                            </label>
                            <div className="flex items-end justify-end gap-2">
                              <Button type="button" variant="secondary" onClick={cancelEdit}>
                                <X className="size-3.5" />
                                Cancel
                              </Button>
                              <Button type="button" variant="accent" onClick={() => void saveEdit(record)}>
                                <Save className="size-3.5" />
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
                            <Badge tone={draft.is_active ? "success" : "warning"}>{draft.is_active ? "active" : "inactive"}</Badge>
                            <Button type="button" variant="secondary" onClick={() => setDraft({ ...draft, is_active: !draft.is_active })}>
                              {draft.is_active ? "Deactivate" : "Activate"}
                            </Button>
                          </div>
                        </div>
                      ) : (
                        <div className="grid gap-3">
                          <div className="flex flex-wrap items-center gap-2">
                            <Badge tone="info">{record.surface}</Badge>
                            <Badge tone={record.is_active ? "success" : "warning"}>{record.is_active ? "active" : "inactive"}</Badge>
                            <Badge tone="neutral">{record.xpath ? "XPath" : record.css_selector ? "CSS" : "Regex"}</Badge>
                            <Badge tone="neutral">{record.source}</Badge>
                          </div>
                          <div className="grid gap-2 xl:grid-cols-[180px_minmax(0,1fr)]">
                            <div className="field-label">Field</div>
                            <div className="text-sm text-foreground">{record.field_name}</div>
                            <div className="field-label">Selector</div>
                            <div className="truncate font-mono text-sm text-muted" title={record.xpath ?? record.css_selector ?? record.regex ?? ""}>
                              {record.xpath ?? record.css_selector ?? record.regex ?? ""}
                            </div>
                          </div>
                          <div className="flex flex-wrap items-center gap-2">
                            <Button type="button" variant="secondary" onClick={() => void toggleActive(record)}>
                              {record.is_active ? "Deactivate" : "Activate"}
                            </Button>
                            <Button type="button" variant="secondary" onClick={() => startEdit(record)}>
                              <Pencil className="size-3.5" />
                              Edit
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
          </Card>
        ))
      ) : (
        <EmptyPanel title="No saved selectors" description="Domain memory is empty. Save selectors from Crawl Studio or the Selector Tool to manage them here." />
      )}
    </div>
  );
}
