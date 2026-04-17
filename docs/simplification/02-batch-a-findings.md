# Batch A Findings — Extract-Directory Duplication Audit

> **Source:** Gemini audit of all 27 files in `backend/app/services/extract/`, run 2026-04-17 per [01-gemini-audit-prompt-pack.md](./01-gemini-audit-prompt-pack.md) Batch A template.
> **Status:** Accepted. Invariants 3 and 7 cleared via surgical read. Findings feed Document 2 (bible) and the Phase 0/1 slice backlog.

## Executive summary

1. **Duplication is severe.** Five canonical fields — `price`, `title`, `image_url`, `availability`, `sku` — are each extracted across 4-6 files with drifting methods. Price alone has three distinct regex patterns in three files.
2. **Page_type × surface branching is mostly accidental.** 8 of 15 audited branches are plumbing / early-exit / key-rename. Only 7 are genuinely essential. The user's "original sin" framing is confirmed as roughly half-accidental, half-essential.
3. **Shared-logic modules have low reach.** `shared_logic.py` (7 exports) is used by 2 files. `extraction_helpers.py` (6 exports) has one importer using 1 symbol, another using 5. Dead exports present.
4. **No invariant violations in Batch A scope.** First-match (Inv. 3) and generic-paths (Inv. 7) both cleared by targeted reads. One layering *concern* noted (Demandware in extract/ vs Shopify in adapters/).
5. **Tunable sprawl is real.** Price regexes in service code — violates Invariant 1 ("no magic values in service code"). Batch 0 consolidation target.

## Invariant clearances

