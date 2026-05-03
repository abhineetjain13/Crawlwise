# Business Logic

> This is the product-behavior map for CrawlerAI.
> Read this after `docs/CODEBASE_MAP.md` and before changing shared runtime or extraction logic.
> If you change one of the rules below, you are changing user-visible behavior.

---

## 1. Purpose

`CODEBASE_MAP.md` answers "where does this live?"

This file answers:

- what decisions the system makes
- which file owns each decision
- what the current rule is
- what kind of bad output appears when the rule is wrong

This is intentionally about behavior, not implementation detail.

---

## 2. Global Rules

| Decision | Owner | Current Rule | If Wrong |
|---|---|---|---|
| Surface is user-owned | `crawl_crud.py`, `pipeline/core.py` | User-selected `surface` is authoritative; heuristics may assist extraction but must not silently rewrite the run | Listing/detail paths blur together and false positives spike |
| Acceptance harness respects explicit surface and quality truth | `harness_support.py`, `run_test_sites_acceptance.py` | Explicit acceptance surfaces stay authoritative; curated commerce acceptance now reuses artifact-backed runs when requested, computes `quality_verdict`/`observed_failure_mode`/`quality_checks`, treats verdict-only `success` as insufficient, rejects same-site wrong-product detail swaps via slug/title identity checks, and requires the first listing sample window to contain at least one real title/url/price row before it can count as clean output | Audits misclassify the same URL, stale artifacts get rerun unnecessarily, stale detail URLs drift onto the wrong product, and false-success output hides missing variants, shell pages, and chrome pollution |
| Extraction bugs are fixed upstream | extraction owners, not `publish/*` | Bad records must be prevented in acquisition/extraction; persistence/verdict code must not compensate for them | Same bug reappears under new sites with more downstream clutter |
| Generic code stays generic | `acquisition/*`, `listing_extractor.py`, `detail_extractor.py` | Site behavior belongs in adapters/config only when it is truly platform-specific | Shared runtime turns into a pile of per-site branches |
| LLM is optional | `llm_runtime.py`, `crawl_crud.py` | LLM flows only run when enabled by run settings and active config | Silent behavior drift and non-deterministic extraction |
| Data enrichment is separate from crawl output | `api/data_enrichment.py`, `data_enrichment/service.py`, `models/crawl.py` | Enrichment reads successful ecommerce detail records, writes derived rows to `enriched_products`, and only updates `crawl_records.enrichment_status` / `enriched_at` on source records | Raw crawl data and derived semantic fields become mixed, making recrawl and re-enrichment lifecycles ambiguous |

---

## 3. Run Creation And Orchestration

| Decision | Owner | Current Rule | If Wrong |
|---|---|---|---|
| Requested fields are preserved raw | `crawl_crud.py`, `field_policy.py`, `pipeline/core.py` | Raw user-entered `requested_fields` / `additional_fields` are stored on the run; normalization happens later where matching logic needs it | Exact section labels such as `Features & Benefits` disappear before extraction sees them |
| Run snapshots freeze runtime config | `crawl_crud.py`, `llm_config_service.py`, `run_config_snapshot.py` | LLM config and extraction runtime settings are stamped onto the run at creation time | Mid-run config drift changes outcomes for the same run |
| Single-URL run creation resolves saved execution defaults before snapshotting | `crawl_crud.py`, `domain_run_profile_service.py`, `models/crawl_settings.py` | For single-URL runs only, resolved settings are `UI defaults -> saved DomainRunProfile -> explicit form edits -> backend normalization/snapshot`; bulk/batch/CSV do not auto-load saved domain profiles | Repeat runs ignore saved domain defaults, or batch-style jobs silently inherit single-URL domain tuning |
| Per-URL pipeline order is fixed | `pipeline/core.py` | Acquire -> extract -> normalize -> persist | Debugging becomes impossible because downstream code mutates upstream semantics |
| Data enrichment runs on demand | `api/data_enrichment.py`, `data_enrichment/service.py` | Users create enrichment jobs from selected ecommerce detail records or a detail run; foundation creates pending enriched rows and skips records already `enriched` or `degraded` | Main crawl starts doing hidden enrichment work, or already-processed records are duplicated |
| Listing zero-record outcome | `publish/verdict.py`, `pipeline/core.py` | Listing pages with zero records become `listing_detection_failed`, not a fake detail success | Listing failures get counted as success or empty detail pages |
| Log label for non-adapter extraction | `pipeline/core.py` | When no adapter matches, logs must say `generic extraction path`, not pretend a `generic adapter` exists | Operators waste time debugging adapter selection when no adapter ran |

