"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { Trash2, Plus } from "lucide-react";
import { useRouter } from "next/navigation";
import { useSearchParams } from "next/navigation";

import { Button, Card, Input, Textarea } from "../../components/ui/primitives";
import { PageHeader } from "../../components/ui/patterns";
import { api } from "../../lib/api";
import { cn } from "../../lib/utils";

type SubmissionTab = "crawl" | "batch" | "csv";
type Vertical = "ecommerce" | "jobs" | "automobile";
type PageType = "category" | "pdp";
type AdvancedMode = "auto" | "paginate" | "scroll" | "load_more";

type ContractRow = {
  id: number;
  field_name: string;
  xpath: string;
  regex: string;
};

type CrawlPrefill = {
  urls?: string[];
  tab?: SubmissionTab;
  vertical?: Vertical;
  pageType?: PageType;
  additional_fields?: string[];
  selectors?: Array<{
    field_name?: string;
    xpath?: string | null;
    regex?: string | null;
  }>;
};

const PAGE_CONFIG: Record<Vertical, Record<PageType, {
  urlLabel: string;
  urlPlaceholder: string;
  surface: string;
  defaultFields: string[];
  maxRecords: number;
}>> = {
  ecommerce: {
    category: {
      urlLabel: "Category URL",
      urlPlaceholder: "https://example.com/collections/chairs",
      surface: "ecommerce_listing",
      defaultFields: ["title", "price", "url", "image_url", "brand", "availability"],
      maxRecords: 100,
    },
    pdp: {
      urlLabel: "PDP URL",
      urlPlaceholder: "https://example.com/products/oak-chair",
      surface: "ecommerce_detail",
      defaultFields: ["title", "brand", "sku", "price", "sale_price", "currency", "availability", "image_url", "description"],
      maxRecords: 1,
    },
  },
  jobs: {
    category: {
      urlLabel: "Jobs Listing URL",
      urlPlaceholder: "https://example.com/jobs/search",
      surface: "job_listing",
      defaultFields: ["title", "company", "location", "apply_url"],
      maxRecords: 100,
    },
    pdp: {
      urlLabel: "Job Detail URL",
      urlPlaceholder: "https://example.com/jobs/view/123",
      surface: "job_detail",
      defaultFields: ["title", "company", "location", "salary", "job_type", "posted_date", "apply_url", "description"],
      maxRecords: 1,
    },
  },
  automobile: {
    category: {
      urlLabel: "Inventory URL",
      urlPlaceholder: "https://example.com/cars-for-sale",
      surface: "automobile_listing",
      defaultFields: ["title", "price", "url", "image_url", "make", "model", "year", "mileage", "location", "dealer_name"],
      maxRecords: 100,
    },
    pdp: {
      urlLabel: "Vehicle Detail URL",
      urlPlaceholder: "https://example.com/vehicle/stock-123",
      surface: "automobile_detail",
      defaultFields: ["title", "price", "make", "model", "year", "trim", "mileage", "vin", "condition", "body_style", "fuel_type", "transmission", "location", "dealer_name", "image_url", "description"],
      maxRecords: 1,
    },
  },
};

const ADVANCED_OPTIONS: AdvancedMode[] = ["auto", "paginate", "scroll", "load_more"];
const VERTICAL_OPTIONS: Array<{ value: Vertical; label: string }> = [
  { value: "ecommerce", label: "Ecommerce" },
  { value: "jobs", label: "Jobs" },
  { value: "automobile", label: "Automobile" },
];

