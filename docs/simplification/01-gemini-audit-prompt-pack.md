# Gemini Audit Prompt Pack — Document 1 of the System Bible

> **Purpose.** Produce a factual evidence base for the Simplification & Consolidation Program.
> **Executor.** User runs each batch in Google AI Studio, pastes structured results back to Claude.
> **Rule.** One batch at a time. Do not batch-dump all files into one session — Gemini skims and produces shallow findings when over-fed.

Batches:
- **A — Extract-dir duplication** (ready below)
- B — Field-policy fragmentation (drafted after A results land)
- C — Page-type × surface branching (grep-driven file list prepared between B and C)
- D — Unify leakage (final batch)
- E — Frontend alignment (optional, after backend bible accepted)

---

## Batch A — Extract-Directory Duplication Audit

### Files to upload to AI Studio

All 27 files in `backend/app/services/extract/`:

```
candidate_processing.py
detail_extractor.py
detail_reconciliation.py
dom_extraction.py
extraction_helpers.py
field_classifier.py
field_decision.py
field_type_classifier.py
__init__.py
json_extractor.py
listing_card_context.py
listing_card_extractor.py
listing_extractor.py
listing_identity.py
listing_item_mapper.py
listing_quality.py
listing_structured_extractor.py
llm_cleanup.py
noise_policy.py
semantic_support.py
service.py
shared_logic.py
shared_variant_logic.py
signal_inventory.py
variant_builder.py
variant_extractor.py
variant_types.py
```

Upload all 27 together. Do **not** include files from other directories in this batch.

### System instruction (paste into AI Studio "System instructions")

```
You are a static code auditor. Your only job is to produce structured, factual findings in the exact output template provided. Do not suggest fixes. Do not editorialize. Do not speculate about intent. If a file does not participate in a question, write "n/a". If you are unsure, write "unclear" and cite the file:line you examined. Keep prose to zero — fill tables and bullet lists only.
```

### Prompt (paste into the AI Studio chat)

````
You are auditing 27 Python files that together form the "extract" stage of a deterministic web-crawling pipeline. The stage extracts canonical fields from HTML, JSON-LD, hydrated JS state, and DOM, for two surfaces (ecommerce, job) and two page types (category/listing, pdp/detail).

The program invariants you must respect while reading:
- Extraction is FIRST-MATCH per field (first valid hit wins; not score-based).
- Source hierarchy per field: adapter → JSON-LD → hydrated JS state → DOM → LLM fallback.
- Listing guard: 0 item records ⇒ `listing_detection_failed`, never falls back to detail extraction.
- Noise (footer/legal/UI chrome/containers/schema metadata) must not leak into records.

Canonical fields to audit (extract-stage output contract):
1. url (canonical item URL)
2. title
3. price
4. currency
5. availability / stock_status
6. description
7. image / image_url
8. images (gallery)
9. brand
10. sku / product_id
11. specifications
12. variants
13. company (jobs)
14. location (jobs)
15. employment_type (jobs)
16. salary (jobs)
17. posted_date (jobs)
18. rating
19. review_count
20. category / breadcrumb

Produce exactly these five deliverables, in this order, filled strictly per template. No extra sections.

═══════════════════════════════════════════════════════════════════
DELIVERABLE 1 — File role summary
═══════════════════════════════════════════════════════════════════
For each of the 27 files, one row. Keep role to ≤12 words.

| File | Primary role | Surface (ecom/job/both/n/a) | Page type (listing/detail/both/n/a) |
|------|--------------|-----------------------------|--------------------------------------|
| candidate_processing.py | … | … | … |
| detail_extractor.py | … | … | … |
| … | | | |

═══════════════════════════════════════════════════════════════════
DELIVERABLE 2 — Field × File extraction matrix
═══════════════════════════════════════════════════════════════════
For each canonical field, list every file that extracts or derives it, and by which method.

Method codes:
- ADPT = adapter-specific
- JLD = JSON-LD / microdata / RDFa
- STATE = hydrated JS state (__NEXT_DATA__, __INITIAL_STATE__, etc.)
- DOM = CSS/XPath selector on rendered HTML
- REGEX = regex over raw HTML/text
- DERIVE = derived/computed from other fields
- PASS = passthrough from upstream payload

Template (one table per field that is extracted in ≥1 file):

### Field: `price`
| File | Method(s) | Function/location | Notes (≤20 words) |
|------|-----------|-------------------|-------------------|
| json_extractor.py | JLD | extract_price() L142 | handles Offer.price + priceSpecification |
| dom_extraction.py | DOM, REGEX | _pick_price() L88 | 4 selector families + currency regex |
| listing_card_extractor.py | DOM | _card_price() L201 | card-scoped DOM path |
| detail_extractor.py | DERIVE | … | … |

