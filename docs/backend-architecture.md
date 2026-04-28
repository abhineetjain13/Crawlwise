# Backend Architecture

> Last updated: 2026-04-23
>
> Canonical detailed backend reference. This is the merged replacement for the older split architecture docs.

## 1. Scope

CrawlerAI backend is a crawl execution, extraction, review, and export system with:

- authenticated FastAPI APIs
- Postgres persistence
- Redis-backed runtime state
- Celery execution
- pooled HTTP and browser acquisition
- structured-source and DOM extraction
- selectors, review, and domain-memory feedback loops
- admin-managed LLM configuration and optional task/runtime assistance

## 2. Runtime Stack

- API: FastAPI in `backend/app/main.py`
- Worker: Celery in `backend/app/tasks.py`
- DB: SQLAlchemy async + Alembic
- Cache/runtime state: Redis
- HTTP: `httpx` plus `curl_cffi`
- Browser: Playwright
- Parsing: BeautifulSoup, `glom`, `jmespath`, `lxml`, `extruct`, `browserforge`, `w3lib`

## 3. Registered API Surface

Routers registered in `backend/app/main.py`:

- `/api/auth`
- `/api/users`
- `/api/dashboard`
- `/api/crawls`
- `/api/crawls/{run_id}/records`
- `/api/records/{record_id}/provenance`
- `/api/jobs`
- `/api/review`
- `/api/selectors`
- `/api/llm`
- `/api/health`
- `/api/metrics`

Important route groups:

- `api/crawls.py`: create runs, CSV ingestion, logs, websocket updates, pause/resume/kill, commit fields, commit LLM suggestions
- `api/records.py`: records list plus JSON/CSV/markdown/artifacts/discoverist exports and provenance
- `api/review.py`: review payload, artifact HTML, save review mapping
- `api/selectors.py`: selector CRUD, cross-surface listing by domain, suggestion, test, preview HTML
- `api/llm.py`: provider catalog, config CRUD, connection test, cost log

Domain-recipe routes now live under `api/crawls.py`:

- `GET /api/crawls/domain-run-profile` — lookup saved run-profile defaults by normalized `(domain, surface)` for single-URL Crawl Studio auto-load
- `GET /api/crawls/{run_id}/domain-recipe` — completed-run payload containing requested-field coverage, grouped winning selector candidates, acquisition evidence, per-field learning state, affordance hints, saved selectors, and the saved domain run profile
- `POST /api/crawls/{run_id}/domain-recipe/promote-selectors` — promote selected winning selector candidates into exact-surface domain memory
- `POST /api/crawls/{run_id}/domain-recipe/save-run-profile` — save the reusable fetch/locality/diagnostics profile for the run's normalized `(domain, surface)`
- `POST /api/crawls/{run_id}/domain-recipe/field-action` — keep/reject field-local learning evidence and deactivate exact-surface saved selectors when a selector-backed field is rejected
- `GET /api/crawls/domain-memory/cookies` — compact domain-scoped cookie-memory summary for the Domain Memory workspace

## 4. Crawl Request and Settings Contract

`CrawlCreate` currently accepts:

- `run_type`: `crawl | batch | csv`
- `url` and/or `urls`
- `surface`: `ecommerce_listing | ecommerce_detail | job_listing | job_detail | automobile_listing | automobile_detail | tabular`
- `settings`
- `requested_fields`
- `additional_fields`

Current live behavior:

- batch and crawl run creation preserve raw user-entered `requested_fields` / `additional_fields` on the run, while runtime-only canonicalization happens later when extraction and confidence scoring need alias matching
- batch run settings persist the resolved `urls` list inside `CrawlRunSettings`, so `_batch_runtime.py` fans out the same URL set that the create request submitted

`CrawlRunSettings` normalizes settings for storage/runtime. Important fields include:

- `proxy_list`
- `fetch_profile`
- `locality_profile`
- `diagnostics_profile`
- `advanced_enabled` / `advanced_mode` as UI-mode compatibility fields
- resolved traversal mode derived from `fetch_profile.traversal_mode`
- `max_records` as a traversal stop target, not a persisted-row hard cap
- `sleep_ms`
- `respect_robots_txt`
- `url_batch_concurrency`
- `url_timeout_seconds`
- `llm_enabled`
- `extraction_contract`
- `llm_config_snapshot`
- `extraction_runtime_snapshot`

