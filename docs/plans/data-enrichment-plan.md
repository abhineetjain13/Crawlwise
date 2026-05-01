# Plan: Data Enrichment

**Created:** 2026-04-30
**Agent:** Codex
**Status:** COMPLETE
**Touches buckets:** Extraction, LLM Admin + Runtime, API + Bootstrap, Frontend, Publish + Persistence

## Goal

Build Data Enrichment as an on-demand ecommerce detail feature. Enrichment reads `crawl_records.data`, writes only enrichment-owned output fields to `enriched_products`, and updates only `crawl_records.enrichment_status` / `enriched_at` on source records.

## Acceptance Criteria

- [ ] Enrichment can run deterministic-only with zero LLM calls.
- [ ] Enriched DB rows contain only trace/status fields plus enriched output fields.
- [ ] Category enrichment runs in deterministic Slice 3, using the official Google Product Category taxonomy first.
- [ ] LLM only helps category/semantic enrichment when user enables it.
- [ ] No raw crawl canonical fields are persisted as enrichment output columns.
- [ ] `python -m pytest tests -q` exits 0 before closing the plan.

## Enriched Fields

Persist in `enriched_products`: `source_run_id`, `source_record_id`, `source_url`, `status`, `diagnostics`, `price_normalized`, `color_family`, `size_normalized`, `size_system`, `gender_normalized`, `materials_normalized`, `availability_normalized`, `seo_keywords`, `category_path`, `intent_attributes`, `audience`, `style_tags`, `ai_discovery_tags`, `suggested_bundles`.

Do not persist all ecommerce canonical fields as columns.

## Do Not Touch

- `publish/*` export compensation paths - raw signal fixes belong upstream in extraction.
- Detail candidate arbitration redesign - current field-by-field candidate system stays intact.
- Main crawl LLM behavior - enrichment LLM is separate and explicit.
- Image enrichment - out of v1.

## Slices

### Slice 1: Raw Signal Fix
**Status:** DONE
**Goal:** Add upstream raw ecommerce signals needed by enrichment.
**Files:** extraction field config, detail structured/DOM extraction, focused backend tests
**Work:** Add ecommerce detail `gender` as canonical extractable field and improve raw `category` extraction from JSON-LD breadcrumbs and DOM breadcrumbs.
**Acceptance Criteria:**
- Detail crawl records can include raw `gender`.
- Detail crawl records can include raw source category/breadcrumb category.
- No enrichment tables required.
- Focused extraction tests pass.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_field_policy.py tests/services/test_detail_extractor_structured_sources.py tests/services/test_selectolax_css_migration.py -q`

### Slice 2: Enrichment Foundation
**Status:** DONE
**Goal:** Add job/table/API shell only.
**Files:** `models/crawl.py`, Alembic, `schemas/data_enrichment.py`, `api/data_enrichment.py`, `services/data_enrichment/`, `services/config/data_enrichment.py`, canonical docs
**Work:** Add `DataEnrichmentJob`, `EnrichedProduct`, crawl record enrichment status metadata, `/api/data-enrichment/jobs`, Google taxonomy/attribute repository path config, and `llm_enabled` job option defaulting to false.
**Acceptance Criteria:**
- Job can be created from selected ecommerce detail records or source run.
- Non-ecommerce records are rejected/skipped.
- Already `enriched`/`degraded` records are skipped.
- Placeholder enriched rows are created with pending status.
- Foundation does not compute enrichment values yet.
- API returns job and enriched row shell.
**Verify:** focused model/API/service tests plus structure smoke if touched.
**Result:** Added foundation models, migration, API routes, service shell, reset hook, enrichment data repository locations, focused tests, and canonical doc updates.

### Slice 3: Deterministic Enrichment + Category
**Status:** DONE
**Goal:** Produce all deterministic enriched fields, including category.
**Files:** data enrichment service/config/data files/tests
**Work:** Add official Google Product Category taxonomy and Google Merchant-style product attribute repository under `backend/app/data/enrichment/`, load paths from config, and populate `price_normalized`, `color_family`, `size_normalized`, `size_system`, `gender_normalized`, `materials_normalized`, `availability_normalized`, `seo_keywords`, and `category_path`. Category uses GPC first: exact path match, then leaf match, then scored best match; low confidence stays null. Attribute presence/null requirements are recorded in diagnostics.
**Acceptance Criteria:**
- Deterministic-only job completes with enriched status.
- Category path can be produced from GPC without LLM.
- Low-confidence category does not guess.
- Currency is normalized into `price_normalized.currency`.
- Size, gender, material, availability use the JSON attribute repository, not hardcoded tables.
- SEO keywords use deterministic normalized fields.
- Tests cover category match, no-match null, price/currency, size, color, gender, material, availability, SEO.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_data_enrichment.py tests/services/test_field_policy.py tests/services/test_field_value_core.py -q`
**Result:** Added official GPC taxonomy, Google product attribute repository, deterministic price/color/size/gender/material/availability/SEO/category enrichment, GPC-first category matching, attribute presence/null diagnostics, and focused tests.