Include every field with ≥1 hit. Omit fields that have zero hits across all 27 files and list those at the end under "Fields with no extractor found".

═══════════════════════════════════════════════════════════════════
DELIVERABLE 3 — Duplication flags
═══════════════════════════════════════════════════════════════════
Bullet list. One bullet per field where the SAME method code appears in 2+ files, OR where 3+ different methods appear for the same field across files. Order by severity (most files / most methods first).

Format:
- **price** — extracted in 5 files: json_extractor.py (JLD), dom_extraction.py (DOM+REGEX), listing_card_extractor.py (DOM), detail_extractor.py (DERIVE), candidate_processing.py (DOM). DOM selector logic appears in 3 files with diverging selector sets — drift risk.
- …

═══════════════════════════════════════════════════════════════════
DELIVERABLE 4 — Shared-logic reach
═══════════════════════════════════════════════════════════════════
`shared_logic.py`, `shared_variant_logic.py`, `extraction_helpers.py`, `semantic_support.py`, `signal_inventory.py` claim to be shared utilities. For each:

| Shared file | Exported symbols (count) | Files that import it | Symbols actually used by each importer |
|-------------|---------------------------|----------------------|-----------------------------------------|
| shared_logic.py | 14 | listing_extractor.py, detail_extractor.py, … | listing_extractor uses: 3 (…); detail_extractor uses: 7 (…) |

Flag symbols exported but never imported anywhere in the 27 files. List them under "Dead exports".

═══════════════════════════════════════════════════════════════════
DELIVERABLE 5 — Listing vs detail entanglement
═══════════════════════════════════════════════════════════════════
List every function or class that branches on `page_type`, `surface`, `is_listing`, `is_detail`, or equivalent. One row per branch.

| File:line | Function/class | Branch variable | Branches (values) | Branch purpose: ESSENTIAL / ACCIDENTAL / UNCLEAR |
|-----------|----------------|-----------------|-------------------|---------------------------------------------------|
| listing_extractor.py:L45 | extract_items() | page_type | category,pdp | ESSENTIAL (different output shape) |
| shared_logic.py:L210 | _build_context() | surface | ecommerce,job | ACCIDENTAL (only renames keys) |

Definition:
- ESSENTIAL = branches produce genuinely different data shapes or semantics.
- ACCIDENTAL = branches differ only in plumbing (key names, log messages, trivial defaults) — could be collapsed.
- UNCLEAR = cannot determine from the 27 files alone.

═══════════════════════════════════════════════════════════════════
END OF OUTPUT. Do not add conclusions, recommendations, or summaries.
═══════════════════════════════════════════════════════════════════
````

### How the user returns results to Claude

Paste the five deliverables verbatim back into the Claude chat. No summarization, no editing. Claude will cross-check against the program invariants and flag anything that looks off before Batch B is drafted.

### Expected runtime in AI Studio

Budget one long Gemini session (Gemini 2.5 Pro or equivalent, long-context). If the model starts truncating tables, split the Deliverable 2 tables into two messages ("produce Deliverable 2 for fields 1-10" / "now fields 11-20") — do not change the template.

---

---

## Batch B — Field-Policy Fragmentation Audit

> **Prerequisite:** Batch A accepted — see [02-batch-a-findings.md](./02-batch-a-findings.md).
> **Purpose:** Map where field aliasing, normalization, noise, and arbitration policy actually live. Batch A proved that **extraction** is duplicated; Batch B determines whether **policy** is equally fragmented and what the single source of truth should be.

### Files to upload to AI Studio

Eight files, exact list:

```
backend/app/services/field_alias_policy.py
backend/app/services/requested_field_policy.py
backend/app/services/config/field_mappings.py
backend/app/services/config/nested_field_rules.py
backend/app/services/config/extraction_rules.py
backend/app/services/pipeline/field_normalization.py
backend/app/services/extract/noise_policy.py
backend/app/services/extract/field_decision.py
```

Upload all 8 together. Do **not** include the 27 extract-stage files from Batch A.

### System instruction (paste into AI Studio "System instructions")

```
You are a static code auditor. Your only job is to produce structured, factual findings in the exact output template provided. Do not suggest fixes. Do not editorialize. Do not speculate about intent. If a file does not participate in a question, write "n/a". If you are unsure, write "unclear" and cite the file:line you examined. Keep prose to zero — fill tables and bullet lists only.
```

### Prompt (paste into the AI Studio chat)

