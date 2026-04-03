"use client";

import { useEffect, useMemo, useState } from "react";
import { Check, Plus, RotateCcw, Save, Search, Wand2 } from "lucide-react";

import { api } from "../../lib/api";
import type { CrawlRun, ReviewPayload, ReviewSelection, SelectorCreatePayload } from "../../lib/api/types";
import { cn } from "../../lib/utils";
import { Badge, Button, Input } from "../ui/primitives";
import { SectionHeader } from "../ui/patterns";

type WorkspaceTab = "fields" | "selectors";
type SelectorKind = "xpath" | "css_selector" | "regex";

type SelectorDraft = {
  key: string;
  selector_id: number | null;
  domain: string;
  field_name: string;
  kind: SelectorKind;
  selector_value: string;
  status: string;
  confidence: number | null;
  sample_value: string;
  source: string;
  source_run_id: number | null;
  is_active: boolean;
  last_saved: string;
};

type SelectorWorkspaceProps = {
  run: CrawlRun | undefined;
  review: ReviewPayload | undefined;
  selections: ReviewSelection[];
  onSelectionChange: (selection: ReviewSelection) => void;
  extraFields: string[];
  onAddExtraField: (field: string) => void;
  onRemoveExtraField: (field: string) => void;
  onSavePromotions: () => void;
  isSavingPromotions: boolean;
  saveError: string;
  onPreviewSelectors?: (payload: { selectors: SelectorCreatePayload[] }) => void;
  isPreviewingSelectors?: boolean;
  artifactUrl?: string;
  onDraftPayloadChange?: (payload: { additional_fields: string[]; selectors: Array<{ field_name: string; xpath?: string; regex?: string }> }) => void;
};

