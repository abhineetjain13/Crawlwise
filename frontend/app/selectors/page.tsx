"use client";

import { AlertCircle, Check, CheckCircle2, Plus, Search, Sparkles, Trash2 } from "lucide-react";
import { useState } from "react";

import { EmptyPanel, PageHeader, SectionHeader } from "../../components/ui/patterns";
import { Badge, Button, Card, Input, Textarea } from "../../components/ui/primitives";
import { api } from "../../lib/api";
import type { SelectorCreatePayload, SelectorSuggestion } from "../../lib/api/types";
import { cn } from "../../lib/utils";

type SelectorKind = "xpath" | "css_selector" | "regex";
type RowState = "idle" | "accepted" | "saved";
type StatusTone = "success" | "warning" | "danger";

type SelectorRow = {
  key: string;
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
  const [expectedColumns, setExpectedColumns] = useState("");
  const [rows, setRows] = useState<SelectorRow[]>([]);
  const [rowMessages, setRowMessages] = useState<Record<string, RowMessage>>({});
  const [loadError, setLoadError] = useState("");
  const [loadingSuggestions, setLoadingSuggestions] = useState(false);
  const [savingAccepted, setSavingAccepted] = useState(false);
  const [activeTestKey, setActiveTestKey] = useState<string | null>(null);
  const [activeDetectKey, setActiveDetectKey] = useState<string | null>(null);

  const parsedColumns = parseExpectedColumns(expectedColumns);
  const domain = normalizeDomain(loadedUrl);

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
      setLoadedUrl(targetUrl);
      setRows(
        parsedColumns.map((field) => {
          const suggestion = response.suggestions[field]?.[0];
          return buildRowFromSuggestion(field, suggestion);
        }),
      );
      setRowMessages({});
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "Unable to load selector suggestions.");
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
        [row.key]: { tone: "warning", message: "Load a URL and enter a field name first." },
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
          [row.key]: { tone: "warning", message: "No selector suggestion found for this field." },
        }));
        return;
      }
      const next = buildRowFromSuggestion(row.fieldName, suggestion);
      updateRow(row.key, {
        kind: next.kind,
        selectorValue: next.selectorValue,
        extractedValue: next.extractedValue,
        source: next.source,
        state: "idle",
      });
      setRowMessages((current) => ({
        ...current,
        [row.key]: { tone: "success", message: "Suggested selector refreshed." },
      }));
    } catch (error) {
      setRowMessages((current) => ({
        ...current,
        [row.key]: { tone: "danger", message: error instanceof Error ? error.message : "Auto-detect failed." },
      }));
    } finally {
      setActiveDetectKey(null);
    }
  }

  async function testRow(row: SelectorRow) {
    if (!loadedUrl || !row.selectorValue.trim()) {
      setRowMessages((current) => ({
        ...current,
        [row.key]: { tone: "warning", message: "Load a URL and enter a selector to test." },
      }));
      return;
    }
    setActiveTestKey(row.key);
    try {
      const response = await api.testSelector({
        url: loadedUrl,
        xpath: row.kind === "xpath" ? row.selectorValue.trim() : undefined,
        css_selector: row.kind === "css_selector" ? row.selectorValue.trim() : undefined,
        regex: row.kind === "regex" ? row.selectorValue.trim() : undefined,
      });
      updateRow(row.key, {
        extractedValue: response.matched_value ?? "",
      });
      setRowMessages((current) => ({
        ...current,
        [row.key]: {
          tone: response.count > 0 ? "success" : "warning",
          message: formatSelectorMatchMessage(response.count),
        },
      }));
    } catch (error) {
      setRowMessages((current) => ({
        ...current,
        [row.key]: { tone: "danger", message: error instanceof Error ? error.message : "Selector test failed." },
      }));
    } finally {
      setActiveTestKey(null);
    }
  }

  async function saveAcceptedRows() {
    const acceptedRows = rows.filter((row) => row.state === "accepted" && row.fieldName.trim() && row.selectorValue.trim());
    if (!acceptedRows.length || !domain) {
      setLoadError("Accept at least one selector row before saving.");
      return;
    }
    setSavingAccepted(true);
    setLoadError("");
    const failedFields: string[] = [];
    try {
      for (const row of acceptedRows) {
        const payload: SelectorCreatePayload = {
          domain,
          field_name: normalizeField(row.fieldName),
          xpath: row.kind === "xpath" ? row.selectorValue.trim() : undefined,
          css_selector: row.kind === "css_selector" ? row.selectorValue.trim() : undefined,
          regex: row.kind === "regex" ? row.selectorValue.trim() : undefined,
          sample_value: row.extractedValue.trim() || undefined,
          source: row.source || selectorSource(row.kind),
          status: "validated",
          is_active: true,
        };
        try {
          await api.createSelector(payload);
          setRows((current) =>
            current.map((entry) => (entry.key === row.key ? { ...entry, state: "saved" } : entry)),
          );
        } catch (error) {
          failedFields.push(row.fieldName.trim() || row.key);
          setRowMessages((current) => ({
            ...current,
            [row.key]: {
              tone: "danger",
              message: error instanceof Error ? error.message : "Unable to save selector.",
            },
          }));
        }
      }
    } finally {
      setSavingAccepted(false);
    }
    if (failedFields.length) {
      setLoadError(`Unable to save ${failedFields.join(", ")}. Saved rows stay marked as saved; failed rows remain accepted for retry.`);
    }
  }

  return (
    <div className="space-y-4">
      <PageHeader title="CSS / XPath Selector" />

      <Card className="space-y-4">
        <SectionHeader title="Selector Inputs" description="Enter a page URL and expected column names, then let the LLM suggest selectors for each field." />
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(280px,0.8fr)_auto] xl:items-end">
          <label className="grid gap-1.5">
            <span className="label-caps">Page URL</span>
            <Input
              value={url}
              onChange={(event) => setUrl(event.target.value)}
              placeholder="https://example.com/products/oak-chair"
              className="font-mono text-sm"
            />
          </label>
          <label className="grid gap-1.5">
            <span className="label-caps">Expected Columns</span>
            <Textarea
              value={expectedColumns}
              onChange={(event) => setExpectedColumns(event.target.value)}
              placeholder="price, sku, availability, brand"
              className="min-h-[80px] text-sm"
            />
          </label>
          <Button type="button" variant="accent" onClick={() => void loadPageAndSuggestions()} disabled={loadingSuggestions}>
            <Sparkles className="size-3.5" />
            {loadingSuggestions ? "Loading..." : "Load Page"}
          </Button>
        </div>
        {loadError ? <div className="rounded-[var(--radius-md)] border border-danger/20 bg-danger/10 px-3 py-2 text-sm text-danger">{loadError}</div> : null}
      </Card>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.05fr)_minmax(420px,0.95fr)]">
        <Card className="space-y-4">
          <SectionHeader title="Page Preview" description={loadedUrl || "Load a page to preview its DOM context."} />
          <div className="overflow-hidden rounded-[var(--radius-lg)] border border-border bg-white shadow-[var(--shadow-sm)]">
            {loadedUrl ? (
              <iframe
                key={loadedUrl}
                src={loadedUrl}
                title="Selector page preview"
                className="h-[760px] w-full bg-white"
                loading="lazy"
                referrerPolicy="no-referrer"
                sandbox=""
              />
            ) : (
              <div className="grid h-[760px] place-items-center text-sm text-muted">
                No page loaded.
              </div>
            )}
          </div>
        </Card>

        <Card className="space-y-4">
          <SectionHeader
            title="Field Rows"
            description="Review LLM suggestions, edit selectors manually, test arbitrary XPath/CSS/regex, then accept the rows you want to save."
            action={
              <Button type="button" variant="ghost" onClick={addFieldRow}>
                <Plus className="size-3.5" />
                Add Field
              </Button>
            }
          />

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
                          <span className="label-caps">Field Name</span>
                          <Input
                            value={row.fieldName}
                            onChange={(event) => updateRow(row.key, { fieldName: event.target.value, state: nextEditedState(row.state) })}
                            placeholder="price"
                          />
                        </label>

                        <label className="grid gap-1">
                          <span className="label-caps">Type</span>
                          <select
                            value={row.kind}
                            onChange={(event) => updateRow(row.key, { kind: event.target.value as SelectorKind, state: nextEditedState(row.state) })}
                            className="control-select focus-ring"
                          >
                            <option value="xpath">XPath</option>
                            <option value="css_selector">CSS</option>
                            <option value="regex">Regex</option>
                          </select>
                        </label>

                        <label className="grid gap-1" htmlFor={selectorInputId}>
                          <span className="label-caps">XPath / CSS / Regex</span>
                          <div className="relative">
                            <Input
                              id={selectorInputId}
                              value={row.selectorValue}
                              onChange={(event) => updateRow(row.key, { selectorValue: event.target.value, state: nextEditedState(row.state) })}
                              placeholder={selectorPlaceholder(row.kind)}
                              className="pr-10 font-mono text-sm"
                            />
                            <div className="pointer-events-none absolute inset-y-0 right-3 flex items-center">
                              {row.selectorValue.trim() ? <CheckCircle2 className="size-4 text-success" /> : <AlertCircle className="size-4 text-muted" />}
                            </div>
                          </div>
                        </label>

                        <div className="flex items-end justify-end">
                          <button
                            type="button"
                            onClick={() => removeFieldRow(row.key)}
                            className="inline-flex size-8 items-center justify-center rounded-[var(--radius-md)] border border-border text-danger transition hover:bg-danger/10"
                            aria-label="Delete field row"
                          >
                            <Trash2 className="size-3.5" />
                          </button>
                        </div>
                      </div>

                      <label className="grid gap-1">
                        <span className="label-caps">Extracted Value Preview</span>
                        <Input
                          value={row.extractedValue}
                          onChange={(event) => updateRow(row.key, { extractedValue: event.target.value })}
                          placeholder="Extracted value"
                          className="font-mono text-sm"
                        />
                      </label>

                      <div className="flex flex-wrap items-center gap-2">
                        <Button type="button" variant="secondary" onClick={() => void redetectRow(row)} disabled={activeDetectKey === row.key}>
                          <Sparkles className="size-3.5" />
                          {activeDetectKey === row.key ? "Detecting..." : "Auto-detect"}
                        </Button>
                        <Button type="button" variant="secondary" onClick={() => void testRow(row)} disabled={activeTestKey === row.key}>
                          <Search className="size-3.5" />
                          {activeTestKey === row.key ? "Testing..." : "Test"}
                        </Button>
                        <Button
                          type="button"
                          variant={row.state === "accepted" || row.state === "saved" ? "secondary" : "ghost"}
                          onClick={() => updateRow(row.key, { state: nextSelectorRowState(row.state) })}
                          disabled={row.state === "saved"}
                        >
                          <Check className="size-3.5" />
                          {selectorStateLabel(row.state)}
                        </Button>
                        <Badge tone={selectorStateTone(row.state)}>
                          {row.state}
                        </Badge>
                      </div>

                      {message ? (
                        <div
                          className={cn(
                            "rounded-[var(--radius-md)] px-3 py-2 text-sm",
                            message.tone === "success" && "bg-success/10 text-success",
                            message.tone === "warning" && "bg-warning/10 text-warning",
                            message.tone === "danger" && "bg-danger/10 text-danger",
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
            <EmptyPanel title="No field rows yet" description="Load a page with expected columns to generate LLM suggestions." />
          )}

          <div className="flex justify-end border-t border-border pt-4">
            <Button type="button" variant="accent" onClick={() => void saveAcceptedRows()} disabled={savingAccepted || !rows.some((row) => row.state === "accepted")}>
              <Check className="size-3.5" />
              {savingAccepted ? "Saving..." : "Save Accepted Selectors"}
            </Button>
          </div>
        </Card>
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
  if (kind === "xpath") return "//span[@class='price']";
  if (kind === "css_selector") return ".price";
  return "\\$[\\d,.]+";
}

function selectorSource(kind: SelectorKind) {
  if (kind === "xpath") return "llm_xpath";
  if (kind === "css_selector") return "llm_css";
  return "llm_regex";
}

function formatSelectorMatchMessage(count: number) {
  if (count <= 0) {
    return "No matches.";
  }
  const suffix = count === 1 ? "" : "s";
  return `Matched ${count} result${suffix}.`;
}

function nextSelectorRowState(state: RowState): RowState {
  if (state === "saved") return "saved";
  if (state === "accepted") return "idle";
  return "accepted";
}

function selectorStateLabel(state: RowState) {
  if (state === "saved") return "Saved";
  if (state === "accepted") return "Accepted";
  return "Accept";
}

function selectorStateTone(state: RowState) {
  if (state === "saved") return "success" as const;
  if (state === "accepted") return "warning" as const;
  return "neutral" as const;
}

function nextEditedState(state: RowState): RowState {
  if (state === "saved") return "accepted";
  if (state === "idle") return "idle";
  return state;
}

function buildRowFromSuggestion(fieldName: string, suggestion?: SelectorSuggestion): SelectorRow {
  if (suggestion?.xpath) {
    return {
      key: createRowKey(),
      fieldName,
      kind: "xpath",
      selectorValue: suggestion.xpath,
      extractedValue: suggestion.sample_value || "",
      source: suggestion.source || "llm_xpath",
      state: "idle",
    };
  }
  if (suggestion?.css_selector) {
    return {
      key: createRowKey(),
      fieldName,
      kind: "css_selector",
      selectorValue: suggestion.css_selector,
      extractedValue: suggestion.sample_value || "",
      source: suggestion.source || "llm_css",
      state: "idle",
    };
  }
  if (suggestion?.regex) {
    return {
      key: createRowKey(),
      fieldName,
      kind: "regex",
      selectorValue: suggestion.regex,
      extractedValue: suggestion.sample_value || "",
      source: suggestion.source || "llm_regex",
      state: "idle",
    };
  }
  return {
    key: createRowKey(),
    fieldName,
    kind: "xpath",
    selectorValue: "",
    extractedValue: "",
    source: "manual",
    state: "idle",
  };
}

function createEmptyRow(): SelectorRow {
  return {
    key: createRowKey(),
    fieldName: "",
    kind: "xpath",
    selectorValue: "",
    extractedValue: "",
    source: "manual",
    state: "idle",
  };
}

function createRowKey() {
  return `selector:${Date.now()}:${Math.random().toString(36).slice(2, 8)}`;
}

function normalizeField(value: string) {
  return value.trim().toLowerCase().replace(/\s+/g, "_");
}

function normalizeDomain(url: string) {
  try {
    return new URL(url).hostname.replace(/^www\./, "").toLowerCase();
  } catch {
    return "";
  }
}