Current live behavior:

- nested run-profile settings are the canonical execution-shaping contract: `fetch_profile`, `locality_profile`, and `diagnostics_profile`
- `create_crawl_run()` resolves single-URL settings in this order: generic UI defaults, saved `DomainRunProfile`, explicit user edits from Crawl Studio, then backend normalization/snapshotting
- saved run profiles are limited to execution defaults only and intentionally exclude selector rows, proxies, LLM config/budgets, requested fields, cookies, auth/session state, and user identifiers
- Crawl Studio now exposes `Quick Mode` and `Advanced Mode` as UI presentation modes only; both dispatch the same nested settings contract to the backend

## 5. High-Level Flow

```text
POST /api/crawls
  -> crawl_ingestion_service
  -> crawl_crud.create_crawl_run
  -> crawl_service.dispatch_run
  -> Celery task process_run
  -> _batch_runtime.process_run
  -> pipeline/core._process_single_url for each URL
  -> acquire page + diagnostics + artifacts
  -> extract records
  -> optional selector self-heal / optional LLM missing-field extraction
  -> publish verdict + metrics + source trace
  -> persist CrawlRecord rows and run summary
```

## 6. Subsystem Ownership

### 6.1 API and bootstrap

Primary files:

- `app/main.py`
- `app/api/*`
- `app/core/config.py`
- `app/core/database.py`
- `app/core/redis.py`
- `app/core/security.py`
- `app/core/telemetry.py`
- `app/core/metrics.py`

Responsibilities:

- app startup/shutdown
- migrations on startup
- route registration
- auth/dependencies
- correlation IDs
- health and metrics

### 6.2 Crawl ingestion and orchestration

Primary files:

- `crawl_ingestion_service.py`
- `crawl_service.py`
- `crawl_crud.py`
- `crawl_events.py`
- `_batch_runtime.py`
- `pipeline/core.py`
- `pipeline/direct_record_fallback.py`
- `pipeline/extraction_retry_decision.py`
- `pipeline/types.py`
- `pipeline/runtime_helpers.py`

Responsibilities:

- create runs from payloads and CSV uploads
- stamp run snapshots
- dispatch and recover runs
- process URLs
- persist records and summary state
- emit logs and progress

Current live behavior:

- local startup recovery only reclaims stale active runs: fresh `pending` rows without a local task id are left alone, while stale `running` rows are forced into `failed` and stale local-dispatch `pending` rows are forced into `killed` so interrupted work does not stay orphaned forever
- batch execution now refreshes `last_heartbeat_at` as runs advance so startup recovery can distinguish live external workers from truly stale local work
- acceptance harness runs now support curated manifest-driven site sets with bucketed expectations, explicit acceptance surfaces remain authoritative instead of being silently re-inferred from URLs, and curated commerce rows can reuse artifact-backed run ids before falling back to live execution
- acceptance reports now distinguish transport verdicts from output quality through `quality_verdict`, `observed_failure_mode`, and `quality_checks`, so runs that technically succeed but return shell pages, promo pages, chrome-heavy listings, or broken variant semantics no longer look healthy
- reusable domain execution defaults are persisted separately from selector memory in `DomainRunProfile`, then merged into single-URL run creation before `CrawlRun.settings` is snapshotted
- `pipeline/core.py` stays the per-URL orchestrator; direct-record LLM fallback, empty-extraction browser retry decisions, browser diagnostics merge, and failure-state persistence live in dedicated pipeline helper modules

### 6.3 Acquisition and browser runtime

Primary files:

- `acquisition/acquirer.py`
- `acquisition/runtime.py`
- `acquisition/browser_capture.py`
- `acquisition/browser_runtime.py`
- `acquisition/http_client.py` (thin adapter over `runtime.get_shared_http_client`)
- `acquisition/browser_identity.py`
- `acquisition/cookie_store.py`
- `acquisition/pacing.py`
- `acquisition/traversal.py`
- `crawl_fetch_runtime.py`
- `config/runtime_settings.py`
- `config/browser_init_scripts.py`
- `config/browser_fingerprint_profiles.py`
- `robots_policy.py`
- `url_safety.py`

