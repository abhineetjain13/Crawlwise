# CrawlerAI — Product Requirements Document

| Field | Value |
|---|---|
| Version | 7.0 |
| Date | 2026-04-02 |
| Status | Active — Source of Truth |
| Prior Version | 6.0 |

---

## v7.0 Change Summary

Eleven issues resolved from architectural review of v6.0. All other content is unchanged from v6.0.

| # | Severity | Area | Change |
|---|---|---|---|
| 1 | CRITICAL | Batch Storage (Section 6d) | Rewrote batch storage model. Every record produced by a batch run is now stored as an individual row in the primary `records` table with a `batch_id` FK. Combined JSON/CSV is generated on-demand by a new `batch/export_generator.py`. Old `result_store.py` (combined-blob) is removed. Re-extract and drift resolution now operate on batch records individually. |
| 2 | CRITICAL | Distributed LLM Lock (Section 11) | Added Redis distributed lock scoped to `domain_memory_lock:{domain}:{task_type}:{field}` around all Domain Memory LLM-write operations. Prevents concurrent Celery workers from triggering redundant LLM calls for the same field on the same domain, enforcing the one-time rule under concurrency. |
| 3 | CRITICAL | SPA/JS Feedback Loop (Stage 1) | Added post-Stage-3 coverage check. If `curl-cffi` was used and canonical field coverage = 0%, Stage 1 re-enters with forced Playwright render before proceeding to Unify. Fires at most once per URL per run. |
| 4 | HIGH | Accuracy Metric Inflation (Section 12c) | Held records now always included in the denominator for all three accuracy metrics. UI shows true degraded numbers, not inflated numbers computed only on the published subset. |
| 5 | HIGH | LLM HTML Minification (Appendix B) | New `llm/html_minifier.py` strips SVGs, style blocks, non-data scripts, hidden elements, and HTML comments from all HTML before any LLM prompt assembly. Enrichment truncation limit raised to 200k post-minification chars (up from 100k raw). |
| 6 | HIGH | Canonical Field Collision Guard (Section 9a) | At submission time, `additional_fields` names are validated against the active canonical schema for the selected surface. Collisions return a structured 400 error with field names identified. Frontend shows inline validation before crawl starts. |
| 7 | MEDIUM | LLM JSON Output Safety (Appendix B1) | `LLMProvider.complete()` now includes a mandatory `_parse_json_safe()` post-processor that strips markdown fences and leading prose before `json.loads()`. `JSONDecodeError` replaced with a structured `{_parse_error: true}` result — pipeline treats it as a miss, no crash. |
| 8 | MEDIUM | Batch Pre-population Scale (Section 6a) | URL count > 500 no longer renders in a textarea. A virtualized 20-row preview list + server-side `pre_population_id` reference replaces it, preventing browser DOM lag. |
| 9 | MEDIUM | Missing Batch API Endpoints (Section 16) | Added `DELETE /crawl/batch/{batch_id}` and `POST /crawl/batch/{batch_id}/re-extract`. Both are possible because records are now stored individually (fix #1 enables fix #9). |
| 10 | LOW | Recrawl Ghost Data (Section 8c) | If a selector is deleted before a Recrawl, any field value produced by that now-absent selector is set to `null`, not preserved. Uses `selector_used` metadata on each stored field value to identify affected fields. |
| 11 | LOW | API Key Write-Only Security (Section 18, Appendix B1) | `GET /admin/llm-config` returns `api_key_set: true` and `api_key_masked: "sk-****"` only. The actual encrypted or decrypted key is never returned in any API response. |

---

## 0. Why This Document Exists

This document licences every build and deletion decision. Any code, module, or behaviour not described or implied here is a candidate for removal. When this document and the code disagree, fix the code or update this document — never leave them in silent disagreement.

This is a two-phase greenfield build. The Phase 1 architecture must make no decisions that close off Phase 2. The Phase 2 spec is written now so the POC is not a throwaway.

---

## 1. Product Vision

CrawlerAI is a local-first, self-improving web data extraction platform that turns any web page into structured, normalised, queryable data — with the user in control of what that structure looks like.

### Two Core Bets

- **Bet 1 — Extraction accuracy compounds.** Every run on a domain makes the next run cheaper, faster, and more accurate.
- **Bet 2 — Schema is user-defined, not system-imposed.** The system extracts everything it can find. The user decides what the output schema looks like.

### Primary Surfaces

| Surface | Examples | Phase |
|---|---|---|
| Commerce Listing | Category pages, search results, PLPs | POC |
| Commerce Detail | Product detail pages (PDP) | POC |
| Job Listing | Job board search results | POC |
| Job Detail | Individual job posting pages | POC |
| Tabular Data | Tables inside listing/detail pages | POC |

### Accuracy Metrics — The Three Efficiency Numbers

> **Computation guarantee:** All three metrics are computed exclusively from real extracted data. Zero LLM involvement. Zero estimation. Each metric is always displayed with a sample-size indicator — e.g. `Site Crawl 84% (n=47 URLs)`. Metrics update in real time as records are published. **Held records are always included in the denominator** — metrics reflect the true state of the run including unresolved records. *(v7.0 correction)*

| Metric | Definition | Computation | POC Target | Final Target |
|---|---|---|---|---|
| Site Crawl Efficiency | % of submitted URLs that returned ≥1 valid published record | (URLs with ≥1 published record) ÷ (total submitted URLs). Pure DB count. | ≥70% | ≥92% |
| Field Coverage Efficiency | % of canonical fields populated across **all** records in a run (published + held) | Per record: non-null canonical fields ÷ total canonical fields for the surface. Averaged across **all records including held**. | ≥60% | ≥85% |
| Data Fidelity Score | % of populated fields that passed validation without coercion | Fields that passed Pydantic validation without normaliser transformation ÷ total populated fields. Logged at normalisation time. | ≥80% | ≥95% |

Metrics are displayed per run and per domain in history view. The `n=` sample size is always shown alongside the percentage.

---

## 2. Tech Stack

### Backend

| Layer | Technology | Notes |
|---|---|---|
| Runtime | Python 3.12+ | |
| Framework | FastAPI | Async-first, OpenAPI docs auto-generated |
| Task queue | Celery + Redis | Background crawl jobs, batch processing |
| HTTP client (primary) | curl-cffi | Chrome TLS fingerprint impersonation |
| HTTP client (fallback) | httpx | Standard async HTTP |
| Browser automation | Playwright (async) | Shared pool, stealth mode. Saves full rendered HTML for all pages. |
| Stealth layer | playwright-stealth | Patches navigator fingerprints, evasion |
| Distributed locking | Redis (via `redis-py` Lua scripts or `redlock-py`) | Used for Domain Memory LLM-write locks. See Section 11. |
| Proxy rotation | rotating-proxy (OSS) [POC] → Bright Data / Oxylabs [FINAL] | Drop-in behind proxy interface |
| Schema validation | Pydantic v2 | |
| LLM integration | Provider-agnostic abstraction layer (see Appendix B) | Default: Llama 3.x via Groq. User-selectable from UI. No hardcoded model strings in pipeline. |

### Frontend

| Layer | Technology | Notes |
|---|---|---|
| Framework | Next.js 15 (App Router) | SSR, API routes, future SaaS path |
| Language | TypeScript | Strict mode |
| Styling | Tailwind CSS v4 | |
| State management | Zustand | Lightweight, no boilerplate |
| Data fetching | TanStack Query | Cache, background refresh, optimistic updates |
| Tables | TanStack Table | Virtual scroll for large record sets |
| Charts | Recharts | Accuracy metrics, run history |

### Data

| Layer | Technology | Notes |
|---|---|---|
| Primary DB | PostgreSQL 16 | JSONB for records, indexes on domain/run_id/batch_id |
| Cache / Locks | Redis | Celery broker, acquisition artifact cache, distributed locks |
| Artifact storage | Local filesystem [POC] → S3-compatible (MinIO) [FINAL] | HTML artifacts, screenshots |
| Migrations | Alembic | |
| Batch output | Export Generator (View over `records` table) | Combined JSON/CSV generated on-demand per `batch_id`. Records stored individually in primary `records` table with `batch_id` FK. See Section 6d. |

---

## 3. The Core Promise

> The system extracts every piece of data a human could see on a rendered page, presents it all to the user, and lets the user define what the output schema looks like — with the schema persisted and improved automatically on every subsequent run. For complex pages where fields are present but hidden in collapsed UI, unexpected JSON-LD patterns, or deeply nested `__NEXT_DATA__` paths, the system attempts extraction from the cached rendered artifact before calling a field missing.

- If a human can see a field in a rendered browser, the system must find it.
- If the system finds a field the user did not ask for, it shows it anyway and lets the user decide.
- If the system cannot extract a field reliably, it says so explicitly — it never invents values.
- If multiple sources on the same page disagree, the system picks the most authoritative one and is transparent about the conflict.
- Schema decisions made by the user on one run are remembered and pre-applied on the next run against the same domain.
- The user can specify additional target fields before any crawl. The system searches for them deterministically first and falls back to LLM only if that fails and Smart Extraction is ON.

---

## 4. Pipeline — Five Stages

The entire extraction pipeline is five stages in a strict sequence. Each stage has a single responsibility and produces an immutable output that the next stage consumes. No stage reaches backward. No stage skips forward. There is exactly one pipeline — no parallel pipelines for any feature, including selector-driven recrawl, batch crawl, or enrichment.

```
ACQUIRE → DISCOVER → EXTRACT → UNIFY → PUBLISH
```

### Stage 1 — ACQUIRE

**What:** Fetch the raw page artifact using the best available method.

> **JS-rendered pages and the artifact:** Playwright renders JS-heavy pages in a real browser context. The output is always the full DOM after JavaScript execution — carousels expanded, accordions in their initial state, all inline script content present. This rendered HTML IS the acquisition artifact and IS always saved to cache. The 'complex JS' extraction problem is therefore never about missing HTML — it is about data hiding inside the rendered DOM in unexpected structures (collapsed UI, non-standard JSON-LD, deeply nested `__NEXT_DATA__` paths). Every stage downstream operates on this full rendered artifact.

#### Acquisition Method Waterfall

1. Check artifact cache (Redis + filesystem). If hit → return cached artifact. Network is never hit on re-extract or enrichment passes.
2. Try `curl-cffi` with Chrome TLS impersonation.
3. If `curl-cffi` signals bot-wall or JS-required → try Stealth Playwright browser. Full rendered HTML is always saved from the Playwright render.
4. If Playwright returns a bot-wall → record `anti_bot_signals=["bot_wall"]`, return artifact with `CrawlStatus.blocked`.

#### SPA/JS Empty-Shell Feedback Loop *(new in v7.0)*

> **Problem:** Many modern Next.js/React apps return a valid HTTP 200 from `curl-cffi` with a fully-populated HTML skeleton (nav, footer, menus) that exceeds the JS-required detection threshold, but the actual product/job data is absent until JavaScript executes. The pipeline would accept this as a valid `curl-cffi` acquisition, find zero canonical fields, and publish an empty shell.

**Rule:** After Stage 3 (EXTRACT) completes, a coverage check is performed before entering Stage 4 (UNIFY):

- **If** the acquisition method was `curl_cffi` **and** canonical field coverage of the extracted candidate set is **0%**: the pipeline **re-enters Stage 1** with acquisition method forced to `browser`. The artifact cache is bypassed. Playwright renders the page fully and the new artifact replaces the prior one. The pipeline then resumes from Stage 2.
- This upgrade fires **at most once per URL per run**. If Playwright also yields 0% canonical coverage, the pipeline proceeds with the Playwright artifact and reports the low coverage truthfully.
- The upgrade event is recorded in the artifact: `acquisition_upgrade_reason: "zero_canonical_coverage_on_curl_cffi"`.

#### JS-Required Signals (direct upgrade to Playwright, no coverage check needed)

- Blank or near-blank body (< 500 chars visible text)
- `<noscript>` redirect present
- "enable javascript" text in body
- Redirect to login or challenge page

#### Output — AcquisitionArtifact (frozen dataclass)

```python
@dataclass(frozen=True)
class AcquisitionArtifact:
    url: str
    html: str                               # Always the full rendered DOM
    network_payloads: list[dict]            # XHR/fetch intercepts (browser only)
    screenshot_path: str | None             # Browser screenshot — always saved when browser is used
    acquisition_method: str                 # 'curl_cffi' | 'httpx' | 'browser'
    acquisition_upgrade_reason: str | None  # Set if Stage 1 was re-entered (new v7.0)
    status_code: int
    timing_ms: int
    anti_bot_signals: tuple[str, ...]
    cache_key: str                          # Deterministic: hash(url + params)
    acquired_at: float
```

#### Advanced Browser Rendering [POC]

| Mode | Behaviour |
|---|---|
| paginate | Detect and click next-page controls. Collect HTML from each page. Stop at max_pages or duplicate-page detection. |
| scroll | Scroll to bottom repeatedly. Stop at max_scrolls or no new content detected. |
| load_more | Click load-more/show-all buttons until exhausted or max_clicks reached. |
| auto | Inspect page, detect mode from signals, execute. Surface detected mode to user. |

#### Cookie Management [POC]

| Mode | Description | Storage |
|---|---|---|
| Manual injection | User pastes raw cookie header string in the crawl form | Ephemeral, per-run |
| Session persistence | Browser cookie jar preserved across all pages in a single crawl run | In-memory, per-run |
| Per-domain cookie jar | Domain-level cookie jar persisted to DB. Reused on all future runs for that domain. | PostgreSQL `domain_cookies` table |

---

### Stage 2 — DISCOVER

**What:** Inspect the acquisition artifact and enumerate every data source present on the page.

| Rank | Source Type | Notes |
|---|---|---|
| 1 | Platform adapter output | Shopify /products.json, Workday feed — config-driven |
| 2 | Browser API interception | XHR/fetch payloads intercepted during Playwright render |
| 3 | `__NEXT_DATA__` / embedded app state | Inline `<script id="__NEXT_DATA__">` |
| 4 | JSON-LD blocks | `<script type="application/ld+json">` |
| 5 | Microdata / RDFa | `itemprop`, `typeof` attributes |
| 6 | DOM / CSS selectors | Saved domain memory selectors applied first; deterministic discovery second |
| 7 | Shadow DOM | Queried if standard DOM yields nothing |
| 8 | HTML tables | Structural table extraction |

**Output — DiscoveryManifest:** an ordered list of `DiscoveredSource` objects, each with `source_type`, `raw_payload`, `confidence`, and `rank`.

---

### Stage 3 — EXTRACT

**What:** For each source in the DiscoveryManifest, extract field values using the appropriate extractor.

- Domain memory selectors are applied first (zero LLM cost).
- Deterministic CSS/XPath patterns are tried next.
- If Smart Extraction is ON and deterministic methods failed for a field, LLM selector discovery is invoked (subject to the distributed lock — see Section 11).
- Each extractor produces a `CandidateRecord`: `{field_name: {value, source_rank, confidence, selector_used}}`.
- Multiple `CandidateRecord`s from different sources proceed to UNIFY for arbitration.

**Output — list[CandidateRecord]**

---

### Stage 4 — UNIFY

**What:** Merge all CandidateRecords into a single authoritative record per extracted entity.

- Source priority is the rank from the DiscoveryManifest.
- When two sources disagree on a field, the higher-ranked source wins. Conflict is logged in `extended_fields._conflicts`.
- Field name mapping (raw → canonical) is applied from the domain's approved Schema Registry mapping. If no approved mapping exists and Smart Extraction is ON, LLM field mapping is invoked (subject to distributed lock).
- Deduplication is performed once at the end of Stage 4, by `record_deduplicator.py`. Never inside individual extractors.

**Output — list[UnifiedRecord]**

---

### Stage 5 — PUBLISH

**What:** Validate, normalise, shape, and persist the UnifiedRecords.

- `shape_for_validation()` pre-processes records.
- Pydantic v2 validation runs on each record. Failed fields are noted for Data Fidelity Score computation.
- `field_normalizers.py` normalises values. All coercions are logged for fidelity tracking.
- Schema Registry version check: if the record's field set drifts from the approved schema version, the record is held (not published) and a `DriftEvent` is created.
- Clean records pass through `shape_records()` — the single output publication boundary — and are persisted.
- **For batch runs: each record is stored in the primary `records` table with the `batch_id` FK.** See Section 6d.

**Output — list[PublishedRecord | HeldRecord]**

---

## 5. Data Models

### 5a. ProductRecord — Canonical Fields

```python
class ProductRecord(BaseModel):
    # Identity
    title: str | None = None
    brand: str | None = None
    sku: str | None = None
    gtin: str | None = None

    # Pricing
    price: Decimal | None = None
    sale_price: Decimal | None = None
    currency: str | None = None
    price_range: str | None = None

    # Media
    image_url: str | None = None
    image_urls: list[str] = Field(default_factory=list)

    # Availability
    availability: str | None = None
    stock_count: int | None = None

    # Classification
    category: str | None = None
    subcategory: str | None = None
    tags: list[str] = Field(default_factory=list)

    # Detail
    description: str | None = None
    rating: float | None = None
    review_count: int | None = None

    # Extended
    extended_fields: dict[str, Any] = Field(default_factory=dict)
```

### 5b. Run Metadata (attached to every record)

```python
source_url: str
run_id: str
batch_id: str | None        # Set for all records produced by a batch run
acquisition_method: str
acquired_at: float
schema_version: str
mapping_version: str
```

### 5c. JobRecord — same structure, job-specific canonical fields

`(salary, company, location, job_type, posted_date, apply_url, remote, department, seniority, skills, requirements, benefits, table_data, extended_fields)`

### 5d. Reserved Internal Fields (never published)

`source`, `confidence`, `selector_used`, `_source`, `_recipe`, `_cluster_id`, `source_url`, `_raw_fields`

---

## 6. Batch Crawl

> **Priority feature:** Batch crawl is the primary use case. Every architectural decision must support it as a first-class path, not a secondary mode.

### 6a. URL Input Methods

**Method 1 — Paste**

On the Batch tab of the Crawl page, the user pastes URLs directly into a text area — one URL per line. The system parses the pasted content, deduplicates, and displays the URL list immediately.

**Method 2 — CSV Upload**

The user uploads a CSV file. The system reads the first column (or a user-designated column) as the URL list. Column headers are detected automatically. Non-URL rows are filtered and flagged. The clean URL list is shown for review before the crawl starts.

**Method 3 — One-Click from Results (Listing → Batch)** *(updated in v7.0)*

> **Flow:** After any listing page crawl completes, a 'Batch Crawl from Results' button appears in the Run Detail header. One click sends the extracted detail-page URLs to the backend, which stores them server-side and returns a `pre_population_id`. The Batch tab is then loaded with that ID.

**Large URL list handling (new in v7.0):**

- If the extracted URL count is **≤ 500**: URLs are rendered in the editable text area (one per line), same as Method 1.
- If the extracted URL count is **> 500**: The text area is **not** used. Instead, the UI displays:
  - A summary banner: *"N URLs ready from [source run]. Saved selectors for [domain] will be applied."*
  - A virtualized read-only preview list showing the first 20 URLs with a scrollbar indicator.
  - An "Edit List" button that opens a modal with a full editable textarea (with performance warning).
  - The full URL list is held server-side referenced by `pre_population_id` and submitted directly on Start.
- This threshold prevents browser DOM lag from rendering thousands of lines in a textarea.

### 6b. URL Review & Edit

- URLs ≤ 500: displayed as plain text in an editable text area — one per line. User selects any text block with the mouse and presses Backspace or Delete to remove those URLs.
- URLs > 500: virtualized preview as described in 6a. No checkbox interface. Direct text editing available via modal.
- A live count shows total URLs and estimated run time before start.

### 6c. Batch Run Execution

- Each URL in the batch runs the full 5-stage pipeline (ACQUIRE → DISCOVER → EXTRACT → UNIFY → PUBLISH).
- Domain memory is pre-loaded before batch execution — saved selectors, recipes, and schema preferences are applied from Stage 3 onward.
- Per-domain rate limiting is respected across the batch. Concurrent jobs across different domains are permitted; same-domain URLs are serialised with the configured rate limit delay.
- Additional fields specified by the user apply to all URLs in the batch.
- Smart Extraction setting applies to all URLs in the batch.
- Concurrent LLM calls for the same domain are governed by the Redis distributed lock described in Section 11.

### 6d. Batch Results Storage *(architectural change in v7.0)*

> **Batch storage rule:** Every record produced by a batch run is stored as an **individual row** in the primary `records` table, with the `batch_id` column set as a foreign key to the `batch_runs` table. Records are not stored as a combined blob. The `batch_id` FK is how all batch records are associated for retrieval, export, accuracy metric computation, re-extract, and drift resolution.

**Why this change was made:**

- Individual per-URL records are required for Re-extract (Section 13) to function on batch results.
- Individual records are required for Schema Registry drift resolution (Section 12b) to hold, selectively update, and publish records independently when resolving drift.
- Individual records are required for per-URL selector inspection in future batch-level tools.
- The prior v6.0 combined-blob model made all three of the above impossible.

**Export behaviour (unchanged from user perspective):**

- JSON export: an Export Generator queries the `records` table WHERE `batch_id = ?` and assembles a single JSON array on demand.
- CSV export: same query, serialised to CSV with consistent columns (union of all fields across records, null-filled where absent).
- The UI shows aggregate stats: total URLs submitted, published count, held count, failed count, and the three accuracy metrics with `n=` indicator.
- Individual URL status (published / held / failed / blocked) is shown in a summary table within the batch result view.

**New in v7.0:**
- `GET /crawl/batch/{batch_id}/records` — paginated individual records for a batch (new, possible because records stored individually).
- `POST /crawl/batch/{batch_id}/re-extract` — re-runs Stages 2–5 on the cached artifact for every URL in the batch and merges updated records.
- `DELETE /crawl/batch/{batch_id}` — deletes the batch run + all associated records + artifacts.
- New file: `batch/export_generator.py` — produces JSON/CSV from a `batch_id` by querying the `records` table. Replaces `batch/result_store.py`.

### 6e. Batch Accuracy Metrics *(updated in v7.0)*

| Metric | Batch Computation |
|---|---|
| Site Crawl Efficiency | (URLs with ≥1 published record) ÷ (total batch URLs). n= total URLs. |
| Field Coverage Efficiency | Average across **all records** in the batch (published + held). Held records contribute their actual coverage value. n= total record count. |
| Data Fidelity Score | Average across all records in the batch (published + held). n= total record count. |

### 6f. Mid-Batch Drift Behaviour

- A drift event on one URL does not pause or halt the remaining URLs.
- All URLs in the batch are evaluated against the same locked schema version.
- Multiple drift events can exist within a single batch run, each with its own `drift_id`.
- Batch status is `partial_publish_drift` if any drift events were raised.
- Drift resolution is per `drift_id` — a single batch can have multiple independent drift events resolved in any order.

---

## 7. Schema Curation — User-Controlled Output

### POC — Hybrid Schema Mode

After any single-URL run completes, the user sees a Schema Curation Panel alongside the results. This is not a modal — it is a persistent side panel in the run detail view. Schema curation is not available in the batch results view.

**Panel — Section A: Canonical Fields**
- Coverage % across all records in this run
- Toggle: Include / Exclude from export
- Source that populated it (e.g., 'JSON-LD', 'CSS selector')

**Panel — Section B: Extended Fields Discovered**
- Sample value (first 3 records), Coverage %
- Toggle: Include in export / Exclude
- Optional: User-assigned display name (rename the field)
- Badge: 'New' if first time seen for this domain

**Panel — Section C: Additional Fields Requested**

Fields the user specified in the Additional Fields input before the crawl. For each:
- Status: Found (with source type + selector discovered) / Not Found
- Value sample (first 3 records), Coverage %
- The discovered selector (CSS/XPath) if one was found — user can inspect, edit, and save

**Panel — Section D: Metadata Fields**

`acquisition_method`, `anti_bot_signals`, `source_url`, `acquired_at`, `screenshot_path`. Each is off by default.

**Persistence:** Schema preferences are saved to domain memory immediately on toggle. The next run against the same domain pre-applies these preferences.

### FINAL — Schema Builder

Rename fields, reorder columns, type-cast fields, computed fields, named schema templates, schema versioning.

### FINAL — Enrichment for Partial Coverage

> **Enrichment scope:** When a single-URL crawl completes with field coverage below 80%, the user can trigger an enrichment pass. This pass takes the cached rendered HTML artifact (already saved from Stage 1), minifies it, and re-runs targeted LLM extraction against the missing fields. No new network call is made.

- Enrichment is user-initiated. User clicks 'Attempt Enrichment'.
- LLM cost for the enrichment pass is shown before execution. Smart Extraction must be ON.
- Enriched fields are stored in `extended_fields` with `_enriched_by: 'llm_enrichment'` provenance tag.
- Enrichment results are merged into the existing published record, not stored separately.
- [FINAL] Enrichment can be triggered in batch — user selects records with coverage below a threshold.

---

## 8. CSS Selector Tab & Selector-Driven Recrawl

> **Single-crawl only:** The CSS Selector tab appears exclusively on the single-URL run detail page. It does not appear in batch results views. This is a current-phase limitation; individual batch record inspection is a FINAL phase feature.

### 8a. CSS Selector Tab — What It Shows

After any single-URL crawl completes, the CSS Selector tab is available alongside the Schema Curation panel.

| Column | Description |
|---|---|
| Field | Canonical or extended field name |
| Source | How the selector was found: `domain_memory` / `deterministic` / `llm_discovered` |
| Selector | The CSS or XPath selector string |
| Status | Valid (returned value in this run) / Failed (no result) / New (not yet tested) |
| Last Validated | Timestamp of last successful extraction using this selector |
| Actions | Test / Save / Delete |

### 8b. Selector Actions

**Test** — The user clicks Test on any selector. The system runs the selector against the currently cached HTML artifact and displays the matched result inline — no network call.

**Save** — The user clicks Save on a tested selector. The selector is persisted to domain memory with `status: validated` and the current timestamp. Applied in Stage 3 on all future crawls for this domain.

**Delete** — Removes the selector from domain memory for this domain. Will not be applied on future crawls.

### 8c. Recrawl This Page *(updated in v7.0)*

> **Behaviour:** The 'Recrawl This Page' button triggers a full 5-stage pipeline run on the same URL. Domain memory is reloaded with any newly saved selectors before the run starts. The artifact cache is bypassed for Stage 1 — a fresh fetch is performed. Results are merged into the run record by field identity: new non-empty values from higher-or-equal rank sources replace existing values.

**Ghost data nulling (new in v7.0):** If a field's selector has been **deleted** or is **invalidated** (removed from domain memory) before a Recrawl, and the field's existing stored value was generated by that now-absent selector, the stored value is set to `null`. It is not preserved.

- The `selector_used` metadata on each field value is the mechanism for identifying which values were produced by a now-deleted selector.
- This rule applies only on Recrawl (fresh fetch). Re-extract (cached artifact, Section 13) follows the standard merge rule.

### 8d. Batch Crawl Similar Pages

> **Behaviour:** 'Batch Crawl Similar Pages' navigates the user to the Batch tab on the main Crawl page. The domain is pre-set. A notice is shown: 'Saved selectors from [domain] will be applied — X selectors active.' The user pastes or uploads the target URLs and clicks Start. Because domain memory already contains the validated selectors for this domain, Stage 3 applies them immediately without LLM discovery.

> **Single pipeline rule:** Selector-driven batch crawl runs the identical full 5-stage pipeline as any other batch. There is no shortcut pipeline, no selector-only extraction mode, and no bypass of any stage.

---

## 9. Additional Fields — Prompt-Driven Extraction

> **Available in:** Both single-URL crawls and batch crawls. The additional fields input is on the main Crawl form, visible in both Single and Batch tabs.

### 9a. User Input *(updated in v7.0)*

Before starting any crawl, the user enters a comma-separated list of field names:

```
material_composition, care_instructions, warranty_period, assembly_required
```

Field names are free-form. The system normalises them (lowercase, underscores) before searching. The original user-entered name is preserved as the display name in output.

**Canonical namespace collision guard (new in v7.0):**

At submission time, the backend validates the `additional_fields` array against the active canonical schema for the selected surface:

- If any additional field name (after normalisation) **matches a canonical field name**, the submission is **rejected** with a `400` error.
- Error response: `{"error": "additional_fields_canonical_collision", "colliding_fields": ["price", "title"]}`.
- The frontend surfaces this as an inline validation error on the Additional Fields input before submission.
- Rationale: the canonical pipeline already extracts canonical fields. A duplicate additional field creates an ambiguous write target in `extended_fields`.
- This validation runs on both single-crawl and batch-crawl submissions.

### 9b. Extraction Priority

1. **Deterministic CSS/XPath pattern search (always runs first, Smart Extraction not required):** System generates candidate selectors by matching the field name and common aliases against DOM attribute names, label text, aria-labels, and adjacent text nodes. Evaluated against the full rendered HTML. If a selector returns a non-empty value → field extracted, selector saved.
2. **Structured source scan (always runs, no LLM):** System scans JSON-LD, `__NEXT_DATA__`, and API payloads for keys matching the field name or known aliases.
3. **LLM fallback (only if Smart Extraction is ON and steps 1–2 failed):** LLM is passed the pre-filtered, minified rendered HTML and the field name. It proposes a CSS or XPath selector. If the selector returns a value → field extracted, selector saved to domain memory. Counts toward one-time-per-task-type rule.

### 9c. Output

- Found fields are added to `extended_fields` in the published record with the user's display name as the key.
- All discovered selectors (CSS/XPath) are displayed in the CSS Selector tab and saved to domain memory.
- Not-found fields are listed in the Field Evidence Panel under 'Missing Fields — Requested but not found' with the reason (`absent` / `deterministic_miss` / `llm_miss`).
- In batch runs: found additional fields are included as columns in the combined CSV/JSON export. Not-found fields appear as null columns.

---

## 10. Domain Memory

Domain memory is the system's compound learned knowledge about a specific domain. It is the mechanism by which every run makes the next run better.

### What Is Stored

```json
{
  "domain": "example.com",
  "sources": {
    "json_ld": {
      "extraction_recipe": {},
      "last_validated": 1743500000,
      "success_count": 14,
      "field_coverage": ["title", "price", "brand", "image"]
    }
  },
  "selectors": {
    "title": { "selector": "h1.product-title", "source": "deterministic", "last_validated": 1743500000, "shadow_dom": false },
    "material_composition": { "selector": "td[data-label=Material]", "source": "llm_discovered", "last_validated": 1743500000, "shadow_dom": false }
  },
  "additional_fields_history": ["material_composition", "care_instructions"],
  "continuation": { "mode": "paginate", "next_selector": "a[aria-label=Next page]", "validated": true },
  "schema_preferences": {
    "include": ["title", "price", "brand", "material_composition"],
    "exclude": ["badge"],
    "display_names": { "material_composition": "Material" },
    "column_order": ["title", "price", "brand", "Material"]
  },
  "cookies": { "jar": {}, "last_updated": 1743500000 },
  "proxy_preference": "residential",
  "rate_limit_delay_ms": 2000,
  "anti_bot_signals": [],
  "accuracy": {
    "site_crawl_efficiency": 0.94, "field_coverage_efficiency": 0.81,
    "data_fidelity_score": 0.97, "runs_count": 14
  },
  "schema_registry": { "canonical_schema_version": "2", "mapping_version": "1", "mapping_status": "approved" }
}
```

### Promotion Rules

Domain memory is always domain-level first. A recipe is only promoted to platform-level when:

1. The same recipe has succeeded on 3+ distinct domains on the same platform.
2. A human has reviewed and approved the promotion via Admin > Domain Memory.

---

## 11. LLM Policy

### Smart Extraction Toggle

All LLM usage is gated by the Smart Extraction toggle. When OFF, the pipeline is purely deterministic — no LLM calls under any circumstances.

### Permitted LLM Uses

| Use Case | Stage | Conditions |
|---|---|---|
| Selector discovery for DOM sources | Extract | No prior selector in domain memory. Saves result. One-time per field per domain. |
| Selector healing when saved selector returns 0 results | Extract | Prior selector fails. Replaces + saves healed selector. |
| Field name mapping (e.g. listPrice → price) | Unify | Novel field name not in canonical mapping. Saves mapping. |
| Source identification in complex `__NEXT_DATA__` blobs | Discover | No known structure matches. Saves path. |
| Additional field discovery (fallback after deterministic miss) | Extract | Deterministic search failed. Smart Extraction ON. Saves selector. One-time per field per domain. |
| Domain mapping proposal for new domain | Schema Registry / Pre-Stage 4 | No existing approved mapping. Smart Extraction ON. Saved as proposed, not applied until user approves. |
| Enrichment pass for hidden fields in cached artifact | Post-Publish (user-initiated) | Coverage <80% or user requests. Minified rendered HTML + missing field list passed to LLM. Cost shown before execution. |
| Vision-based extraction from screenshot [FINAL] | Extract (last resort) | Coverage < threshold after all HTML methods exhausted. Vision-capable model selected. Screenshot from Stage 1 used. |

### Banned LLM Uses

| Use Case | Reason |
|---|---|
| Raw record extraction from HTML without a field target | Primary hallucination mode — produces fabricated field values |
| Arbitration between conflicting field values | Deterministic source priority only |
| Deduplication decisions | Deterministic identity matching only |
| Schema curation suggestions without user confirmation | User owns schema — system does not impose it |
| Computing or adjusting accuracy metrics | Metrics are pure math on real data — zero LLM involvement |

### Core LLM Rule — One-Time Rule

> If the LLM ran on a domain once successfully for a given task type, it never runs on that domain again for that task. The result is saved to domain memory and the deterministic path is used on all future runs. Enforced under concurrency by the Redis distributed lock.

### Distributed Lock for Domain Memory LLM Writes *(new in v7.0)*

> **Problem:** In a batch run (or multi-user environment), multiple Celery workers may process URLs from the same domain concurrently. Without a lock, all workers will simultaneously check Domain Memory, find no selector, and each trigger an independent LLM call for the same field on the same domain — defeating the one-time rule.

**Rule:** Before any LLM task type that **writes** to Domain Memory, the calling worker must acquire a Redis distributed lock:

```
lock_key  = f"domain_memory_lock:{domain}:{task_type}:{field_name}"
lock_ttl  = 30 seconds            # Max LLM call + DB write time
retry     = 3 attempts, 500ms backoff
```

**Lock behaviour:**

1. Worker A acquires the lock, finds no selector in Domain Memory → calls LLM → saves result → releases lock.
2. Workers B, C, D block on the lock. When Worker A releases, the next worker acquires it, re-checks Domain Memory, **finds the selector Worker A saved**, and proceeds deterministically without an LLM call.
3. If a worker cannot acquire the lock within the retry window, it proceeds deterministic-only for this URL and logs a `lock_timeout` warning. It does not call the LLM.

**Implementation:** `domain_memory/store.py` owns the lock acquisition via `core/redis.py`. No other module manages domain memory locks. Lock applies only to LLM-write operations. Read operations are never locked.

### Cost Tracking

```json
{
  "domain": "string",
  "task_type": "selector_discovery | field_mapping | selector_healing | source_identification | additional_field_discovery | domain_mapping_proposal | enrichment | vision_extraction",
  "input_tokens": 0,
  "output_tokens": 0,
  "cost_usd": 0.0,
  "provider": "groq | anthropic | openai",
  "model": "string",
  "timestamp": 0.0
}
```

---

## 12. Schema Registry

### Overview

- **Phase 1 — Internal Contract Engine [POC]:** Versioned domain mappings, drift detection, partial-publish gate, drift resolution flow.
- **Phase 2 — User-Facing Control Center [FINAL]:** Full Schema Registry UI — Screen 8.

### 12a. Two-Layer Architecture

**Layer 1 — Canonical Schema (User-Owned):** The user-approved, surface-scoped master output contract. Shared across all domains for a surface. Never modified without explicit user approval.

**Layer 2 — Domain Mapping (System-Owned):** Maps domain-specific raw field names to canonical fields. LLM-proposed on first encounter, user-approved, per-domain.

### 12b. Version Drift Detection [POC]

**Drift Signals:**
- A mapped field returns zero results across 3+ consecutive runs.
- A field's inferred type changes.
- A new field appears with no mapping in the current registry version.
- Field coverage drops below domain historical baseline by >15%.

**Drift Resolution:**

| Action | Behaviour |
|---|---|
| Re-map | LLM re-mapping → review → approve → new schema version → publish held records. |
| Override | Manual mapping edit → approve → new schema version → publish held records. |
| Discard | Discard held records permanently. Domain remains on previous schema version. |

Because records are now stored individually (Section 6d), "publish held records" operates as a standard record-level state transition (`held → published`) for each affected row.

### 12c. Accuracy Metrics During Drift *(corrected in v7.0)*

> **v6.0 error:** v6.0 excluded held records from the denominator, causing inflated metrics (e.g., 100% Field Coverage Efficiency when 50% of records were held). This gave a false impression of success while records were failing in the background.

> **v7.0 correction:** Held records are **always included in the denominator** for all three metrics. The UI will show a degraded metric reflecting the true state. A footnote identifies the held count.

| Metric | Computation During Partial-Publish Drift |
|---|---|
| Site Crawl Efficiency | Held records included in denominator as non-published. Metric degrades proportionally. n= reflects total submitted URLs. Footnote: 'X records held — metrics will improve after drift resolution.' |
| Field Coverage Efficiency | Held records included in the per-record average at their actual coverage value. Metric degrades. Same footnote. |
| Data Fidelity Score | Held records included. Same footnote. |

### 12d. Rollback Path for Incorrect Mappings

1. **User identifies incorrect mapping** (e.g., `offerPrice` mapped to `price` but should be `sale_price`).
2. **User opens Domain Mapping Detail** and selects Override on the incorrect field.
3. **Correction creates a new `mapping_version`.** New mapping applies to all future runs only.
4. **Historical records not automatically corrected.** User triggers re-extract on any affected run — re-extract uses the new mapping and merges corrected fields.
5. **All mapping versions retained in version history** with approval timestamp and `approved_by` identifier.

---

## 13. Re-extract

Re-extract operates on the cached artifact from a prior run. The network is never hit.

### Behaviour

1. Load HTML artifact from cache using `cache_key`.
2. Re-run Stages 2–5 only (Discover, Extract, Unify, Publish).
3. Use updated domain memory — new selectors, updated recipes, corrected mappings.
4. Merge new records into existing saved records by URL/title identity — not wholesale replacement.
5. Fields from re-extract: update if new value is non-empty and source rank is equal or higher.
6. Existing fields not touched by re-extract: preserved.

> **Schema mapping on re-extract:** If the original run was flagged `schema_unmapped` (Smart Extraction was OFF), a re-extract with Smart Extraction ON triggers the LLM domain mapping pass against the cached artifact. No new network fetch required. Proposed mapping is surfaced for user approval before being applied.

**Batch re-extract (new in v7.0):** `POST /crawl/batch/{batch_id}/re-extract` runs the above process for every URL in the batch using its individually stored record and cached artifact. Records are merged individually. Batch aggregate metrics are recomputed after completion.

---

## 14. Architecture Boundaries

| Boundary | Rule |
|---|---|
| `field_normalizers.py` | All value normalisation lives here. No inline normalisation anywhere else. |
| `url_classification.py` | All URL type classification lives here. |
| `record_deduplicator.py` | All deduplication lives here. Called exactly once per run, at the end of Stage 4. |
| `shape_records()` | The only output publication boundary. All records pass through here before persistence. |
| `shape_for_validation()` | The only pre-validation shaping boundary. |
| `acquisition/http_client.py` | All `curl-cffi` and `httpx` HTTP calls live here. No other module makes direct HTTP calls except platform adapters. |
| `acquisition/browser_client.py` | The shared browser pool lives here. No other module instantiates a browser pool. |
| `schema_curation/` | All schema preference read/write lives here. |
| `domain_memory/store.py` | All domain memory read/write **and lock management** lives here. No hardcoded extraction defaults. |
| `proxy/` | All proxy selection and rotation lives here. |
| `schema_registry/mapper.py` | All domain-to-canonical field translation lives here. |
| `schema_registry/validator.py` | All schema version validation lives here. |
| `schema_registry/store.py` | All registry read/write lives here. |
| `llm/provider.py` | All LLM provider instantiation and API calls live here. No other module calls a provider SDK directly. Includes mandatory `_parse_json_safe()` post-processor. |
| `llm/html_minifier.py` | All HTML pre-processing for LLM prompt assembly lives here. No other module strips HTML for LLM input. |
| `additional_fields/resolver.py` | All additional-field deterministic search and LLM fallback orchestration lives here. |
| `batch/export_generator.py` | All batch JSON/CSV export generation lives here. Queries the primary `records` table by `batch_id`. No combined-blob storage. |

---

## 15. What Does NOT Exist

| Pattern | Why Banned |
|---|---|
| `@field_validator('*', mode='before')` wildcard | Severe performance penalty. |
| `model_construct()` as a fallback | Bypasses validation silently. |
| Deduplication inside extractors or per-source phases | Multi-pass deduplication. |
| Site-specific code branches in orchestration | Maintenance debt. |
| LLM raw record extraction from HTML without a field target | Primary hallucination mode. |
| A private browser pool outside `browser_client.py` | Split-brain browser state. |
| Re-fetching the page during re-extract | Re-extract is artifact-bound. Recrawl is a separate operation. |
| Publishing blank success shells | Bot walls, 404s are explicit failures. |
| Inline normalisation outside `field_normalizers.py` | Creates divergence. |
| Field truncation (except HTML tag stripping) | Data fidelity invariant. |
| Multiple `shape_records()` implementations | Exactly one. |
| Direct `curl-cffi` or `httpx` calls outside `http_client.py` | Split acquisition paths. |
| LLM calls when Smart Extraction is OFF | Deterministic mode must be purely deterministic. |
| Hardcoded model strings in pipeline code | Model is user-selected from UI. Provider config loaded from DB at runtime. |
| Parallel pipeline implementations for any feature | Exactly one pipeline. Features differ only in how domain memory is pre-loaded. |
| Combined-blob storage for batch results | Batch records are individual rows in `records` table with `batch_id` FK. Export generated on demand. |
| LLM Domain Memory writes without acquiring the Redis distributed lock | Violates the one-time rule under concurrency. |
| HTML passed to LLM without running through `llm/html_minifier.py` first | Wastes context window on SVGs, hidden elements. May truncate data-bearing content. |
| Additional field names that collide with canonical field names | Ambiguous write target. Rejected at submission with a 400 error. |
| LLM API keys returned in any API response | Keys are write-only. GET returns `api_key_set: true` + masked string only. |
| Accuracy metrics that exclude held records from the denominator | Produces inflated metrics that mask drift failures. |

---

## 16. API Endpoints *(updated in v7.0)*

### Single Crawl

| Method | Path | Description |
|---|---|---|
| POST | `/crawl` | Submit single URL. Body includes `url`, `surface`, `smart_extraction`, `advanced_rendering`, `cookies`, `proxy`, `additional_fields[]` |
| GET | `/crawl/{run_id}` | Get run result |
| DELETE | `/crawl/{run_id}` | Delete run + artifacts |
| POST | `/crawl/{run_id}/re-extract` | Re-run stages 2–5 on cached artifact |

### Batch Crawl *(updated in v7.0)*

| Method | Path | Description |
|---|---|---|
| POST | `/crawl/batch` | Submit batch. Body: `urls[]` or `csv_upload`, plus `smart_extraction`, `additional_fields[]`, `surface` |
| GET | `/crawl/batch/{batch_id}` | Get batch status + aggregate results |
| GET | `/crawl/batch/{batch_id}/records` | Get paginated individual records for this batch *(new)* |
| DELETE | `/crawl/batch/{batch_id}` | Delete batch run + all associated records + artifacts *(new in v7.0)* |
| POST | `/crawl/batch/{batch_id}/re-extract` | Re-run stages 2–5 on cached artifacts for all URLs in batch *(new in v7.0)* |
| GET | `/crawl/batch/{batch_id}/export/csv` | Download combined CSV (generated on demand by Export Generator) |
| GET | `/crawl/batch/{batch_id}/export/json` | Download combined JSON (generated on demand by Export Generator) |
| POST | `/crawl/{run_id}/batch-from-results` | Create batch from listing run results. Returns `batch_id` + `pre_population_id` for UI. |

### Selector Management

| Method | Path | Description |
|---|---|---|
| GET | `/crawl/{run_id}/selectors` | Get all selectors for this run (canonical + additional + domain memory) |
| POST | `/crawl/{run_id}/selectors/test` | Test a selector against cached artifact. Returns matched value. |
| PUT | `/domain/{domain}/selectors/{field}` | Save selector to domain memory |
| DELETE | `/domain/{domain}/selectors/{field}` | Remove selector from domain memory |

### Schema Registry

| Method | Path | Description |
|---|---|---|
| GET | `/registry/schemas` | List all canonical schemas by surface |
| GET | `/registry/schemas/{surface}` | Get canonical schema with version history |
| PUT | `/registry/schemas/{surface}` | Propose canonical schema update (requires user approval) |
| GET | `/registry/domains/{domain}/mapping` | Get domain mapping |
| PUT | `/registry/domains/{domain}/mapping` | Approve or override domain mapping |
| POST | `/registry/domains/{domain}/remap` | Trigger LLM re-mapping for drifted fields |
| GET | `/registry/drift` | List all active drift events (paginated) |
| POST | `/registry/drift/{drift_id}/resolve` | Resolve drift event (remap / override / discard) |

### Intelligence

| Method | Path | Description |
|---|---|---|
| GET | `/intelligence/llm-cost` | LLM cost log (paginated, filterable by provider/model/task_type) |
| GET | `/intelligence/accuracy` | Accuracy metrics per domain and globally |
| GET | `/intelligence/proxy-health` | Proxy pool status |

### Crawl Request Schema

```json
{
  "url": "https://example.com/products",
  "surface": "ecommerce_listing",
  "smart_extraction": true,
  "additional_fields": ["material_composition", "care_instructions"],
  "advanced_rendering": {
    "enabled": false, "mode": "auto", "max_pages": 10,
    "max_scrolls": 20, "scroll_pause_ms": 800,
    "load_more_clicks": 15, "timeout_seconds": 90
  },
  "cookies": { "mode": "jar", "raw_header": null },
  "proxy": { "use_proxy": true, "force_type": null },
  "max_records": null
}
```

---

## 17. File Structure

> **`schema_registry` location:** `schema_registry` is inside `app/services/` — not at root. This was corrected in v5.0 and remains so.

```
backend/
  app/
    main.py
    core/
      config.py
      database.py
      redis.py                             # Includes distributed lock utilities
    models/
      schemas.py
      record_schemas.py
      record_shaper.py
    api/
      crawl_routes.py
      batch_routes.py
      selector_routes.py
      admin_routes.py
      intelligence_routes.py
      registry_routes.py
    services/
      pipeline_service.py
      acquisition/
        artifact.py
        cache.py
        http_client.py
        browser_client.py
        acquirer.py                        # Includes SPA feedback loop logic
        advanced_renderer.py
        cookie_manager.py
      discover/
        discoverer.py
        additional_field_scanner.py
        types.py
      extract/
        service.py
        types.py
        shopify_adapter.py
        workday_adapter.py
        jsonld_extractor.py
        next_data_extractor.py
        api_interception.py
        css_extractor.py
        shadow_dom_extractor.py
        table_extractor.py
        llm_extractor.py
      unify/
        service.py
        identity_cluster.py
        field_selector.py
        types.py
      publish/
        service.py
        shape_records.py
        accuracy_calculator.py            # Held records always in denominator
      batch/
        service.py
        csv_uploader.py
        export_generator.py               # ← NEW (replaces result_store.py)
      normalization/
        field_normalizers.py
      deduplication/
        record_deduplicator.py
      schema_curation/
        service.py
        types.py
      schema_registry/
        store.py
        mapper.py
        validator.py
        drift_detector.py
        types.py
      domain_memory/
        store.py                          # Owns all Domain Memory R/W + Redis lock acquisition
      continuation/
        detector.py
        executor.py
      proxy/
        manager.py
        oss_provider.py
        third_party_provider.py           # [FINAL]
      enrichment/
        service.py
        llm_enricher.py
      llm/
        provider.py                       # LLMProvider interface + _parse_json_safe() post-processor
        groq_provider.py
        anthropic_provider.py
        openai_provider.py
        vision_provider.py                # [FINAL]
        config_store.py
        prompt_registry.py
        html_minifier.py                  # ← NEW: strips SVG/style/hidden elements before LLM prompts
      url_classification.py
      additional_fields/
        resolver.py
```

```
frontend/
  src/
    app/
      layout.tsx
      page.tsx
      crawl/page.tsx
      runs/page.tsx
      runs/[run_id]/page.tsx
      batch/[batch_id]/page.tsx
      admin/page.tsx
      admin/domains/[domain]/page.tsx
      admin/llm/page.tsx
      registry/page.tsx                   # [FINAL]
    components/
      crawl/
        CrawlForm.tsx
        BatchTab.tsx
        AdditionalFieldsInput.tsx         # Includes canonical collision inline validation
        AdvancedRenderingPanel.tsx
        CookiePanel.tsx
        ProxyPanel.tsx
      results/
        RecordsTable.tsx
        FieldEvidencePanel.tsx
        SchemaCurationPanel.tsx
        CssSelectorTab.tsx
        AccuracyBadge.tsx                 # Always shows n= sample size
        ExtendedFieldsPanel.tsx
        AdditionalFieldsPanel.tsx
        EnrichmentPanel.tsx
      batch/
        BatchResultsTable.tsx
        BatchUrlEditor.tsx                # Handles ≤500 (textarea) and >500 (virtualized) modes
        BatchAccuracySummary.tsx
      admin/
        LlmProviderConfig.tsx             # API key shown as masked; never actual key
      registry/
        CanonicalSchemaTable.tsx
        DomainMappingTable.tsx
        DriftAlertBanner.tsx
        MappingDetailPanel.tsx
        SchemaVersionHistory.tsx
      shared/
        StatusChip.tsx
        StatCard.tsx
        ModeBadge.tsx
        RunsTable.tsx
    api/client.ts
    api/types.ts
    store/crawlStore.ts
    store/schemaStore.ts
    store/batchStore.ts
```

```
tests/
  contracts/
    test_acquire_contract.py
    test_discover_contract.py
    test_extract_contract.py
    test_unify_contract.py
    test_publish_contract.py
    test_schema_curation_contract.py
    test_schema_registry_contract.py
    test_drift_detection_contract.py
    test_domain_mapping_contract.py
    test_admin_contract.py
    test_batch_contract.py
    test_additional_fields_contract.py
    test_selector_tab_contract.py
    test_llm_provider_contract.py
    test_domain_memory_lock_contract.py   # ← NEW
    test_spa_feedback_loop_contract.py    # ← NEW
    test_html_minifier_contract.py        # ← NEW
  accuracy/
    test_accuracy_metrics.py
    test_accuracy_during_drift.py         # Updated: verifies held records in denominator
    test_accuracy_sample_size.py
  fixtures/
    sample_pages/
```

---

## 18. UI Screens

### Screen 1 — Dashboard

- Headline stats: total records extracted, total runs, total batches, average accuracy scores.
- Domain leaderboard: top 10 domains by run count, with per-domain accuracy numbers.
- Recent runs + recent batches (last 10 each): URL/batch label, surface, status, record count, accuracy (n=), timestamp.
- Quick crawl input: URL field + submit → Crawl page with URL pre-filled in Single tab.

### Screen 2 — Crawl (Single + Batch tabs)

**Single Tab**

- Primary URL input. Surface auto-detection (editable).
- **Additional Fields input:** Comma-separated field names. Placeholder: `material_composition, care_instructions...`. Inline validation error shown if any name collides with a canonical field for the selected surface.
- Three collapsible sections: Smart Extraction (LLM toggle + estimated cost when ON); Advanced Browser Rendering; Advanced Options (cookies, proxy, rate limit).
- Submit → live progress view (ACQUIRE / DISCOVER / EXTRACT / UNIFY / PUBLISH with timing). On complete → Run Detail.

**Batch Tab**

> **Batch tab is part of the same Crawl page — not a separate route.** Navigating from 'Batch Crawl from Results' or 'Batch Crawl Similar Pages' lands here with the URL list pre-populated.

- URL input: large text area (one URL per line) + CSV upload button side by side.
- Live URL count displayed above the text area.
- URL editing: standard text area for ≤ 500 URLs — user selects any text block with mouse and presses Backspace or Delete. No checkbox interface.
- For > 500 URLs: virtualized preview list (first 20 rows visible) + summary count banner + optional "Edit List" modal. No massive textarea rendering.
- **Additional Fields input:** Same comma-separated input as Single tab. Applies to all URLs. Same canonical collision validation.
- Start Batch button → batch launches immediately. Progress shown as aggregate stats updating in real time (submitted / crawling / complete / failed counts).
- When pre-populated from results: notice shown — 'N URLs loaded from [source run]. Saved selectors for [domain] will be applied.'

### Screen 3 — Single Run Detail

**Layout**

- Top bar: three accuracy badges with `n=` indicator. Re-extract button. Export (JSON / CSV).
- Left panel: Records table (TanStack Table, virtual scroll, column visibility).
- Right side: three tabs — Schema Curation | CSS Selectors | Field Evidence

**CSS Selectors Tab**

- Table of all discovered selectors: field, source type, selector string, status, last validated, Test / Save / Delete actions.
- Test: runs selector against cached artifact, shows matched value inline. No network call.
- Save: persists to domain memory. Selector is active on all future runs for this domain.
- **Recrawl This Page:** Full 5-stage pipeline run on same URL. Fresh fetch — cache bypassed. Results merged. Fields whose selectors have been deleted are nulled out (see Section 8c).
- **Batch Crawl Similar Pages:** Navigates to Batch tab with domain pre-set and saved-selector notice.

**Schema Curation Tab**

- Sections A–D as defined in Section 7 (canonical, extended, additional fields, metadata).

**Field Evidence Tab**

- Published fields / Extended discovered / Dropped (with reason) / Missing / New.
- If any fields were deleted before Recrawl and had their values nulled out, they appear under 'Nulled — selector deleted'.
- Enrichment Panel: visible when coverage < 80%. Shows missing field list + LLM cost estimate + 'Attempt Enrichment' button.

### Screen 4 — Batch Result

- Header: batch label (auto-generated from domain + timestamp), total URLs, published count, held count, failed count.
- Three accuracy badges with `n=` sample size. **Held records are included in metric computations** — if a batch has drift, metrics will reflect the degraded state.
- URL summary table: each submitted URL with status (published / held / failed / blocked) and record count.
- Combined records table: all published records across all URLs in a single table. Held records shown in a separate "Held" tab with drift resolution actions.
- Export: single CSV and single JSON button. Downloads the combined dataset for published records in the batch.
- Drift alert: if held records exist, a banner shows affected URLs and resolution actions.

### Screen 5 — Run History

- Combined table: single-URL runs and batch runs in one view, with a Type column (single / batch).
- Filter: surface, status, type, date range, domain.
- Bulk actions: Delete Selected, Export All CSV.
- Each row → Run Detail (single) or Batch Result (batch).

### Screen 6 — Admin

- Tab 1 — LLM Configuration: See Screen 7.
- Tab 2 — Domain Memory: searchable table. Click domain → Domain Detail.
- Tab 3 — Proxy Pool: list management, health status, rotation stats.
- Tab 4 — Accuracy: global accuracy trend (30 days). Per-domain table.
- Tab 5 — Stats: total LLM cost by provider/model, total calls, total records, total runs, total batches.

### Screen 7 — LLM Configuration *(updated in v7.0)*

> **New screen:** Was a tab in Admin in v5.0, now a dedicated page due to multi-provider config complexity.

- **Provider selection:** Dropdown — Groq (default), Anthropic, OpenAI. Switching provider reloads the model list for that provider.
- **Model selection:** Dropdown of available models for the selected provider. Default: `llama-3.1-8b-instant` (Groq). No hardcoded model strings — model list loaded from provider config at runtime.
- **Task-to-model assignment:** User can assign different models per task type (`selector_discovery`, `field_mapping`, `enrichment`, `vision` [FINAL]).
- **API key input:** Per provider. **Write-only field** — the input accepts a new key but is never pre-filled with the existing key value. *(updated in v7.0)*
  - `GET /admin/llm-config` returns `"api_key_set": true` and `"api_key_masked": "sk-****"` for each provider. The actual encrypted or decrypted key is never returned in any API response.
  - The frontend renders the masked value as a placeholder and shows a 'Key saved ✓' badge when `api_key_set` is true.
  - Keys are never written to logs at any level.
- **Per-domain LLM budget:** Max cost in USD per domain per day. Alert sent when 80% consumed.
- **Global session budget:** Hard cap in USD. LLM calls are rejected (not queued) once cap is hit.
- **Cost summary:** Live running total by provider and model, last 30 days.

### Screen 8 — Schema Registry [FINAL]

- Left sidebar: surface selector. Current canonical schema version badge.
- Centre panel: canonical schema table — display name, type, required/optional, 30-day coverage %.
- Right panel: domain mapping health table — mapping version, status, last run, field coverage, unmapped count.
- Drift Alert Banner: sticky banner when active drift events exist.
- Extraction Health Chart: per-field coverage trend, 30 days.
- Domain Mapping Detail: raw field → canonical field mappings, unmapped fields, drift history, approve/override/remap, mapping version history with rollback.

### Screen 9 — Domain Detail (Admin)

- Cookie jar viewer + editor.
- Schema preferences editor.
- Selector table: all saved selectors for this domain, with test/save/delete. Same interface as CSS Selector tab.
- Continuation recipe viewer + manual selector editor.
- Run history for this domain.
- Delete domain memory button.

---

## 19. Phase Summary

### Phase 1 — POC

| Area | What Ships |
|---|---|
| Pipeline | Full 5-stage ACQUIRE→DISCOVER→EXTRACT→UNIFY→PUBLISH. Single pipeline for all features. SPA feedback loop (Stage 1 upgrade on 0% coverage). |
| Surfaces | Commerce Listing, Commerce Detail, Job Listing, Job Detail, Tabular Data |
| Batch crawl | CSV upload + paste input. One-click batch from listing results (virtualized preview for >500 URLs). Combined JSON/CSV export generated on demand. Individual records stored per URL with `batch_id` FK. |
| Additional fields | Comma-separated input. Canonical collision guard at submission. Deterministic search first, LLM fallback (Smart Extraction ON). Selectors always shown and saved. |
| CSS Selector tab | On single-run results only. Shows all discovered selectors. Test, save, delete. Ghost data nulling on recrawl of deleted selectors. Recrawl this page. Batch crawl similar pages. |
| Acquisition | curl-cffi + Stealth Playwright (always saves full rendered HTML) + httpx fallback |
| Advanced rendering | Toggle + mode selector + all controls |
| Cookie management | All three modes |
| Schema curation | Hybrid: canonical + extended_fields + additional fields. Curation panel on single-run only. |
| Enrichment | Artifact-based enrichment for hidden fields. HTML minified before LLM. User-initiated, cost-shown, Smart Extraction required. |
| Accuracy metrics | All three metrics. Pure math on real data. Zero LLM. Held records always in denominator. n= sample size always shown. |
| Domain memory | Full: sources, selectors (canonical + additional), continuation, schema preferences, cookies. Redis distributed lock on all LLM-write operations. |
| LLM | Multi-provider abstraction. Default: Llama via Groq. User-selectable provider + model per task type. No hardcoded model strings. JSON output safety cleaner in provider layer. |
| Proxy | OSS rotating proxy with health check |
| Schema Registry | Internal contract engine: versioned mappings, drift detection, partial-publish gate, drift resolution |
| Tech stack | FastAPI, Next.js, PostgreSQL, Redis, Playwright, curl-cffi, Groq/Llama default |

### Phase 2 — Final Product

| Area | What Ships |
|---|---|
| Vision model | Screenshot-based extraction as last-resort fallback when HTML coverage < threshold. Vision-capable model selected by user. Gated by Vision Extraction toggle. |
| Schema builder | Full schema builder: rename, reorder, type-cast, computed fields, named schemas, versioning |
| Enrichment (batch) | Batch enrichment — trigger enrichment pass across all records in a batch below a coverage threshold |
| Proxy | Bright Data / Oxylabs as drop-in behind proxy interface |
| Storage | S3-compatible artifact storage (MinIO) |
| Infrastructure | Docker Compose → Kubernetes-ready |
| Self-healing | LLM heals broken selectors automatically on detection |
| Platform memory | Recipe promotion from domain-level to platform-level after 3+ domain successes |
| SaaS path | Next.js SSR, multi-user auth, team workspaces |
| Schema Registry UI | Screen 8: canonical schema browser, domain mapping health, drift alert banner, extraction health chart, schema version history with rollback |

---

## 20. User Collaboration Model

| User Action | Effect |
|---|---|
| Paste URLs or upload CSV | Batch tab pre-populated with URL list |
| Click 'Batch Crawl from Results' | Navigates to Batch tab with extracted detail URLs pre-filled (virtualized for >500) |
| Enter additional fields before crawl | Collision guard runs at submission. System searches deterministically then falls back to LLM. Selectors saved. |
| Inspect CSS Selector tab | See every selector found, by source. Test live on cached artifact. |
| Save a selector | Persisted to domain memory. Applied on all future runs for this domain. |
| Delete a selector, then Recrawl | Fields produced by the deleted selector are nulled out. Re-extracted from scratch. |
| Click 'Recrawl This Page' | Full pipeline re-run on same URL. Fresh fetch. Results merged. |
| Click 'Batch Crawl Similar Pages' | Navigates to Batch tab with domain pre-set and saved selectors active. |
| Include/exclude fields from output | Saved to domain schema preferences |
| Trigger enrichment pass | LLM re-runs against minified cached artifact for missing fields. Cost shown first. |
| View accuracy metrics | Three-number summary with n= always visible. Held records always in denominator. |
| Change LLM provider or model | Applied immediately to all future LLM calls. No code change required. |
| Configure API key | Submitted write-only. GET returns `api_key_set: true` + masked value only. |

---

## Appendix A — Glossary

| Term | Definition |
|---|---|
| Acquisition Artifact | Frozen dataclass output of Stage 1. Always contains the full rendered HTML (from Playwright for JS pages) + screenshot path + network payloads + cache key. May include `acquisition_upgrade_reason` if Stage 1 was re-entered due to SPA empty-shell detection. |
| Additional Fields | User-specified comma-separated field names entered before a crawl. Validated against canonical schema at submission (collision rejection). Searched deterministically first, LLM fallback if Smart Extraction ON. |
| Batch Run | A crawl of multiple URLs submitted together. Results stored as **individual rows** in the primary `records` table, each with a `batch_id` FK. Combined JSON/CSV generated on demand by the Export Generator. |
| Canonical Schema | The user-approved, surface-scoped master output contract. Never modified without explicit user approval. |
| Canonical Schema Version | Monotonically incrementing identifier for a locked canonical schema snapshot. |
| CSS Selector Tab | Tab on the single-URL run detail page showing all discovered selectors. Not available in batch result views in POC phase. |
| Distributed Lock | Redis-backed lock scoped to `domain_memory_lock:{domain}:{task_type}:{field}`. Acquired before any Domain Memory LLM-write operation to prevent concurrent stampede. |
| Domain Mapping | System-maintained translation layer between a domain's raw field names and canonical schema fields. LLM-proposed, user-approved, per-domain. |
| Domain Memory | Compound learned knowledge about a specific domain: sources, selectors (canonical + additional), continuation, schema preferences, cookies, proxy, accuracy. |
| Drift Event | A recorded instance of version drift, identified by a `drift_id`. Resolved independently via remap, override, or discard. |
| Enrichment Pass | User-initiated re-extraction from the cached rendered HTML artifact targeting specific missing fields. HTML is minified before LLM prompt assembly. No new network call. |
| Export Generator | `batch/export_generator.py`. Generates combined JSON/CSV for a batch by querying the primary `records` table WHERE `batch_id = ?`. Not a storage mechanism. |
| Field Coverage Efficiency | Accuracy metric: average % of canonical fields populated across **all** records (published + held). Held records always included in denominator. |
| Data Fidelity Score | Accuracy metric: % of populated fields that passed Pydantic validation without normaliser coercion. |
| HTML Minifier | `llm/html_minifier.py`. Strips `<svg>`, `<style>`, non-data `<script>`, `<img>` (keeps `alt`/`src`), hidden elements, and HTML comments from HTML before any LLM prompt. |
| LLM Provider | Abstraction behind `llm/provider.py`. Supported: Groq (default, Llama models), Anthropic, OpenAI. Includes mandatory `_parse_json_safe()` JSON output cleaner. |
| Mapping Version | Per-domain incrementing version of the domain mapping. Incremented on every approved re-mapping or override. |
| One-Time LLM Rule | If the LLM ran successfully on a domain for a given task type, it never runs again for that task on that domain. Enforced by the distributed lock under concurrency. |
| Partial-Publish Policy | Clean records published immediately. Drifted records held pending user resolution. Drift on some records never blocks clean records. Single source of truth. |
| Pre-population ID | Server-side reference token for a large URL list (>500). Batch tab uses this token to submit the list without rendering it entirely in the browser DOM. |
| Proposed Mapping | LLM-generated domain mapping not yet approved by user. Not applied to any records until approved. |
| Recrawl This Page | Full 5-stage pipeline re-run on the same single URL with a fresh network fetch. Cache bypassed for Stage 1. Fields whose selectors were deleted are nulled out. Distinct from Re-extract. |
| Re-extract | Re-run Stages 2–5 on the cached artifact. No network call. Available for both single runs and batch runs. |
| Schema Registry | Versioned contract store for canonical schemas and domain mappings. Validates output before publish and detects version drift. |
| Schema Unmapped | Run state when a domain has no approved domain mapping and Smart Extraction is OFF. Run completes but no registry validation is applied. |
| Selector-Driven Batch Crawl | Batch crawl where domain memory already contains validated selectors. Full pipeline runs — Stage 3 applies saved selectors without LLM discovery. |
| Site Crawl Efficiency | Accuracy metric: (URLs with ≥1 published record) ÷ (total submitted URLs). Pure DB count. |
| Smart Extraction | User-facing toggle that gates all LLM usage. When OFF, pipeline is purely deterministic. |
| SPA Feedback Loop | If `curl-cffi` acquisition yields 0% canonical field coverage, Stage 1 is re-entered with forced Playwright render. Fires at most once per URL per run. |
| Version Drift | When extracted data from a domain no longer conforms to the previously approved schema version. |
| Vision Extraction [FINAL] | Last-resort extraction using a screenshot of the rendered page passed to a vision-capable model. Gated by Vision Extraction toggle. |

---

## Appendix B — LLM Integration & Prompts

> **Purpose:** This appendix is the single source of truth for all LLM-related implementation decisions. Keeping this separate from the pipeline spec ensures the system remains modular — swapping providers or tuning prompts requires no pipeline changes.

### B1. Provider Abstraction Architecture *(updated in v7.0)*

All LLM SDK calls are routed through a single interface defined in `llm/provider.py`. No pipeline module calls a provider SDK directly.

```python
# llm/provider.py — the ONLY entry point for LLM calls

class LLMProvider(ABC):

    @abstractmethod
    async def complete(self, task_type: str, prompt: str, context: dict) -> LLMResult:
        ...

    def _parse_json_safe(self, raw: str) -> dict:
        """
        Mandatory post-processor. Called by every concrete provider's complete()
        before returning LLMResult. Never raises JSONDecodeError to the caller.

        Steps:
        1. Strip leading/trailing whitespace.
        2. If content starts with a markdown code fence (```json or ```), extract
           only the content between the first ``` and the last ```.
        3. If content contains leading prose before the first '{' or '[', strip
           everything before the first occurrence of '{' or '['.
        4. Attempt json.loads(). On success, return the parsed dict/list.
        5. On JSONDecodeError: log the raw string at DEBUG level and return
           {"_parse_error": true, "raw": raw[:500]}.
        The caller (pipeline task) treats _parse_error: true as an LLM miss —
        the same as a null result — and proceeds without crashing.
        """
        ...

@dataclass
class LLMResult:
    content: str
    parsed: dict | list | None          # Output of _parse_json_safe()
    input_tokens: int
    output_tokens: int
    cost_usd: float
    provider: str
    model: str
    task_type: str
    domain: str
    parse_error: bool = False           # True if _parse_json_safe() fell back
```

#### API Key Security *(new in v7.0)*

- API keys are stored encrypted at rest in the `llm_config` table.
- `GET /admin/llm-config` returns `api_key_set: true` (bool) and `api_key_masked: "sk-****"` (last 4 chars visible, rest masked). The actual key — encrypted or decrypted — is **never** included in any API response.
- The frontend renders the masked value as a non-editable placeholder. A 'Key saved ✓' badge is shown when `api_key_set` is `true`. The user submits a new key via a write-only input field.
- Keys are never written to logs at any level.

#### Supported Providers

| Provider | Module | Default Model | Notes |
|---|---|---|---|
| Groq | `groq_provider.py` | `llama-3.1-8b-instant` | Default for all POC task types. Best cost/performance for selector discovery and field mapping. |
| Anthropic | `anthropic_provider.py` | `claude-sonnet-4-20250514` | Available as user-selectable option. |
| OpenAI | `openai_provider.py` | `gpt-4o-mini` | Available as user-selectable option. |
| Vision [FINAL] | `vision_provider.py` | User-selectable vision-capable model | Activated only for `vision_extraction` task type. Screenshot passed as image input. |

#### Provider Config Storage

Provider and model selection is persisted to the database, not to environment variables or code. At runtime, `llm/config_store.py` loads the current provider config for each task type. Changing a model in the UI takes effect on the next LLM call — no restart required.

```json
{
  "task_type": "selector_discovery",
  "provider": "groq",
  "model": "llama-3.1-8b-instant",
  "api_key_encrypted": "...",
  "per_domain_daily_budget_usd": 0.50,
  "global_session_budget_usd": 10.00
}
```

### B2. HTML Minification Before LLM Calls *(new in v7.0)*

> **Problem:** Fully JS-rendered Playwright DOMs (especially e-commerce or job boards with embedded SVGs, base64 images, and `__NEXT_DATA__` blobs) frequently exceed 300k–500k characters. Truncating naively at a token limit removes the bottom portion of the page — where the fields most likely to need enrichment (reviews, extended specs) actually live.

**Rule:** All HTML passed to any LLM prompt — for any task type — must be processed by `llm/html_minifier.py` before prompt assembly. No exceptions.

```python
def minify_for_llm(html: str, keep_data_scripts: bool = True) -> str:
    """
    Strips:
    - All <svg>...</svg> blocks (including inline SVGs)
    - All <style>...</style> blocks
    - All <script> blocks UNLESS keep_data_scripts=True AND the script has
      type="application/ld+json" or id="__NEXT_DATA__" (data-bearing scripts kept)
    - All <img> tags: replaced with <img alt="{alt}" src="{src}"> (no other attrs)
    - All elements with display:none or visibility:hidden inline styles
    - All elements with aria-hidden="true"
    - All HTML comments (<!-- ... -->)
    - Runs of 3+ consecutive blank lines collapsed to 1

    Does NOT strip:
    - <meta> tags (may contain structured data)
    - data- attributes (used by selectors)
    - JSON-LD script blocks
    - __NEXT_DATA__ script blocks
    - Any text content
    """
```

**Token budget after minification:**

| Task Type | Post-minification truncation limit |
|---|---|
| `selector_discovery` | 50,000 chars (pre-filtered to relevant DOM section first) |
| `source_identification` | 30,000 chars |
| `additional_field_discovery` | 50,000 chars |
| `enrichment` | 200,000 chars (raised from v6.0's 100k; minification makes this realistic) |
| All others | 50,000 chars |

### B3. Task Types & Prompt Structure

> **Prompt templates:** Prompt templates live exclusively in `llm/prompt_registry.py`. No prompt strings exist in any other module. The structure below is authoritative — the exact wording is tuned during development.

#### Task Type 1 — selector_discovery

| Attribute | Specification |
|---|---|
| Purpose | Discover a CSS or XPath selector for a named field from rendered HTML |
| Input | Field name, field aliases, minified rendered HTML (truncated to 50k chars from relevant DOM section) |
| Output format | JSON: `{ 'selector': 'string', 'selector_type': 'css\|xpath', 'confidence': 0.0-1.0, 'sample_value': 'string' }` |
| Model (default) | `llama-3.1-8b-instant` via Groq |
| One-time rule | Result saved to domain memory. Not called again for same field+domain. |
| Banned inputs | Do not pass the entire raw HTML of a full page — always pre-filter to the relevant DOM section first, then minify. |

#### Task Type 2 — selector_healing

| Attribute | Specification |
|---|---|
| Purpose | Repair a saved selector that now returns 0 results |
| Input | Field name, broken selector, minified rendered HTML (pre-filtered), last known value |
| Output format | JSON: `{ 'selector': 'string', 'selector_type': 'css\|xpath', 'confidence': 0.0-1.0 }` |
| Trigger | Selector returns 0 results on 1 run (heal immediately, do not wait for 3 failures) |
| Post-action | Healed selector replaces broken selector in domain memory |

#### Task Type 3 — field_mapping

| Attribute | Specification |
|---|---|
| Purpose | Map a novel raw field name to a canonical schema field |
| Input | Raw field name, sample values (first 5), list of canonical field names + descriptions |
| Output format | JSON: `{ 'canonical_field': 'string \| null', 'confidence': 0.0-1.0, 'reasoning': 'string' }` |
| null output | If no canonical field matches, return null — do not force a mapping |
| Post-action | Mapping saved to domain memory `field_mappings` table |

#### Task Type 4 — source_identification

| Attribute | Specification |
|---|---|
| Purpose | Identify the JSON path to a specific data type inside a complex `__NEXT_DATA__` or API payload |
| Input | Target surface type, JSON payload (truncated to 30k chars) |
| Output format | JSON: `{ 'json_path': 'string', 'record_count_hint': int, 'confidence': 0.0-1.0 }` |
| Post-action | JSON path saved to domain memory `sources.next_data.extraction_recipe` |

#### Task Type 5 — additional_field_discovery

| Attribute | Specification |
|---|---|
| Purpose | Discover a selector for a user-specified additional field when deterministic search failed |
| Input | Field name (user-entered), field aliases generated from name, relevant DOM section (minified) |
| Output format | JSON: `{ 'selector': 'string', 'selector_type': 'css\|xpath', 'confidence': 0.0-1.0, 'sample_value': 'string' }` |
| Deterministic first | This task type is only invoked after the deterministic CSS/XPath pattern search in `additional_field_scanner.py` has failed |
| Post-action | Selector saved to domain memory selectors dict with `source: 'llm_discovered'` |

#### Task Type 6 — domain_mapping_proposal

| Attribute | Specification |
|---|---|
| Purpose | Propose a complete domain mapping (raw field → canonical field) for a new domain |
| Input | List of raw field names + sample values from extracted candidates, list of canonical fields + descriptions |
| Output format | JSON: `{ 'mappings': { 'raw_field': 'canonical_field' }, 'unmapped': ['raw_field'], 'confidence_per_field': {} }` |
| Post-action | Stored as proposed mapping. NOT applied until user approves in Schema Registry UI. |
| Smart Extraction gate | Only invoked when Smart Extraction is ON |

#### Task Type 7 — enrichment *(updated in v7.0)*

| Attribute | Specification |
|---|---|
| Purpose | Extract values for specific missing fields from a cached rendered HTML artifact |
| Input | List of missing field names, **minified** rendered HTML artifact (up to 200k chars post-minification) |
| Output format | JSON: `{ 'fields': { 'field_name': { 'value': 'any', 'selector': 'string\|null', 'confidence': 0.0-1.0 } } }` |
| User-initiated only | Never called automatically. User must click 'Attempt Enrichment'. Cost shown before execution. |
| Coverage target | Use this task type when canonical field coverage is < 80% after standard pipeline completes |
| HTML pre-processing | `html_minifier.py` MUST be called before prompt assembly. Raw HTML is never passed directly. |
| Post-action | Values merged into `extended_fields` with `_enriched_by: 'llm_enrichment'` tag. Selectors saved to domain memory if found. |

#### Task Type 8 — vision_extraction [FINAL]

| Attribute | Specification |
|---|---|
| Purpose | Extract field values from a rendered screenshot when HTML extraction coverage is below threshold |
| Input | Screenshot image (from Stage 1 artifact), list of target fields, surface type |
| Output format | JSON: `{ 'fields': { 'field_name': { 'value': 'any', 'bounding_box': null, 'confidence': 0.0-1.0 } } }` |
| Trigger | HTML coverage < configurable threshold (default: 50%) after all DOM-based methods exhausted |
| Phase | FINAL only. Not part of POC. |
| Gating | Requires Vision Extraction toggle ON + Smart Extraction toggle ON |
| Provider | User selects a vision-capable model. Groq does not support vision — Anthropic `claude-opus-4-6` or OpenAI `gpt-4o` recommended. |

### B4. Prompt Engineering Rules

- All prompts must specify output format (always JSON) and include an explicit instruction to return `null` or an empty object rather than guessing when confidence is low.
- No prompt asks the LLM to 'extract all fields from this page' — every call targets a specific field or task. Untargeted extraction is banned (hallucination risk).
- HTML passed to any prompt must be pre-filtered to the relevant DOM section by the calling module, and then passed through `html_minifier.py`, before the prompt is assembled. Full-page raw HTML is never passed to any prompt.
- All prompts include a 'do not invent values' instruction. If the field is not present, the model must return `null` for that field.
- Prompt templates are versioned in `prompt_registry.py`. Changing a template increments its version. The version is logged in `llm_cost_log` alongside each call for debugging and rollback.
- LLM output is always processed through `_parse_json_safe()` in the provider layer before any pipeline module accesses it. No pipeline module calls `json.loads()` directly on LLM output.

### B5. Cost Control

| Control | Behaviour |
|---|---|
| Per-domain daily budget | Configurable per domain. LLM calls for a domain are rejected (not queued) once the daily budget is hit. User notified. |
| Global session budget | Hard cap in USD. All LLM calls rejected once hit. Requires manual reset. |
| Cost preview | For user-initiated operations (enrichment, domain re-mapping), cost estimate is shown before execution. User must confirm. |
| One-time rule | The primary cost control: once a selector/mapping is saved, that task never runs again for the same domain. Enforced under concurrency by the Redis distributed lock. |
| Cost log | Every call logged to `llm_cost_log` with `provider`, `model`, `task_type`, `tokens`, `cost_usd`, `domain`, `timestamp`. |

---

*End of Document — Version 7.0*

*Phase 1 (POC) and Phase 2 (Final Product) are both specced here so Phase 1 makes no architectural decisions that close off Phase 2.*