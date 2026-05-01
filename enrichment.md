# Crawlwise — Product Enrichment Feature Spec
**Version**: 1.0  
**Surface**: Ecommerce only  
**Trigger**: Post-detail-crawl (toggle or on-demand)

---

## What This Feature Does

After a product detail page is crawled, the enrichment pipeline reads those raw extracted fields and produces a structured, discovery-ready enriched record stored in a separate table. It never modifies the source detail record.

**Enriched output shape** (target for all phases combined):

```json
{
  "detail_record_id": 42,
  "price_normalized": { "amount": 49.99, "currency": "USD" },
  "color_family": "navy blue",
  "seo_keywords": ["navy blue cocktail dress", "midi formal dress"],
  "image_tags": ["navy", "a-line cut", "knee-length", "solid color"],
  "category_path": "Women > Dresses > Formal > Midi",
  "intent_attributes": ["evening wear", "cocktail", "A-line", "midi", "formal occasion"],
  "audience": ["women 25-40", "professional", "event-goer"],
  "style_tags": ["elegant", "classic", "minimalist"],
  "ai_discovery_tags": ["formal-dress", "evening-wear", "midi-length"],
  "suggested_bundles": ["matching clutch", "statement earrings", "nude heels"],
  "enrichment_status": "enriched",
  "enriched_at": "2026-04-30T10:00:00Z"
}
```

Fields are populated phase by phase. Later phases fill in fields that earlier phases leave null.

---

## Trigger Model

**Toggle mode** — User enables "Enrich after crawl" at the crawl job level (not global). When on, enrichment is queued automatically as each detail record is committed to the DB. For batch detail crawls, enrichment queues per-record as each one lands, not after the whole batch finishes.

**On-demand mode** — From the detail records list UI, user selects one or more records and triggers "Enrich selected". Uses the same pipeline, same phases.

**Concurrency** — User-controlled. A setting on the crawl job (or global settings page) lets the user configure max parallel enrichment workers (default: 3, max: recommended 10). This directly controls LLM/vision API call parallelism and cost.

---

## Status Tracking

**D4 decision**: `enrichment_status` lives as an enum column on the `detail_records` table itself. No separate status table.

Add two columns to `detail_records`:
- `enrichment_status`: enum — `unenriched | enriching | enriched | failed`
- `enriched_at`: nullable timestamp

Rationale: The status is a property of a detail record, not a separate entity. This avoids a join on every detail records list query and keeps the UI status display simple.

The `enriched_products` table holds the actual enriched fields and has a 1-to-1 FK to `detail_records`.

---

## System Invariants

These are hard rules the implementation must respect across all phases:

**INV-01** — Enrichment only ever reads `detail_records`. It never reads from `listing_records` and never writes to `detail_records` (except `enrichment_status` and `enriched_at`).

**INV-02** — `surface_type` is checked at pipeline entry. Any record with `surface_type != ecommerce` is rejected immediately. No ecommerce enrichment logic runs on job listings.

**INV-03** — A detail record with `enrichment_status = enriched` is skipped silently. No re-enrichment in current scope.

**INV-04** — No partial enrichment states are persisted. The `enriched_products` row is written in a single transaction after all synchronous phases (1 + 2) complete. If any synchronous phase fails, `enrichment_status` is set to `failed` and no `enriched_products` row is written.

**INV-05** — Phase 3 (image) is async and decoupled. The `enriched_products` row is written after Phase 2 with `image_tags = null`. Phase 3 updates `image_tags` in place when it completes. A failed Phase 3 does not change the record status from `enriched` — it simply leaves `image_tags = null`.

**INV-06** — Phase 4 (LLM) runs as one structured prompt per product. All LLM-derivable fields are requested in a single API call. No per-field prompt chaining.

**INV-07** — LLM and vision prompt inputs are assembled from extracted, normalized fields only. Raw HTML, raw description blobs, and extraction pipeline artifacts are never passed into a prompt.

**INV-08** — All enriched fields are committed directly to `enriched_products` with no user review gate in current scope.

---

## Phase 1 — Deterministic Normalization

**Goal**: Clean and normalize raw numeric and categorical fields that need no inference.  
**LLM calls**: 0  
**Blocking**: Yes (must complete before Phase 2)

### Price Normalization

Input: raw price string from `detail_records` (e.g., `"$49.99"`, `"£10–£50"`, `"49,99 €"`).