---

## 4. Acquisition Decisions

### 4.1 Fetch Method

| Decision | Owner | Current Rule | If Wrong |
|---|---|---|---|
| HTTP vs browser escalation | `crawl_fetch_runtime.py`, `acquisition/acquirer.py` | Browser escalation is driven by runtime policy plus observed block/shell evidence, not by hardcoded site names in generic paths | Sites appear "hardcoded" because generic runtime starts behaving site-specifically |
| User-owned fetch mode is authoritative | `crawl_fetch_runtime.py`, `acquisition/acquirer.py`, `models/crawl_settings.py` | `fetch_profile.fetch_mode` is the canonical execution choice: `http_only`, `browser_only`, `http_then_browser`, and `auto` each shape acquisition directly; this replaces the older flat `force_browser` idea | Crawl Studio shows one fetch choice while runtime executes another |
| Learned acquisition contract | `domain_run_profile_service.py`, `pipeline/core.py`, `crawl_fetch_runtime.py` | A successful acquisition/extraction/persist path may autosave an editable `DomainRunProfile.acquisition_contract` scoped by `(domain, surface)`. Future runs reuse the proven engine, safe curl-cookie handoff, and learned selector path unless explicit run settings override it, learned memory is reset, or repeated acquisition-quality failures mark the contract stale. Listing/extraction misses do not stale acquisition by themselves | Sites that already succeeded regress to Patchright/http, or stale contracts keep forcing a path after the site changed |
| Ecommerce detail field contract | `field_policy.py`, `selector_self_heal.py`, `direct_record_fallback.py`, `extraction_retry_decision.py` | The repair truth is user-requested fields plus limited canonical defaults. For ecommerce detail, default canonical repair/browser/LLM targets are `price`, `title`, and `image_url`; deeper fields such as `brand`, `sku`, and `variants` are attempted when explicitly requested | Setup crawls waste time forcing optional fields, or future crawls miss user-requested fields because only defaults were learned |
| Traversal is separate from render escalation | `crawl_fetch_runtime.py`, `acquisition/traversal.py`, `models/crawl_settings.py`, `frontend/components/crawl/crawl-config-screen.tsx` | The system may escalate to browser automatically, but traversal/pagination only runs when the run settings allow it. Quick/default runs leave traversal disabled; traversal only activates from an explicit advanced traversal choice or another explicit settings payload. | Browser use accidentally expands crawl scope |
| Robots handling | `robots_policy.py`, `pipeline/runtime_helpers.py` | robots.txt is enforced only when enabled; logs must state whether it was honored or ignored | Operators cannot trust the crawl mode they selected |
| Acquisition timeout budget split | `crawl_fetch_runtime.py`, `config/runtime_settings.py` | HTTP attempts are capped at `http_timeout_seconds` (10s); the remaining `acquisition_attempt_timeout_seconds` (90s) budget is reserved for browser fallback. Browser-first or `browser_only` mode skips HTTP and uses the full budget. | HTTP hangs on bot-defended sites (e.g., BestBuy) consume the entire budget, leaving no time for browser fallback; URLs timeout at 105s despite working under forced browser |

### 4.2 Browser Readiness

| Decision | Owner | Current Rule | If Wrong |
|---|---|---|---|
| Listing readiness requires listing evidence | `acquisition/browser_readiness.py` | Listing pages do not become ready from shell text alone; actual listing evidence is required | JS-heavy listings persist 1 shell/menu row instead of real products |
| Structured data is weak evidence for listings | `acquisition/browser_page_flow.py` | On listing surfaces, generic structured data does not justify skipping the extra wait/readiness path when card evidence is missing | SPA listings fast-path too early and extract half-hydrated shells |
| Detail expansion must not navigate away | `acquisition/browser_detail.py`, `browser_runtime.py` | Detail expansion may click bounded in-page expanders, but plain navigation anchors like `careers` / `about us` / `returns` must be skipped | Browser acquisition lands on random utility pages and the run looks “hardcoded” or polluted |
| Browser diagnostics are mandatory on browser attempts | `crawl_fetch_runtime.py`, `acquisition/browser_page_flow.py` | Browser attempts must emit meaningful diagnostics, including stop reason/outcome and bounded rendered/visual artifact-capture timings | Runtime failures look like `{}` or hang inside opaque browser-side capture steps and cannot be debugged |
| Block detection preserves usable content | `crawl_fetch_runtime.py`, `browser_page_flow.py` | Vendor markers alone do not override clearly extractable listing/detail content | Recoverable pages get classified as blocked and never reach extraction |

