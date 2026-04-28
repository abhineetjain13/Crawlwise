"use client";

import { Copy, Download, Loader2, X } from "lucide-react";
import React, { useEffect } from "react";

import { Badge, Button, Dropdown, Field, Input, Textarea } from "../../components/ui/primitives";
import type { ProductIntelligenceDiscoveryResponse, ProductIntelligenceOptions } from "../../lib/api/types";
import { cn } from "../../lib/utils";

export const SEARCH_PROVIDER_OPTIONS: Array<{ value: ProductIntelligenceOptions["search_provider"]; label: string }> = [
  { value: "serpapi", label: "SerpAPI" },
  { value: "google_native", label: "Google Native" },
];

export function searchProviderLabel(provider: string) {
  const option = SEARCH_PROVIDER_OPTIONS.find((item) => item.value === provider);
  return option?.label ?? provider;
}

function hideBrokenImage(event: React.SyntheticEvent<HTMLImageElement>): void {
  event.currentTarget.style.display = "none";
}

export function ExternalCandidateImage({
  src,
  alt,
  className,
}: Readonly<{
  src: string;
  alt: string;
  className: string;
}>) {
  return (
    <>
      {/* eslint-disable-next-line @next/next/no-img-element -- external candidate URLs are not known at build time */}
      <img
        src={src}
        alt={alt}
        className={className}
        onError={hideBrokenImage}
      />
    </>
  );
}

export function JsonModal({
  candidate,
  onClose,
}: Readonly<{
  candidate: ProductIntelligenceDiscoveryResponse["candidates"][number];
  onClose: () => void;
}>) {
  const intelligence = isRecord(candidate.intelligence) ? candidate.intelligence : {};
  const hasIntelligence = Object.keys(intelligence).length > 0;
  const text = JSON.stringify(hasIntelligence ? intelligence : (candidate.payload ?? {}), null, 2);

  return (
    <>
      <div className="fixed inset-0 z-50 bg-black/40" onClick={onClose} aria-hidden="true" />
      <div className="fixed left-1/2 top-1/2 z-50 flex max-h-[80vh] w-[640px] max-w-[90vw] -translate-x-1/2 -translate-y-1/2 flex-col rounded-[var(--radius-md)] border border-border bg-background-elevated shadow-xl">
        <div className="flex items-center justify-between border-b border-divider px-4 py-3">
          <h3 className="text-sm font-medium text-foreground type-heading">Raw JSON</h3>
          <Button type="button" variant="ghost" size="icon" className="h-7 w-7" onClick={onClose} aria-label="Close">
            <X className="size-3.5" />
          </Button>
        </div>
        <div className="flex-1 overflow-auto p-4">
          <pre className="crawl-terminal crawl-terminal-json text-xs leading-relaxed">{text}</pre>
        </div>
        <div className="flex items-center justify-end gap-2 border-t border-divider px-4 py-3">
          <Button type="button" variant="ghost" size="sm" className="h-7 text-xs" onClick={() => void navigator.clipboard.writeText(text)}>
            <Copy className="mr-1 size-3" /> Copy
          </Button>
          <Button
            type="button"
            variant="accent"
            size="sm"
            className="h-7 text-xs"
            onClick={() => {
              const blob = new Blob([text], { type: "application/json" });
              const url = URL.createObjectURL(blob);
              const a = document.createElement("a");
              a.href = url;
              a.download = `candidate-${candidate.domain || "data"}.json`;
              a.click();
              URL.revokeObjectURL(url);
            }}
          >
            <Download className="mr-1 size-3" /> Download
          </Button>
        </div>
      </div>
    </>
  );
}