Logic:
1. Strip all currency symbols, whitespace, and formatting characters.
2. Detect price range pattern (two numbers separated by `–`, `-`, or `to`). If found, emit `price_min` and `price_max`. Otherwise emit single `amount`.
3. Detect currency from symbol or ISO code. If absent from the string, fall back to the crawl job's configured locale/domain currency.
4. Parse to float. If parsing fails, set all price fields to `null` — do not abort the pipeline.

Output fields: `price_normalized: { amount, currency }` or `{ price_min, price_max, currency }`.

### Color Family Mapping

Input: raw `color` field from `detail_records`, or fallback to first color token extracted from the product title.

Logic:
1. Lowercase and strip the raw color string.
2. Match against a color lookup file (JSON, loaded at startup, path: `data/enrichment/color_families.json`).
3. File structure: `{ "navy": "navy blue", "cobalt": "navy blue", "royal blue": "navy blue", "red": "red", ... }`.
4. First exact match wins. If no match: `color_family = null`.

This file is the single source of truth for color normalization. New color terms are added here, never hardcoded in Python.

---

## Phase 2 — Rule-Based Structured Enrichment

**Goal**: Derive structured fields from title, attributes, and category signals using string operations and lookup tables — no inference, no model.  
**LLM calls**: 0  
**Blocking**: Yes (runs after Phase 1, completes before Phase 3/4 are queued)

### SEO Keywords

Input: normalized title tokens + `color_family` (from Phase 1) + any structured attribute fields present on the detail record (brand, material, size, category).

Logic:
1. Tokenize the title: lowercase, split on whitespace and punctuation.
2. Remove stopwords (a, the, and, in, for, with, etc.) and tokens shorter than 3 characters.
3. Combine remaining title tokens with `color_family`, brand, material, and category raw string (if present).
4. Deduplicate.
5. Generate 2-token phrases from adjacent title tokens (bigrams) and include top 5 by position.
6. Final output: deduplicated flat list of strings, max 20 items.

Output field: `seo_keywords: list[str]`

### Attribute Normalization

Input: any structured attributes already present on the detail record (size, gender, age group, material).

Logic:
1. Size system detection: if a size value matches known US/UK/EU patterns, tag it with `size_system`. Use a static conversion table at `data/enrichment/size_systems.json`.
2. Gender inference: scan category string and title for gendered keywords ("women's", "men's", "girls", "boys", "unisex"). Map to canonical values: `female | male | unisex | null`.
3. These outputs are stored as normalized attribute fields on `enriched_products`, not as separate tables.

---

## Phase 3 — Image Enrichment (Async, Optional)

**Goal**: Extract visual attributes from the product image.  
**Model**: Claude (multimodal) — see vendor decision below.  
**Blocking**: No. Runs asynchronously after Phase 1+2 are committed.

### Vendor Decision (D1)

**Recommended: Claude Haiku (multimodal)** for Phase 3.

Rationale:
- Already in the stack — no new API key, no new vendor relationship.
- Can be prompted to return a specific JSON schema directly, skipping any post-processing to map generic vision labels to your field shape.
- Produces semantic tags ("a-line cut", "knee-length") rather than computer-vision labels ("garment", "sleeve"), which matches the enrichment output shape you want.
- Haiku keeps cost low at high volume relative to Sonnet.

Alternatives if cost becomes a concern at scale: Google Cloud Vision API returns structured labels at lower per-image cost, but requires a mapping layer to translate generic labels into your field schema.

### Image Enrichment Logic

1. Read `image_url` from the detail record. If null or empty: skip, leave `image_tags = null`.
2. Fetch the image via HTTP GET (no Playwright, no JS rendering). If response is not 2xx or content-type is not an image: skip.
3. Base64-encode the image bytes.
4. Send to Claude with the following prompt contract (see Phase 4 prompt schema section for format conventions):

```
You are analyzing a product image for an ecommerce catalog.
Return ONLY a JSON object with this exact shape:
{
  "image_tags": ["tag1", "tag2", ...],       // max 8 visual attribute tags
  "dominant_colors": ["color1", "color2"],    // max 3 colors visible in image
  "image_quality": "good" | "low" | "unusable"
}
No explanation. No markdown. Only the JSON object.
```

5. Parse response. Validate: `image_tags` is a list of strings, `dominant_colors` is a list of strings, `image_quality` is one of the three values. If validation fails: set all image fields to null.
6. Write `image_tags` and `dominant_colors` to `enriched_products` in place (UPDATE, not INSERT).

