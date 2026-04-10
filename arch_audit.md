EXECUTIVE SUMMARY
Health scores (0–10):
Architecture: 5
Correctness: 4
Reliability: 6
Maintainability: 4
Security: 6
Test maturity: 6

Top 5 existential risks:

Shared detail-field arbitration currently gives datalayer a higher trust score than json_ld, so garbage analytics values can legitimately beat canonical product data in production.
Advanced traversal is only partially correct: auto mode mixes pagination detection with pagination execution, and paginate mode misreports collected pages, so operators cannot trust whether the mode actually worked.
Extraction policy is fragmented across candidate coercion, validation, sanitization, merge heuristics, listing sanitizers, and adapter merges, so the same field can resolve differently depending on which path produced it.
The extractor aggressively ingests broad embedded JSON and data-* blobs, which materially expands the contamination surface for analytics/config payloads.
A few core runtime contracts are already drifting from reality: dead compatibility stubs, duplicate helper implementations, and tests that lock in unsafe source precedence.
Top 5 strengths:

Public-target validation and non-public request blocking are present in both HTTP and browser acquisition paths.
Queue leasing, stale-run recovery, and worker ownership are better than typical crawler backends of this size.
The browser layer has meaningful challenge handling, cookie persistence controls, and artifact/diagnostic capture.
The codebase has a real test suite for extraction, traversal, queueing, and security boundaries.
Listing extraction avoids the common “detail-page fallback on listing page” corruption path.
Production readiness:
This backend is not ready for high-confidence production crawling at scale without a remediation pass. It has solid infrastructure instincts, but the shared extraction policy is not coherent enough yet: source priority, validation, traversal, and site-specific behavior are split across too many layers, and a few current choices actively bias the system toward wrong-but-non-null values rather than null-and-retry behavior.

2) ARCHITECTURE FINDINGS (Ranked by Severity)

Severity: Critical
Confidence: High
Category: Schema
Evidence: extraction_rules.py, service.py, core.py, test_extract.py
Problem: Shared ranking puts datalayer at 10 and json_ld at 9, and both _finalize_candidates and _reconcile_detail_candidate_values select the highest-ranked accepted row.
Production impact: Analytics strings can override canonical schema.org values whenever they pass lightweight validation; this directly matches the active schema-pollution symptom.
Minimal fix: Drop datalayer below json_ld for detail extraction and add a field-level allowlist for which datalayer fields are even eligible.
Ideal fix: Replace raw numeric source ranking with a field-aware source policy matrix enforced in one canonical arbitration function.
Effort: M
Regression risk if unchanged: Critical

Severity: High
Confidence: High
Category: Design
Evidence: service.py, core.py, field_normalization.py
Problem: Source-of-truth policy is duplicated across candidate filtering, final candidate ranking, downstream reconciliation, and adapter/candidate merge preference.
Production impact: Two records with identical raw evidence can resolve differently depending on whether they came through adapter merge, direct-candidate reconciliation, or listing normalization.
Minimal fix: Centralize canonical field arbitration for detail records and make merge helpers call it instead of applying separate heuristics.
Ideal fix: Introduce a single typed “FieldDecisionEngine” with source policy, sanitization, and trace output.
Effort: L
Regression risk if unchanged: High

Severity: High
Confidence: High
Category: Traversal
Evidence: traversal.py, traversal.py
Problem: auto mode calls click_and_observe_next_page() as a probe before collect_paginated_html(), but that helper may actually click the control and mutate the page.
Production impact: Button-based pagination can skip a page, double-advance, or produce mixed pre-pagination/paginated fragments with misleading traces.
Minimal fix: Split pagination into peek_next_page() and advance_next_page(); auto should only probe, never mutate.
Ideal fix: Make traversal a state machine with explicit discover, advance, capture, and dedupe phases.
Effort: M
Regression risk if unchanged: High

Severity: High
Confidence: High
Category: Traversal
Evidence: traversal.py, crawl_metrics.py, batch_runtime.py
Problem: paginate mode emits page_count, but metrics and run summaries read pages_collected.
Production impact: paginate runs look unsuccessful in metrics, traversal success counters under-report, and the UI/logs show broken advanced traversal even when pages were collected.
Minimal fix: Normalize paginate summaries to emit pages_collected.
Ideal fix: Define and enforce a single traversal summary schema across traversal, browser client, metrics, and UI.
Effort: S
Regression risk if unchanged: High

Severity: High
Confidence: High
Category: Correctness
Evidence: service.py
Problem: _coerce_price_field() rejects bare numeric prices below 10.
Production impact: Legitimate low-price items are silently dropped whenever the source emits 9.99 instead of $9.99; fallback sources may then win with stale or null values.
Minimal fix: Remove the hard <10 rejection for canonical price fields.
Ideal fix: Make “suspicious tiny counter” filtering source-aware and field-aware instead of globally numeric.
Effort: S
Regression risk if unchanged: High

Severity: Medium
Confidence: High
Category: Schema
Evidence: source_parsers.py, service.py
Problem: Embedded JSON ingestion parses any application/json script, many script IDs, and data-* attributes containing tokens like config, schema, or payload, then deep-scans aliases through them.
Production impact: Analytics/config payloads enter the same candidate pool as product data, increasing false positives for title/category/availability/brand.
Minimal fix: Restrict embedded JSON ingestion to a narrower allowlist and tag every blob with a sub-source type.
Ideal fix: Parse source families explicitly instead of using broad blob harvesting plus alias recursion.
Effort: M
Regression risk if unchanged: High

Severity: Medium
Confidence: High
Category: HardcodedHack
Evidence: acquirer.py, core.py, selectors.py
Problem: Site/platform logic is scattered across config, acquirer, pipeline core, selectors, and adapters, with duplicated platform lists.
Production impact: Adding or changing a platform requires touching multiple layers; drift between lists will cause silent misclassification.
Minimal fix: Consolidate platform family membership into one registry and remove literal duplicate sets.
Ideal fix: Introduce platform strategy objects with per-platform readiness, traversal, and recovery policy.
Effort: L
Regression risk if unchanged: High