````
You are auditing 8 Python files that together encode "field policy" for a deterministic web-crawling pipeline: aliasing, normalization, noise detection, and field arbitration. The pipeline stages are ACQUIRE → EXTRACT → UNIFY → PUBLISH, and these 8 files span three of those stages plus two top-level service utilities.

Program invariants to respect while reading:
- Extraction is FIRST-MATCH per field (first valid hit wins). Arbitration picks the first valid source in a fixed hierarchy; it is not a score.
- Source hierarchy per field: adapter → JSON-LD → hydrated JS state → DOM → LLM fallback.
- No magic values in service code — tunables should live in typed config.
- Noise (footer/legal/UI chrome/containers/schema metadata) must never leak into records.
- User controls (page type, surface, LLM toggle) are authoritative — policy must not silently rewrite them.

The four policy concerns under audit:
1. ALIASING — mapping many upstream key names to one canonical field (e.g., `productName` / `item_name` → `title`)
2. NORMALIZATION — cleaning, coercing, or reshaping a value after extraction (e.g., price "$1,299.00" → Decimal("1299.00"))
3. NOISE — detecting and removing non-data content (footer boilerplate, UI chrome, schema metadata, container scaffolding)
4. ARBITRATION — choosing the winning value when the same field is produced by multiple sources

Produce exactly these five deliverables, in this order, filled strictly per template.

═══════════════════════════════════════════════════════════════════
DELIVERABLE 1 — File policy-role summary
═══════════════════════════════════════════════════════════════════
One row per file. Concerns column lists which of the four policy concerns the file participates in.

| File | Primary role (≤15 words) | Concerns (A/N/Ns/Ar, comma-sep) | Stage owner (acquire/extract/unify/publish/service) |
|------|--------------------------|----------------------------------|------------------------------------------------------|
| field_alias_policy.py | … | A | service |
| requested_field_policy.py | … | … | service |
| config/field_mappings.py | … | … | config |
| config/nested_field_rules.py | … | … | config |
| config/extraction_rules.py | … | … | config |
| pipeline/field_normalization.py | … | … | unify |
| extract/noise_policy.py | … | … | extract |
| extract/field_decision.py | … | … | extract |

Key:  A=Aliasing, N=Normalization, Ns=Noise, Ar=Arbitration.

═══════════════════════════════════════════════════════════════════
DELIVERABLE 2 — Rule inventory per file
═══════════════════════════════════════════════════════════════════
For each file, list every distinct RULE it encodes. A rule = one named policy unit (function, class, constant/dict, regex constant, predicate). One row per rule.

Rule-kind codes:
- ALIAS_TABLE — dict/list mapping input keys to canonical field names
- NORM_FN — function that reshapes/cleans a value
- NORM_REGEX — regex constant used for matching/extraction/cleaning
- NOISE_FN — function that detects or strips noise
- NOISE_SET — set/list of noise tokens or selectors
- ARB_FN — function that chooses among competing candidates
- ARB_ORDER — constant declaring source hierarchy
- TYPE_RULE — type-validation / coercion rule
- CONTRACT — output-shape contract (required fields, surface-specific)
- OTHER — anything else (describe briefly)

Template per file:

### File: `field_alias_policy.py`
| Rule name / symbol | Kind | Canonical field(s) touched | Used by (importers) | Notes (≤20 words) |
|--------------------|------|---------------------------|---------------------|-------------------|
| GENERIC_ALIAS_MAP (L42) | ALIAS_TABLE | title, description, price, … | listing_item_mapper, json_extractor | 180-entry dict |
| resolve_field_alias (L110) | ALIAS_FN | all | … | lookup wrapper with fallback |
| … | | | | |

Repeat for all 8 files.

═══════════════════════════════════════════════════════════════════
DELIVERABLE 3 — Policy-concern × file matrix
═══════════════════════════════════════════════════════════════════
For each of the four policy concerns, list which files carry rules for it, grouped by canonical field. One table per concern.

### Concern: ALIASING
| Canonical field | Files carrying alias rules | Notes |
|-----------------|---------------------------|-------|
| title | field_alias_policy.py, config/field_mappings.py | Overlap — same keys mapped in both |
| price | … | … |

### Concern: NORMALIZATION
| Canonical field | Files carrying normalization | Notes |
|-----------------|------------------------------|-------|
| price | pipeline/field_normalization.py, config/extraction_rules.py | … |

### Concern: NOISE
| Noise category (footer/UI-chrome/schema-meta/container) | Files carrying detection | Notes |

### Concern: ARBITRATION
| Canonical field | Files carrying arbitration | Declared source order (if any) |