export function ProductIntelligenceJobRow({
  job,
  active,
  onOpen,
}: Readonly<{
  job: {
    id: number;
    status: string;
    summary: Record<string, unknown>;
    created_at: string;
  };
  active: boolean;
  onOpen: () => void;
}>) {
  const candidateCount = Number(job.summary?.candidate_count ?? 0);
  return (
    <tr className={cn("border-b border-divider last:border-0 hover:bg-background-alt transition-colors", active && "bg-background-alt")}>
      <td className="p-0">
        <button type="button" onClick={onOpen} className="flex w-full flex-col text-left gap-1.5 p-2.5 focus:outline-none">
          <div className="flex w-full items-center justify-between">
            <span className="font-mono text-sm font-normal text-accent hover:underline">#{job.id}</span>
            <Badge tone={job.status === "complete" ? "success" : job.status === "failed" ? "danger" : "neutral"} className="scale-90 origin-right">
              {job.status}
            </Badge>
          </div>
          <div className="flex w-full items-center justify-between text-xs text-muted">
            <span>{candidateCount} URLs found</span>
            <span className="font-mono">{formatShortDate(job.created_at)}</span>
          </div>
        </button>
      </td>
    </tr>
  );
}

export function DiscoveryStatus({
  provider,
  sourceCount,
  maxCandidates,
}: Readonly<{
  provider: string;
  sourceCount: number;
  maxCandidates: number;
}>) {
  const providerLabel = searchProviderLabel(provider);
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-[var(--radius-md)] border border-accent/30 bg-accent-subtle px-4 py-3 text-xs text-foreground">
      <Loader2 className="size-4 animate-spin text-accent" aria-hidden="true" />
      <div className="min-w-[180px] flex-1">
        <div className="font-medium">{providerLabel} discovery running</div>
        <div className="mt-0.5 text-muted">
          Searching {sourceCount} source product{sourceCount === 1 ? "" : "s"}, filtering source domains, ranking brand sites before aggregators.
        </div>
      </div>
      <div className="flex items-center gap-2">
        <Badge tone="info" className="h-5 px-1.5 text-xs">{providerLabel}</Badge>
        <Badge tone="neutral" className="h-5 px-1.5 text-xs">Max {maxCandidates}/product</Badge>
      </div>
    </div>
  );
}

export function DiscoveryTableLoading({ provider }: Readonly<{ provider: string }>) {
  const providerLabel = searchProviderLabel(provider);
  return (
    <div className="flex min-h-[220px] flex-col items-center justify-center gap-4 px-6 py-10 text-center">
      <div className="relative">
        <div className="size-12 rounded-full border border-accent/25 bg-accent-subtle" />
        <Loader2 className="absolute left-1/2 top-1/2 size-5 -translate-x-1/2 -translate-y-1/2 animate-spin text-accent" aria-hidden="true" />
      </div>
      <div>
        <div className="text-sm font-medium text-foreground">{providerLabel} is searching product candidates</div>
        <div className="mt-1 max-w-[520px] text-xs leading-5 text-muted">
          Querying organic results, removing blocked/source domains, classifying domains, and scoring each result from title, brand, identifiers, price, and source authority.
        </div>
      </div>
      <div className="grid w-full max-w-[560px] gap-2 text-left sm:grid-cols-3">
        <DiscoveryLoadingStep label="Search" detail="Provider request active" />
        <DiscoveryLoadingStep label="Filter" detail="Source domain excluded" />
        <DiscoveryLoadingStep label="Rank" detail="Brand DTC first" />
      </div>
    </div>
  );
}