Responsibilities:

- safe target validation
- pooled HTTP/browser fetch
- JS-shell and blocked-page escalation
- browser identity generation
- network payload capture
- temporary screenshot staging for browser artifacts
- detail-page expansion
- listing traversal
- cookie policy enforcement
- robots handling when enabled

Current live behavior:

- fetch results carry headers, blocked state, browser diagnostics, transient browser artifacts, and network payload metadata
- browser runtime is pooled and exposes runtime snapshots
- `browserforge`-backed context identity is active
- browser fetch uses `patchright` as the primary acquisition engine. There is no legacy `playwright-stealth` stack and no silent generic Chromium fallback. Explicit `real_chrome` remains an escalation lane for protected ecommerce detail pages and Product Intelligence native Google discovery when `C:\Program Files\Google\Chrome\Application\chrome.exe` (or `CRAWLER_RUNTIME_BROWSER_REAL_CHROME_EXECUTABLE_PATH`) is available.
- `run_browser_surface_probe.py` is the canonical browser-surface verification harness for acquisition changes. It runs through the same shared browser runtime as crawls and writes timestamped `browser_surface_probe` artifacts with direct JS baseline, Sannysoft/Pixelscan/CreepJS extracted values, consensus drift, connection source metadata, and normalized findings.
- the browser-surface probe treats `window.chrome.runtime` as healthy when its type is `object`, and its `isTrusted` behavioral smoke now uses real Playwright mouse input against a temporary overlay target instead of JS-dispatched synthetic events, so probe findings reflect actual runtime leaks instead of expected DOM-event semantics
- browser contexts now reload engine-scoped per-run Playwright storage state first and then fall back to engine-scoped domain cookie memory, so `chromium`, `patchright`, and `real_chrome` do not replay each other's cookies/localStorage while still reusing learned state inside the same lane
- domain cookie memory is intentionally filtered acquisition memory, not a verbatim storage-state cache: challenge-only bot-defense state (for example PerimeterX `_px*`, `pxcts`, PX localStorage) is dropped on load/save, and blocked browser runs do not persist domain memory
- blocked browser runs also do not rewrite per-run Playwright storage snapshots, so one challenged detail page does not poison later URLs in the same batch run
- browser diagnostics now persist explicit lane identity (`browser_engine`, `browser_profile`, launch mode, native-context flag, stealth-enabled flag) so metrics and audits can distinguish shaped Chromium from native real Chrome without inferring from free-form logs
- traversal is explicit and separate from browser escalation
- JSON-expected acquisition now stays in `acquisition/http_client.py`; adapters consume decoded payloads instead of compensating for transport quirks
- browser network interception is bounded through a small response-queue worker pool with per-endpoint payload budgets instead of untracked background tasks
- adapter-owned acquisition URL normalization now runs before runtime policy selection, so platform-specific URL cleanup stays in adapters instead of generic acquisition code
- browser diagnostics now classify `browser_reason` and `browser_outcome`, record phase timings and HTML bytes, and preserve failed browser-attempt evidence even when the final acquisition method stays HTTP
- browser diagnostics now also expose rendered-listing evidence counts (`rendered_listing_fragment_count`, `listing_visual_element_count`) plus stage-aware browser failures (`failure_stage`, `timeout_phase`) so browser-heavy listing regressions can be triaged without replaying the whole run
- rendered-listing-fragment capture and visual-element capture are now bounded by a dedicated runtime timeout and recorded in `phase_timings_ms` (`rendered_listing_fragment_capture`, `listing_visual_capture`) so heavy browser pages cannot stall the whole acquisition tail indefinitely
- browser stages (`navigation`, `settle`, `serialize`, `finalize`) now run in cancellation-aware tasks; if a stage times out or the run is killed mid-flight, the runtime force-closes the page/context before unwinding so local hard-kill does not wait forever on a stuck Playwright DOM call
- browser rendering now probes extractability at `domcontentloaded`, skips optimistic/network-idle/readiness waits when content is already usable, and limits detail expansion with bounded DOM-first then accessibility-assisted fallback
- listing readiness no longer fast-paths from thin shell text alone; listing surfaces now require actual listing evidence before browser acquisition is considered ready
- detail expansion now skips plain navigation anchors with real `href`s (for example footer/about/careers/returns links) unless they behave like true in-page expanders, which prevents Souled Store-style utility-page navigations during PDP acquisition
- blocked-page detection is evidence-based: anti-bot vendor markers alone do not block a page, but challenge-specific signals such as CAPTCHA-delivery elements and corroborating blocker text do
- browser outcomes now distinguish challenge pages, low-content terminal shells, and explicit navigation/page-closed failures instead of collapsing them into generic browser HTML
- listing traversal now captures bounded per-step listing snapshots for extraction instead of concatenating full rendered DOMs across page turns, and diagnostics expose traversal fragment count plus traversal HTML bytes
- traversal, browser artifact capture, and listing extraction now share the same canonical listing-fragment selector/scoring owner in `extract/listing_card_fragments.py`; traversal is orchestration, not a separate listing-card pipeline
- listing-card counting now falls back to the shared heuristic when configured selectors miss a real grid, and the shared ecommerce selector set accepts case-variant `productCard`-style class names instead of requiring a single casing convention
- traversal-enabled browser fetches now retain both traversal-composed HTML and the full rendered HTML so the pipeline can retry extraction once when traversal fragments produce zero records
- browser block classification now preserves usable listing/detail content when vendor markers and challenge widgets coexist with clear extractable signals, instead of forcing a blocked verdict from anti-bot evidence alone
- traversal stop reasons remain diagnostic when the first rendered listing page is already usable: no-progress traversal keeps the full rendered HTML as the primary payload and only downgrades to `traversal_failed` when listing evidence is still below threshold
- detail-page expansion is field-aware and commerce-safe: requested fields now contribute expansion tokens, blocked action labels such as add-to-cart/login are skipped, and ARIA-driven affordances (`aria-expanded`, `aria-controls`, tabs, summaries) are considered even when the initial detail readiness probe already looks usable
- detail-page expansion now short-circuits when the current rendered DOM already exposes the requested section headings, avoiding unrelated follow-up clicks that would otherwise mutate an already-extractable detail page
- thin browser listing results can trigger one bounded recovery re-acquisition that performs ordered listing actions (`clear filters`, `view all`, `next page`) before traversal/extraction, and the pipeline only keeps the retry when it improves record count
- browser acquisition now generates internal `page_markdown` context from rendered HTML plus visible links and the accessibility snapshot; detail-page serialization prunes review/Q&A/payment containers and drops low-signal chrome lines before persistence so semantic expansion stays anchored to product content instead of whole-page UI noise
- browser screenshots are staged to temp files inside the artifacts area and then persisted by the pipeline, avoiding large in-memory PNG handoffs on the hot path
- a single shared HTTP client pool in `acquisition/runtime.py` is keyed on `(proxy, address-family preference, force_ipv4)`; `acquisition/http_client.py` no longer maintains a second pool and simply delegates to `get_shared_http_client`
- curl_cffi impersonation target is now an actionable setting (`crawler_runtime_settings.curl_impersonate_target`, default `chrome131`) rather than dead config, and httpx clients ship with a matching default Chrome `User-Agent`/`Accept` header set so direct HTTP requests present a coherent identity
- acquisition identity now repairs malformed browser client-hint headers before Playwright contexts are created, and the shared HTTP default headers advertise the same Chrome client-hint family (`sec-ch-ua*`, `Upgrade-Insecure-Requests`) when the configured UA is Chrome-like instead of sending a partial browser header set
- tracked detail URLs are normalized upstream before reuse: extracted and user-entered commerce/job targets now drop low-signal click/search context params (`utm_*`, `click_*`, `content_source`, `pf_from`, `sr_prefetch`, `qs`, and similar short replay flags) while preserving functional params such as `variant`, `q`, and `id`
- hosts with repeated hard blocks can temporarily prefer browser-first acquisition within the pacing TTL, but one successful browser recovery clears that host memory so random PDP challenges do not taint the whole host
- risky detail browser navigations can spend the configured `origin_warm_pause_ms` budget warming the site origin before the direct PDP navigation, which gives consent/session code a chance to settle before the high-risk page load
- origin warmup now respects the active lane profile and runs without the removed stealth layer
- browser contexts accept a per-fetch `proxy` for rotated-proxy traversal; `temporary_browser_page` is a thin wrapper over `SharedBrowserRuntime.page(proxy=...)`
- `browser_identity` is host-OS-locked via `browserforge`, with a small regeneration loop to reject fingerprints whose UA tokens disagree with the OS
- browser identity also normalizes exposed runtime hardware upstream: `hardwareConcurrency` is clamped to host-consistent values, `deviceMemory` is bucketed like Chrome, and page JS sees the same values as the generated context identity.
- browser identity init scripts now patch `window.chrome.runtime` with a Chrome-like runtime stub, mask Audio/OfflineAudio analyser/channel APIs with deterministic per-identity noise, and apply deterministic canvas/WebGL spoofing (canvas image-data/export noise plus profile-consistent WebGL vendor/renderer/readPixels overrides); the browser-surface probe now emits flattened canvas hash/data-url and WebGL vendor/renderer baseline fields for quick verification
- browser runtime settings are split by concern: `runtime_settings.py` owns tunables/launch args, `browser_init_scripts.py` owns JS payload builders, and `browser_fingerprint_profiles.py` owns static profile data
- blocked-page escalation is now two-pronged: vendor-specific response headers (DataDome, Cloudflare, Akamai, PerimeterX, Sucuri, ...) classified via `classify_block_from_headers` short-circuit into the browser and mark the host vendor-blocked so sibling fetchers skip further HTTP attempts; HTML heuristics continue to catch vendor-silent blocks
- `is_non_retryable_http_status` keeps `401` out of browser escalation (auth walls) while still escalating `403`/`429` challenges, and `classify_blocked_page` emits typed `BlockPageClassification` outcomes (`auth_wall`, `rate_limited`, `challenge_page`, ...) distinct from network failures
- `classify_blocked_page` must keep provider/body evidence even on forced `403` / `429` outcomes; status-only early returns are not enough because recovery, diagnostics, and regression triage need the concrete blocker family
- platform/runtime policy no longer hardcodes vendor-owned domains just to force browser usage; escalation is driven by runtime policy, response/header evidence, and structured blocker signatures
- host pacing is now enforced before both HTTP and browser attempts in `crawl_fetch_runtime.py`, and protection evidence can temporarily widen the per-host interval instead of hammering the same blocked edge
- after browser navigation, blocked challenge pages now get one bounded recovery window: the runtime polls for clearance, checks Akamai-style `_abck` issuance when relevant, and only then performs a single paced reload before surfacing the failure
- the legacy `async def fetch_page` trampoline in `acquisition/runtime.py` has been removed; callers import `fetch_page` from `crawl_fetch_runtime` directly