═══════════════════════════════════════════════════════════════════
DELIVERABLE 4 — Duplication, overlap, contradiction flags
═══════════════════════════════════════════════════════════════════
Bullet list. One bullet per case where:
- (a) two files encode alias or normalization rules for the SAME canonical field, OR
- (b) two files define contradictory rules (different mappings, different clean-up order, different noise-token sets for the same category), OR
- (c) a file imports rules from another AND locally overrides or re-implements them.

Format:
- **price normalization** — `pipeline/field_normalization.py:L88 _clean_price()` strips "$" and commas; `config/extraction_rules.py:L142 PRICE_CLEANUP` declares a different regex. Output diverges on values with trailing text. CONTRADICTION.
- **title aliasing** — `field_alias_policy.py:L42 GENERIC_ALIAS_MAP` and `config/field_mappings.py:L61 TITLE_ALIASES` both map `productName`. Identical. DUPLICATION.
- …

Order: CONTRADICTION first, DUPLICATION next, LOCAL-OVERRIDE last.

═══════════════════════════════════════════════════════════════════
DELIVERABLE 5 — Implicit dependencies and import graph
═══════════════════════════════════════════════════════════════════
Two tables.

(5a) Direct imports among the 8 files:
| From (importer) | To (imported) | Symbols imported | Notes |
|-----------------|---------------|------------------|-------|
| extract/field_decision.py | field_alias_policy.py | resolve_field_alias | … |

(5b) Implicit coupling — cases where a file reads/modifies data whose SHAPE is defined elsewhere in the 8, without importing the definition:
| File | Implicit shape dependency | Source of truth for that shape | Evidence (file:line) |
|------|--------------------------|-------------------------------|----------------------|
| pipeline/field_normalization.py | field names assumed to already be canonical | field_alias_policy.GENERIC_ALIAS_MAP | field_normalization.py:L45 uses bare string "price" without consulting alias policy |

═══════════════════════════════════════════════════════════════════
END OF OUTPUT. Do not add conclusions, recommendations, or summaries.
═══════════════════════════════════════════════════════════════════
````

### How the user returns results to Claude

Paste all five deliverables verbatim. Claude writes `03-batch-b-findings.md`, then begins drafting Phase 0 and Phase 1 slice files in `docs/simplification/slices/` so Codex can start work in parallel with Batches C+D.

---

## Batch C — Page-Type × Surface Branching, Codebase-Wide Sweep

> **Prerequisite:** Batch A accepted — see [02-batch-a-findings.md](./02-batch-a-findings.md). Batch B accepted — see [03-batch-b-findings.md](./03-batch-b-findings.md).
> **Purpose:** Batch A inventoried 15 `page_type` / `surface` / `is_listing` / `is_detail` branches **inside `extract/`**. Batch C hunts the same branches **everywhere else** in `backend/app/services/**` and produces one unified removability ranking.
> **Scoping note:** Narrowed from 60 files with token hits to 23 files that carry meaningful branching logic. Extract-dir files are deliberately excluded (owned by Batch A). Batch D files (`pipeline/core.py`, `pipeline/stages.py`, `pipeline/runner.py`, `pipeline/field_normalization.py`, `pipeline/utils.py`, `publish/metadata.py`, `publish/verdict.py`) are excluded here — cross-reference only. Platform-family adapters (shopify, amazon, ebay, walmart, linkedin, indeed, greenhouse, icims, jibe, paycom, oracle_hcm, saashr, adp, remotive, remoteok) are excluded: they are surface-specific by construction, so their branches are definitionally essential and add no signal. `adapters/base.py` and `adapters/registry.py` are included because they sit above the family split. `config/field_mappings.py` and `field_alias_policy.py` are covered by Batch B; cross-reference only.

### Files to upload to AI Studio

23 files, exact list:

```
backend/app/services/acquisition/acquirer.py
backend/app/services/acquisition/policy.py
backend/app/services/acquisition/browser_client.py
backend/app/services/acquisition/browser_readiness.py
backend/app/services/acquisition/traversal.py
backend/app/services/acquisition/recovery.py
backend/app/services/pipeline/detail_flow.py
backend/app/services/pipeline/listing_flow.py
backend/app/services/pipeline/listing_helpers.py
backend/app/services/pipeline/types.py
backend/app/services/publish/trace_builders.py
backend/app/services/publish/review_shaping.py
backend/app/services/normalizers/listings.py
backend/app/services/schema_service.py
backend/app/services/discover/signal_inventory.py
backend/app/services/discover/state_inventory.py
backend/app/services/discover/network_inventory.py
backend/app/services/adapters/base.py
backend/app/services/adapters/registry.py
backend/app/services/review/__init__.py
backend/app/services/llm_runtime.py
backend/app/services/crawl_crud.py
backend/app/services/crawl_ingestion_service.py
```