---

## 5. Listing Extraction Decisions

### 5.1 Candidate Sources

| Decision | Owner | Current Rule | If Wrong |
|---|---|---|---|
| Listing and detail stay separate | `crawl_engine.py`, `listing_extractor.py` | Listing extraction never falls back into synthetic single-record detail behavior | Category pages persist one bogus row and look "successful" |
| Standalone structured product metadata is not a listing row | `listing_extractor.py`, `structured_sources.py` | Listing extraction only accepts standalone typed `Product` / `JobPosting` payloads when the source exposes real listing evidence such as an `ItemList` or multiple typed items; single page-level metadata blobs are ignored | Brand/category pages leak one polluted first row with page-level brand/description/rating data attached to a product URL |
| Candidate-set ranking | `listing_extractor.py`, `extract/listing_candidate_ranking.py` | Structured, DOM, and rendered candidate sets are ranked by record quality; the best set wins | Weak structured rows or chrome tiles out-rank real product cards |
| Rendered visual fallback is last resort | `listing_extractor.py`, `extract/listing_visual.py` | Visual artifacts are only used after non-visual candidate sets fail | Bounding-box noise becomes user-facing records |

### 5.2 DOM Selection

| Decision | Owner | Current Rule | If Wrong |
|---|---|---|---|
| Listing-card counting fallback | `acquisition/traversal.py` | If configured selectors miss, shared card heuristics still count the grid | New sites repeat the same `listing_card_count=0` failure class |
| Cleaned DOM vs original DOM | `listing_extractor.py`, `extraction_context.py` | Cleaned DOM is preferred, but listing extraction may retry the original DOM when noise removal strips detail-link evidence from cards | Pages like IndiaMART collapse to a few taxonomy/spec fragments while real product rows are present in raw HTML |
| Same-site cross-subdomain detail links | `listing_extractor.py`, `field_value_core.py` | Listing anchors may target the same registrable site even when the hostname differs (`dir.example.com` -> `www.example.com`) | Real detail links are discarded as "external" |
| Detail-path recognition | `surface_hints.py`, `listing_extractor.py`, `field_value_core.py` | Generic ecommerce detail-path hints include common product routes such as `/product`, `/products/`, `/dp/`, and `/proddetail/` | Valid product links are treated as structural/category links and lose ranking/support |
| Job listing hubs are not job rows | `listing_extractor.py` | Job listing extraction must reject search/city hub links such as `jobs in Bangalore` and cross-surface academy/product links, while still treating numeric terminal job slugs as detail-like postings during candidate ranking | Sites like Instahyre emit city links, academy links, or other hub noise instead of actual jobs, or valid boards like Startup.jobs drop every row after ranking |
| Chrome/title noise filtering | `listing_extractor.py` | Listing titles must reject menu labels, promo copy, rating-only text, and numeric-only fragments | Utility rails and SEO clouds persist as products |

### 5.3 Requested Listing Fields

| Decision | Owner | Current Rule | If Wrong |
|---|---|---|---|
| Listing field scope stays narrow | `field_policy.py`, `config/field_mappings.py`, `listing_extractor.py` | Listing output is limited to high-signal user-facing fields; low-value gallery spillover stays out | Listing rows become bloated and unstable across sites |

---

## 6. Detail Extraction Decisions

