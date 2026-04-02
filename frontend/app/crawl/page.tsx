"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

import { Button, Card, Input, Textarea } from "../../components/ui/primitives";
import { PageHeader } from "../../components/ui/patterns";
import { api } from "../../lib/api";
import { cn } from "../../lib/utils";

type SubmissionTab = "crawl" | "batch" | "csv";
type PageType = "category" | "pdp";
type AdvancedMode = "auto" | "paginate" | "scroll" | "load_more";

type ContractRow = {
  id: number;
  field_name: string;
  xpath: string;
  regex: string;
};

const PAGE_CONFIG: Record<PageType, {
  urlLabel: string;
  urlPlaceholder: string;
  surface: string;
  defaultFields: string[];
  maxRecords: number;
}> = {
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
};

const ADVANCED_OPTIONS: AdvancedMode[] = ["auto", "paginate", "scroll", "load_more"];

export default function CrawlStudioPage() {
  const router = useRouter();
  const [tab, setTab] = useState<SubmissionTab>("crawl");
  const [pageType, setPageType] = useState<PageType>("category");
  const [url, setUrl] = useState("");
  const [batchUrls, setBatchUrls] = useState("");
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [advancedEnabled, setAdvancedEnabled] = useState(false);
  const [advancedMode, setAdvancedMode] = useState<AdvancedMode>("auto");
  const [maxPages, setMaxPages] = useState("10");
  const [maxRecords, setMaxRecords] = useState(String(PAGE_CONFIG.category.maxRecords));
  const [sleepMs, setSleepMs] = useState("500");
  const [proxyEnabled, setProxyEnabled] = useState(false);
  const [proxyListInput, setProxyListInput] = useState("");
  const [llmEnabled, setLlmEnabled] = useState(false);
  const [contractRows, setContractRows] = useState<ContractRow[]>(() => createDefaultRows("category"));
  const [nextRowId, setNextRowId] = useState(contractRows.length + 1);
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const pageConfig = PAGE_CONFIG[pageType];

  function updatePageType(next: PageType) {
    setPageType(next);
    setMaxRecords(String(PAGE_CONFIG[next].maxRecords));
    const rows = createDefaultRows(next);
    setContractRows(rows);
    setNextRowId(rows.length + 1);
  }

  function addContractRow() {
    setContractRows((current) => [
      ...current,
      { id: nextRowId, field_name: "", xpath: "", regex: "" },
    ]);
    setNextRowId((current) => current + 1);
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
    const defaults = new Set(pageConfig.defaultFields);
    return Array.from(
      new Set(
        getExtractionContract()
          .map((row) => row.field_name)
          .filter((fieldName) => !defaults.has(fieldName)),
      ),
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
      <PageHeader title="Crawl Studio" description="Submit category, PDP, batch, or CSV crawls." />

      <form className="grid gap-6 xl:grid-cols-[minmax(0,1.5fr)_340px]" onSubmit={submitCrawl}>
        <div className="space-y-6">
          <Card className="space-y-4">
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

            {tab === "crawl" ? (
              <div className="grid gap-2">
                <label className="text-sm font-medium text-foreground">{pageConfig.urlLabel}</label>
                <Input
                  value={url}
                  onChange={(event) => setUrl(event.target.value)}
                  placeholder={pageConfig.urlPlaceholder}
                />
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

            <div className="overflow-hidden rounded-[1.5rem] border border-border">
              <div className="grid grid-cols-[180px_minmax(0,1fr)_220px_52px] gap-3 border-b border-border bg-panel-strong/80 px-4 py-3 text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">
                <span>Field</span>
                <span>XPath</span>
                <span>Regex</span>
                <span />
              </div>
              <div className="divide-y divide-border">
                {contractRows.map((row) => (
                  <div
                    key={row.id}
                    className="grid grid-cols-[180px_minmax(0,1fr)_220px_52px] gap-3 px-4 py-3"
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
                    <Button type="button" variant="ghost" onClick={() => removeContractRow(row.id)}>
                      Del
                    </Button>
                  </div>
                ))}
              </div>
            </div>
          </Card>

          {error ? (
            <Card className="border-red-500/30 bg-red-500/8 text-sm text-red-700 dark:text-red-300">
              {error}
            </Card>
          ) : null}
        </div>

        <div className="xl:sticky xl:top-4 xl:self-start">
          <Card className="space-y-3">
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

            <CompactRow label="Advanced">
              <div className="flex items-center gap-2">
                <MiniToggle enabled={advancedEnabled} onToggle={() => setAdvancedEnabled((current) => !current)} />
                {advancedEnabled ? (
                  <select
                    value={advancedMode}
                    onChange={(event) => setAdvancedMode(event.target.value as AdvancedMode)}
                    className="h-9 rounded-2xl border border-border bg-transparent px-3 text-sm text-foreground outline-none transition focus:border-brand focus:ring-2 focus:ring-brand/20"
                  >
                    {ADVANCED_OPTIONS.map((option) => (
                      <option key={option} value={option}>
                        {option}
                      </option>
                    ))}
                  </select>
                ) : null}
              </div>
            </CompactRow>

            <CompactRow label="Max Pages">
              <Input value={maxPages} onChange={(event) => setMaxPages(event.target.value)} inputMode="numeric" className="h-9 w-24" />
            </CompactRow>

            <CompactRow label="Max Records">
              <Input value={maxRecords} onChange={(event) => setMaxRecords(event.target.value)} inputMode="numeric" className="h-9 w-24" />
            </CompactRow>

            <CompactRow label="Wait ms">
              <Input value={sleepMs} onChange={(event) => setSleepMs(event.target.value)} inputMode="numeric" className="h-9 w-24" />
            </CompactRow>

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

            <CompactRow label="Surface">
              <span className="text-sm font-medium text-foreground">{pageConfig.surface}</span>
            </CompactRow>

            <Button type="submit" className="w-full" disabled={isSubmitting}>
              {isSubmitting ? "Submitting..." : "Start crawl"}
            </Button>
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
    <div className="flex items-center justify-between gap-3 rounded-2xl border border-border/80 bg-panel-strong/40 px-3 py-2.5">
      <span className="text-sm font-medium text-foreground">{label}</span>
      <div className="flex items-center justify-end gap-2">{children}</div>
    </div>
  );
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
        "inline-flex h-9 items-center justify-center rounded-2xl px-3.5 text-sm font-semibold transition",
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
        "relative inline-flex h-6 w-11 items-center rounded-full transition",
        enabled ? "bg-brand" : "bg-panel",
      )}
    >
      <span
        className={cn(
          "inline-block h-5 w-5 rounded-full bg-white transition",
          enabled ? "translate-x-5" : "translate-x-1",
        )}
      />
    </button>
  );
}

function createDefaultRows(pageType: PageType): ContractRow[] {
  return PAGE_CONFIG[pageType].defaultFields.map((fieldName, index) => ({
    id: index + 1,
    field_name: fieldName,
    xpath: "",
    regex: "",
  }));
}

function splitLines(value: string) {
  return value
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean);
}