export function SelectorWorkspace({
  run,
  review,
  selections,
  onSelectionChange,
  extraFields,
  onAddExtraField,
  onRemoveExtraField,
  onSavePromotions,
  isSavingPromotions,
  saveError,
  onPreviewSelectors,
  isPreviewingSelectors = false,
  artifactUrl,
  onDraftPayloadChange,
}: Readonly<SelectorWorkspaceProps>) {
  const [tab, setTab] = useState<WorkspaceTab>("selectors");
  const [drafts, setDrafts] = useState<SelectorDraft[]>([]);
  const [rowStatus, setRowStatus] = useState<Record<string, { tone: "neutral" | "success" | "warning" | "danger"; message: string }>>({});
  const [savingRows, setSavingRows] = useState<Record<string, boolean>>({});
  const [testingRows, setTestingRows] = useState<Record<string, boolean>>({});
  const domain = useMemo(() => readString(review?.run.result_summary?.domain) ?? getDomain(run?.url), [review?.run.result_summary?.domain, run?.url]);
  const sourceUrl = useMemo(() => run?.url || review?.records?.[0]?.source_url || "", [review?.records, run?.url]);

  useEffect(() => {
    setDrafts(buildSelectorDrafts(review, domain));
    setRowStatus({});
    setSavingRows({});
    setTestingRows({});
  }, [domain, review]);

  useEffect(() => {
    if (!onDraftPayloadChange) {
      return;
    }
    const selectorRows = drafts
      .filter((draft) => draft.field_name.trim() && draft.selector_value.trim())
      .map((draft) => ({
        field_name: normalizeFieldName(draft.field_name),
        xpath: draft.kind === "xpath" ? draft.selector_value.trim() : undefined,
        regex: draft.kind === "regex" ? draft.selector_value.trim() : undefined,
      }));
    onDraftPayloadChange({
      additional_fields: Array.from(new Set([
        ...extraFields,
        ...selections.filter((item) => item.selected).map((item) => normalizeFieldName(item.output_field || item.source_field)),
        ...drafts.filter((draft) => draft.field_name.trim()).map((draft) => normalizeFieldName(draft.field_name)),
      ].filter(Boolean))),
      selectors: selectorRows,
    });
  }, [drafts, extraFields, onDraftPayloadChange, selections]);

  const selectorMemoryCount = review?.selector_memory?.length ?? 0;
  const suggestionCount = Object.values(review?.selector_suggestions ?? {}).reduce((count, rows) => count + rows.length, 0);

  const fieldRows = useMemo(() => {
    if (!review) return [];
    const fields = [...new Set([...review.normalized_fields, ...review.discovered_fields, ...review.canonical_fields])];
    return fields.map((field) => {
      const selection = selections.find((item) => item.source_field === field) ?? {
        source_field: field,
        output_field: field,
        selected: review.canonical_fields.includes(field) || review.normalized_fields.includes(field),
      };
      return selection;
    });
  }, [review, selections]);

  async function saveRow(draft: SelectorDraft) {
    if (!domain || !draft.field_name.trim() || !draft.selector_value.trim()) {
      setRowStatus((current) => ({
        ...current,
        [draft.key]: { tone: "warning", message: "Domain, field, and selector are required." },
      }));
      return;
    }

    setSavingRows((current) => ({ ...current, [draft.key]: true }));
    setRowStatus((current) => ({ ...current, [draft.key]: { tone: "neutral", message: "Saving selector..." } }));
    try {
      const payload: SelectorCreatePayload = {
        domain,
        field_name: draft.field_name.trim(),
        css_selector: draft.kind === "css_selector" ? draft.selector_value.trim() : undefined,
        xpath: draft.kind === "xpath" ? draft.selector_value.trim() : undefined,
        regex: draft.kind === "regex" ? draft.selector_value.trim() : undefined,
        status: draft.status || "validated",
        confidence: draft.confidence ?? undefined,
        sample_value: draft.sample_value.trim() || undefined,
        source: draft.source || "manual",
        source_run_id: draft.source_run_id ?? undefined,
        is_active: draft.is_active,
      };

      if (draft.selector_id) {
        const updated = await api.updateSelector(draft.selector_id, payload);
        setDrafts((current) =>
          current.map((row) =>
            row.key === draft.key
              ? { ...row, last_saved: new Date(updated.updated_at).toLocaleString() }
              : row,
          ),
        );
      } else {
        const saved = await api.createSelector(payload);
        setDrafts((current) =>
          current.map((row) =>
            row.key === draft.key
              ? {
                  ...row,
                  selector_id: saved.id,
                  last_saved: new Date(saved.updated_at).toLocaleString(),
                }
              : row,
          ),
        );
      }

      setRowStatus((current) => ({
        ...current,
        [draft.key]: { tone: "success", message: "Selector saved." },
      }));
    } catch (error) {
      setRowStatus((current) => ({
        ...current,
        [draft.key]: { tone: "danger", message: error instanceof Error ? error.message : "Failed to save selector." },
      }));
    } finally {
      setSavingRows((current) => ({ ...current, [draft.key]: false }));
    }
  }

  async function testRow(draft: SelectorDraft) {
    if (!sourceUrl.trim() || !draft.selector_value.trim()) {
      setRowStatus((current) => ({
        ...current,
        [draft.key]: { tone: "warning", message: "Need a source URL and a selector to test." },
      }));
      return;
    }

    setTestingRows((current) => ({ ...current, [draft.key]: true }));
    try {
      const response = await api.testSelector({
        url: sourceUrl,
        css_selector: draft.kind === "css_selector" ? draft.selector_value.trim() : undefined,
        xpath: draft.kind === "xpath" ? draft.selector_value.trim() : undefined,
        regex: draft.kind === "regex" ? draft.selector_value.trim() : undefined,
      });
      const message = response.count > 0
        ? `Matched ${response.count} time${response.count === 1 ? "" : "s"}`
        : "No matches";
      setRowStatus((current) => ({
        ...current,
        [draft.key]: { tone: response.count > 0 ? "success" : "warning", message: response.selector_used ? `${message} via ${response.selector_used}` : message },
      }));
    } catch (error) {
      setRowStatus((current) => ({
        ...current,
        [draft.key]: { tone: "danger", message: error instanceof Error ? error.message : "Failed to test selector." },
      }));
    } finally {
      setTestingRows((current) => ({ ...current, [draft.key]: false }));
    }
  }

  function updateDraft(key: string, patch: Partial<SelectorDraft>) {
    setDrafts((current) => current.map((draft) => (draft.key === key ? { ...draft, ...patch } : draft)));
  }

  function addDraft() {
    setDrafts((current) => [
      {
        key: `manual:${Date.now()}:${current.length + 1}`,
        selector_id: null,
        domain,
        field_name: "",
        kind: "xpath",
        selector_value: "",
        status: "manual",
        confidence: null,
        sample_value: "",
        source: "manual",
        source_run_id: run?.id ?? null,
        is_active: true,
        last_saved: "",
      },
      ...current,
    ]);
  }

  function selectorPayloadFromDrafts() {
    return drafts
      .filter((draft) => draft.field_name.trim() && draft.selector_value.trim())
      .map((draft) => ({
        field_name: normalizeFieldName(draft.field_name),
        xpath: draft.kind === "xpath" ? draft.selector_value.trim() : undefined,
        regex: draft.kind === "regex" ? draft.selector_value.trim() : undefined,
      }));
  }

  function fullSelectorPayloadFromDrafts(): SelectorCreatePayload[] {
    return drafts
      .filter((draft) => draft.field_name.trim() && draft.selector_value.trim())
      .map((draft) => ({
        domain,
        field_name: normalizeFieldName(draft.field_name),
        css_selector: draft.kind === "css_selector" ? draft.selector_value.trim() : undefined,
        xpath: draft.kind === "xpath" ? draft.selector_value.trim() : undefined,
        regex: draft.kind === "regex" ? draft.selector_value.trim() : undefined,
        status: draft.status || "validated",
        confidence: draft.confidence ?? undefined,
        sample_value: draft.sample_value.trim() || undefined,
        source: draft.source || "manual",
        source_run_id: draft.source_run_id ?? undefined,
        is_active: draft.is_active,
      }));
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 border-b border-border pb-3 sm:flex-row sm:items-end sm:justify-between">
        <SectionHeader
          title="Selectors"
          description="Use the saved HTML snapshot, edit selectors, save them, and rerun them on this same page."
        />
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="secondary" type="button" onClick={addDraft}>
            <Plus className="size-3.5" />
            Add selector
          </Button>
          {onPreviewSelectors ? (
            <Button variant="secondary" type="button" onClick={() => onPreviewSelectors({ selectors: fullSelectorPayloadFromDrafts() })} disabled={isPreviewingSelectors}>
              <Wand2 className="size-3.5" />
              {isPreviewingSelectors ? "Rerunning..." : "Rerun saved HTML"}
            </Button>
          ) : null}
        </div>
      </div>

      <div className="inline-flex rounded-md border border-border bg-panel-strong p-0.5">
        <TabButton active={tab === "selectors"} onClick={() => setTab("selectors")}>Selectors</TabButton>
        <TabButton active={tab === "fields"} onClick={() => setTab("fields")}>Fields</TabButton>
      </div>

      {tab === "selectors" ? (
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-3">
            <StatPill label="Domain" value={domain || "--"} />
            <StatPill label="Selector rows" value={String(drafts.length)} />
            <StatPill label="Memory" value={`${selectorMemoryCount} saved / ${suggestionCount} suggestions`} />
          </div>

          {drafts.length ? (
            <div className="space-y-2">
              {drafts.map((draft) => {
                const status = rowStatus[draft.key];
                return (
                  <div key={draft.key} className="rounded-lg border border-border bg-panel-strong/40 p-3">
                    <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                      <div className="min-w-0 flex-1 space-y-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <div className="text-[13px] font-medium text-foreground">{draft.field_name || "Unnamed field"}</div>
                          <Badge tone={draft.selector_id ? "success" : "neutral"}>{draft.selector_id ? "saved" : "new"}</Badge>
                          <Badge tone={draft.is_active ? "success" : "warning"}>{draft.is_active ? "active" : "inactive"}</Badge>
                        </div>
                        <div className="text-[11px] text-muted">
                          {draft.source || "manual"}{draft.last_saved ? ` · ${draft.last_saved}` : ""}
                        </div>
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        <Button type="button" variant="secondary" onClick={() => void testRow(draft)} disabled={testingRows[draft.key]}>
                          <Search className="size-3.5" />
                          {testingRows[draft.key] ? "Testing..." : "Test"}
                        </Button>
                        <Button type="button" variant="secondary" onClick={() => void saveRow(draft)} disabled={savingRows[draft.key]}>
                          <Save className="size-3.5" />
                          {savingRows[draft.key] ? "Saving..." : "Save"}
                        </Button>
                        <Button
                          type="button"
                          variant="ghost"
                          onClick={() =>
                            onSelectionChange({
                              source_field: draft.field_name,
                              output_field: draft.field_name,
                              selected: true,
                            })
                          }
                        >
                          <Plus className="size-3.5" />
                          Use in CSV
                        </Button>
                      </div>
                    </div>

                    <div className="mt-3 grid gap-3 md:grid-cols-[180px_minmax(0,1fr)_140px]">
                      <label className="grid gap-1">
                        <span className="text-[11px] font-medium uppercase tracking-[0.04em] text-muted">Field</span>
                        <Input
                          value={draft.field_name}
                          onChange={(event) => updateDraft(draft.key, { field_name: event.target.value })}
                          placeholder="field_name"
                        />
                      </label>

                      <label className="grid gap-1">
                        <span className="text-[11px] font-medium uppercase tracking-[0.04em] text-muted">Selector</span>
                        <Input
                          value={draft.selector_value}
                          onChange={(event) => updateDraft(draft.key, { selector_value: event.target.value })}
                          placeholder="//*[@itemprop='name']"
                        />
                      </label>

                      <label className="grid gap-1">
                        <span className="text-[11px] font-medium uppercase tracking-[0.04em] text-muted">Type</span>
                        <select
                          value={draft.kind}
                          onChange={(event) => updateDraft(draft.key, { kind: event.target.value as SelectorKind })}
                          className="focus-ring h-9 rounded-md border border-border bg-background px-3 text-[13px] text-foreground"
                        >
                          <option value="xpath">XPath</option>
                          <option value="css_selector">CSS</option>
                          <option value="regex">Regex</option>
                        </select>
                      </label>
                    </div>

                    <div className="mt-3 grid gap-3 md:grid-cols-3">
                      <label className="grid gap-1">
                        <span className="text-[11px] font-medium uppercase tracking-[0.04em] text-muted">Status</span>
                        <Input
                          value={draft.status}
                          onChange={(event) => updateDraft(draft.key, { status: event.target.value })}
                          placeholder="validated"
                        />
                      </label>
                      <label className="grid gap-1">
                        <span className="text-[11px] font-medium uppercase tracking-[0.04em] text-muted">Sample</span>
                        <Input
                          value={draft.sample_value}
                          onChange={(event) => updateDraft(draft.key, { sample_value: event.target.value })}
                          placeholder="sample value"
                        />
                      </label>
                      <label className="grid gap-1">
                        <span className="text-[11px] font-medium uppercase tracking-[0.04em] text-muted">Confidence</span>
                        <Input
                          value={draft.confidence ?? ""}
                          onChange={(event) =>
                            updateDraft(draft.key, {
                              confidence: event.target.value ? Number(event.target.value) : null,
                            })
                          }
                          placeholder="0.8"
                        />
                      </label>
                    </div>

                    {status ? (
                      <div className={cn(
                        "mt-3 rounded-md px-3 py-2 text-[12px]",
                        status.tone === "success" && "bg-success/10 text-success",
                        status.tone === "warning" && "bg-warning/10 text-warning",
                        status.tone === "danger" && "bg-danger/10 text-danger",
                        status.tone === "neutral" && "bg-panel-strong text-muted",
                      )}>
                        {status.message}
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          ) : (
            <p className="text-[13px] text-muted">No selector suggestions available for this run yet.</p>
          )}

          <div className="space-y-3 pt-2">
            <div className="rounded-md border border-border bg-panel-strong px-3 py-2 text-[12px] text-muted">
              Click inside the saved HTML snapshot and use the current selector row as your target, like the old field mapper flow.
            </div>
            <div className="overflow-hidden rounded-xl border border-border bg-white shadow-card">
              {artifactUrl ? (
                <iframe
                  src={artifactUrl}
                  title="Saved HTML artifact"
                  className="h-[46rem] w-full bg-white"
                  sandbox="allow-same-origin"
                />
              ) : (
                <div className="grid h-[46rem] place-items-center text-[13px] text-muted">
                  No saved HTML artifact available for this run.
                </div>
              )}
            </div>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="grid gap-2 sm:grid-cols-3">
            <StatPill label="Selected fields" value={String(selections.filter((item) => item.selected).length)} />
            <StatPill label="Extra fields" value={String(extraFields.length)} />
            <StatPill label="Source URL" value={sourceUrl ? "available" : "missing"} />
          </div>

          <div className="space-y-1.5">
            {fieldRows.map((selection) => (
              <div key={selection.source_field} className="flex flex-col gap-2 rounded-lg border border-border bg-panel-strong/40 px-3 py-3">
                <div className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={selection.selected}
                    onChange={(event) =>
                      onSelectionChange({
                        ...selection,
                        selected: event.target.checked,
                      })
                    }
                    className="accent-accent"
                  />
                  <div className="min-w-0 flex-1">
                    <div className="text-[12px] text-muted">{selection.source_field}</div>
                  </div>
                </div>
                <Input
                  value={selection.output_field}
                  onChange={(event) =>
                    onSelectionChange({
                      ...selection,
                      output_field: normalizeFieldName(event.target.value),
                    })
                  }
                  placeholder="canonical_name"
                  className="h-8 text-[12px]"
                />
              </div>
            ))}
          </div>

          <div className="space-y-2 rounded-lg border border-border bg-panel-strong/40 p-3">
            <div className="text-[13px] font-medium text-foreground">Additional fields</div>
            <p className="text-[12px] text-muted">These are extra output columns, and they will carry into bulk crawl along with the saved selectors.</p>
            <div className="flex flex-wrap gap-1.5">
              {extraFields.length ? extraFields.map((field) => (
                <button
                  key={field}
                  type="button"
                  onClick={() => onRemoveExtraField(field)}
                  className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-[11px] text-muted transition hover:border-danger/40 hover:text-danger"
                >
                  {field} <span>&times;</span>
                </button>
              )) : <span className="text-[12px] text-muted">No additional fields added yet.</span>}
            </div>
          </div>

          {saveError ? (
            <div className="rounded-md border border-danger/20 bg-danger/5 px-3 py-2 text-[12px] text-danger">
              {saveError}
            </div>
          ) : null}

          <div className="flex flex-wrap items-center gap-2">
            <Button variant="accent" type="button" onClick={onSavePromotions} disabled={isSavingPromotions}>
              <Check className="size-3.5" />
              {isSavingPromotions ? "Saving..." : "Save fields"}
            </Button>
            <Button
              variant="secondary"
              type="button"
              onClick={() => {
                const nextField = sourceUrl ? "url" : "";
                if (nextField) onAddExtraField(nextField);
              }}
            >
              <RotateCcw className="size-3.5" />
              Add URL field
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

function TabButton({
  active,
  children,
  onClick,
}: Readonly<{ active: boolean; children: string; onClick: () => void }>) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-[5px] px-3 py-1.5 text-[12px] font-medium transition-all",
        active ? "bg-background text-foreground shadow-sm" : "text-muted hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

function StatPill({ label, value }: Readonly<{ label: string; value: string }>) {
  return (
    <div className="rounded-md border border-border bg-background px-3 py-2">
      <div className="text-[10px] font-medium uppercase tracking-[0.05em] text-muted">{label}</div>
      <div className="mt-0.5 text-[13px] font-medium text-foreground">{value}</div>
    </div>
  );
}

function buildSelectorDrafts(review: ReviewPayload | undefined, domain: string): SelectorDraft[] {
  if (!review) return [];
  const fields = [...new Set([...review.normalized_fields, ...review.discovered_fields, ...review.canonical_fields])];
  const memory = review.selector_memory ?? [];
  const suggestions = review.selector_suggestions ?? {};

  return fields.map((field) => {
    const selector = pickSelectorCandidate(
      memory.find((entry) => readString(entry.field_name) === field) ??
        suggestions[field]?.[0] ??
        undefined,
    );
    const selectorId = readNumber(
      memory.find((entry) => readString(entry.field_name) === field)?.id,
    );

    return {
      key: `${domain}:${field}`,
      selector_id: selectorId,
      domain,
      field_name: field,
      kind: selector.kind,
      selector_value: selector.value,
      status: readString(
        memory.find((entry) => readString(entry.field_name) === field)?.status,
      ) ?? "validated",
      confidence: readNumber(
        memory.find((entry) => readString(entry.field_name) === field)?.confidence,
      ),
      sample_value: readString(
        memory.find((entry) => readString(entry.field_name) === field)?.sample_value,
      ) ?? readString(suggestions[field]?.[0]?.sample_value) ?? "",
      source: readString(
        memory.find((entry) => readString(entry.field_name) === field)?.source,
      ) ?? readString(suggestions[field]?.[0]?.source) ?? "manual",
      source_run_id: readNumber(
        memory.find((entry) => readString(entry.field_name) === field)?.source_run_id,
      ),
      is_active: Boolean(
        memory.find((entry) => readString(entry.field_name) === field)?.is_active ?? true,
      ),
      last_saved: readString(
        memory.find((entry) => readString(entry.field_name) === field)?.updated_at,
      ) ?? "",
    };
  });
}

function pickSelectorCandidate(entry: Record<string, unknown> | undefined): { kind: SelectorKind; value: string } {
  if (!entry) {
    return { kind: "xpath", value: "" };
  }
  const xpath = readString(entry.xpath);
  if (xpath) return { kind: "xpath", value: xpath };
  const css = readString(entry.css_selector);
  if (css) return { kind: "css_selector", value: css };
  const regex = readString(entry.regex);
  if (regex) return { kind: "regex", value: regex };
  const selector = readString(entry.selector_used) ?? "";
  if (selector) {
    return { kind: selector.startsWith("//") || selector.startsWith("(") ? "xpath" : "css_selector", value: selector };
  }
  return { kind: "xpath", value: "" };
}

function normalizeFieldName(value: string) {
  return value.trim().toLowerCase().replace(/\s+/g, "_");
}

function readString(value: unknown) {
  return typeof value === "string" ? value : undefined;
}

function readNumber(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function getDomain(url: string | undefined) {
  if (!url) return "";
  try {
    return new URL(url).hostname.toLowerCase();
  } catch {
    return url.toLowerCase();
  }
}
