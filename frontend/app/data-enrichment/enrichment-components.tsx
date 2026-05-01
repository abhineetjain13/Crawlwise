'use client';

import { Loader2 } from 'lucide-react';
import React from 'react';

import { Badge } from '../../components/ui/primitives';
import { cn } from '../../lib/utils';

export function EnrichmentStatus({
  sourceCount,
  llmEnabled,
}: Readonly<{
  sourceCount: number;
  llmEnabled: boolean;
}>) {
  return (
    <div className="border-accent/30 bg-accent-subtle text-foreground animate-in fade-in flex flex-wrap items-center gap-3 rounded-[var(--radius-md)] border px-4 py-3 text-xs duration-300">
      <Loader2 className="text-accent size-4 animate-spin" aria-hidden="true" />
      <div className="min-w-[180px] flex-1">
        <div className="font-medium">Enrichment running</div>
        <div className="text-muted mt-0.5">
          Processing {sourceCount} record{sourceCount === 1 ? '' : 's'}. Normalizing price, color,
          size, and category. {llmEnabled ? 'LLM refinement active.' : 'Deterministic rules only.'}
        </div>
      </div>
      <div className="flex items-center gap-2">
        <Badge
          tone={llmEnabled ? 'accent' : 'neutral'}
          className="h-5 px-1.5 text-[10px] font-bold tracking-tight uppercase"
        >
          {llmEnabled ? 'LLM ENABLED' : 'RULES ONLY'}
        </Badge>
        <Badge tone="info" className="h-5 px-1.5 text-[10px] font-bold tracking-tight uppercase">
          {sourceCount} RECORDS
        </Badge>
      </div>
    </div>
  );
}

export function EnrichmentTableLoading({ llmEnabled }: Readonly<{ llmEnabled: boolean }>) {
  return (
    <div className="animate-in fade-in zoom-in-95 flex min-h-[220px] flex-col items-center justify-center gap-4 px-6 py-10 text-center duration-500">
      <div className="relative">
        <div className="border-accent/25 bg-accent-subtle size-12 rounded-full border" />
        <Loader2
          className="text-accent absolute top-1/2 left-1/2 size-5 -translate-x-1/2 -translate-y-1/2 animate-spin"
          aria-hidden="true"
        />
      </div>
      <div>
        <div className="text-foreground text-sm font-medium">
          Analyzing and enriching product records
        </div>
        <div className="text-muted mt-1 max-w-[520px] text-xs leading-5">
          Executing deterministic attribute matching, category taxonomy alignment, and{' '}
          {llmEnabled ? 'LLM-driven semantic expansion.' : 'rule-based field normalization.'}
        </div>
      </div>
      <div className="grid w-full max-w-[640px] gap-2 text-left sm:grid-cols-2 lg:grid-cols-4">
        <EnrichmentLoadingStep label="Normalize" detail="Price, size & materials" />
        <EnrichmentLoadingStep label="Taxonomy" detail="Google Category match" />
        <EnrichmentLoadingStep label="Attributes" detail="Color & gender labels" />
        <EnrichmentLoadingStep
          label={llmEnabled ? 'LLM Refine' : 'SEO Build'}
          detail={llmEnabled ? 'Intent & semantic tags' : 'Keyword synthesis'}
        />
      </div>
    </div>
  );
}

function EnrichmentLoadingStep({ label, detail }: Readonly<{ label: string; detail: string }>) {
  return (
    <div className="border-divider bg-background-alt/50 hover:bg-background-alt rounded-[var(--radius-md)] border px-3 py-2 transition-colors">
      <div className="text-foreground flex items-center gap-2 text-[11px] font-bold tracking-tight uppercase">
        <span className="bg-accent size-1.5 animate-pulse rounded-full" />
        {label}
      </div>
      <div className="text-muted mt-1 text-[10px] leading-tight">{detail}</div>
    </div>
  );
}

export function formatPrice(price: unknown, currency: string): string {
  if (price === null || price === undefined) return '--';
  const stringifyStructuredPrice = (value: object) => {
    try {
      return JSON.stringify(value);
    } catch {
      return String(value);
    }
  };
  const safeCurrency = (value: unknown) => {
    const normalized = String(value || '')
      .trim()
      .toUpperCase();
    return /^[A-Z]{3}$/.test(normalized) ? normalized : 'USD';
  };
  const formatAmount = (amount: number, currencyCode: unknown) => {
    try {
      return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: safeCurrency(currencyCode),
      }).format(amount);
    } catch {
      return String(amount);
    }
  };
  if (typeof price === 'object') {
    if (Array.isArray(price)) {
      return stringifyStructuredPrice(price);
    }
    const p = price as Record<string, unknown>;
    const amount = p.amount ?? p.price_min;
    if (typeof amount === 'number') {
      return formatAmount(amount, p.currency || currency);
    }
    return stringifyStructuredPrice(p);
  }
  if (typeof price === 'number') {
    return formatAmount(price, currency);
  }
  return String(price);
}
