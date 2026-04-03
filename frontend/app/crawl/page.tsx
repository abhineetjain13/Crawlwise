"use client";

import { FormEvent, useState } from "react";
import { Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";

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
    <div className="space-y-6">
      <PageHeader title="Crawl Studio" description="Run single, batch, or CSV crawls." />

      <form className="grid gap-5 xl:grid-cols-[minmax(0,1.65fr)_360px]" onSubmit={submitCrawl}>
        <div className="space-y-5">
          <Card className="space-y-4">
            <div className="flex items-center justify-between gap-3">
              <div className="flex flex-wrap gap-2">
                <StudioToggleButton active={tab === "crawl"} onClick={() => setTab("crawl")}>
                  Crawl
                </StudioToggleButton>
                <StudioToggleButton active={tab === "batch"} onClick={() => setTab("batch")}>
                  Batch
                </StudioToggleButton>
                <StudioToggleButton active={tab === "csv"} onClick={() => setTab("csv")}>
                  CSV
                </StudioToggleButton>
              </div>
              <Button type="submit" disabled={isSubmitting}>
                {isSubmitting ? "Submitting..." : "Start crawl"}
              </Button>
            </div>

            {tab === "crawl" ? (
              <div className="grid gap-2">
                <label className="text-sm font-medium text-foreground">{pageConfig.urlLabel}</label>
                <Input
                  value={url}
                  onChange={(event) => setUrl(event.target.value)}
                  placeholder={pageConfig.urlPlaceholder}
                />
                <div className="grid gap-3">
                  <label className="text-sm font-medium text-foreground">Additional Fields</label>
                  <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto]">
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
                      Add fields
                    </Button>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {additionalFields.length ? additionalFields.map((field) => (
                      <button
                        key={field}
                        type="button"
                        onClick={() => removeAdditionalField(field)}
                        aria-label={`Remove ${field}`}
                        className="group inline-flex items-center gap-1.5 rounded-full border border-border bg-background-elevated px-3 py-1.5 text-xs font-medium text-foreground transition hover:border-brand hover:text-brand focus-visible:border-brand focus-visible:text-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/20"
                      >
                        <span>{field}</span>
                        <span
                          aria-hidden="true"
                          className="text-[13px] leading-none text-muted transition group-hover:text-brand"
                        >
                          ×
                        </span>
                      </button>
                    )) : null}
                  </div>
                </div>
              </div>
            ) : null}

            {tab === "batch" ? (
              <div className="grid gap-2">
                <label className="text-sm font-medium text-foreground">Batch URLs</label>
                <Textarea
                  value={batchUrls}
                  onChange={(event) => setBatchUrls(event.target.value)}
                  placeholder={"https://example.com/products/a\nhttps://example.com/products/b"}
                  className="min-h-40"
                />
              </div>
            ) : null}

            {tab === "csv" ? (
              <div className="grid gap-2">
                <label className="text-sm font-medium text-foreground">CSV Upload</label>
                <Input
                  type="file"
                  accept=".csv,text/csv"
                  onChange={(event) => setCsvFile(event.target.files?.[0] ?? null)}
                  className="h-auto py-3"
                />
              </div>
            ) : null}
          </Card>

          <Card className="space-y-4">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-lg font-semibold tracking-tight text-foreground">Extraction Contract</h2>
              <Button type="button" variant="secondary" onClick={addContractRow}>
                Add row
              </Button>
            </div>

            {contractRows.length ? (
              <div className="overflow-hidden rounded-xl border border-border">
                <div className="grid grid-cols-[180px_minmax(0,1fr)_220px_56px] gap-3 border-b border-border bg-panel-strong/60 px-4 py-3 text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">
                  <span>Field</span>
                  <span>XPath</span>
                  <span>Regex</span>
                  <span />
                </div>
                <div className="divide-y divide-border">
                  {contractRows.map((row) => (
                    <div
                      key={row.id}
                      className="grid grid-cols-[180px_minmax(0,1fr)_220px_56px] gap-3 px-4 py-3"
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
                        placeholder="price:\\s*([\\d.]+)"
                      />
                      <button
                        type="button"
                        onClick={() => removeContractRow(row.id)}
                        className="inline-flex h-11 items-center justify-center rounded-xl text-muted transition hover:bg-panel-strong hover:text-foreground"
                        aria-label="Delete row"
                        title="Delete row"
                      >
                        <Trash2 className="size-4" />
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </Card>

          {error ? (
            <Card className="border-red-500/30 bg-red-500/10 text-sm text-red-700 dark:text-red-300">
              {error}
            </Card>
          ) : null}
        </div>

        <div className="xl:sticky xl:top-4 xl:self-start">
          <Card className="space-y-2">
            <h2 className="text-lg font-semibold tracking-tight text-foreground">Crawl Settings</h2>

            <CompactRow label="Page Type">
              <div className="flex gap-2">
                <StudioToggleButton active={pageType === "category"} onClick={() => updatePageType("category")}>
                  Category
                </StudioToggleButton>
                <StudioToggleButton active={pageType === "pdp"} onClick={() => updatePageType("pdp")}>
                  PDP
                </StudioToggleButton>
              </div>
            </CompactRow>

            <CompactRow label="Vertical">
              <select
                value={vertical}
                onChange={(event) => updateVertical(event.target.value as Vertical)}
                className="h-9 w-[150px] rounded-xl border border-border bg-background-elevated px-3 text-sm text-foreground outline-none transition focus:border-brand focus:ring-2 focus:ring-brand/20"
                aria-label="Vertical"
              >
                {VERTICAL_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </CompactRow>

            <CompactRow label="Advanced">
              <MiniToggle enabled={advancedEnabled} onToggle={() => setAdvancedEnabled((current) => !current)} />
            </CompactRow>

            {advancedEnabled ? (
              <div className="pb-1">
                <div className="grid gap-3 rounded-lg border border-border/60 bg-panel-strong/35 px-3.5 py-3.5">
                  <label className="grid gap-1.5">
                    <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">Mode</span>
                    <select
                      value={advancedMode}
                      onChange={(event) => setAdvancedMode(event.target.value as AdvancedMode)}
                      className="h-9 rounded-lg border border-border bg-background-elevated px-3 text-sm text-foreground outline-none transition focus:border-brand focus:ring-2 focus:ring-brand/20"
                    >
                      {ADVANCED_OPTIONS.map((option) => (
                        <option key={option} value={option}>
                          {formatAdvancedMode(option)}
                        </option>
                      ))}
                    </select>
                  </label>

                  <SliderControl
                    label="Pages"
                    value={maxPages}
                    min={1}
                    max={50}
                    step={1}
                    onChange={setMaxPages}
                  />
                  <SliderControl
                    label="Records"
                    value={maxRecords}
                    min={1}
                    max={pageType === "pdp" ? 10 : 500}
                    step={pageType === "pdp" ? 1 : 10}
                    onChange={setMaxRecords}
                  />
                  <SliderControl
                    label="Wait Time"
                    value={sleepMs}
                    min={0}
                    max={5000}
                    step={100}
                    suffix=" ms"
                    onChange={setSleepMs}
                  />
                </div>
              </div>
            ) : null}

            <CompactRow label="Proxy">
              <MiniToggle enabled={proxyEnabled} onToggle={() => setProxyEnabled((current) => !current)} />
            </CompactRow>

            {proxyEnabled ? (
              <Textarea
                value={proxyListInput}
                onChange={(event) => setProxyListInput(event.target.value)}
                placeholder={"http://user:pass@host:port\nhttp://user:pass@host-2:port"}
                className="min-h-24"
              />
            ) : null}

            <CompactRow label="LLM">
              <MiniToggle enabled={llmEnabled} onToggle={() => setLlmEnabled((current) => !current)} />
            </CompactRow>
          </Card>
        </div>
      </form>
    </div>
  );
}

function CompactRow({
  label,
  children,
}: Readonly<{ label: string; children: React.ReactNode }>) {
  return (
    <div className="grid min-h-10 gap-2 py-1.5 sm:grid-cols-[140px_minmax(0,1fr)] sm:items-center sm:gap-3">
      <span className="text-sm font-medium text-foreground">{label}</span>
      <div className="flex flex-wrap items-center justify-start gap-2">{children}</div>
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
    <label className="grid gap-1.5">
      <div className="flex items-center justify-between gap-3 text-sm">
        <span className="font-medium text-foreground">{label}</span>
        <span className="font-mono text-xs text-muted">
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
        className="h-2 w-full cursor-pointer accent-[var(--brand)]"
      />
    </label>
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

function StudioToggleButton({
  active,
  children,
  onClick,
}: Readonly<{ active: boolean; children: React.ReactNode; onClick: () => void }>) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex h-8 items-center justify-center rounded-xl px-3.5 text-sm font-semibold transition",
        active ? "bg-brand text-brand-foreground shadow-sm" : "border border-border bg-panel text-foreground hover:bg-panel-strong",
      )}
    >
      {children}
    </button>
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
        "relative inline-flex h-6 w-11 items-center rounded-full border transition",
        enabled ? "border-brand bg-brand" : "border-border bg-panel-strong",
      )}
    >
      <span
        className={cn(
          "inline-block h-4 w-4 rounded-full transition",
          enabled ? "translate-x-6 bg-white" : "translate-x-1 bg-muted",
        )}
      />
    </button>
  );
}

function splitLines(value: string) {
  return value
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean);
}