Upload all 23 together. Do **not** include files from `extract/` (Batch A), `pipeline/core.py`, `pipeline/stages.py`, `pipeline/runner.py`, `pipeline/field_normalization.py`, `pipeline/utils.py`, `publish/metadata.py`, `publish/verdict.py` (Batch D), or the family-specific adapters.

### System instruction (paste into AI Studio "System instructions")

```
You are a static code auditor. Your only job is to produce structured, factual findings in the exact output template provided. Do not suggest fixes. Do not editorialize. Do not speculate about intent. If a file does not participate in a question, write "n/a". If you are unsure, write "unclear" and cite the file:line you examined. Keep prose to zero — fill tables and bullet lists only.
```

### Prompt (paste into the AI Studio chat)

````
You are auditing 23 Python files that span acquisition, pipeline orchestration, publish, discovery, adapter routing, review, normalization, and the LLM runtime layer of a deterministic web-crawling pipeline. Pipeline stages are ACQUIRE → EXTRACT → UNIFY → PUBLISH. These files sit *outside* the `extract/` directory, which was audited separately (Batch A found 15 branches inside `extract/`; your job is to find every remaining branch).

The branch variables under audit are exactly:
- `page_type` (values typically: "category" | "pdp")
- `surface` (values typically: "ecommerce_listing" | "ecommerce_detail" | "job_listing" | "job_detail", sometimes coarser "ecommerce" | "job")
- `is_listing` / `is_detail` (booleans, often derived from the above)
- Any locally-named alias that is definitionally one of the above (e.g., `kind`, `record_type`, `mode` ONLY when the values are the listing/detail or ecommerce/job split)

A BRANCH counts if code reads one of these variables and either:
- takes a different code path (`if`, `elif`, `match`, ternary),
- indexes a mapping/table by it to pick behavior,
- calls a different function by it,
- OR routes data through a different shape/key by it.

Passing the value downstream without reading it is NOT a branch. Type hints alone are NOT a branch.

Program invariants to respect while reading:
- Invariant 6 (rewritten): extraction is backfilled + quality-scored, not first-match. Candidates come from every active source; the scorer picks the winner; source hierarchy breaks ties.
- Invariant 8: listing pages with 0 item records ⇒ `listing_detection_failed` verdict. Never fall back to detail extraction.
- Invariant 11: listing outputs stay canonical. No detail-only fields, variant payloads, or schema spillover on listings.
- Invariant 12 (rewritten): page-native field identity is preserved on detail. Canonical schemas apply only when the page genuinely exposes those concepts. Canonical fields must not be invented. Page-native fields must not be force-fitted into canonical slots.
- Invariants 16-19: user-owned controls (page type, surface, LLM toggle, proxy, traversal mode) are authoritative. Backend must not rewrite them. Browser rendering escalation ≠ traversal authorization.
- Invariant 29: generic paths stay generic; platform logic is family-based, not tenant/site hardcoded.

Produce exactly these five deliverables, in this order, filled strictly per template. No extra sections.

═══════════════════════════════════════════════════════════════════
DELIVERABLE 1 — File role summary
═══════════════════════════════════════════════════════════════════
One row per file. Role ≤15 words.

| File | Primary role | Stage (acquire/unify/publish/discover/adapter/review/runtime/crud) | Contains page_type/surface branches? (Y/N) |
|------|--------------|---------------------------------------------------------------------|---------------------------------------------|
| acquisition/acquirer.py | … | acquire | Y |
| acquisition/policy.py | … | … | … |
| … | | | |

═══════════════════════════════════════════════════════════════════
DELIVERABLE 2 — Branch inventory
═══════════════════════════════════════════════════════════════════
One row per branch. Every branch in every file must appear. If a file has zero branches, it does not appear in this table.

| File:line | Function/class | Branch variable | Branch values observed | What changes across branches (≤25 words) | Classification |
|-----------|----------------|-----------------|------------------------|--------------------------------------------|----------------|
| acquisition/acquirer.py:L142 | _select_fetch_plan() | surface | ecommerce,job | job surface gets longer timeout; ecommerce gets extra retry | ESSENTIAL |
| pipeline/detail_flow.py:L88 | _post_extract() | page_type | category,pdp | category path renames `items` → `records`; pdp path passthrough | ACCIDENTAL |
| … | | | | | |