export function SettingsDrawer({
  open,
  onClose,
  options,
  onOptionsChange,
  allowedDomainsText,
  onAllowedDomainsTextChange,
  excludedDomainsText,
  onExcludedDomainsTextChange,
  maxSourceProductsLimit,
  maxCandidatesPerProductLimit,
  defaultOptions,
}: Readonly<{
  open: boolean;
  onClose: () => void;
  options: ProductIntelligenceOptions;
  onOptionsChange: (patch: Partial<ProductIntelligenceOptions>) => void;
  allowedDomainsText: string;
  onAllowedDomainsTextChange: (value: string) => void;
  excludedDomainsText: string;
  onExcludedDomainsTextChange: (value: string) => void;
  maxSourceProductsLimit: number;
  maxCandidatesPerProductLimit: number;
  defaultOptions: ProductIntelligenceOptions;
}>) {
  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <>
      <div
        className="fixed inset-0 z-40 bg-black/20"
        onClick={onClose}
        aria-hidden="true"
      />
      <div className="fixed right-0 top-0 z-50 h-full w-[380px] max-w-full overflow-y-auto border-l border-divider bg-background-elevated p-5 shadow-xl animate-in slide-in-from-right-4 duration-200">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-medium text-foreground type-heading">Configuration</h2>
          <Button type="button" variant="ghost" size="icon" className="h-7 w-7" onClick={onClose} aria-label="Close settings">
            <X className="size-3.5" />
          </Button>
        </div>
        <div className="mt-4 space-y-4">
          <Field label="Provider">
            <div className="flex gap-1.5">
              {SEARCH_PROVIDER_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => onOptionsChange({ search_provider: opt.value })}
                  aria-pressed={options.search_provider === opt.value}
                  className={cn(
                    "flex-1 rounded-[var(--radius-md)] border px-3 py-1.5 text-sm font-medium transition-[background-color,border-color] text-center",
                    options.search_provider === opt.value
                      ? "border-accent bg-accent-subtle text-accent"
                      : "border-border-strong bg-background-elevated text-foreground hover:bg-background-alt"
                  )}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </Field>
          <Field label="Max Sources">
            <Input
              type="number"
              min={1}
              max={maxSourceProductsLimit}
              value={options.max_source_products}
              onChange={(event) => onOptionsChange({
                max_source_products: clampInt(event.target.value, 1, maxSourceProductsLimit, defaultOptions.max_source_products),
              })}
            />
          </Field>
          <Field label="Max URLs">
            <Input
              type="number"
              min={1}
              max={maxCandidatesPerProductLimit}
              value={options.max_candidates_per_product}
              onChange={(event) => onOptionsChange({
                max_candidates_per_product: clampInt(event.target.value, 1, maxCandidatesPerProductLimit, defaultOptions.max_candidates_per_product),
              })}
            />
          </Field>
          <Field label="Private Label">
            <Dropdown
              value={options.private_label_mode}
              onChange={(value) => onOptionsChange({ private_label_mode: value as ProductIntelligenceOptions["private_label_mode"] })}
              options={[
                { value: "flag", label: "Flag" },
                { value: "exclude", label: "Exclude" },
                { value: "include", label: "Include" },
              ]}
            />
          </Field>
          <Field label="LLM Cleanup">
            <div className="surface-muted flex h-[var(--control-height)] items-center justify-between rounded-[var(--radius-md)] px-3 shadow-sm">
              <span className="text-xs font-normal text-muted">Enable Enrichment</span>
              <input
                type="checkbox"
                checked={options.llm_enrichment_enabled}
                onChange={(event) => onOptionsChange({ llm_enrichment_enabled: event.target.checked })}
                className="h-3.5 w-3.5 rounded border-divider text-accent focus:ring-accent"
              />
            </div>
          </Field>
          <Field label="Allowed Domains">
            <Textarea
              value={allowedDomainsText}
              onChange={(event) => onAllowedDomainsTextChange(event.target.value)}
              className="min-h-[76px] text-xs"
              placeholder="ralphlauren.com"
            />
          </Field>
          <Field label="Excluded Domains">
            <Textarea
              value={excludedDomainsText}
              onChange={(event) => onExcludedDomainsTextChange(event.target.value)}
              className="min-h-[76px] text-xs"
              placeholder="amazon.com"
            />
          </Field>
        </div>
      </div>
    </>
  );
}

function DiscoveryLoadingStep({ label, detail }: Readonly<{ label: string; detail: string }>) {
  return (
    <div className="rounded-[var(--radius-md)] border border-divider bg-background-alt px-3 py-2">
      <div className="flex items-center gap-2 text-xs font-medium text-foreground">
        <span className="size-1.5 rounded-full bg-accent" />
        {label}
      </div>
      <div className="mt-1 text-xs text-muted">{detail}</div>
    </div>
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function searchProvider(value: unknown): ProductIntelligenceOptions["search_provider"] {
  return value === "google_native" || value === "serpapi" ? value : "google_native";
}

function clampInt(value: unknown, min: number, max: number, fallback: number) {
  const parsed = Number.parseInt(String(value), 10);
  if (!Number.isFinite(parsed)) {
    return fallback;
  }
  return Math.min(Math.max(parsed, min), max);
}

function formatShortDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