### 6.4 Extraction

Primary files:

- `crawl_engine.py`
- `detail_extractor.py`
- `listing_extractor.py`
- `structured_sources.py`
- `js_state_mapper.py`
- `network_payload_mapper.py`
- `field_value_*`
- `field_url_normalization.py`
- `public_record_firewall.py`
- `extract/variant_record_normalization.py`
- `extract/*`
- `adapters/*`

Responsibilities:

- choose listing vs detail path
- run platform adapters
- parse JSON-LD, embedded JSON, JS state, microdata, Open Graph, and network payloads
- extract field values from structured sources and DOM
- normalize field values before publish

Important implemented features:

- `structured_sources.py` now integrates extruct-backed microdata and Open Graph extraction, with fallback parsing when dependencies are unavailable
- Nuxt `__NUXT_DATA__` payload revival is live in structured-source harvesting
- `network_payload_mapper.py` now uses declarative specs from `config/network_payload_specs.py`, and browser-side endpoint classification derives its path tokens from that same spec source instead of maintaining a parallel capture-only token table
- network payload detail inference now keeps its signature/list-container config in `config/network_payload_specs.py`, recognizes normalized camel/Pascal-case commerce keys (`ProductName`, `DetailUrl`, `FieldValues`), and rejects product/detail payloads whose explicit URL anchor does not match the current detail page
- generic ghost-route payload fallback now rejects multi-record listing envelopes for detail surfaces, so paginated product-list APIs cannot masquerade as a single detail payload just because one row happens to expose product-like keys
- tracking-parameter stripping is live in field-value normalization via `w3lib`
- tracking URL cleanup has its own owner in `field_url_normalization.py`; generic value coercion stays in `field_value_core.py`
- platform registry config in `config/platforms.json` now owns adapter registration metadata, network signatures, JS-state mappings, and listing-readiness selectors/waits
- extraction runtime now short-circuits raw XML sitemap/listing payloads into deterministic URL records before HTML DOM parsing, which keeps sitemap targets out of the expensive BeautifulSoup listing path
- ecommerce detail title selection now ranks structured sources ahead of raw DOM headings, rejects noisy DOM `<h1>/<title>` values such as promo or generic-results text, and only promotes fallback titles when the replacement source is materially stronger
- ecommerce detail extraction now drops low-signal site-shell records when the surviving title still resolves to site-brand chrome and no real product anchors survive, preventing stale SPA/detail misses from being persisted as false product successes
- ecommerce-detail extraction now threads the originally requested PDP URL through materialization so same-site utility redirects can either preserve the requested product identity when the product metadata still matches or drop the row entirely when the utility page is carrying mismatched stale product data
- detail extraction now has a DOM variant fallback for `ecommerce_detail` pages when structured data and JS state leave variant axes empty
- variant record normalization has its own owner in `extract/variant_record_normalization.py`; `detail_extractor.py` extracts candidates and delegates final variant axis/value cleanup
- DOM variant recovery now recognizes radio/checkbox-based size and color groups, associates labels via `for`/parent label structure, and carries stock-derived availability (`0 Left`, `17 Left`, etc.) into `variants` and `selected_variant`
- JS-state ecommerce-detail mapping now scores candidate product payloads so richer nested PDP nodes beat shallow landing/navigation shells, and generic direct-axis variant keys such as `condition`, `grade`, `storage`, and `memory` are normalized without adapter-specific branches
- DOM listing extraction no longer accepts the first non-empty candidate set; it now ranks structured, DOM, and browser-captured rendered-card candidates by record quality and keeps visual elements as a last-resort fallback only
- job-listing detail-path recognition now treats numeric terminal posting slugs as detail-like URLs, so boards such as Startup.jobs survive candidate-set ranking without reopening city/search hub noise
- listing extraction may retry the original uncleaned DOM when noise-removal cleanup strips card detail-link evidence from the cleaned DOM, which protects header-nested product links on sites such as IndiaMART without weakening global cleanup rules
- listing title filtering now rejects numeric-only titles before persistence, and detail DOM image fallback keeps linked gallery media instead of dropping anchored product thumbnails
- generic ecommerce detail-path recognition now includes vendor-common routes such as `/proddetail/`, and listing anchor selection accepts same-site cross-subdomain detail links instead of requiring an exact hostname match
- DOM image extraction now scores likely product-gallery media higher and filters obvious tracking, logo, and spacer assets before building `additional_images`
- image dedupe now canonicalizes Next.js-style image proxy URLs back to their underlying asset, so transformed `/_next/image?...` duplicates do not survive as fake `additional_images` beside the same hero image
- ecommerce-detail DOM completion now treats missing `additional_images` as a high-value gap, so structured-data early exit does not suppress DOM gallery recovery when only a primary image was found upstream
- DOM section extraction now follows accordion/tab structures through `aria-controls`, native `details/summary`, and common wrapped content containers before falling back to plain heading-sibling scans
- requested-content extractability now only promotes canonical or explicitly requested section labels, preventing arbitrary product headings from being treated as synthetic extractable fields in browser diagnostics and DOM-completion gating
- raw requested field labels are preserved through crawl creation, and ecommerce-detail DOM section matching now checks those exact requested labels before collapsing to broader canonical aliases; composite headings such as `Features & Benefits` therefore extract into `features_benefits` instead of being silently reduced to a generic alias like `benefits`
- surface alias lookup now keeps normalized requested labels addressable as identity mappings as well as exact requested-field keys, so custom dynamic fields continue to flow through candidate collection even when they do not collapse to a built-in alias
- requested custom ecommerce-detail fields now keep DOM completion active when matching section headings are present, so structured-data early exit does not hide fields such as `product_story` after detail expansion
- DOM variant fallback now materializes concrete variant rows, keeps `variant_count` aligned with those rows, and avoids widening an already authoritative `selected_variant` choice with later DOM-only axis noise
- selector-backed fields that survive into `record.data` now persist exact selector provenance under `record.source_trace.field_discovery[field_name].selector_trace`, including selector kind/value, selector source, source run id, sample value, page URL, and `survived_to_final_record`
- ecommerce-detail long-text ranking now prefers explicit DOM sections over thinner structured blurbs when the page exposes a real description/spec-style accordion body, and `product_details` remains a separate field instead of being collapsed into `specifications`
- long-text candidate intake now rejects low-signal placeholders such as single-word review/schema values or accordion index labels before they can win `description` / `specifications`, and selector-backed long-text fields must expose non-interactive prose rather than button/tab indexes
- ecommerce-detail output no longer exposes platform slug fields such as `handle` by default; those values remain requestable explicitly, but the default user-facing detail schema stays limited to higher-signal commerce fields
- DOM section intake now rejects very short non-prose tab/button label clusters before they can override a real product description or specifications body
- ecommerce-detail JS-state product detection now requires real commerce cues instead of accepting arbitrary titled image blocks, and JS-state image harvesting filters payment, logo, bookmark, swatch, and video assets before they can outrank structured product media
- output schema validation now applies to listing surfaces as well as detail surfaces before persistence, so type mismatches on listing records are nullified instead of silently bypassing validation
- persistence now applies a final public-record firewall before `CrawlRecord.data`: unknown/internal fields, empty fields, invalid scalar/list/object shapes, non-navigation URLs, API/event/tracking URLs, and overlong opaque URLs are rejected into `source_trace.extraction.rejected_public_fields` instead of public data
- the final persisted-data firewall is owned by `public_record_firewall.py`, not `pipeline/persistence.py`; persistence calls it before writing `CrawlRecord.data`
- pipeline post-processing now has two bounded optional recovery layers: selector self-heal for detail pages, and a snapshot-backed `direct_record_extraction` LLM task that only replaces weak deterministic record sets when the LLM result scores better

