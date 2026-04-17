DELIVERABLE 1 — File role summary
═══════════════════════════════════════════════════════════════════
| File | Primary role | Stage (acquire/unify/publish/discover/adapter/review/runtime/crud) | Contains page_type/surface branches? (Y/N) |
|------|--------------|---------------------------------------------------------------------|---------------------------------------------|
| acquirer.py | Orchestrates curl-to-Playwright waterfall acquisition | acquire | N |
| policy.py | Defines runtime policies for browser escalation | acquire | Y |
| browser_client.py | Playwright context management and HTML rendering | acquire | Y |
| browser_readiness.py | Wait loops for page hydration and DOM stability | acquire | Y |
| recovery.py | Attempts adapter recovery on blocked pages | acquire | Y |
| traversal.py | Navigates pagination and infinite scroll interfaces | acquire | Y |
| base.py | Base interface for platform adapters | adapter | N |
| registry.py | Routes URLs to specific platform adapters | adapter | Y |
| init.py | Exports review and promotion service models | review | N |
| crawl_crud.py | Database operations for crawl runs and logs | crud | N |
| crawl_ingestion_service.py | Creates run records from CSV payloads | crud | N |
| llm_runtime.py | LLM completion calls and prompt generation | runtime | N |
| listing_flow.py | Orchestrates listing record extraction and persistence | publish | Y |
| listing_helpers.py | Sanitization rules for listing DOM records | publish | Y |
| types.py | Dataclass boundaries for pipeline stages | runtime | N |
| review_shaping.py | Normalizes fields for the human review bucket | publish | N |
| trace_builders.py | Compiles manifest and field provenance logs | publish | N |
| listings.py | Normalizes arrays into structured listing records | unify | Y |
| schema_service.py | Infers and manages persistent domain schemas | unify | Y |
| network_inventory.py | Maps XHR payloads to known extraction schemas | discover | Y |
| signal_inventory.py | Scores HTML to detect listings and shells | discover | Y |
| state_inventory.py | Maps nested JSON blobs to listing arrays | discover | Y |
| detail_flow.py | Orchestrates detail record extraction and persistence | publish | N |
═══════════════════════════════════════════════════════════════════
DELIVERABLE 2 — Branch inventory
═══════════════════════════════════════════════════════════════════
| File:line | Function/class | Branch variable | Branch values observed | What changes across branches (≤25 words) | Classification |
|-----------|----------------|-----------------|------------------------|--------------------------------------------|----------------|
| policy.py:L107 | requires_browser_first | platform_family | generic_jobs, job families | forces browser rendering if the domain resolves to a job platform | ESSENTIAL |
| policy.py:L133 | browser_escalation_decision | surface | ecommerce_listing, job_listing, ecommerce_detail, job_detail | validates if surface is supported before evaluating missing data rules | ACCIDENTAL |
| policy.py:L152 | browser_escalation_decision | surface | *.endswith("listing") | suppresses browser escalation if page has strong listing signals despite shell | ESSENTIAL |
| policy.py:L158 | browser_escalation_decision | surface | *.endswith("detail") | escalates to browser if JS shell detected on detail page | ESSENTIAL |
| policy.py:L176 | browser_escalation_decision | surface | *.endswith("detail") | blocks structured data (JSON-LD) from overriding JS shell escalation on detail pages | ESSENTIAL |
| policy.py:L214 | decide_acquisition_execution | surface | ecommerce_listing, ecommerce_detail | assigns diagnostic tracking payload (listing_completeness vs variant_completeness) | ACCIDENTAL |
| policy.py:L240 | resolve_traversal_surface_policy | surface | *.endswith("_detail") | disables pagination/scroll traversal automatically for detail pages | ESSENTIAL |
| policy.py:L245 | resolve_traversal_surface_policy | surface | job | selects job-specific DOM card selectors over commerce selectors | ESSENTIAL |
| policy.py:L325 | should_retry_browser_launch_profile | surface | *.endswith("_listing") | enables profile retry (e.g., fallback to Chrome) on low-value listing pages | ESSENTIAL |
| policy.py:L404 | diagnose_commerce_surface_page | surface | ecommerce_listing, ecommerce_detail | aborts diagnostics early if not an ecommerce surface | ACCIDENTAL |
| policy.py:L467 | diagnose_job_surface_page | surface | job_listing, job_detail | aborts diagnostics early if not a job surface | ACCIDENTAL |
| browser_client.py:L323 | _fetch_rendered_html_attempt | surface | *.endswith("listing") | awaits listing-specific card hydration rather than generic detail readiness | ESSENTIAL |
| browser_readiness.py:L21 | _is_listing_surface | surface | *.endswith("listing") | alias check evaluating if surface requires listing handling | ACCIDENTAL |
| browser_readiness.py:L65 | _wait_for_listing_readiness | surface | *.endswith("listing") | early exit returning None if page is not a listing | ACCIDENTAL |
| browser_readiness.py:L68 | _wait_for_listing_readiness | surface | job_listing | picks job card DOM selectors instead of ecommerce card selectors | ESSENTIAL |
| browser_readiness.py:L197 | _detail_readiness_selectors | surface | job_detail, ecommerce_detail | picks specific DOM elements (price vs salary) to await hydration | ESSENTIAL |
| browser_readiness.py:L218 | wait_for_surface_readiness | surface | .endswith("listing") | routes to listing readiness loop instead of detail readiness loop | ESSENTIAL |
| recovery.py:L29 | recover_blocked_listing_acquisition | surface | ecommerce_listing, job_listing | disables adapter-based recovery specifically for detail pages | ESSENTIAL |
| traversal.py:L382 | _card_selectors_for_surface | surface | job | selects job-specific DOM cards for infinite scroll verification | ESSENTIAL |
| traversal.py:L422 | apply_traversal_mode | surface | .endswith("_detail") | explicitly aborts any traversal logic if on a detail page | ESSENTIAL |
| registry.py:L55 | try_blocked_adapter_recovery | surface | ecommerce_listing, ecommerce_detail, job_listing, job_detail | aborts API recovery if surface is totally unrecognized | ACCIDENTAL |
| listing_flow.py:L39 | listing_quality_flags | surface | job_listing | flags job record payload as low-quality if context fields are missing | ESSENTIAL |
| listing_flow.py:L61 | listing_quality_flags | surface | ecommerce | flags payload if duplicate URLs are found across listing cards | ESSENTIAL |
| listing_flow.py:L205 | extract_listing | surface | job_listing | aborts early with listing_detection_failed instead of running loading-shell heuristics | ESSENTIAL |
| listing_helpers.py:L31 | _looks_like_loading_listing_shell | surface | listing | aborts shell heuristic evaluation if surface is not listing | ACCIDENTAL |
| listing_helpers.py:L34 | _looks_like_loading_listing_shell | surface | job | disables loading shell detection entirely for job surfaces | ESSENTIAL |
| listing_helpers.py:L45 | _sanitize_listing_record_fields | surface | job | bypasses job-specific cleanup steps for ecommerce records | ESSENTIAL |
| listing_helpers.py:L62 | _sanitize_listing_record_fields | surface | job | strips transactional action links strictly from non-job listings | ESSENTIAL |
| listings.py:L83 | canonical_listing_fields | surface | job | defines job-specific canonical schema vs ecommerce schema | ESSENTIAL |
| listings.py:L112 | normalize_record_fields | surface | job, job | infers currency from URL only on ecommerce surfaces | ESSENTIAL |
| listings.py:L186 | apply_surface_record_contract | surface | job | applies job-specific identifier backfills and url synthesis | ESSENTIAL |
| listings.py:L286 | normalize_ld_item | surface | ecommerce | maps JSON-LD 'offers' attributes to canonical ecommerce fields | ESSENTIAL |
| listings.py:L299 | normalize_ld_item | surface | job | maps JSON-LD 'hiringOrganization' to canonical job fields | ESSENTIAL |
| listings.py:L454 | _normalize_generic_item | surface | ecommerce | drops record entirely if it looks like a size/color variant option | ESSENTIAL |
| listings.py:L480 | _normalize_generic_item | surface | ecommerce | attempts deep URL extraction from raw payload if missing on ecommerce | ESSENTIAL |
| listings.py:L494 | _normalize_generic_item | surface | job | forces currency inference if a price exists on a non-job surface | ESSENTIAL |
| listings.py:L501 | _normalize_generic_item | surface | ecommerce | invalidates record if no URL and no price exists on ecommerce surface | ESSENTIAL |
| listings.py:L558 | _preferred_generic_item_values | surface | job | routes location keys for job surfaces | ESSENTIAL |
| listings.py:L586 | _preferred_generic_item_values | surface | job | routes identifier keys for job surfaces | ESSENTIAL |
| listings.py:L599 | _preferred_generic_item_values | surface | job | routes category keys for job surfaces | ESSENTIAL |
| listings.py:L602 | _preferred_generic_item_values | surface | job | routes posting date keys for job surfaces | ESSENTIAL |
| listings.py:L605 | _preferred_generic_item_values | surface | job | routes description keys for job surfaces | ESSENTIAL |
| schema_service.py:L46 | _field_allowed_for_surface | surface | job_listing, job_detail | prevents ecommerce schema spillover into job schemas | ESSENTIAL |
| schema_service.py:L48 | _field_allowed_for_surface | surface | ecommerce_listing, ecommerce_detail | prevents job schema spillover into ecommerce schemas | ESSENTIAL |
| network_inventory.py:L56 | payload_spec_name | surface | job | ignores job-platform API intercept heuristics for commerce surfaces | ESSENTIAL |
| signal_inventory.py:L61 | collect_listing_signal_summary | surface | *.endswith("listing") | zeroes out listing score automatically for detail surfaces | ESSENTIAL |
| signal_inventory.py:L98 | collect_listing_signal_summary | surface | job | grants score multiplier if job listing has multiple title candidates | ESSENTIAL |
| signal_inventory.py:L120 | find_promotable_iframe_sources | surface | job | restricts iframe promotion heuristics strictly to job surfaces | ESSENTIAL |
| signal_inventory.py:L154 | assess_extractable_html | surface | *.endswith("listing") | runs JSON-LD count and NEXT_DATA signal checks for listings | ESSENTIAL |
| signal_inventory.py:L208 | assess_extractable_html | surface | *.endswith("detail") | runs field-hit thresholds (price, sku) strictly for detail surfaces | ESSENTIAL |
| state_inventory.py:L114 | _collection_from_specs | surface | ecommerce_listing, job_listing | queries predefined glom paths specifically indexed by surface | ESSENTIAL |
═══════════════════════════════════════════════════════════════════
DELIVERABLE 3 — Cross-reference to Batch A (dedupe)
═══════════════════════════════════════════════════════════════════
| Batch C file:line | Upstream extract/ branch it mirrors (file:line if knowable, else "unknown") | Relationship (echo / consumer / independent) |
|-------------------|-------------------------------------------------------------------------------|-----------------------------------------------|
| policy.py:L240 | Unknown (Batch A: ESSENTIAL) | echo — enforces traversal block matched by listing extractor |
| traversal.py:L422 | Unknown (Batch A: ESSENTIAL) | echo — aborts traversal on detail identical to extract/ pipeline |
| listings.py:L83 | Unknown (Batch A: ESSENTIAL) | echo — enforces schema split applied by listing_extractor.py |
| schema_service.py:L46 | Unknown (Batch A: ESSENTIAL) | independent — manages DB persistence constraints directly |
═══════════════════════════════════════════════════════════════════
DELIVERABLE 4 — Ranked removability list
═══════════════════════════════════════════════════════════════════
| Rank | File:line | Classification | Collapse strategy | Estimated blast radius (this file / this module / cross-module) |
|------|-----------|----------------|-------------------|------------------------------------------------------------------|
| 1 | browser_readiness.py:L21 | ACCIDENTAL | inline the string check where needed | this file |
| 2 | browser_readiness.py:L65 | ACCIDENTAL | let readiness loop fail naturally; remove early exit | this file |
| 3 | listing_helpers.py:L31 | ACCIDENTAL | evaluate shell DOM blindly; remove early exit | this file |
| 4 | policy.py:L404 | ACCIDENTAL | execute DOM heuristics regardless of surface | this module |
| 5 | policy.py:L467 | ACCIDENTAL | execute DOM heuristics regardless of surface | this module |
| 6 | policy.py:L133 | ACCIDENTAL | drop bounds check; evaluate JS shell rules blindly | this module |
| 7 | policy.py:L214 | ACCIDENTAL | consolidate expected evidence strings blindly | this module |
| 8 | registry.py:L55 | ACCIDENTAL | allow adapter logic to decline URLs blindly | cross-module |
═══════════════════════════════════════════════════════════════════
DELIVERABLE 5 — Invariant-risk flags
═══════════════════════════════════════════════════════════════════
policy.py:L107 — Inv. 29 risk. Branch hardcodes Playwright escalation based on job family classification. Removing it breaks the abstraction that generic sites operate via generic policies, forcing hardcoded logic into the acquisition runtime.
policy.py:L158 — Inv. 16 risk. Branch forces browser escalation specifically for detail pages showing JS shells. Removing it blindly applies rendering to non-detail shells or disables rendering for detail pages, violating user surface directives.
schema_service.py:L46 — Inv. 11 risk. Branch enforces strict surface-based schema bounds before database persistence. Removing it allows ecommerce concepts (variants, cart details) to permanently pollute job listing entities.
schema_service.py:L48 — Inv. 12 risk. Branch enforces strict surface-based schema bounds before database persistence. Removing it allows job concepts (salary, remote status) to permanently pollute ecommerce product entities.
listing_flow.py:L205 — Inv. 8 risk. Branch intercepts zero-item job boards and instantly fails them with listing_detection_failed. Removing it allows job boards to fall back to detail extraction, violating the listing invariant.
signal_inventory.py:L154 — Inv. 6 risk. Branch routes to listing-specific NEXT_DATA thresholds. Removing it merges listing and detail signal counting, breaking the confidence scoring that determines which extraction mechanism wins arbitration.
listings.py:L454 — Inv. 11 risk. Branch filters out size/color dropdown variants masquerading as distinct listing items. Removing it pollutes the canonical ecommerce listing array with raw JSON variant fragments.

