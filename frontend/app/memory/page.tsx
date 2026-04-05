"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Pencil, Save, Trash2, X } from "lucide-react";
import { useMemo, useState } from "react";

import { PageHeader, SectionHeader } from "../../components/ui/patterns";
import { Badge, Button, Card, Input } from "../../components/ui/primitives";
import { api } from "../../lib/api";
import type { CrawlRun, SelectorRecord, SelectorUpdatePayload, SiteMemoryRecord } from "../../lib/api/types";

type DraftState = Record<number, SelectorUpdatePayload>;

export default function SiteMemoryPage() {
  const queryClient = useQueryClient();
  const [expandedDomain, setExpandedDomain] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<DraftState>({});
  const [pendingSaveId, setPendingSaveId] = useState<number | null>(null);
  const [pendingDeleteId, setPendingDeleteId] = useState<number | null>(null);
  const [pendingDeleteDomain, setPendingDeleteDomain] = useState<string | null>(null);
  const [clearingAll, setClearingAll] = useState(false);
  const [actionError, setActionError] = useState("");
  const meQuery = useQuery({ queryKey: ["me"], queryFn: api.me });
  const selectorsQuery = useQuery({ queryKey: ["selectors"], queryFn: () => api.listSelectors() });
  const siteMemoryQuery = useQuery({ queryKey: ["site-memory"], queryFn: () => api.listSiteMemory() });
  const runsQuery = useQuery({
    queryKey: ["memory-runs"],
    queryFn: () => api.listCrawls({ page: 1, limit: 100 }),
  });

  const grouped = useMemo(
    () => groupByDomain(selectorsQuery.data ?? [], runsQuery.data?.items ?? [], siteMemoryQuery.data ?? []),
    [selectorsQuery.data, runsQuery.data?.items, siteMemoryQuery.data],
  );
  const hasError = meQuery.isError || selectorsQuery.isError || siteMemoryQuery.isError || runsQuery.isError;
  const queryError = firstErrorMessage(meQuery.error, selectorsQuery.error, siteMemoryQuery.error, runsQuery.error);

  const saveMutation = useMutation({
    mutationFn: ({ selectorId, payload }: { selectorId: number; payload: SelectorUpdatePayload }) =>
      api.updateSelector(selectorId, payload),
    onSuccess: (_, variables) => {
      setDrafts((current) => {
        const next = { ...current };
        delete next[variables.selectorId];
        return next;
      });
      void queryClient.invalidateQueries({ queryKey: ["selectors"] });
    },
    onError: (error) => {
      console.error("Failed to save selector", error);
      setActionError(error instanceof Error ? error.message : "Unable to save selector.");
    },
    onSettled: () => {
      setPendingSaveId(null);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (selectorId: number) => api.deleteSelector(selectorId),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["selectors"] }),
    onError: async (error) => {
      console.error("Failed to delete selector", error);
      setActionError(error instanceof Error ? error.message : "Unable to delete selector.");
      await queryClient.invalidateQueries({ queryKey: ["selectors"] });
    },
    onSettled: () => {
      setPendingDeleteId(null);
    },
  });

  const deleteDomainMutation = useMutation({
    mutationFn: async (domain: string) => {
      await api.deleteSelectorsByDomain(domain);
      await api.deleteSiteMemory(domain);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["selectors"] });
      await queryClient.invalidateQueries({ queryKey: ["site-memory"] });
    },
    onError: async (error) => {
      console.error("Failed to delete domain selectors", error);
      setActionError(error instanceof Error ? error.message : "Unable to delete domain selectors.");
      await queryClient.invalidateQueries({ queryKey: ["selectors"] });
    },
    onSettled: () => {
      setPendingDeleteDomain(null);
    },
  });

  const clearAllMutation = useMutation({
    mutationFn: async () => {
      await api.clearAllSiteMemory();
      await api.clearAllDomainMemory();
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["selectors"] });
      await queryClient.invalidateQueries({ queryKey: ["site-memory"] });
    },
    onError: async (error) => {
      console.error("Failed to clear site memory", error);
      setActionError(error instanceof Error ? error.message : "Unable to clear site memory.");
      await queryClient.invalidateQueries({ queryKey: ["selectors"] });
    },
    onSettled: () => {
      setClearingAll(false);
    },
  });

  if (hasError) {
    return (
      <div className="space-y-4">
        <PageHeader title="Site Memory" />
        <Card>
          <p className="text-[13px] text-danger">
            Unable to load site memory. {queryError ?? "Refresh and try again."}
          </p>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title="Site Memory"
        actions={
          meQuery.data?.role === "admin" ? (
            <Button
              type="button"
              variant="danger"
              onClick={() => {
                if (window.confirm("Clear all saved Site Memory entries?")) {
                  setActionError("");
                  setClearingAll(true);
                  clearAllMutation.mutate();
                }
              }}
              disabled={clearingAll || !grouped.length}
            >
              <Trash2 className="size-3.5" />
              {clearingAll ? "Clearing..." : "Clear All Site Memory"}
            </Button>
          ) : null
        }
      />

      <Card className="space-y-4">
        <SectionHeader
          title="Saved Domains"
          description="Domain-level selector mappings and learned crawl memory. Editing here updates what future crawls auto-apply."
        />

        {actionError ? <p className="text-[13px] text-danger">{actionError}</p> : null}

        {selectorsQuery.isLoading || siteMemoryQuery.isLoading ? <p className="text-[13px] text-muted">Loading site memory…</p> : null}
        {!selectorsQuery.isLoading && !siteMemoryQuery.isLoading && !grouped.length ? (
          <p className="text-[13px] text-muted">No Site Memory entries saved yet.</p>
        ) : null}

        {grouped.map((group) => {
          const open = expandedDomain === group.domain;
          return (
            <div key={group.domain} className="rounded-[var(--radius-lg)] border border-border bg-background-elevated">
              <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-4">
                <div className="min-w-0">
                  <div className="font-mono text-[13px] font-semibold text-foreground">{group.domain}</div>
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-[12px] text-muted">
                    <span>{group.reusableFields.length} reusable field{group.reusableFields.length === 1 ? "" : "s"}</span>
                    <span>•</span>
                    <span>{group.fields.length} field{group.fields.length === 1 ? "" : "s"}</span>
                    <span>•</span>
                    <span>{group.lastCrawl ? `Last crawl ${formatDate(group.lastCrawl)}` : "No crawl timestamp"}</span>
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={() => setExpandedDomain((current) => (current === group.domain ? null : group.domain))}
                  >
                    {open ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
                    {open ? "Hide" : "View"}
                  </Button>
                  <Button
                    type="button"
                    variant="danger"
                    onClick={() => {
                      if (window.confirm(`Delete all Site Memory for ${group.domain}?`)) {
                        setActionError("");
                        setPendingDeleteDomain(group.domain);
                        deleteDomainMutation.mutate(group.domain);
                      }
                    }}
                    disabled={pendingDeleteDomain === group.domain}
                  >
                    <Trash2 className="size-3.5" />
                    Delete Domain
                  </Button>
                </div>
              </div>

              {open ? (
                <div className="border-t border-border px-4 py-4">
                  {group.reusableFields.length ? (
                    <div className="mb-4">
                      <div className="mb-2 text-[12px] font-semibold uppercase tracking-[0.08em] text-muted">Reusable Fields</div>
                      <div className="flex flex-wrap gap-1.5">
                        {group.reusableFields.map((field) => (
                          <Badge key={field} tone="neutral">{field}</Badge>
                        ))}
                      </div>
                    </div>
                  ) : null}
                  <div className="overflow-auto rounded-[var(--radius-md)] border border-border">
                    <table className="compact-data-table">
                      <thead>
                        <tr>
                          <th>Field</th>
                          <th>Source</th>
                          <th>XPath / CSS / Regex</th>
                          <th>Status</th>
                          <th>Last Updated</th>
                          <th className="text-right">Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {group.fields.map((selector) => {
                          const draft = drafts[selector.id];
                          const selectorValue = draft !== undefined
                            ? draft.xpath ?? draft.css_selector ?? draft.regex ?? ""
                            : selector.xpath ?? selector.css_selector ?? selector.regex ?? "";
                          const isEditing = Boolean(draft);
                          return (
                            <tr key={selector.id}>
                              <td className="font-medium text-foreground">{selector.field_name}</td>
                              <td>{selector.source}</td>
                              <td className="min-w-[320px]">
                                {isEditing ? (
                                  <Input
                                    value={selectorValue}
                                    onChange={(event) =>
                                      setDrafts((current) => ({
                                        ...current,
                                        [selector.id]: buildDraft(selector, event.target.value),
                                      }))
                                    }
                                    className="font-mono text-[12px]"
                                  />
                                ) : (
                                  <span className="block max-w-[420px] truncate font-mono text-[12px]" title={selectorValue}>
                                    {selectorValue || "--"}
                                  </span>
                                )}
                              </td>
                              <td>
                                <Badge tone={selector.is_active ? "success" : "warning"}>{selector.status}</Badge>
                              </td>
                              <td>{formatDate(selector.updated_at)}</td>
                              <td>
                                <div className="flex justify-end gap-2">
                                  {isEditing ? (
                                    <>
                                      <Button
                                        type="button"
                                        variant="secondary"
                                        onClick={() =>
                                          setDrafts((current) => {
                                            const next = { ...current };
                                            delete next[selector.id];
                                            return next;
                                          })
                                        }
                                      >
                                        <X className="size-3.5" />
                                        Cancel
                                      </Button>
                                      <Button
                                        type="button"
                                        variant="accent"
                                        onClick={() => {
                                          if (!draft) {
                                            return;
                                          }
                                          setActionError("");
                                          setPendingSaveId(selector.id);
                                          saveMutation.mutate({ selectorId: selector.id, payload: draft });
                                        }}
                                        disabled={pendingSaveId === selector.id}
                                      >
                                        <Save className="size-3.5" />
                                        Save
                                      </Button>
                                    </>
                                  ) : (
                                    <>
                                      <Button
                                        type="button"
                                        variant="ghost"
                                        onClick={() =>
                                          setDrafts((current) => ({
                                            ...current,
                                            [selector.id]: buildDraft(selector, selector.xpath ?? selector.css_selector ?? selector.regex ?? ""),
                                          }))
                                        }
                                      >
                                        <Pencil className="size-3.5" />
                                        Edit
                                      </Button>
                                      <Button
                                        type="button"
                                        variant="danger"
                                        onClick={() => {
                                          if (window.confirm(`Delete ${selector.field_name} from ${selector.domain}?`)) {
                                            setActionError("");
                                            setPendingDeleteId(selector.id);
                                            deleteMutation.mutate(selector.id);
                                          }
                                        }}
                                        disabled={pendingDeleteId === selector.id}
                                      >
                                        <Trash2 className="size-3.5" />
                                        Delete
                                      </Button>
                                    </>
                                  )}
                                </div>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              ) : null}
            </div>
          );
        })}
      </Card>
    </div>
  );
}

function buildDraft(selector: SelectorRecord, value: string): SelectorUpdatePayload {
  const nextValue = value.trim();
  if (selector.xpath) {
    return { xpath: nextValue, css_selector: null, regex: null, status: "manual", is_active: selector.is_active };
  }
  if (selector.regex) {
    return { regex: nextValue, xpath: null, css_selector: null, status: "manual", is_active: selector.is_active };
  }
  return { css_selector: nextValue, xpath: null, regex: null, status: "manual", is_active: selector.is_active };
}

function groupByDomain(selectors: SelectorRecord[], runs: CrawlRun[], siteMemory: SiteMemoryRecord[]) {
  const lastCrawlByDomain = new Map<string, string>();
  for (const run of runs) {
    const domain = normalizeDomain(run.url);
    if (!domain) continue;
    const current = lastCrawlByDomain.get(domain);
    if (!current || new Date(run.updated_at).getTime() > new Date(current).getTime()) {
      lastCrawlByDomain.set(domain, run.updated_at);
    }
  }
  for (const memory of siteMemory) {
    const domain = normalizeDomain(memory.domain);
    if (!domain || !memory.last_crawl_at) continue;
    const current = lastCrawlByDomain.get(domain);
    if (!current || new Date(memory.last_crawl_at).getTime() > new Date(current).getTime()) {
      lastCrawlByDomain.set(domain, memory.last_crawl_at);
    }
  }

  const grouped = new Map<string, SelectorRecord[]>();
  for (const selector of selectors) {
    const domain = normalizeDomain(selector.domain);
    if (!domain) continue;
    const rows = grouped.get(domain) ?? [];
    rows.push({ ...selector, domain });
    grouped.set(domain, rows);
  }

  const fieldsByDomain = new Map<string, string[]>();
  for (const memory of siteMemory) {
    const domain = normalizeDomain(memory.domain);
    if (!domain) continue;
    fieldsByDomain.set(domain, [...(memory.payload?.fields ?? [])].sort((a, b) => a.localeCompare(b)));
  }

  const allDomains = new Set([...grouped.keys(), ...fieldsByDomain.keys()]);
  return [...allDomains]
    .map((domain) => ({
      domain,
      reusableFields: fieldsByDomain.get(domain) ?? [],
      fields: [...(grouped.get(domain) ?? [])].sort((a, b) => a.field_name.localeCompare(b.field_name)),
      lastCrawl: lastCrawlByDomain.get(domain) ?? null,
    }))
    .sort((a, b) => a.domain.localeCompare(b.domain));
}

function normalizeDomain(value: string) {
  try {
    return new URL(value).hostname.replace(/^www\./, "").toLowerCase();
  } catch {
    return "";
  }
}

function formatDate(value: string | null) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--";
  return date.toLocaleString();
}

function firstErrorMessage(...errors: unknown[]) {
  for (const error of errors) {
    if (!error) continue;
    if (error instanceof Error) return error.message;
    if (typeof error === "string") return error;
  }
  return null;
}