Severity: Medium
Confidence: High
Category: Maintainability
Evidence: core.py, core.py, crawl_utils.py, field_normalization.py, crawl_metrics.py
Problem: There is dead compatibility code and duplicate helper logic (_looks_like_job_listing_page, _validate_extraction_contract, _requested_field_coverage).
Production impact: Tests and future edits can keep passing while targeting obsolete contracts instead of live behavior.
Minimal fix: Delete dead stubs and route all callers to one helper implementation.
Ideal fix: Reduce compatibility exports and stop shaping runtime code around obsolete test import paths.
Effort: S
Regression risk if unchanged: Medium

3) SITE-SPECIFIC HACKS REGISTER

ID	Location (file:function)	Domain/Pattern Matched	Classification	Risk	Consolidation Action
H001	config/extraction_rules.py:1818 PLATFORM_FAMILIES	icims.com, workforcenow.adp.com, oraclecloud.com, paycomonline.net, recruiting.ultipro.com, boards.greenhouse.io	SMELL	Platform-family and browser-first matching still live in runtime python config	Create an acquisition-only PlatformRegistry and move family matching/browser-first policy there
H002	config/selectors.py:160 resolve_listing_readiness_override	Oracle HCM, ADP, Paycom, UKG URL token groups	SMELL	Selectors module still owns domain matching alongside readiness selectors	Keep selectors.py family-keyed only; move domain/family detection to PlatformRegistry
H003	acquisition/acquirer.py:_requires_browser_first	browser-first policy for adp and configured domains	SMELL	Duplicate browser policy path separate from platform registry	Fold into unified platform runtime policy
H004	acquisition/acquirer.py:_JOB_ADAPTER_HINTS	literal adapter-name set	SMELL	Duplicates adapter/platform membership and can drift	Derive from adapter registry or platform registry
H005	pipeline/core.py:_resolve_listing_surface	literal adapter-hint set (adp, greenhouse, icims, etc.)	DANGEROUS	Backend surface normalization can drift if job-vs-commerce detection comes from scattered heuristics instead of one URL/platform policy source	Keep listing/detail intent from the request, derive job-vs-commerce from registry-backed URL/platform detection, and downgrade redirect-shell title heuristics to diagnostics only
H006	config/extraction_rules.py:1368 acquisition guards	canonical https://www.schooljobs.com/ redirect shell	JUSTIFIED	Specific false-positive/redirect guard	Keep, but isolate under explicit platform guard rules
H007	config/extraction_rules.py:1808 cookie policy overrides	your-domain.com placeholder	DANGEROUS	Runtime template ships as active config and test coverage assumes it	Delete placeholder from runtime config
H008	adapters/*.py:can_handle	Amazon, Walmart, Ebay, ADP, ICIMS, Indeed, LinkedIn, Greenhouse, etc.	JUSTIFIED	Adapter boundary is the right place for domain-specific parsing	Keep, but keep only adapter matching there
H009	adapters/greenhouse.py:29	HTML substring greenhouse.io plus grnhse_app	DANGEROUS	Loose HTML matching can overlap embeds/non-board pages	Replace with normalized platform-family detection helper
H010	adapters/remotive.py	remotive.com vs remoteok.com in one adapter	SMELL	Two unrelated sites share one adapter class and branch logic	Split into distinct adapters
H011	selectors.py:240	URL substring group matching via all(token in normalized_url)	DANGEROUS	Loose token overlap can apply wrong readiness selectors to unrelated URLs	Use domain + path regexes scoped per family
H012	cookie_store.py:18	per-domain cookie policy override lookup	SMELL	Cookie behavior is domain-specific but hidden in generic store logic	Keep config-driven, but require explicit validated domains only
Consolidation strategy:
What should move to site config:

Acquisition-only family matching, browser-first policy, redirect-shell guards, cookie overrides.
Listing-readiness selectors may stay in selectors.py, but only keyed by platform family. PlatformRegistry should identify the family; it should not become an extraction/selector rules store.
What should become a strategy/adapter class:

Platform-specific pagination/readiness behavior.
Blocked-page public-endpoint recovery.
Any site family with custom HTML/JSON interpretation beyond simple selectors.
What can be deleted:

Placeholder cookie override for your-domain.com.
Literal duplicate platform sets in core.py and acquirer.py.
Mixed-site RemotiveAdapter branch logic after split.
Correct order to consolidate without breaking active sites:

Make an acquisition-only platform registry authoritative for family detection and browser-first policy.
Switch core.py, acquirer.py, and selectors to read the family identity from it.
Delete duplicate literal sets.
Split mixed adapters.
Remove placeholder config and tighten validation.
4) SCHEMA POLLUTION TRACE REPORT

Field: category
Priority: P0
Effort: M
Category: Schema
File(s): backend/app/services/extract/service.py, backend/app/services/config/extraction_rules.py, backend/app/services/pipeline/core.py
All observed sources feeding this field, in effective priority order: contract XPath, contract regex, adapter, datalayer, JSON-LD, network intercept, embedded JSON, next data, hydrated state, microdata, selector/DOM, breadcrumb DOM, semantic text.
Exact arbitration/fallback logic: _collect_candidates() appends candidates by source family; _finalize_candidate_rows() coerces, validates, sanitizes; _finalize_candidates() keeps the highest-ranked row using SOURCE_RANKING; _reconcile_detail_candidate_values() repeats normalization and again picks the highest-ranked accepted row.
Specific condition under which garbage wins: any non-empty datalayer category string that survives _coerce_category_field() and validate_value() beats a valid JSON-LD category because datalayer=10 and json_ld=9.
Universal or site-specific: Universal shared bug.
Minimal fix: Rank json_ld above datalayer and add reject rules for analytics/page-type/category-shell tokens.
Ideal fix: Add a canonical post-arbitration categorical-field sanitizer with max length, token blocklist, and source-family allowlist.

Field: availability
Priority: P0
Effort: M
Category: Schema
File(s): backend/app/services/extract/service.py, backend/app/services/normalizers/__init__.py, backend/app/services/pipeline/core.py
All observed extraction sources feeding this field, in effective priority order: contract, adapter, datalayer, JSON-LD, network intercept, embedded JSON, next data, hydrated state, microdata, selector/DOM, semantic/text.
Exact arbitration/fallback logic: same two-stage ranking path as category, then persistence through _split_detail_output_fields().
Specific condition under which garbage wins: _coerce_availability_field() returns almost any non-empty string, and validate_value() only rejects very long strings and GA metric tokens; a short UI string can outrank JSON-LD.
Universal or site-specific: Universal shared bug.
Minimal fix: Canonicalize availability to an enum/closed vocabulary before ranking winners.
Ideal fix: Per-field source contracts so only JSON-LD/offers, adapter, and vetted DOM selectors can populate availability.

Field: title
Priority: P1
Effort: M
Category: Schema
File(s): backend/app/services/extract/source_parsers.py, backend/app/services/extract/service.py
All observed extraction sources feeding this field, in effective priority order: contract, adapter, JSON-LD, network intercept, embedded JSON, next data, hydrated state, open graph, microdata, selector/DOM, semantic section, text pattern.
Exact arbitration/fallback logic: structured blobs from scripts and data-* attributes are harvested first, then _finalize_candidates() picks the highest-ranked surviving candidate.
Specific condition under which garbage wins: a config/analytics blob with a key alias like title or name parsed from embedded JSON or a data-* attribute will outrank H1/DOM if it passes generic-title filters.
Universal or site-specific: Universal shared bug.
Minimal fix: Stop parsing generic data-* JSON blobs and lower embedded/hydrated states below JSON-LD plus vetted DOM for title.
Ideal fix: Tag each structured blob family and gate title extraction by blob family and semantic context.

Field: brand
Priority: P1
Effort: M
Category: Schema
File(s): backend/app/services/extract/service.py, backend/app/services/normalizers/__init__.py
All observed extraction sources feeding this field, in effective priority order: contract, adapter, JSON-LD, network intercept, embedded JSON, next data, hydrated state, microdata, selector/DOM, text pattern.
Exact arbitration/fallback logic: _append_source_candidates() skips GA datalayer for entity_name, but other structured-state blobs still enter; _reconcile_detail_candidate_values() then selects the highest-ranked accepted source.
Specific condition under which garbage wins: a retailer/store/company label from hydrated or embedded state beats selector DOM brand because those sources outrank DOM and brand validation is still permissive for short non-breadcrumb strings.
Universal or site-specific: Universal shared bug; exact payload family depends on site.
Minimal fix: Add brand source-family restrictions and reject store/account/navigation labels.
Ideal fix: Separate brand from generic entity_name and require product-scoped evidence.

Field: color
Priority: P1
Effort: M
Category: Schema
File(s): backend/app/services/extract/service.py, backend/app/services/normalizers/__init__.py
All observed extraction sources feeding this field, in effective priority order: contract, adapter, network intercept, embedded JSON, next data, hydrated state, selector/DOM, semantic/text.
Exact arbitration/fallback logic: _coerce_color_field() calls _normalize_color_candidate(); surviving candidates are ranked and persisted like other detail fields.
Specific condition under which garbage wins: evidence is incomplete for the exact cookie/consent contamination path, but any short structured-state UI label that is not CSS, not “select…”, and not over 40 chars can beat DOM color because structured-state sources outrank selector/DOM.
Universal or site-specific: Need confirmation with a contaminated artifact to name the exact source family.
Minimal fix: Add a field-specific allowlist/pattern validator for colors and reject generic CTA/UI labels.
Ideal fix: Make color population source-aware and variant-aware instead of free-text.

5) BROWSER TRAVERSAL MODE — BUG TRACE & FIX PLAN
Traversal opt-in note:
Listing traversal is user-owned. Browser rendering for initial acquisition/readiness is allowed without explicit traversal permission, but `paginate`, `scroll_to_bottom`, and `click_load_more` / `load_more` must execute only when the normalized traversal mode derived from `advanced_mode` is present.

Paginated:

Is it implemented end-to-end? Partial
Evidence: apply_traversal_mode() in backend/app/services/acquisition/traversal.py:167; collect_paginated_html() in .../traversal.py:275; metrics ingestion in backend/app/services/crawl_metrics.py:44
Exact failure mode: paginate emits page_count not pages_collected, so runtime metrics say 0 pages collected; auto mode also uses a mutating pagination probe before pagination collection.
Minimal fix: emit pages_collected=len(fragments) in paginate summary and replace the auto-mode probe with a non-mutating “peek next page” helper.
Ideal fix: explicit traversal state machine with separate discover/advance/capture stages.
Test case: https://example.com/products?page=1 with 3 linked pages should report pages_collected=3, traversal_succeeded=true, and preserve pages 1–3 exactly once.
Priority: P0
Effort: M
Infinite Scroll:

Is it implemented end-to-end? Partial
Evidence: scroll_to_bottom() in backend/app/services/acquisition/traversal.py:618
Exact failure mode: progress detection relies on link/card/text/height deltas only; virtualized grids or replaced items can cause premature stop or duplicated output without identity-based verification.
Minimal fix: track a stable set of discovered item hrefs/ids across iterations and require identity growth before success.
Ideal fix: add mutation-observer-backed readiness plus per-iteration record dedupe before fragment capture.
Test case: infinite-scroll listing where DOM recycles old cards should still accumulate all unique listing URLs exactly once.
Priority: P1
Effort: M
View All / Load More:

Is it implemented end-to-end? Partial
Evidence: resolve_traversal_mode() maps view_all -> load_more in backend/app/services/crawl_utils.py:105; click_load_more() in backend/app/services/acquisition/traversal.py:870
Exact failure mode: success is defined by metric growth only; if content replaces in place without raising link/card counts immediately, the click is marked as failure and traversal stops.
Minimal fix: wait for either button disappearance, DOM mutation, or unique item identity growth after each click.
Ideal fix: treat “load more/view all” as a first-class traversal type with explicit post-click readiness rules.
Test case: a page where View all replaces 12 items with 120 items in the same container should end with pages_collected>=2 and at least 120 unique URLs.
Priority: P1
Effort: M
6) BUG & DEFECT CANDIDATE LIST

ID	P	Sev	File:Function	Symptom	Trigger	Root Cause	Fix	Test to Add	Status
BUG-001	P0	Critical	config/extraction_rules.py:source_ranking	Wrong field wins	Datalayer + JSON-LD disagreement	datalayer ranked above json_ld	Lower rank and gate allowed datalayer fields	polluted category/availability arbitration test	LIKELY BUG
BUG-002	P0	High	extract/service.py:_coerce_price_field	Cheap items lose price	bare numeric 9.99	hard-coded <10 rejection	remove threshold or make source-aware	sub-$10 price regression	LIKELY BUG
BUG-003	P0	High	acquisition/traversal.py:collect_paginated_html	paginate looks broken in metrics	any paginate run	emits page_count, not pages_collected	normalize summary schema	paginate metrics integration test	LIKELY BUG
BUG-004	P0	High	acquisition/traversal.py:apply_traversal_mode	auto skips/doubles pagination steps	button-only next control	probe helper mutates page	split peek vs advance helpers	auto button-pagination state test	LIKELY BUG
BUG-005	P1	High	extract/source_parsers.py:parse_datalayer	stale/partial ecommerce payload wins	multiple dataLayer.push events	returns first valid payload only	choose best product/detail payload, not first	multi-push datalayer arbitration test	LIKELY BUG
BUG-006	P1	Medium	extract/source_parsers.py:extract_embedded_json	analytics/config blobs enter candidate pool	data-config, data-schema, generic JSON scripts	ingestion scope too broad	narrow allowlist and tag blob families	embedded-config pollution test	LIKELY BUG
BUG-007	P1	Medium	pipeline/core.py:_looks_like_job_listing_page	false confidence in legacy contract	tests/imports use stub	exported stub always returns False	delete or replace with real detector	delete-legacy-import test	ARCH SMELL
BUG-008	P1	Medium	pipeline/core.py:_save_listing_records	duplicates are persisted	duplicate URLs after traversal/merge	duplicates only flagged after save	dedupe before DB write	multi-page duplicate save test	LIKELY BUG
BUG-009	P2	Medium	pipeline/core.py:_validate_extraction_contract	dead duplicate validator	none	orphaned helper never called	delete and reuse crawl_utils helper	N/A	ARCH SMELL
BUG-010	P2	Medium	extract/listing_extractor.py:LISTING_PAGE_ALLOWED_FIELDS	dead/misleading contract constant	maintenance edits	unused constant also says image_link not image_url	delete or actually enforce	constant drift test	ARCH SMELL
7) CODE REDUCTION & SIMPLIFICATION BACKLOG
TODO-SIMP-001: Collapse duplicate field-coverage helpers
Priority: P1
Effort: S
Files affected: backend/app/services/pipeline/field_normalization.py, backend/app/services/crawl_metrics.py, backend/app/services/crawl_metadata.py
What to remove/merge/collapse: three nearly identical _requested_field_coverage implementations
What to keep: one shared helper in crawl_metadata.py or a new field_coverage.py
Estimated LoC delta: -40
Bug surface reduction: Medium, because coverage semantics stop drifting across persistence and metrics
Risk of simplification: low; validate with existing coverage tests

TODO-SIMP-002: Delete dead extraction-contract validator copy
Priority: P2
Effort: S
Files affected: backend/app/services/pipeline/core.py, backend/app/services/crawl_utils.py
What to remove/merge/collapse: unused _validate_extraction_contract() in pipeline core
What to keep: crawl_utils.validate_extraction_contract()
Estimated LoC delta: -20
Bug surface reduction: Low, mainly removes drift
Risk of simplification: very low; no live callers

TODO-SIMP-003: Remove legacy job-listing stub export
Priority: P2
Effort: S
Files affected: backend/app/services/pipeline/core.py, backend/app/services/crawl_service.py, backend/app/services/pipeline/__init__.py, tests importing it
What to remove/merge/collapse: _looks_like_job_listing_page() compatibility stub and export plumbing
What to keep: no stub, or a real detector in one place
Estimated LoC delta: -25
Bug surface reduction: Medium, because tests stop anchoring dead behavior
Risk of simplification: medium; update import-path tests first

TODO-SIMP-004: Converge platform-family membership into one registry
Priority: P1
Effort: M
Files affected: backend/app/services/config/extraction_rules.py, backend/app/services/acquisition/acquirer.py, backend/app/services/pipeline/core.py
What to remove/merge/collapse: _JOB_ADAPTER_HINTS, literal adapter-hint sets, duplicated browser-first membership
What to keep: one registry-driven lookup API
Estimated LoC delta: -80
Bug surface reduction: High, because platform drift is a current reliability risk
Risk of simplification: medium; validate across adapter-routing and surface-remap tests

TODO-SIMP-005: Collapse browser-client traversal wrappers or make them public contracts
Priority: P2
Effort: M
Files affected: backend/app/services/acquisition/browser_client.py, backend/app/services/acquisition/traversal.py
What to remove/merge/collapse: thin wrapper duplicates like _collect_paginated_html, _scroll_to_bottom, _click_load_more, _find_next_page_url
What to keep: either direct shared-module calls or a stable adapter layer with one purpose
Estimated LoC delta: -120
Bug surface reduction: Medium, because traversal schema drift already happened
Risk of simplification: medium; validate existing traversal tests

TODO-SIMP-006: Remove unused listing contract constant or enforce it for real
Priority: P2
Effort: S
Files affected: backend/app/services/extract/listing_extractor.py
What to remove/merge/collapse: LISTING_PAGE_ALLOWED_FIELDS if unused
What to keep: actual live enforcement via DETAIL_ONLY_FIELDS and canonical_listing_fields()
Estimated LoC delta: -10
Bug surface reduction: Low
Risk of simplification: low

8) AGENT-EXECUTABLE REMEDIATION BACKLOG

P0

TODO-001: Re-rank detail-field arbitration so JSON-LD beats datalayer
Priority: P0
Effort: M (2h–1d)
Category: Schema
File(s): backend/app/services/config/extraction_rules.py, backend/app/services/extract/service.py, backend/tests/services/extract/test_extract.py
Problem: The shared ranking currently gives datalayer a higher score than json_ld, and both candidate-finalization passes honor that ranking. That makes analytics payloads the canonical winner when they are merely non-null, even if JSON-LD has cleaner product data.
Action: Lower datalayer below json_ld; add a regression test where datalayer contains a noisy but syntactically valid category/availability and JSON-LD contains the correct value; update or delete tests that currently enforce datalayer-first precedence.
Acceptance criteria: polluted datalayer values no longer beat valid JSON-LD values for detail fields; tests fail if source ranking regresses.
Depends on: none

TODO-002: Add a canonical post-arbitration sanitization gate for categorical fields
Priority: P0
Effort: M (2h–1d)
Category: Schema
File(s): backend/app/services/pipeline/core.py, backend/app/services/normalizers/__init__.py, backend/app/services/extract/service.py, backend/tests/services/extract/test_arbitration.py
Problem: Validation is fragmented and mostly source-local. Availability, category, brand, and color can still accept wrong-but-non-null short strings and become canonical winners.
Action: Create one post-arbitration sanitizer that runs after _reconcile_detail_candidate_values() and before persistence; enforce per-field max length, reject phrases, token blocklists, and closed vocabularies where possible; keep rejection traces in reconciliation.
Acceptance criteria: canonical detail record fields cannot persist known pollution phrases or generic UI strings; source trace shows rejections.
Depends on: TODO-001

TODO-003: Fix paginate traversal summary contract
Priority: P0
Effort: S (< 2h)
Category: Traversal
File(s): backend/app/services/acquisition/traversal.py, backend/app/services/crawl_metrics.py, backend/app/services/_batch_runtime.py, backend/tests/services/acquisition/test_browser_client.py
Problem: paginate mode emits page_count, but downstream metrics read pages_collected. Runs therefore report broken traversal even when pages were collected.
Action: Change paginate summaries to include pages_collected; keep page_count only as a compatibility alias if needed; add a test that verifies metrics and run summaries record the collected count.
Acceptance criteria: paginate runs increment traversal_succeeded, logs show non-zero pages collected, and existing traversal tests pass.
Depends on: none

TODO-004: Split pagination probing from pagination execution in auto mode
Priority: P0
Effort: M (2h–1d)
Category: Traversal
File(s): backend/app/services/acquisition/traversal.py, backend/app/services/acquisition/browser_client.py, backend/tests/services/acquisition/test_browser_client.py
Problem: auto mode currently calls a helper that may click the next-page control during detection, then starts pagination collection on a mutated page. This is unsafe for button-based pagers.
Action: Add a non-mutating peek_next_page() path; make auto use it; keep click_and_observe_next_page() only inside actual pagination advancement.
Acceptance criteria: a button-only next-page fixture captures each page once and never advances during probe.
Depends on: none

TODO-005: Stop dropping legitimate sub-$10 prices
Priority: P0
Effort: S (< 2h)
Category: Correctness
File(s): backend/app/services/extract/service.py, backend/tests/services/extract/test_extract.py
Problem: _coerce_price_field() rejects bare numerics below 10, which silently discards valid cheap-item prices.
Action: Remove the blanket threshold or limit it to specific noisy structured-source contexts; add unit coverage for 9.99, 5.49, and 0.99 canonical prices.
Acceptance criteria: low-price detail fields survive extraction when otherwise valid.
Depends on: none

P1

TODO-006: Narrow embedded JSON and data-* ingestion to product/job-scoped blobs
Priority: P1
Effort: M (2h–1d)
Category: Schema
File(s): backend/app/services/extract/source_parsers.py, backend/app/services/extract/service.py, backend/tests/services/extract/test_extract.py
Problem: the parser currently ingests generic application/json, many script IDs, and data-config/data-schema/data-payload attributes, then deep-scans them for aliases. This is a major contamination path.
Action: Replace token-based blob harvesting with an allowlist of known payload families; tag each blob family in the trace; refuse generic data-* JSON unless explicitly enabled by a platform strategy.
Acceptance criteria: analytics/config blobs no longer surface title/category/availability candidates in tests.
Depends on: TODO-001

TODO-007: Make datalayer parsing choose the best ecommerce payload instead of the first valid one
Priority: P1
Effort: M (2h–1d)
Category: Correctness
File(s): backend/app/services/extract/source_parsers.py, backend/tests/services/extract/test_datalayer.py
Problem: parse_datalayer() returns on the first valid ecommerce payload. Many sites push multiple ecommerce events, and the first one is often stale, incomplete, or page-level.
Action: score all ecommerce pushes, prefer product/detail payloads with richer canonical fields, and keep a trace of the chosen push index.
Acceptance criteria: multi-push pages choose the richest product payload, not the first valid one.
Depends on: none

TODO-008: Dedupe listing records immediately before persistence
Priority: P1
Effort: S (< 2h)
Category: Reliability
File(s): backend/app/services/pipeline/core.py, backend/tests/services/pipeline/test_listing_no_fallback.py
Problem: listing duplicates are only flagged after save, not prevented before DB insert. Traversal duplicates therefore still pollute persisted output.
Action: apply identity-based dedupe in _save_listing_records() using the same strong-key logic used upstream; record dropped-duplicate counts in source trace.
Acceptance criteria: duplicate listing URLs/identity keys are not persisted twice in multi-page runs.
Depends on: none

TODO-009: Consolidate platform-family lookups and remove literal duplicate sets
Priority: P1
Effort: M (2h–1d)
Category: HardcodedHack
File(s): backend/app/services/config/extraction_rules.py, backend/app/services/acquisition/acquirer.py, backend/app/services/pipeline/core.py, backend/app/services/config/selectors.py
Problem: platform membership and job-surface hints are duplicated across multiple modules. That is already causing policy drift risk.
Action: expose one helper for platform-family membership and browser/readiness policy; replace literal sets in acquirer.py and core.py with that helper.
Acceptance criteria: platform-family lists exist in one place only; all surface-remap and browser-first tests still pass.
Depends on: none

TODO-010: Remove placeholder cookie domain override from runtime config
Priority: P1
Effort: S (< 2h)
Category: Security
File(s): backend/app/services/config/extraction_rules.py, backend/app/services/acquisition/cookie_store.py, backend/tests/services/acquisition/test_browser_client.py
Problem: runtime config still ships a your-domain.com cookie override template, and tests currently assert behavior against it. That is unsafe configuration debt.
Action: delete the placeholder override, update tests to use explicit temporary overrides, and fail startup if placeholder domains remain in prod config.
Acceptance criteria: no placeholder domains remain in runtime config; tests no longer depend on them.
Depends on: none

TODO-011: Add identity-based progress checks for scroll and load-more traversal
Priority: P1
Effort: M (2h–1d)
Category: Traversal
File(s): backend/app/services/acquisition/traversal.py, backend/app/services/acquisition/browser_client.py, backend/tests/services/acquisition/test_browser_client.py
Problem: traversal success currently depends on link/card/text/height deltas only. Virtualized or in-place-updating pages can fool this logic.
Action: snapshot visible item hrefs/ids before and after each action; treat traversal as progressed only when unique item identity grows or a verified DOM mutation occurs.
Acceptance criteria: virtualized-scroll and load-more fixtures stop only when unique item identity stops growing.
Depends on: TODO-004

TODO-012: Delete dead compatibility stubs and duplicate validators
Priority: P1
Effort: S (< 2h)
Category: Simplification
File(s): backend/app/services/pipeline/core.py, backend/app/services/crawl_service.py, backend/app/services/crawl_utils.py, tests importing legacy symbols
Problem: _looks_like_job_listing_page() is a dead stub and _validate_extraction_contract() is an orphaned duplicate. They create test/runtime drift.
Action: remove the dead symbols, update imports, and route all extraction-contract validation through crawl_utils.
Acceptance criteria: no dead compatibility stubs remain in live imports; tests target active behavior only.
Depends on: none

P2

TODO-013: Collapse duplicate requested-field coverage helpers
Priority: P2
Effort: S (< 2h)
Category: Simplification
File(s): backend/app/services/pipeline/field_normalization.py, backend/app/services/crawl_metrics.py, backend/app/services/crawl_metadata.py
Problem: the same helper exists in three places with slightly different empty-case semantics.
Action: keep one implementation and update all callers.
Acceptance criteria: one helper remains and all coverage-related tests pass.
Depends on: none

TODO-014: Split mixed-site RemotiveAdapter into separate adapters
Priority: P2
Effort: S (< 2h)
Category: HardcodedHack
File(s): backend/app/services/adapters/remotive.py, backend/app/services/adapters/registry.py, adapter tests
Problem: one adapter contains branches for remotive.com and remoteok.com, which are separate products and should not share runtime parsing logic.
Action: create separate adapters and register them independently.
Acceptance criteria: registry selection and adapter tests pass with no in-class site branching.
Depends on: TODO-009

TODO-015: Remove or enforce LISTING_PAGE_ALLOWED_FIELDS
Priority: P2
Effort: S (< 2h)
Category: Simplification
File(s): backend/app/services/extract/listing_extractor.py, listing extractor tests
Problem: the constant is unused and even names image_link instead of the live image_url field.
Action: delete it if obsolete, or wire it into actual enforcement after correcting the field names.
Acceptance criteria: no dead listing field contract constant remains.
Depends on: none

9) TECHNICAL DEBT REGISTER

ID	Debt Item	Type	Daily Cost	Paydown Effort	Action	Priority
TD-001	Datalayer-first source policy codified in config and tests	drift	polluted output and wrong root-cause debugging	M	reverse precedence and rewrite tests	P0
TD-002	Field arbitration split across four layers	complexity	inconsistent winners, harder fixes	L	centralize canonical arbitration	P0
TD-003	Platform-family lists duplicated in multiple modules	hardcoded-hack	silent drift on new sites	M	unify registry lookups	P1
TD-004	Broad embedded JSON/data-attribute harvesting	complexity	constant schema-noise tuning	M	narrow source ingestion	P1
TD-005	Dead compatibility stubs and exports	dead-code	misleading tests and imports	S	delete or replace	P1
TD-006	Duplicate field coverage helpers	duplication	subtle reporting drift	S	keep one implementation	P2
TD-007	Giant god-modules (core.py, acquirer.py, service.py, listing_extractor.py)	over-abstraction	high change risk, slow review	L	extract stable policy components, not more wrappers	P1
TD-008	Placeholder cookie override shipped in runtime config	config-debt	accidental unsafe prod config	S	delete and add startup validation	P1
10) RELIABILITY & INCIDENT READINESS
TODO-REL-001: Alert on traversal fallback rate by mode and domain
Priority: P1
Effort: S
Category: Reliability
File(s): backend/app/services/_batch_runtime.py, backend/app/services/crawl_metrics.py
Problem: traversal failures can currently degrade to single-page behavior without any aggregate alerting.
Action: emit metrics for traversal_fallback_used, grouped by traversal_mode_used and normalized domain; alert on spikes.
Acceptance criteria: operators can see fallback spikes per mode/domain within one dashboard view.

TODO-REL-002: Alert on blocked-page verdict spikes per acquisition method
Priority: P1
Effort: S
Category: Reliability
File(s): backend/app/services/pipeline/core.py, backend/app/services/crawl_metrics.py
Problem: blocked pages are persisted, but there is no explicit production alert when one domain suddenly starts blocking all requests.
Action: emit counters for VERDICT_BLOCKED by method and domain and add a threshold alert.
Acceptance criteria: a domain-wide blocking event pages an operator.

TODO-REL-003: Emit field-winning-source metrics for polluted canonical fields
Priority: P1
Effort: M
Category: Reliability
File(s): backend/app/services/pipeline/core.py, backend/app/services/runtime_metrics.py
Problem: current logs show some winning sources, but there is no aggregate metric telling you when datalayer or embedded_json starts winning category or availability.
Action: emit per-field winner-source counters for detail extraction.
Acceptance criteria: dashboards show winner-source distribution for top risky fields.

TODO-REL-004: Alert on duplicate listing URL persistence
Priority: P1
Effort: S
Category: Reliability
File(s): backend/app/services/pipeline/core.py
Problem: duplicate listing URLs are only a quality flag today.
Action: emit a counter when _listing_quality_flags() finds duplicates and alert on non-zero rates by run/domain.
Acceptance criteria: duplicate-listing incidents are visible without manual record inspection.

TODO-REL-005: Alert on queue stale-running count and orphan recovery
Priority: P1
Effort: S
Category: Reliability
File(s): backend/app/services/workers.py, backend/app/main.py
Problem: stale lease recovery exists, but there is no operator-facing signal that it is happening repeatedly.
Action: export stale_running, queue_recovered_stale_leases_total, and repeated recovery counts as alerts.
Acceptance criteria: repeated orphan recovery surfaces as an ops alert.

TODO-REL-006: Alert on proxy exhaustion and per-domain timeout clusters
Priority: P1
Effort: S
Category: Reliability
File(s): backend/app/services/acquisition/acquirer.py, backend/app/services/_batch_runtime.py
Problem: proxy exhaustion and URL timeouts end runs, but they are not alert-worthy events today.
Action: emit domain-tagged counters for proxy exhaustion and watchdog timeouts.
Acceptance criteria: timeouts and proxy pool exhaustion produce actionable alerts.

TODO-REL-007: Add structured log context for domain, run id, surface, and field
Priority: P1
Effort: S
Category: Reliability
File(s): backend/app/services/pipeline/core.py, backend/app/services/_batch_runtime.py
Problem: many logs describe failures but not always the field or winner-source involved.
Action: standardize structured log payloads for extraction and traversal logs.
Acceptance criteria: every critical extraction/traversal log includes domain, run id, surface, and when relevant field/source.

TODO-REL-008: Detect browser pool leaks and long-lived pooled browser count
Priority: P1
Effort: S
Category: Reliability
File(s): backend/app/services/acquisition/browser_client.py
Problem: the pool has cleanup code, but no metric/alert proves it is healthy in long-running service lifetimes.
Action: export current pool size, forced evictions, and idle cleanup counts.
Acceptance criteria: browser pool saturation or repeated forced evictions are alertable.

TODO-REL-009: Alert on schema-sanitizer rejection spikes
Priority: P1
Effort: M
Category: Reliability
File(s): backend/app/services/extract/service.py, backend/app/services/pipeline/core.py
Problem: after adding better sanitizers, operators will need visibility into rejection volumes to find broken sites.
Action: emit counters per field/source/rejection reason.
Acceptance criteria: dashboards can distinguish “site broke” from “sanitizer working”.

TODO-REL-010: Add run-level incident snapshot for partial failures
Priority: P2
Effort: M
Category: Reliability
File(s): backend/app/services/_batch_runtime.py, backend/app/services/pipeline/core.py
Problem: partial runs preserve artifacts, but there is no compact incident snapshot for triage.
Action: persist final failure snapshot with domain, surface, acquisition method, traversal summary, blocked verdict, and top rejected fields.
Acceptance criteria: one run record is enough to triage most crawl incidents.

11) SECURITY AUDIT SNAPSHOT
TODO-SEC-001: Stop accepting invalid HTTPS certificates by default
Priority: P1
Effort: S
Category: Security
File(s): backend/app/services/acquisition/browser_client.py
Problem: browser contexts currently set ignore_https_errors=True globally. That weakens content integrity for an external-content pipeline.
Action: make invalid-cert acceptance opt-in for explicit troubleshooting only; keep strict TLS by default.
Acceptance criteria: default browser contexts reject invalid certificates unless a guarded flag is enabled.

TODO-SEC-002: Remove broad bypass_csp=True from default browser contexts
Priority: P1
Effort: S
Category: Security
File(s): backend/app/services/acquisition/browser_client.py
Problem: CSP bypass increases execution surface in pages you do not control and is not obviously required for standard extraction.
Action: disable by default, measure breakage, and only enable per-platform where necessary.
Acceptance criteria: default contexts do not bypass CSP, and required exceptions are explicit.

TODO-SEC-003: Validate runtime cookie override domains at startup
Priority: P1
Effort: S
Category: Security
File(s): backend/app/services/config/extraction_rules.py, backend/app/services/acquisition/cookie_store.py, backend/app/main.py
Problem: cookie override config can whitelist cookies for arbitrary domains and currently ships a placeholder entry.
Action: fail startup on placeholder or malformed override domains and require explicit approved domains.
Acceptance criteria: invalid or placeholder cookie overrides block startup.

TODO-SEC-004: Tag and redact suspicious extracted PII before persistence
Priority: P2
Effort: M
Category: Security
File(s): backend/app/services/pipeline/core.py, backend/app/services/normalizers/__init__.py
Problem: crawled content may include emails, phone numbers, or user-generated text, and the pipeline currently persists extracted values without PII classification.
Action: add optional PII tagging/redaction for non-schema fields and review-bucket content.
Acceptance criteria: review buckets and discovered fields do not persist obvious incidental PII untagged.

TODO-SEC-005: Add integrity guards for embedded JSON from untrusted blobs
Priority: P2
Effort: M
Category: Security
File(s): backend/app/services/extract/source_parsers.py, backend/app/services/extract/service.py
Problem: the parser currently trusts broadly harvested embedded JSON and data-* blobs. On compromised or MITM content, that becomes a direct poisoning surface.
Action: couple blob-family allowlists with stricter validation and trace provenance.
Acceptance criteria: only approved blob families can influence canonical fields.

12) PERFORMANCE & SCALABILITY AUDIT
Top bottlenecks:

Repeated parsing of the same HTML into multiple trees and source inventories across acquisition, source parsing, detail extraction, and listing extraction.
Very large god-modules increase branch density and cache-unfriendly control flow.
Traversal captures full HTML fragments repeatedly; large pages can pay expensive page.content() and string concatenation costs.
Browser fallback can fully reacquire and re-extract a listing after a failed curl pass.
Browser/renderer inefficiencies:

Full-page HTML capture after every traversal step is expensive.
auto mode does scroll, maybe load-more, then pagination, even when earlier evidence might already be enough.
Listing readiness and traversal progress use generic DOM metrics instead of targeted item identity, causing wasted waits/retries.
Profiling plan:

Time acquire, parse_page_sources, extract_candidates, extract_listing_records, _reconcile_detail_candidate_values, and DB write phases with per-domain tags.
Measure page.content() count and total captured bytes in traversal modes.
Sample candidate counts per field/source to identify noisy source families.
Compare curl-only, browser-first, and retry-to-browser runs by domain/platform family.
Optimization opportunities ranked by ROI:

Narrow embedded JSON parsing and alias scans.
Eliminate duplicate HTML parsing and reuse parsed artifacts between source parsing and extraction.
Replace metric-only traversal progress with item-identity progress.
Stop full second-pass browser extraction when the first pass already produced strong structured data.
13) TEST COVERAGE GAP ANALYSIS

Path description: canonical detail-field arbitration when JSON-LD and datalayer disagree on category or availability
Why it's high risk: this is the active pollution class
Recommended test type: integration
Specific test case to write: datalayer category="page" + JSON-LD category="Camera" -> output must be Camera
Priority: P0

Path description: sub-$10 price extraction from numeric-only structured sources
Why it's high risk: current code drops valid cheap prices
Recommended test type: unit
Specific test case to write: embedded JSON price=9.99 -> output retains 9.99
Priority: P0

Path description: auto traversal with button-only pagination
Why it's high risk: current auto probe can mutate page before collection
Recommended test type: integration
Specific test case to write: page 1 -> button click -> page 2 -> next button -> page 3, no hrefs; expect pages 1–3 exactly once
Priority: P0

Path description: paginate metrics contract
Why it's high risk: operators currently get false negatives
Recommended test type: integration
Specific test case to write: paginate run with 2 pages -> traversal_pages_collected==2 and traversal_succeeded==1
Priority: P0

Path description: embedded JSON/data-attribute config blob pollution
Why it's high risk: universal contamination source
Recommended test type: integration
Specific test case to write: data-config='{\"title\":\"Cookie Banner\"}' plus H1 product title -> canonical title must stay H1/JSON-LD
Priority: P1

Path description: multi-push datalayer arbitration
Why it's high risk: first valid push is often stale
Recommended test type: unit
Specific test case to write: first push pageview, second push product detail -> parser must choose second
Priority: P1

Path description: listing duplicate suppression after traversal
Why it's high risk: duplicates currently only flagged after save
Recommended test type: integration
Specific test case to write: page 1 and page 2 contain repeated product URL -> only one persisted record
Priority: P1

Path description: platform registry drift
Why it's high risk: duplicated platform sets across modules
Recommended test type: contract
Specific test case to write: all platform-family consumers derive membership from one registry and remain identical
Priority: P2

14) “IF I OWNED THIS CODEBASE” — TOP 12 ACTIONS

Reverse datalayer-vs-JSON-LD precedence for detail fields. Why: it removes the current highest-severity correctness risk. How long: half day. What I would not touch yet: LLM cleanup flow; it is not the primary pollution source.
Add one canonical post-arbitration sanitizer for risky fields. Why: it creates a true final gate before persistence. How long: 1 day. What I would not touch yet: adapter internals.
Fix paginate traversal summary schema. Why: it restores operator trust in traversal outcomes immediately. How long: 1 hour. What I would not touch yet: traversal UX.
Split auto-mode pagination probe from execution. Why: it addresses the most likely real traversal breakage. How long: half day. What I would not touch yet: scroll heuristics.
Remove the sub-$10 price rejection. Why: it is a concrete shared correctness bug. How long: 1 hour. What I would not touch yet: currency heuristics.
Narrow embedded JSON/data-attribute ingestion. Why: it shrinks the pollution surface materially. How long: 1 day. What I would not touch yet: semantic extractor rules.
Dedupe listing records at persistence. Why: it blocks duplicate output even if traversal still over-collects. How long: 2 hours. What I would not touch yet: listing scoring heuristics.
Consolidate platform-family membership into one registry. Why: it removes current hardcoded drift. How long: 1 day. What I would not touch yet: splitting every giant module.
Delete dead compatibility stubs and duplicate helper copies. Why: it improves auditability quickly. How long: 2 hours. What I would not touch yet: public API contracts.
Remove placeholder cookie overrides and tighten browser security defaults. Why: low-effort security hardening with little downside. How long: 2 hours. What I would not touch yet: proxy architecture.
Add winner-source and sanitizer-rejection metrics. Why: future extraction regressions become observable instead of anecdotal. How long: half day. What I would not touch yet: dashboards beyond the first few counters.
Then start extracting a real policy engine from service.py and core.py. Why: after the hot correctness fixes, this creates the highest leverage for maintainability. How long: 2–3 days. What I would not touch yet: frontend.