### 6.5 Publish and persistence

Primary files:

- `publish/verdict.py`
- `publish/metrics.py`
- `publish/metadata.py`
- `artifact_store.py`
- `pipeline/core.py`
- `pipeline/persistence.py`

Responsibilities:

- compute per-URL verdicts
- compute acquisition and URL metrics
- build/persist field-discovery metadata
- persist HTML artifacts plus browser diagnostics/screenshot sidecars when a browser attempt occurred
- keep artifact I/O and `CrawlRecord` persistence out of the orchestration hot path in `pipeline/core.py`
- write `CrawlRecord` rows and update run summaries
- skip already-persisted `(run_id, url_identity_key)` identities on rerun/re-entry so detail/listing retries stay idempotent instead of failing the run on a duplicate-key insert

Current verdict rules:

- records + not blocked -> `success`
- records + blocked -> `partial`
- blocked + no records -> `blocked`
- listing + no records -> `listing_detection_failed`
- detail + no records -> `empty`

### 6.6 Review, selectors, and domain memory

Primary files:

- `review/__init__.py`
- `selectors_runtime.py`
- `selector_self_heal.py`
- `domain_memory_service.py`

Responsibilities:

- build review payloads
- save approved field mappings
- expose review artifact HTML
- store and manage selectors in domain memory
- suggest/test selectors
- synthesize and validate selectors during self-heal flows