---

## Phase 4 — LLM Text Enrichment

**Goal**: Derive the full semantic enrichment layer that requires inference from product context.  
**Model**: Claude Sonnet (text)  
**Blocking**: Queued after Phase 1+2 complete. Runs in parallel with Phase 3.

Fields produced: `category_path`, `intent_attributes`, `audience`, `style_tags`, `ai_discovery_tags`, `suggested_bundles`.

### On Category Path

A category path is a hierarchical classification of a product within a product taxonomy — a multi-level tree of product types used by ecommerce platforms for search, filtering, and discovery (e.g., Shopify's open-source taxonomy has 12,000+ categories). `Women > Dresses > Formal > Midi` means: start from the broadest type and drill down to the most specific known classification.

For Crawlwise, the LLM infers the path from the product's title and available attributes. The path is a plain text string — not a foreign key to a taxonomy DB. It can be null if the LLM cannot confidently classify the product. There is no hardcoded tree in the codebase; the LLM's training knowledge of product taxonomy is the reference.

### Prompt Input Assembly (INV-07 applied)

Assemble the prompt context object from these fields on the detail + enriched record:

```json
{
  "title": "...",
  "brand": "...",
  "price_normalized": { "amount": 49.99, "currency": "USD" },
  "color_family": "navy blue",
  "material": "...",
  "size": "...",
  "gender": "female",
  "description_excerpt": "first 300 chars of cleaned description text only"
}
```

`description_excerpt` is the first 300 characters of the extracted description, stripped of HTML tags and whitespace runs. If the description is unavailable, omit the field from the prompt context. Never pass raw HTML.

### Prompt Output Schema (D3 decision)

The LLM is instructed to return only this JSON object — no markdown, no preamble:

```json
{
  "category_path": "Women > Dresses > Formal > Midi",
  "intent_attributes": ["string", "..."],
  "audience": ["string", "..."],
  "style_tags": ["string", "..."],
  "ai_discovery_tags": ["string", "..."],
  "suggested_bundles": ["string", "..."]
}
```

**Field constraints to include in the prompt**:
- `category_path`: single string, `>` separated, null if uncertain
- `intent_attributes`: 3–8 short phrases describing occasion, cut, or function
- `audience`: 2–5 descriptors (age range, lifestyle, persona)
- `style_tags`: 2–5 single adjectives (aesthetic descriptors)
- `ai_discovery_tags`: 3–8 hyphenated slugs (machine-readable, used for faceted search)
- `suggested_bundles`: 3–5 complementary product types (not specific products)

### Validation and Persistence

1. Parse the LLM response as JSON.
2. For each field: check type (string or list of strings) and reasonable length (no single tag > 60 chars, no list > 10 items).
3. Fields that fail validation are set to null individually — other fields are still persisted.
4. Write all Phase 4 fields to the existing `enriched_products` row (UPDATE).
5. If the entire JSON parse fails: log the error, set all Phase 4 fields to null, do not mark the record as failed (Phases 1–3 already succeeded).

---

## What This Feature Explicitly Does Not Do

- Does not merge listing records with detail records.
- Does not modify any field on `detail_records` except `enrichment_status` and `enriched_at`.
- Does not process job surface records.
- Does not re-enrich already-enriched records.
- Does not generate user review summaries (no reviews in scope).
- Does not apply a user accept/reject gate to enriched fields.

---

## Summary of Data Files Required

| File | Purpose | Format |
|------|---------|--------|
| `data/enrichment/color_families.json` | Color token → canonical color family mapping | JSON flat dict |
| `data/enrichment/size_systems.json` | Size value → detected size system (US/EU/UK) | JSON with patterns |
| `data/enrichment/stopwords.txt` | Stopword list for SEO keyword extraction | Newline-separated |

These files are loaded at application startup, not at enrichment runtime. They are versioned in the repo.

---

## Open Items Before Implementation Starts

| # | Item | Owner |
|---|------|-------|
| O1 | Confirm `detail_records` table schema — which extracted fields are guaranteed present vs optional | Review actual DB schema |
| O2 | Confirm crawl job has a `locale` or `currency` field for Phase 1 price currency fallback | Review crawl job model |
| O3 | Confirm Claude API key has multimodal (vision) access for Phase 3 | API key check |
| O4 | Decide: does the enrichment queue use background threads, an async task queue, or SQLite-backed job table | Architecture choice before Phase 3 async design |