### Slice 4: Optional LLM Hybrid Enrichment
**Status:** DONE
**Goal:** Use LLM only when enabled to fill gaps and semantic fields.
**Files:** LLM task config/prompts, enrichment service/tests
**Work:** Add one structured LLM call per product when `llm_enabled=true`. Prompt input uses extracted + deterministic enriched fields only. LLM may fill missing/low-confidence `category_path` if GPC-valid and populates `intent_attributes`, `audience`, `style_tags`, `ai_discovery_tags`, `suggested_bundles`.
**Acceptance Criteria:**
- `llm_enabled=false` causes zero LLM calls.
- `llm_enabled=true` sends one prompt per product.
- Prompt excludes raw HTML and raw crawl artifacts.
- LLM category must match GPC or be rejected/null.
- Bad JSON response does not fail deterministic enrichment.
- Tests cover disabled LLM, valid payload, invalid taxonomy category, malformed response.
**Verify:** LLM payload validation and invalid taxonomy path tests.
**Result:** Added `data_enrichment_semantic` LLM task, prompt files, `llm_enabled` gating, GPC validation, and tests for disabled/enabled LLM behavior.

### Slice 5: Frontend
**Status:** DONE
**Goal:** Add user-facing Data Enrichment workflow.
**Files:** frontend Data Enrichment page, API types/client, nav, crawl run action
**Work:** Add `/data-enrichment`, selected-record prefill from successful ecommerce detail runs, job history, LLM toggle, and enriched result display.
**Acceptance Criteria:**
- User can enrich selected ecommerce detail records.
- User can choose deterministic-only or deterministic + LLM.
- UI shows pending/running/enriched/degraded/failed.
- UI displays all enriched fields.
- Already enriched records are not duplicated.
**Verify:** frontend tests for prefill, job list, status badges, and result rendering.
**Result:** Added `/data-enrichment`, API types/client methods, sidebar nav, run detail prefill action, LLM toggle, job list, and enriched result display.

## Doc Updates Required

- [x] `docs/backend-architecture.md` - Data Enrichment service/API/model ownership after foundation slice.
- [x] `docs/CODEBASE_MAP.md` - Data Enrichment files after new files are added.
- [x] `docs/BUSINESS_LOGIC.md` - user-visible enrichment status/job behavior after foundation slice.
- [x] This plan - mark each slice done only after verify passes; append verify command and result.

## Notes

- `backend/app/data/enrichment/google_product_category.txt` is the official GPC taxonomy source.
- `backend/app/data/enrichment/google_product_data_attributes.json` is the local product attribute, null-attribute, and normalization repository. It is based on Google Merchant product data attributes.
- Official live Amazon product type definitions and per-product-type attribute requirements require SP-API Product Type Definitions credentials; no complete public static Amazon file is available.
- V1 queue uses FastAPI `BackgroundTasks`, matching Product Intelligence.
- Status values: `unenriched`, `pending`, `running`, `enriched`, `degraded`, `failed`.
- Existing foundation is still in git diff, so amend it directly before continuing.
- 2026-04-30: Slice 1 passed focused verify: `176 passed, 4 skipped` for field policy, detail structured extraction, selectolax migration, and public firewall tests.
- 2026-04-30: Slice 2 passed focused verify: `187 passed, 4 skipped` for data enrichment service, structure, field policy, field value core, detail structured extraction, and selectolax migration tests.
- 2026-04-30: Slice 3/4 focused verify passed: `50 passed` for data enrichment, field policy, and field value core tests.
- 2026-04-30: Full backend verify passed: `1131 passed, 4 skipped`.
- 2026-04-30: Frontend lint passed: `npm run lint`.
- 2026-04-30: Frontend tests passed: `80 passed`.
- 2026-04-30: Reverted bad Amazon seed. Restored official GPC taxonomy and added Google product attribute/null-attribute repository.
- 2026-04-30: Corrected source verify passed: `1131 passed, 4 skipped`.