Classification definitions (same as Batch A — match these exactly):
- ESSENTIAL = branches produce genuinely different data shapes, semantics, or fetch strategies that cannot be expressed as a single uniform path.
- ACCIDENTAL = branches differ only in plumbing (key names, log messages, trivial defaults, early exits by surface, surface-scoped telemetry) and could be collapsed without losing behavior.
- UNCLEAR = cannot determine from the 23 files alone. Cite the reason in the "What changes" column and use UNCLEAR.

If a single `if page_type == ...` chain contains multiple arms, record each arm as a separate row only when different files or different functions consume it; otherwise record the whole chain as one row with `values observed` listing all arms.

═══════════════════════════════════════════════════════════════════
DELIVERABLE 3 — Cross-reference to Batch A (dedupe)
═══════════════════════════════════════════════════════════════════
Batch A already inventoried 15 branches inside `extract/`. If any branch in your Deliverable 2 exists because code in `extract/` forces it (e.g., a flag passed back to `pipeline/detail_flow.py` only because `listing_extractor.py` branches on `page_type`), mark it. Do NOT re-inventory the 15 `extract/` branches; just flag the downstream echoes.

| Batch C file:line | Upstream `extract/` branch it mirrors (file:line if knowable, else "unknown") | Relationship (echo / consumer / independent) |
|-------------------|-------------------------------------------------------------------------------|-----------------------------------------------|
| pipeline/listing_flow.py:L… | listing_extractor.py:L47 (Batch A: ESSENTIAL) | echo — same shape decision propagated |

If no cross-file echoes exist, write "None" and move on.

═══════════════════════════════════════════════════════════════════
DELIVERABLE 4 — Ranked removability list
═══════════════════════════════════════════════════════════════════
From Deliverable 2, list every branch classified ACCIDENTAL or UNCLEAR, ranked by removal cost (easiest first). For each, name the collapse strategy in ≤15 words. Do not propose refactors beyond the collapse of this specific branch.

| Rank | File:line | Classification | Collapse strategy | Estimated blast radius (this file / this module / cross-module) |
|------|-----------|----------------|-------------------|------------------------------------------------------------------|
| 1 | pipeline/detail_flow.py:L88 | ACCIDENTAL | rename unconditionally; drop the branch | this file |
| 2 | … | … | … | … |

═══════════════════════════════════════════════════════════════════
DELIVERABLE 5 — Invariant-risk flags
═══════════════════════════════════════════════════════════════════
One bullet per branch (from Deliverable 2) that, if removed or altered naively, would risk violating one of the stated invariants. Be specific.

Format:
- **acquisition/acquirer.py:L142 — Inv. 16 risk.** Branch gates `playwright` escalation by user-provided surface. Collapsing to a uniform path would auto-enable rendering for surfaces the user did not request. Requires invariant-preserving redesign, not simple collapse.
- …

If no branches carry invariant risk, write "None".

═══════════════════════════════════════════════════════════════════
END OF OUTPUT. Do not add conclusions, recommendations, or summaries.
═══════════════════════════════════════════════════════════════════
````

### How the user returns results to Claude

Paste all five deliverables verbatim. Claude writes `04-batch-c-findings.md`, cross-checks against Invariants 6/8/11/12/16-19/29, and drafts Slice 3 (accidental-branch collapse) once Batch D lands.

---

## Batch D — Unify Leakage Audit

> **Prerequisite:** Batch A accepted. Batch B accepted. Batch C can run in parallel with Batch D (different files, no dependency).
> **Purpose:** Identify every place pipeline/publish code re-parses, re-cleans, re-derives, or re-arbitrates a field that extract should have emitted canonical. These are *leaks*: extract-stage work being redone downstream. The unify boundary is where extract ends and persistence begins; anything that looks like extract logic on the unify side is a leak.
> **Scoping note:** 7 files total, all explicitly named in the original approved plan. Invariant 12 (rewritten 2026-04-17) introduces a new probe: page-native field identity must be preserved end-to-end, so any downstream code that force-fits a page-native key into a canonical slot (or vice versa) is a new class of leak to flag.

### Files to upload to AI Studio

7 files, exact list:

```
backend/app/services/pipeline/core.py
backend/app/services/pipeline/stages.py
backend/app/services/pipeline/runner.py
backend/app/services/pipeline/field_normalization.py
backend/app/services/pipeline/utils.py
backend/app/services/publish/metadata.py
backend/app/services/publish/verdict.py
```

Upload all 7 together. Do **not** include files from `extract/` (Batch A), policy/config (Batch B), or the wider pipeline/acquisition/publish set (Batch C).