| Invariant | Flag reason | Clearance evidence | Status |
|-----------|-------------|--------------------|--------|
| 3 — First-match, not score-based | Gemini flagged `_card_group_scorer` as "scorer routing to sub-scorers" | [listing_card_extractor.py:141-163, 247-](../../backend/app/services/extract/listing_card_extractor.py#L141) — scorer ranks **DOM container groups** (card-cluster detection), not field sources | CLEARED |
| 7 — Generic paths, family-based | Demandware helpers in `variant_builder.py` | [variant_builder.py:312-648](../../backend/app/services/extract/variant_builder.py#L312) — detects Demandware *payload shape* via `_is_demandware_variation_payload_url`; Demandware = Salesforce Commerce Cloud = platform family | CLEARED |

**Layering concern (not an invariant violation):** Demandware variant parsing lives in `extract/variant_builder.py`, but Shopify equivalent lives in `adapters/shopify.py`. Two platform families, two different homes. Inconsistent. Route to bible's "module boundary" section.

## Duplication inventory (high-severity fields)

| Field | File count | Methods present | Primary drift risk |
|-------|-----------|-----------------|--------------------|
| `price` | 6 | DOM, REGEX, STATE, JLD, PASS, DERIVE | Three regex patterns in three files: `_PRICE_WITH_CURRENCY_RE`, `LISTING_BUY_BOX_PRICE_PATTERN`, `NEXT_FLIGHT_SALE_PRICE_PATTERN` |
| `title` | 5 | DOM, STATE, JLD, REGEX | Breadcrumb-h1 logic in `dom_extraction` overlaps with generic title paths |
| `image_url` | 5 | DOM, STATE, JLD, DERIVE | `extraction_helpers._extract_image_urls` sanitizer used only in one consumer |
| `availability` | 4 | DOM, REGEX, STATE, JLD | Stock-state text detection diverges between variant and card paths |
| `sku` | 4 | DOM, REGEX, STATE, JLD | Part#/SKU# text hunting in cards vs. direct payload maps on detail |

Full field × file matrix: see user-pasted Gemini output in chat log (Deliverable 2). Not duplicated here — would just drift.

## Branching analysis (15 branches total)

**Accidental (8) — removal candidates:**
- `listing_extractor.py:L142` `_extract_dom_listing_records` — passes page_type back up
- `listing_card_extractor.py:L143` `_card_group_scorer` surface routing — sub-scorer dispatch by name
- `listing_item_mapper.py:L114` `_looks_like_listing_variant_option` — early exit if not ecommerce
- `detail_extractor.py:L480` `_extract_from_comparison_tables` — early exit if job
- `detail_extractor.py:L614` `_build_dynamic_structured_rows` — skip spec aggregate if job
- `semantic_support.py:L142` `_build_dynamic_semantic_rows` — skip spec aggregate if job
- `dom_extraction.py:L129` `extract_label_value_from_text` — plumbing arg for alias lookup
- `variant_extractor.py:L109` `assess_variant_completeness` — early exit if not ecommerce_detail

**Essential (7) — preserve:**
- `listing_extractor.py:L47` — drops detail-only fields on listings (output-shape guarantee)
- `listing_card_extractor.py:L221` — commerce price/image vs job company/salary (genuinely different)
- `listing_item_mapper.py:L57` — job-specific vs commerce alias keys
- `listing_quality.py:L62` — different MVP fields per surface
- `listing_quality.py:L186` — different validation signals per surface
- `service.py:L170` — short-circuits entire pipeline when surface is listing
- `json_extractor.py:L218` — dynamic surface classification

**Pattern:** Accidental branches are "skip this block if job surface" or "rename key if commerce." Essential branches are "fundamentally different data shape." The architectural fix is to hoist surface-aware output shaping to one place (quality/contract layer) and delete the in-function guards.

## Shared-logic reach

| Module | Exports | Importers | Utilization | Action |
|--------|---------|-----------|-------------|--------|
| `shared_logic.py` | 7 | 2 (`listing_item_mapper`, `json_extractor`) | 3 + 3 used | Consolidate — low reach, obvious home in policy module |
| `shared_variant_logic.py` | 2 | 3 (incl. `adapters/shopify.py` — cross-layer) | 2 + 2 | Cross-layer import = layering concern, route to bible |
| `extraction_helpers.py` | 6 | 2 (`service.py` uses 5, `detail_extractor.py` uses 1) | Uneven | Split — most is service-internal; image helper likely belongs elsewhere |
| `semantic_support.py` | 2 | 1 (`service.py`) | 2 used | Single-consumer — inline or keep narrow |
| `signal_inventory.py` | 3 | 1 (`service.py`) | 2 used + 1 type-hint | Single-consumer — keep narrow |

**Dead exports flagged:** `shared_logic.normalized_field_token`, `shared_logic.coerce_nested_text`, `signal_inventory.SignalInventory` (type-hint only).

## Data quality caveats (Gemini output)

- **Deliverable 4 symbol-name drift.** Gemini listed 4 distinct names as used from `shared_logic.py` (`_extract_image_candidates`, `extract_image_values`, `find_alias_values`, `resolve_slug_url`, `coerce_scalar_text`). `shared_logic.py` exports 7. Underscore/prefix handling inconsistent. Not worth re-running — will verify exact symbols during Batch B authoring, which re-touches `shared_logic`.
- **No UNCLEAR branches.** Gemini was fully confident on all 15. Likely overconfident. Batch C (codebase-wide `page_type`/`surface` sweep) will catch anything missed.
- **`listing_card_context.py` marked ecom-only.** May also serve jobs via card-metadata extraction. Minor — check during Phase 0.

## Implications for the bible (Document 2)

1. **Field-source registry, not scattered extractors.** Per-field source hierarchy (ADPT → JLD → STATE → DOM → LLM) should become data (a registry table), not code duplicated across 5 files.
2. **Noise policy centralization.** Noise-strip logic referenced in Batch A; Batch B will confirm fragmentation. Likely one consolidated policy module.
3. **Surface-aware shaping at one boundary.** All 8 accidental branches collapse if output-shape contracts are applied once, post-extraction.
4. **Platform-family adapters vs extractors.** Demandware/Shopify question needs a rule: platform-family logic lives in `adapters/`, generic extraction lives in `extract/`. Enforce uniformly.
5. **Regex / magic-value registry.** Price regexes move to typed config per Invariant 1.

## Implications for the slice backlog (Document 3)

**Phase 0 — Kill dead code** (ready to draft after Batch B; targets already identified):
- `shared_logic.normalized_field_token`
- `shared_logic.coerce_nested_text`
- `signal_inventory.SignalInventory` if confirmed unreferenced at runtime

**Phase 1 — Policy module consolidation** (requires Batch B to fully scope).

**Phase 2 — Collapse duplicate field extractors** (Batch A gives the field × file map; wait for Batch B to confirm no policy rules hide inside the extractors).

**Phase 4 — Remove accidental branches** (8 concrete targets listed above).

## Raw Gemini output

User pasted full Deliverables 1-5 into the chat on 2026-04-17. Not re-embedded here to avoid drift. If re-checking is needed, re-run Batch A per the prompt pack template.