| Decision | Owner | Current Rule | If Wrong |
|---|---|---|---|
| Source priority | `detail_extractor.py`, `structured_sources.py`, `js_state_mapper.py`, `network_payload_mapper.py` | Structured and authoritative signals outrank weaker DOM text, but DOM stays available when higher tiers are thin or noisy | Thin metadata wins over the actual page, or noisy DOM overrides better structured data |
| Requested section labels are exact-first | `detail_extractor.py`, `field_policy.py`, `field_value_dom.py` | Exact requested labels are checked before broader alias collapse | User-requested fields vanish behind over-normalization |
| Common accordion labels resolve upstream | `field_value_dom.py`, `config/field_mappings.py`, `detail_extractor.py` | Anchor/hash-driven accordion headers such as `Product Description` and `Product Details` must bind to their own panel bodies and map to canonical fields before weaker metadata wins | Long-form PDP content gets trapped in markdown, mapped onto the wrong field, or replaced by a one-line OG/JSON-LD blurb |
| Detail expansion is field-aware | `acquisition/browser_detail.py`, `browser_page_flow.py` | Expansion clicks are bounded and only run when the requested/valuable content is not already extractable | Pages mutate unnecessarily and extraction quality drops |
| Variant recovery is quality-gated | `detail_extractor.py`, `extract/shared_variant_logic.py` | Weak existing variant data does not block stronger DOM/JS recovery, but noisy axes/values are rejected | Variant fields disappear or fill with button-copy garbage |
| Utility-page redirects keep or reject detail identity upstream | `detail_extractor.py`, `pipeline/core.py` | Same-site detail runs that land on utility URLs may keep the originally requested PDP identity only when the extracted product still matches that requested slug; otherwise the record is dropped | Batch/detail crawls persist `/faqs` or `/mywishlist` as fake products, or swap in the wrong product under the requested URL |
| Labeled product option groups are real variants | `detail_extractor.py`, `extract/shared_variant_logic.py` | DOM variant recovery must recognize labeled select/radio/checkbox option groups generically, normalize common aliases, carry per-option stock/availability where present, keep `option_values` as the source of truth for multi-axis variant rows, and avoid emitting duplicate size summaries when `available_sizes` already covers the size axis | Sites with visible product-option chips such as `Weight`, `Flavour`, `Shade`, or `Storage` keep losing `variant_axes`, `variants`, selected availability, or emit duplicated size/color payloads even though the DOM has them |
| Site-shell rejection | `detail_extractor.py` | Detail extraction must reject records that are really site chrome, stale SPA shells, or generic OG/title blobs | Dead or non-product pages persist as fake product records |

---

## 7. Persistence, Identity, And Exports

| Decision | Owner | Current Rule | If Wrong |
|---|---|---|---|
| Record identity within a run | `pipeline/persistence.py` | `url_identity_key` is unique per `(run_id, url_identity_key)` and reruns/re-entry skip already-persisted identities before insert | Duplicate-key crashes abort otherwise recoverable runs |
| `record.data` is user-facing only | `pipeline/persistence.py`, `record_export_service.py` | Persisted/exported user payload contains populated logical fields only; internals stay in provenance/raw payloads | JSON/CSV exports leak markdown, page context, and internal scaffolding |
| Detail markdown is fallback context, not nav spillover | `browser_page_flow.py`, `record_export_service.py` | Detail-page markdown should prefer body content and avoid appending visible-link sections when useful text is already present | Markdown becomes bloated with breadcrumb/support links and obscures the actually missing fields |
| Provenance stays reviewable | `publish/metadata.py`, `record_export_service.py` | `raw_data`, `discovered_data`, and `source_trace` retain the forensic view without polluting normal output | Operators cannot audit a bad extraction after the fact |

---

## 8. Review, Selectors, And Memory