### System instruction (paste into AI Studio "System instructions")

```
You are a static code auditor. Your only job is to produce structured, factual findings in the exact output template provided. Do not suggest fixes. Do not editorialize. Do not speculate about intent. If a file does not participate in a question, write "n/a". If you are unsure, write "unclear" and cite the file:line you examined. Keep prose to zero — fill tables and bullet lists only.
```

### Prompt (paste into the AI Studio chat)

````
You are auditing 7 Python files that form the unify + publish layer of a deterministic web-crawling pipeline. Pipeline stages are ACQUIRE → EXTRACT → UNIFY → PUBLISH. These files sit in `pipeline/` and `publish/`. The extract stage (not uploaded here) is responsible for turning acquired HTML/JSON into canonical field values. The unify/publish stage should only shape, validate, persist, and compute verdicts — NOT redo extraction work.

Program invariants to respect while reading:
- Invariant 1: no magic values in service code. Tunables live in typed config via `pipeline_config.py`.
- Invariant 6 (rewritten): extraction is backfilled + quality-scored, not first-match. Candidates come from every active source; scorer picks the winner; source hierarchy breaks ties. Backfill happens in extract, NOT in unify.
- Invariant 7: verdict is based on VERDICT_CORE_FIELDS only. Requested-field coverage is metadata, not a verdict input.
- Invariant 11: listing outputs stay canonical. Publish must not back-fill listing records with detail-only fields.
- Invariant 12 (rewritten): page-native field identity preserved. Fields exposed on the source page retain their native labels (normalized to snake_case) in `record.data`. Canonical schemas apply only when the page genuinely exposes those concepts. Canonical fields must not be invented when the page does not expose them. Page-native fields must not be force-fitted into canonical slots that happen to sound similar. Residual buckets (`description`, `features`, `specifications`) hold only content the page itself groups as prose/attribute lists; they are not overflow bins.
- Invariant 13: commerce/job schema pollution forbidden — footer/legal/UI-chrome/container metadata must be filtered before persistence.
- Invariant 14: clean record API — empty/null values and `_`-prefixed keys stripped on output.

LEAK DEFINITIONS. A leak is any pipeline/publish code that does the work of extraction. There are four leak kinds; one bullet per kind:

- RE-PARSE — pipeline/publish code parses a raw payload (HTML, JSON-LD, hydrated state, XHR body, regex-over-text) to recover a field value that extract should have already surfaced. Example: `re.search(r"\\$([0-9]+\\.[0-9]{2})", raw_text)` inside `publish/metadata.py`.
- RE-CLEAN — pipeline/publish code strips/normalizes/reshapes a field value (trimming noise phrases, stripping "$", collapsing whitespace, lowercasing, deduplicating) beyond what a simple output-contract validator would do. Example: `price.replace("$","").replace(",","")` inside `pipeline/field_normalization.py`.
- RE-DERIVE — pipeline/publish code computes a field value from other fields (e.g., derives `currency` from `price` text; derives `availability` from a stock-state boolean; derives `title` by concatenating brand + model). Derivation belongs in extract. Example: computing `total_price = price + shipping`.
- RE-ARBITRATE — pipeline/publish code picks between competing candidate values for the same field (e.g., "if `state_price` is present prefer it over `dom_price`"). Per Invariant 6, arbitration belongs in extract's scorer.