Model 10:00 PM
═══════════════════════════════════════════════════════════════════
DELIVERABLE 1 — File role summary
═══════════════════════════════════════════════════════════════════
File	Primary role	Expected legitimate concerns (≤20 words)	Contains at least one leak? (Y/N)
pipeline/core.py	Legacy pipeline entrypoints and global stage orchestration.	orchestration, stage sequencing, failure recovery, log injection	N
pipeline/stages.py	Concrete execution steps comprising the pipeline chain.	stage implementation, metrics recording, branching on verdict	Y
pipeline/runner.py	Sequential orchestrator for pipeline stages and hooks.	orchestration, error catching, elapsed timing, hook firing	N
pipeline/field_normalization.py	Enforces surface contracts and filters internal record fields.	contract validation, stripping internal keys, coverage math	N
pipeline/utils.py	Generic utilities for text cleaning and dict compaction.	string coercion, dict filtering, fingerprinting	Y
publish/metadata.py	Formats trace metadata and discovered fields for database.	field discovery status updates, commit metadata	Y
publish/verdict.py	Computes extraction success status based on core fields.	verdict computation, extraction completeness	N
═══════════════════════════════════════════════════════════════════
DELIVERABLE 2 — Leak inventory
═══════════════════════════════════════════════════════════════════
File:line	Function/class	Field touched (canonical name or page-native name)	Leak kind (RE-PARSE/RE-CLEAN/RE-DERIVE/RE-ARBITRATE)	Evidence snippet (≤15 words, verbatim)	Recommended extract-side owner (≤10 words)
pipeline/stages.py:L48	_discover_child_listing_candidate_from_soup	url / child_listing_url	RE-PARSE	for anchor in soup.select("a[href]"):	discover or extract module
pipeline/stages.py:L74	_discover_child_listing_candidate_from_soup	title / anchor text	RE-CLEAN	" ".join(anchor.get_text(" ", strip=True).split()).lower()	extract text normalizers
pipeline/stages.py:L75	_discover_child_listing_candidate_from_soup	title / anchor text	RE-DERIVE	if text and any(token in text for token in PIPELINE_CONFIG...	extract or discover heuristic
pipeline/stages.py:L101	_looks_like_category_tile_listing	url, title, image_url	RE-DERIVE	if (image_value.startswith("data:image/") or "icon" in title_value...	extract listing quality assessment
pipeline/utils.py:L26	_clean_page_text	generic text	RE-CLEAN	unescape(str(value or "")).replace("\u00a0", " ")	extract candidate processing
pipeline/utils.py:L39	_normalize_committed_field_name	field names	RE-CLEAN	text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)	extract or normalize schema mappers
pipeline/utils.py:L50	_review_bucket_fingerprint	review_bucket values	RE-CLEAN	normalized_value = _normalize_review_value(value)	extract or normalize review formatters
publish/metadata.py:L16	_clean_candidate_text	generic text	RE-CLEAN	" ".join(str(value).split()).strip()	extract candidate processing
═══════════════════════════════════════════════════════════════════
DELIVERABLE 3 — Invariant 12 probe (page-native identity)
═══════════════════════════════════════════════════════════════════
None
═══════════════════════════════════════════════════════════════════
DELIVERABLE 4 — Invariant-risk flags (non-12)
═══════════════════════════════════════════════════════════════════
pipeline/stages.py:L48 — Inv. 13 (noise filtering) risk. _discover_child_listing_candidate_from_soup manually selects a[href] tags from the entire soup object to discover child listings, without respecting the established container noise policies (e.g., stripping footers/nav bars) that the extract stage enforces. This can leak navigation chrome URLs into the pipeline's retry logic.
═══════════════════════════════════════════════════════════════════
DELIVERABLE 5 — Leak concentration summary
═══════════════════════════════════════════════════════════════════
File	RE-PARSE count	RE-CLEAN count	RE-DERIVE count	RE-ARBITRATE count	Inv. 12 violations	Total
pipeline/core.py	0	0	0	0	0	0
pipeline/stages.py	1	1	2	0	0	4
pipeline/runner.py	0	0	0	0	0	0
pipeline/field_normalization.py	0	0	0	0	0	0
pipeline/utils.py	0	3	0	0	0	3
publish/metadata.py	0	1	0	0	0	1
publish/verdict.py	0	0	0	0	0	0
TOTAL	1	5	2	0	0	8
info
Google AI models may make mistakes, so double-check outputs.