Current storage/runtime model:

- selector/domain memory is stored by normalized `(domain, surface)`
- selectors are persisted inside `DomainMemory`
- reusable run defaults are persisted separately in `DomainRunProfile`, keyed by the same normalized `(domain, surface)` scope but never mixed into selector rows or `DomainMemory.selectors`
- reusable browser cookie/local-storage state is persisted separately in `DomainCookieMemory`, keyed by normalized domain only, because acquisition reuse is host-level rather than surface-level
- completed-run field keep/reject actions are persisted separately in `DomainFieldFeedback`, keyed by normalized `(domain, surface)` and the field/source that was accepted or rejected
- runtime can layer surface-specific and generic rules
- `GET /api/selectors` can now list all selector records for a domain across surfaces when `surface` is omitted, which is what the frontend uses for domain-memory management and crawl-config prefill
- selector self-heal reuses stamped extraction runtime snapshot data
- selector self-heal persists only validated improvements and reuses domain memory on later runs before attempting another synthesis pass
- once reused domain-memory rules satisfy the requested fields for a record, the pipeline does not launch a second generic selector-synthesis round just because confidence remains low
- completed runs now expose a Domain Recipe workflow that combines acquisition evidence, field-local keep/reject actions, selector promotion, and saved run-profile editing in one surface; rejecting a selector-backed field deactivates the exact matching saved selector for that `(domain, surface)` without mutating unrelated memory