An output-shape check (e.g., "is this field present", "is this field empty") is NOT a leak. Verdict computation over already-extracted fields is NOT a leak (it's publish's job). Alias lookup using a policy table is NOT a leak (it's policy, audited in Batch B).

Produce exactly these five deliverables, in this order, filled strictly per template. No extra sections.

═══════════════════════════════════════════════════════════════════
DELIVERABLE 1 — File role summary
═══════════════════════════════════════════════════════════════════
One row per file. Role ≤15 words.

| File | Primary role | Expected legitimate concerns (≤20 words) | Contains at least one leak? (Y/N) |
|------|--------------|-------------------------------------------|-----------------------------------|
| pipeline/core.py | … | orchestration, stage sequencing, error handling | … |
| pipeline/stages.py | … | … | … |
| pipeline/runner.py | … | … | … |
| pipeline/field_normalization.py | … | contract validation, empty-value filtering, cross-field coherence | … |
| pipeline/utils.py | … | … | … |
| publish/metadata.py | … | build source_trace, persistence metadata | … |
| publish/verdict.py | … | compute VERDICT_CORE_FIELDS-based verdict | … |

═══════════════════════════════════════════════════════════════════
DELIVERABLE 2 — Leak inventory
═══════════════════════════════════════════════════════════════════
One row per leak. Every leak in every file must appear. If a file has zero leaks, it does not appear in this table.

| File:line | Function/class | Field touched (canonical name or page-native name) | Leak kind (RE-PARSE/RE-CLEAN/RE-DERIVE/RE-ARBITRATE) | Evidence snippet (≤15 words, verbatim) | Recommended extract-side owner (≤10 words) |
|-----------|----------------|----------------------------------------------------|------------------------------------------------------|------------------------------------------|---------------------------------------------|
| publish/metadata.py:L142 | _attach_price() | price | RE-PARSE | re.search(r"\\$([0-9.,]+)", raw_html) | json_extractor price path |
| pipeline/field_normalization.py:L88 | _coerce_price() | price | RE-CLEAN | value.replace("$","").replace(",","") | extract/normalizers or decimal coercer upstream |
| pipeline/field_normalization.py:L201 | _pick_title() | title | RE-ARBITRATE | prefer state_title over dom_title | extract scorer (Invariant 6) |
| … | | | | | |

If the same line encodes multiple leak kinds (e.g., re-parse + re-clean in one function), record separate rows.

═══════════════════════════════════════════════════════════════════
DELIVERABLE 3 — Invariant 12 probe (page-native identity)
═══════════════════════════════════════════════════════════════════
Invariant 12 was rewritten this week. It says: fields exposed on the source page retain their native labels; canonical fields must NOT be invented when absent on the page; page-native fields must NOT be force-fitted into canonical slots that happen to sound similar.

For each of the 7 files, flag any line that does one of the following:

(3a) FORCE-FITS a page-native field name into a canonical slot (e.g., remaps a page-native key `item_part_number` → canonical `sku` without evidence the page actually exposes the concept of "SKU").

(3b) INVENTS a canonical field (e.g., synthesizes an `availability` value from heuristics when the page does not expose availability).

(3c) OVERFLOWS page-native content into a canonical residual bucket (`description` / `features` / `specifications`) when the page itself did not group the content as prose or attribute list.

| File:line | Function/class | Violation kind (3a/3b/3c) | Field(s) touched | Evidence (≤20 words) |
|-----------|----------------|---------------------------|------------------|-----------------------|
| publish/metadata.py:L… | … | 3a | … | … |

If no violations found, write "None".

═══════════════════════════════════════════════════════════════════
DELIVERABLE 4 — Invariant-risk flags (non-12)
═══════════════════════════════════════════════════════════════════
Same structure as Deliverable 3, but for Invariants 1, 6, 7, 11, 13, 14. One bullet per violation.

Format:
- **pipeline/field_normalization.py:L201 — Inv. 6 risk.** Re-arbitration by preferring `state_title` over `dom_title` contradicts extract-stage scorer ownership. Arbitration belongs in extract.
- **publish/verdict.py:L… — Inv. 7 risk.** Verdict computation reads requested-field coverage. Per invariant, requested fields are metadata, not verdict input.
- …

If no violations, write "None".

═══════════════════════════════════════════════════════════════════
DELIVERABLE 5 — Leak concentration summary
═══════════════════════════════════════════════════════════════════
Rolled-up counts. Used to prioritize Slice 4.

| File | RE-PARSE count | RE-CLEAN count | RE-DERIVE count | RE-ARBITRATE count | Inv. 12 violations | Total |
|------|----------------|----------------|-----------------|--------------------|--------------------|-------|
| pipeline/core.py | 0 | 0 | 0 | 0 | 0 | 0 |
| pipeline/stages.py | … | … | … | … | … | … |
| pipeline/runner.py | … | … | … | … | … | … |
| pipeline/field_normalization.py | … | … | … | … | … | … |
| pipeline/utils.py | … | … | … | … | … | … |
| publish/metadata.py | … | … | … | … | … | … |
| publish/verdict.py | … | … | … | … | … | … |
| **TOTAL** | … | … | … | … | … | … |

═══════════════════════════════════════════════════════════════════
END OF OUTPUT. Do not add conclusions, recommendations, or summaries.
═══════════════════════════════════════════════════════════════════
````

### How the user returns results to Claude

Paste all five deliverables verbatim. Claude writes `05-batch-d-findings.md`, cross-checks against Batch A (where the leak's extract-side owner actually lives) and Batch B (policy ownership for anything that looks like a leak but is actually alias/noise work), and drafts Slice 4 (unify-leak repatriation to extract) once both Batch C and Batch D findings land.

---

## Batch E

Drafted after backend bible (Document 2) is accepted. Same structure. Covers frontend selector/submission surfaces.