export default function CrawlStudioPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const initializedFromQuery = useRef(false);
  const [tab, setTab] = useState<SubmissionTab>("crawl");
  const [vertical, setVertical] = useState<Vertical>("ecommerce");
  const [pageType, setPageType] = useState<PageType>("category");
  const [url, setUrl] = useState("");
  const [batchUrls, setBatchUrls] = useState("");
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [advancedEnabled, setAdvancedEnabled] = useState(false);
  const [advancedMode, setAdvancedMode] = useState<AdvancedMode>("auto");
  const [maxPages, setMaxPages] = useState("10");
  const [maxRecords, setMaxRecords] = useState(String(PAGE_CONFIG.ecommerce.category.maxRecords));
  const [sleepMs, setSleepMs] = useState("500");
  const [proxyEnabled, setProxyEnabled] = useState(false);
  const [proxyListInput, setProxyListInput] = useState("");
  const [llmEnabled, setLlmEnabled] = useState(false);
  const [additionalFieldInput, setAdditionalFieldInput] = useState("");
  const [additionalFields, setAdditionalFields] = useState<string[]>([]);
  const [contractRows, setContractRows] = useState<ContractRow[]>([]);
  const [nextRowId, setNextRowId] = useState(1);
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const pageConfig = PAGE_CONFIG[vertical][pageType];

  const applyPrefill = useCallback((prefill: CrawlPrefill) => {
    if (prefill.tab) {
      setTab(prefill.tab);
    }
    if (prefill.vertical) {
      setVertical(prefill.vertical);
    }
    if (prefill.pageType) {
      setPageType(prefill.pageType);
      const configVertical = prefill.vertical ?? vertical;
      setMaxRecords(String(PAGE_CONFIG[configVertical][prefill.pageType].maxRecords));
    }
    if (Array.isArray(prefill.urls) && prefill.urls.length) {
      setBatchUrls(prefill.urls.join("\n"));
      if ((prefill.tab ?? requestedSubmissionTab(prefill.urls.length)) === "crawl") {
        setUrl(prefill.urls[0] ?? "");
      }
    }
    if (Array.isArray(prefill.additional_fields) && prefill.additional_fields.length) {
      setAdditionalFields(Array.from(new Set(prefill.additional_fields.map(normalizeFieldName).filter(Boolean))));
    }
    if (Array.isArray(prefill.selectors) && prefill.selectors.length) {
      const rows = prefill.selectors
        .map((row, index) => ({
          id: index + 1,
          field_name: normalizeFieldName(String(row.field_name ?? "")),
          xpath: String(row.xpath ?? "").trim(),
          regex: String(row.regex ?? "").trim(),
        }))
        .filter((row) => row.field_name && (row.xpath || row.regex));
      setContractRows(rows);
      setNextRowId(rows.length + 1);
    }
  }, [vertical]);

  useEffect(() => {
    if (initializedFromQuery.current) return;
    initializedFromQuery.current = true;

    const requestedTab = searchParams.get("tab");
    if (requestedTab === "batch" || requestedTab === "csv" || requestedTab === "crawl") {
      setTab(requestedTab);
    }

    const pastedUrls = searchParams.get("urls");
    if (pastedUrls && requestedTab === "batch") {
      setBatchUrls(pastedUrls);
    } else if (typeof window !== "undefined") {
      const stored = window.sessionStorage.getItem("bulk-crawl-prefill-v1");
      if (stored) {
        try {
          applyPrefill(JSON.parse(stored) as CrawlPrefill);
        } catch {
          // Ignore malformed prefill data.
        } finally {
          window.sessionStorage.removeItem("bulk-crawl-prefill-v1");
        }
      }
    }
  }, [applyPrefill, searchParams]);

  function updatePageType(next: PageType) {
    setPageType(next);
    setMaxRecords(String(PAGE_CONFIG[vertical][next].maxRecords));
    setContractRows([]);
    setNextRowId(1);
    setAdditionalFields([]);
    setAdditionalFieldInput("");
  }

  function updateVertical(next: Vertical) {
    setVertical(next);
    setPageType("category");
    setMaxRecords(String(PAGE_CONFIG[next].category.maxRecords));
    setContractRows([]);
    setNextRowId(1);
    setAdditionalFields([]);
    setAdditionalFieldInput("");
  }

  function addContractRow() {
    setContractRows((current) => [
      ...current,
      { id: nextRowId, field_name: "", xpath: "", regex: "" },
    ]);
    setNextRowId((current) => current + 1);
  }

  function addAdditionalFields(rawValue: string) {
    const nextFields = rawValue
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
    if (!nextFields.length) {
      return;
    }
    setAdditionalFields((current) => {
      const merged = new Set(current);
      for (const field of nextFields) {
        merged.add(field);
      }
      return Array.from(merged);
    });
    setAdditionalFieldInput("");
  }

  function removeAdditionalField(fieldName: string) {
    setAdditionalFields((current) => current.filter((field) => field !== fieldName));
  }

  function updateContractRow(id: number, key: "field_name" | "xpath" | "regex", value: string) {
    setContractRows((current) =>
      current.map((row) => (row.id === id ? { ...row, [key]: value } : row)),
    );
  }

  function removeContractRow(id: number) {
    setContractRows((current) => current.filter((row) => row.id !== id));
  }

  function getExtractionContract() {
    return contractRows
      .map((row) => ({
        field_name: row.field_name.trim(),
        xpath: row.xpath.trim(),
        regex: row.regex.trim(),
      }))
      .filter((row) => row.field_name);
  }

  function getAdditionalFields() {
    return Array.from(
      new Set([
        ...additionalFields,
        ...getExtractionContract().map((row) => row.field_name),
      ]),
    );
  }

  function getSettings() {
    return {
      page_type: pageType,
      advanced_mode: advancedEnabled ? advancedMode : null,
      max_pages: Number.parseInt(maxPages, 10) || 10,
      max_records: Number.parseInt(maxRecords, 10) || pageConfig.maxRecords,
      sleep_ms: Number.parseInt(sleepMs, 10) || 0,
      proxy_list: proxyEnabled ? splitLines(proxyListInput) : [],
      llm_enabled: llmEnabled,
      extraction_contract: getExtractionContract(),
    };
  }

  async function submitCrawl(event: FormEvent) {
    event.preventDefault();
    setError("");
    setIsSubmitting(true);
    try {
      const settings = getSettings();
      const additionalFields = getAdditionalFields();

      if (tab === "crawl") {
        if (!url.trim()) {
          throw new Error("Enter a URL to start the crawl.");
        }
        const response = await api.createCrawl({
          run_type: "crawl",
          url: url.trim(),
          surface: pageConfig.surface,
          settings,
          additional_fields: additionalFields,
        });
        router.push(`/runs/${response.run_id}`);
        return;
      }

      if (tab === "batch") {
        const urls = splitLines(batchUrls);
        if (!urls.length) {
          throw new Error("Paste one or more URLs for the batch crawl.");
        }
        const response = await api.createCrawl({
          run_type: "batch",
          url: urls[0],
          urls,
          surface: pageConfig.surface,
          settings: { ...settings, urls },
          additional_fields: additionalFields,
        });
        router.push(`/runs/${response.run_id}`);
        return;
      }

      if (!csvFile) {
        throw new Error("Select a CSV file with URLs in the first column.");
      }
      const response = await api.createCsvCrawl({
        file: csvFile,
        surface: pageConfig.surface,
        additionalFields,
        settings,
      });
      router.push(`/runs/${response.run_id}`);
    } catch (submissionError) {
      setError(submissionError instanceof Error ? submissionError.message : "Unable to submit crawl.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="space-y-4">
      <PageHeader title="Crawl Studio" description="Run single, batch, or CSV crawls." />

      <form className="grid gap-4 xl:grid-cols-[minmax(0,1.65fr)_320px]" onSubmit={submitCrawl}>
        <div className="stagger-children space-y-4">
          {/* Submission card */}
          <Card className="space-y-4">
            <div className="flex items-center justify-between gap-3">
              <TabGroup>
                <TabButton active={tab === "crawl"} onClick={() => setTab("crawl")}>
                  Crawl
                </TabButton>
                <TabButton active={tab === "batch"} onClick={() => setTab("batch")}>
                  Batch
                </TabButton>
                <TabButton active={tab === "csv"} onClick={() => setTab("csv")}>
                  CSV
                </TabButton>
              </TabGroup>
              <Button type="submit" variant="accent" disabled={isSubmitting}>
                {isSubmitting ? "Submitting..." : "Start crawl"}
              </Button>
            </div>

            {tab === "crawl" ? (
              <div className="grid gap-1.5">
                <label className="text-[13px] font-medium text-foreground">{pageConfig.urlLabel}</label>
                <Input
                  value={url}
                  onChange={(event) => setUrl(event.target.value)}
                  placeholder={pageConfig.urlPlaceholder}
                />
              </div>
            ) : null}

            {tab === "batch" ? (
              <div className="grid gap-1.5">
                <label className="text-[13px] font-medium text-foreground">Batch URLs</label>
                <Textarea
                  value={batchUrls}
                  onChange={(event) => setBatchUrls(event.target.value)}
                  placeholder={"https://example.com/products/a\nhttps://example.com/products/b"}
                  className="min-h-36"
                />
              </div>
            ) : null}

            {tab === "csv" ? (
              <div className="grid gap-1.5">
                <label className="text-[13px] font-medium text-foreground">CSV Upload</label>
                <Input
                  type="file"
                  accept=".csv,text/csv"
                  onChange={(event) => setCsvFile(event.target.files?.[0] ?? null)}
                  className="h-auto py-2.5"
                />
              </div>
            ) : null}

            {/* Additional fields */}
            <div className="grid gap-2">
              <label className="text-[13px] font-medium text-foreground">Additional Fields</label>
              <div className="grid gap-2 md:grid-cols-[minmax(0,1fr)_auto]">
                <Input
                  value={additionalFieldInput}
                  onChange={(event) => setAdditionalFieldInput(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      addAdditionalFields(additionalFieldInput);
                    }
                  }}
                  placeholder="material, finish, warranty"
                />
                <Button type="button" variant="secondary" onClick={() => addAdditionalFields(additionalFieldInput)}>
                  Add
                </Button>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {additionalFields.length ? additionalFields.map((field) => (
                  <button
                    key={field}
                    type="button"
                    onClick={() => removeAdditionalField(field)}
                    aria-label={`Remove ${field}`}
                    className="group inline-flex items-center gap-1 rounded-md border border-border bg-panel-strong px-2 py-1 text-[12px] font-medium text-foreground transition hover:border-danger/40 hover:text-danger"
                  >
                    <span>{field}</span>
                    <span aria-hidden="true" className="text-muted transition group-hover:text-danger">
                      &times;
                    </span>
                  </button>
                )) : null}
              </div>
            </div>
          </Card>

          {/* Extraction contract */}
          <Card className="space-y-3">
            <div className="flex items-center justify-between gap-3">
              <div className="space-y-1">
                <h2 className="text-[15px] font-semibold tracking-[-0.01em] text-foreground">Additional Field Selectors</h2>
                <p className="text-[12px] text-muted">Use XPath or regex to add extra fields for single, bulk, or CSV crawls.</p>
              </div>
              <Button type="button" variant="secondary" onClick={addContractRow}>
                <Plus className="size-3.5" />
                Add row
              </Button>
            </div>

            {contractRows.length ? (
              <div className="overflow-hidden rounded-md border border-border">
                <div className="grid grid-cols-[160px_minmax(0,1fr)_180px_40px] gap-2 border-b border-border bg-panel-strong px-3 py-2 text-[11px] font-medium uppercase tracking-[0.04em] text-muted">
                  <span>Field</span>
                  <span>XPath</span>
                  <span>Regex</span>
                  <span />
                </div>
                <div className="divide-y divide-border">
                  {contractRows.map((row) => (
                    <div
                      key={row.id}
                      className="grid grid-cols-[160px_minmax(0,1fr)_180px_40px] gap-2 px-3 py-2 animate-fade-in"
                    >
                      <Input
                        value={row.field_name}
                        onChange={(event) => updateContractRow(row.id, "field_name", event.target.value)}
                        placeholder="field_name"
                      />
                      <Input
                        value={row.xpath}
                        onChange={(event) => updateContractRow(row.id, "xpath", event.target.value)}
                        placeholder="//h1 | //*[@itemprop='name']"
                      />
                      <Input
                        value={row.regex}
                        onChange={(event) => updateContractRow(row.id, "regex", event.target.value)}
                        placeholder="price:\s*([\d.]+)"
                      />
                      <button
                        type="button"
                        onClick={() => removeContractRow(row.id)}
                        className="inline-flex h-9 items-center justify-center rounded-md text-muted transition hover:bg-danger/10 hover:text-danger"
                        aria-label="Delete row"
                      >
                        <Trash2 className="size-3.5" />
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </Card>

          {error ? (
            <div className="animate-fade-in rounded-md border border-danger/20 bg-danger/5 px-3 py-2.5 text-[13px] text-danger">
              {error}
            </div>
          ) : null}
        </div>

        {/* Settings rail */}
        <div className="xl:sticky xl:top-4 xl:self-start">
          <Card className="space-y-1">
            <h2 className="pb-2 text-[15px] font-semibold tracking-[-0.01em] text-foreground">Settings</h2>

            <SettingRow label="Page Type">
              <TabGroup compact>
                <TabButton active={pageType === "category"} onClick={() => updatePageType("category")} compact>
                  Category
                </TabButton>
                <TabButton active={pageType === "pdp"} onClick={() => updatePageType("pdp")} compact>
                  PDP
                </TabButton>
              </TabGroup>
            </SettingRow>

            <SettingRow label="Vertical">
              <select
                value={vertical}
                onChange={(event) => updateVertical(event.target.value as Vertical)}
                className="focus-ring h-7 rounded-md border border-border bg-background px-2 text-[12px] text-foreground transition hover:border-border-strong"
                aria-label="Vertical"
              >
                {VERTICAL_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </SettingRow>

            <SettingRow label="Advanced">
              <MiniToggle enabled={advancedEnabled} onToggle={() => setAdvancedEnabled((current) => !current)} />
            </SettingRow>

            {advancedEnabled ? (
              <div className="animate-fade-in space-y-2.5 rounded-md border border-border bg-panel-strong/50 px-3 py-3">
                <label className="grid gap-1">
                  <span className="text-[11px] font-medium text-muted">Mode</span>
                  <select
                    value={advancedMode}
                    onChange={(event) => setAdvancedMode(event.target.value as AdvancedMode)}
                    className="focus-ring h-7 rounded-md border border-border bg-background px-2 text-[12px] text-foreground"
                  >
                    {ADVANCED_OPTIONS.map((option) => (
                      <option key={option} value={option}>
                        {formatAdvancedMode(option)}
                      </option>
                    ))}
                  </select>
                </label>

                <SliderControl label="Pages" value={maxPages} min={1} max={50} step={1} onChange={setMaxPages} />
                <SliderControl label="Records" value={maxRecords} min={1} max={pageType === "pdp" ? 10 : 500} step={pageType === "pdp" ? 1 : 10} onChange={setMaxRecords} />
                <SliderControl label="Wait Time" value={sleepMs} min={0} max={5000} step={100} suffix=" ms" onChange={setSleepMs} />
              </div>
            ) : null}

            <SettingRow label="Proxy">
              <MiniToggle enabled={proxyEnabled} onToggle={() => setProxyEnabled((current) => !current)} />
            </SettingRow>

            {proxyEnabled ? (
              <Textarea
                value={proxyListInput}
                onChange={(event) => setProxyListInput(event.target.value)}
                placeholder={"http://user:pass@host:port\nhttp://user:pass@host-2:port"}
                className="min-h-20 animate-fade-in"
              />
            ) : null}

            <SettingRow label="LLM">
              <MiniToggle enabled={llmEnabled} onToggle={() => setLlmEnabled((current) => !current)} />
            </SettingRow>
          </Card>
        </div>
      </form>
    </div>
  );
}

/* --- Local components --- */

function TabGroup({ children, compact }: Readonly<{ children: React.ReactNode; compact?: boolean }>) {
  return (
    <div className={cn(
      "inline-flex items-center rounded-md border border-border bg-panel-strong",
      compact ? "gap-0 p-0.5" : "gap-0 p-0.5",
    )}>
      {children}
    </div>
  );
}

function TabButton({
  active,
  children,
  onClick,
  compact,
}: Readonly<{ active: boolean; children: React.ReactNode; onClick: () => void; compact?: boolean }>) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex items-center justify-center rounded-[5px] font-medium transition-all",
        compact ? "h-6 px-2.5 text-[11px]" : "h-7 px-3 text-[13px]",
        active
          ? "bg-background text-foreground shadow-sm"
          : "text-muted hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

function SettingRow({
  label,
  children,
}: Readonly<{ label: string; children: React.ReactNode }>) {
  return (
    <div className="flex min-h-8 items-center justify-between gap-3 py-1">
      <span className="text-[13px] text-muted">{label}</span>
      <div className="flex items-center gap-2">{children}</div>
    </div>
  );
}

function SliderControl({
  label,
  value,
  min,
  max,
  step,
  suffix,
  onChange,
}: Readonly<{
  label: string;
  value: string;
  min: number;
  max: number;
  step: number;
  suffix?: string;
  onChange: (value: string) => void;
}>) {
  return (
    <label className="grid gap-1">
      <div className="flex items-center justify-between gap-3">
        <span className="text-[12px] text-foreground">{label}</span>
        <span className="font-mono text-[11px] text-muted">
          {value}{suffix ?? ""}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={clampSliderValue(value, min, max)}
        onChange={(event) => onChange(event.target.value)}
        className="h-1.5 w-full cursor-pointer appearance-none rounded-full bg-border accent-accent"
      />
    </label>
  );
}

function MiniToggle({
  enabled,
  onToggle,
}: Readonly<{ enabled: boolean; onToggle: () => void }>) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className={cn(
        "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors",
        enabled ? "bg-accent" : "bg-border-strong",
      )}
    >
      <span
        className={cn(
          "inline-block size-3.5 rounded-full bg-white shadow-sm transition-transform",
          enabled ? "translate-x-[18px]" : "translate-x-[3px]",
        )}
      />
    </button>
  );
}

function clampSliderValue(value: string, min: number, max: number) {
  const parsed = Number.parseInt(value, 10);
  if (Number.isNaN(parsed)) {
    return min;
  }
  return Math.min(max, Math.max(min, parsed));
}

function formatAdvancedMode(mode: AdvancedMode) {
  if (mode === "load_more") {
    return "Load More";
  }
  return mode.charAt(0).toUpperCase() + mode.slice(1);
}

function splitLines(value: string) {
  return value
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function normalizeFieldName(value: string) {
  return value.trim().toLowerCase().replace(/\s+/g, "_");
}

function requestedSubmissionTab(urlCount: number): SubmissionTab {
  return urlCount > 1 ? "batch" : "crawl";
}