### 6.7 LLM admin and runtime

Primary files:

- `llm_runtime.py`
- `llm_provider_client.py`
- `llm_config_service.py`
- `llm_cache.py`
- `llm_circuit_breaker.py`
- `llm_tasks.py`
- `llm_types.py`
- `api/llm.py`

Responsibilities:

- manage provider configs
- test provider connectivity
- run task-specific prompts
- cache responses and isolate failures
- expose provider catalog and cost log

Current crawl/runtime usage:

- optional missing-field extraction in the pipeline
- selector suggestion and review cleanup support
- config snapshots prevent mid-run drift

## 7. Persistence Model

Primary models:

- `User`
- `CrawlRun`
- `CrawlRecord`
- `CrawlLog`
- `DomainRunProfile`
- `DomainCookieMemory`
- `DomainFieldFeedback`
- `ReviewPromotion`
- `LLMConfig`
- `LLMCostLog`
- `DomainMemory`

Notable current schema direction:

- durable queue lease support
- max-records trigger support
- URL identity keys on records
- domain-memory storage
- split crawl-data reset versus domain-memory reset, so destructive cleanup no longer wipes learned selectors/profiles/cookies by default

## 8. Record, Review, and Provenance Contracts

`CrawlRecordResponse` intentionally cleans user-facing output:

- `data`: populated logical fields only
- `raw_data`: full stored extraction payload
- `discovered_data`: trimmed review/provenance metadata
- `source_trace`: acquisition and extraction provenance
- `review_bucket`: unverified attributes exposed for review
- `provenance_available`: indicates manifest/provenance detail exists

`CrawlRecordProvenanceResponse` exposes the fuller provenance/debug view:

- `raw_data`
- `discovered_data`
- `source_trace`
- `manifest_trace`
- `raw_html_path`

The normal records API hides:

- empty/null values
- `_`-prefixed internal fields
- obsolete raw manifest containers in standard display responses

## 9. Recent Feature Status From Plans/Audits

Implemented from recent extraction/audit work:

- extruct-backed microdata + Open Graph support
- generic network payload specs
- browserforge identity restoration
- URL tracking-param stripping
- Nuxt data revival
- selector self-heal + domain memory
- provenance/review bucket response cleanup

Still worth treating as active engineering concerns:

- generic-path hardcodes that should live in adapters/config
- large utility/service modules that still own too many concerns
- frontend/backend client-surface drift where unused client methods outlive removed routes
- selector tool and Crawl Studio now share selector memory semantics, so future selector changes need tests in both surfaces instead of assuming one page is authoritative

## 10. Operational References

Useful local commands:

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe run_acquire_smoke.py commerce
.\.venv\Scripts\python.exe run_extraction_smoke.py
.\.venv\Scripts\python.exe run_test_sites_acceptance.py
```

Acceptance harness note:

- `harness_support.parse_test_sites_markdown()` consumes literal URLs from `TEST_SITES.md` lines and markdown tables without rewriting them; when a table `Surface` cell says `Listing`, `Detail`, `AJAX listing`, `Infinite scroll`, or `SPA Detail`, that label only steers surface inference (`ecommerce_listing` vs `ecommerce_detail`) while the source URL remains unchanged

Companion docs:

- [../AGENTS.md](../AGENTS.md)
- [ENGINEERING_STRATEGY.md](ENGINEERING_STRATEGY.md)
- [INVARIANTS.md](INVARIANTS.md)
- [frontend-architecture.md](frontend-architecture.md)