| Decision | Owner | Current Rule | If Wrong |
|---|---|---|---|
| Domain memory scope | `domain_memory_service.py`, `selectors_runtime.py` | Selector/domain memory is scoped by normalized `(domain, surface)` | A good rule for one surface poisons another |
| Selector self-heal gating | `selector_self_heal.py`, `pipeline/core.py` | Self-heal only runs when requested fields remain unsatisfied, and only persists validated improvements | Every weak run writes more junk selectors |
| Review save source of truth | `review/__init__.py`, `schema_service` callers | Approved mappings must be persisted and later loaded from `ReviewPromotion`, not transient in-memory state | Review UI and later runs disagree about what was approved |
| Completed-run promotion is the primary recipe workflow | `review/__init__.py`, `api/crawls.py`, `frontend/components/crawl/crawl-run-screen.tsx` | Completed runs expose requested-field coverage, winning selector candidates, affordance hints, saved selectors, and the editable domain run profile in one Domain Recipe panel; users promote selectors there instead of needing a second standalone flow first | Operators have to reconstruct which selectors actually worked, or save execution defaults in a disconnected tool |
| Completed-run field learning is field-local | `review/__init__.py`, `api/crawls.py`, `selectors_runtime.py`, `frontend/components/crawl/crawl-run-screen.tsx` | Keep/reject actions are saved per field and per XPath winner on normalized `(domain, surface)` memory; Learning shows successful XPath extraction signals, not duplicate extracted data | Rejecting one bad field mutates unrelated selectors, or the UI shows CSV-like values instead of reusable selectors |
| Saved selectors and saved run profiles stay separate | `selectors_runtime.py`, `domain_run_profile_service.py`, `crawl_crud.py` | Selector memory persists executable selectors in `DomainMemory`; reusable execution defaults persist in `DomainRunProfile`; neither storage shape contains the other | Selector CRUD starts mutating fetch defaults, or run-profile saves accidentally rewrite selector memory |
| Cookie memory is domain-scoped acquisition memory | `acquisition/cookie_store.py`, `acquisition/browser_runtime.py`, `api/crawls.py` | Browser cookie/local-storage reuse is stored in `DomainCookieMemory` by normalized domain only, reused before navigation on later runs, and only rewritten when the normalized state fingerprint changes | Every browser context rewrites unchanged state, or a selector/profile reset accidentally becomes the only way to clear learned cookies |
| Quick and Advanced mode are presentation-only | `frontend/components/crawl/crawl-config-screen.tsx`, `crawl_crud.py`, `models/crawl_settings.py` | `Quick Mode` exposes repeat-run essentials and uses saved domain defaults when present; `Advanced Mode` exposes the full fetch/locality/diagnostics profile plus manual selectors. Both dispatch the same nested settings contract, and explicit user edits always win for that run | The UI appears to have two incompatible crawl systems, or saved defaults become impossible to override explicitly |
| Reset is split by data ownership | `api/dashboard.py`, `dashboard_service.py`, `frontend/components/layout/app-shell.tsx` | `Reset Crawl Data` clears runs/artifacts/runtime files only; `Reset Domain Memory` clears selectors, saved run profiles, cookie memory, and field feedback only | Operators lose learned memory when they intended to clear run history, or stale learned memory survives a supposed memory reset |

---

## 9. LLM Decisions

| Decision | Owner | Current Rule | If Wrong |
|---|---|---|---|
| LLM use is explicit | `llm_runtime.py`, `crawl_crud.py` | No silent activation; run settings and active config both matter | Deterministic runs become nondeterministic |
| LLM is not the primary extractor | `pipeline/core.py`, extraction owners | Deterministic extraction runs first; LLM only fills approved gaps or beats weak deterministic output under explicit gating | The system drifts toward opaque extraction behavior |
| LLM failures degrade cleanly | `llm_circuit_breaker.py`, `llm_runtime.py` | Failures remain visible in diagnostics and do not corrupt deterministic state | Intermittent provider issues look like extraction bugs |

---

## 10. Debugging Use

When a crawl looks wrong, trace it in this order:

1. Was the run shaped correctly?
   Owner: `crawl_crud.py`, `pipeline/core.py`
2. Did acquisition choose the right method and wait long enough?
   Owner: `crawl_fetch_runtime.py`, `acquisition/browser_*`
3. Did listing/detail routing choose the right extractor?
   Owner: `crawl_engine.py`
4. Which candidate set won and why?
   Owner: `listing_extractor.py`, `detail_extractor.py`
5. Did persistence change the semantics or only store the result?
   Owner: `pipeline/persistence.py`, `record_export_service.py`

If the answer is "the same failure keeps reappearing on new sites", the bug is usually in one of these shared decisions:

- readiness classification
- listing-card evidence
- detail-path recognition
- candidate-set ranking
- site-shell rejection
- run-level identity dedupe

---

## 11. Update Rule

Update this file when one of the following changes:

- a shared decision rule changes
- a new critical decision point is introduced
- a repeated failure class reveals an undocumented rule that operators need to understand

Do not update this file for:

- routine refactors
- file moves without behavior change
- test-only changes
