Fix the following issues. The issues can be from different files or can overlap on same lines in one file.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/models/llm.py around lines 44 - 48, Define the outcome strings as a centralized constant/enum and update the CheckConstraint to use those constants: add a StrEnum (e.g., LLMOutcome with SUCCESS="success" and ERROR="error") or module-level constants, then replace the literal strings in __table_args__' CheckConstraint (name="ck_llm_cost_log_outcome") to reference LLMOutcome.SUCCESS.value and LLMOutcome.ERROR.value (or the constants) so service code can import LLMOutcome and avoid magic strings when logging LLM calls.

- 

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/config/extraction_rules.py at line 144, Define a single canonical noise-word collection and reuse it instead of duplicating terms: create a shared symbol like NOISE_WORDS = ("popular","sale","discount","off") and then set OPTION_VALUE_NOISE_WORDS = NOISE_WORDS and build VARIANT_OPTION_TEXT_CHILD_DROP_PATTERNS by composing a regex from NOISE_WORDS (e.g., join escaped words with "|" and include the extra multiword phrases like "sold out", "unavailable", "left in stock"); update references to use the shared symbol so future updates stay in sync.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/config/llm_runtime.py around lines 22 - 24, DEFAULT_LLM_TOKEN_PRICING_PER_MILLION_USD currently only lists "groq/llama-3.3-70b-versatile" while SUPPORTED_LLM_PROVIDERS also includes "anthropic" and "nvidia", so add sensible default per-million-token pricing entries for those providers (or a safe fallback entry) to DEFAULT_LLM_TOKEN_PRICING_PER_MILLION_USD so usage tracking always has pricing; update the mapping to include keys for representative model identifiers (or provider-level keys) for "anthropic" and "nvidia" and ensure any code that reads DEFAULT_LLM_TOKEN_PRICING_PER_MILLION_USD (e.g., pricing lookup logic) will fall back to these defaults when token_pricing_json is missing.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/config/llm_runtime.py around lines 76 - 100, get_token_pricing currently returns an empty dict if the user-provided token_pricing_json parses but all entries are filtered out; change it to fall back to DEFAULT_LLM_TOKEN_PRICING_PER_MILLION_USD when the resulting pricing is empty. After the loop in get_token_pricing, check if pricing is empty and if so populate pricing from DEFAULT_LLM_TOKEN_PRICING_PER_MILLION_USD (convert its "provider/model" keys into (provider.strip().lower(), model.strip().lower()) tuples and Decimal values just like the main loop does) or simply re-run the same parsing logic on that default mapping, ensuring the returned dict has the same type shape as before; reference get_token_pricing, token_pricing_json, DEFAULT_LLM_TOKEN_PRICING_PER_MILLION_USD and SUPPORTED_LLM_PROVIDERS.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/data_enrichment/service.py around lines 739 - 751, The module currently compiles DATA_ENRICHMENT_MATERIAL_CONTEXT_STRIP_PATTERNS at import time via _compiled_material_strip_patterns(), causing logger.warning() to run before logging is configured; change this to defer compilation and logging by removing the module-level call to create COMPILED_DATA_ENRICHMENT_MATERIAL_CONTEXT_STRIP_PATTERNS and instead implement a lazy accessor (e.g., get_compiled_material_strip_patterns() or cache the result on first call inside _compiled_material_strip_patterns()) that compiles patterns on first use and emits warnings at runtime when logging is configured; update any code that referenced COMPILED_DATA_ENRICHMENT_MATERIAL_CONTEXT_STRIP_PATTERNS to call the new accessor so no regex compilation or logger.warning() occurs at import time.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/data_enrichment/shopify_catalog.py around lines 49 - 57, The normalize_taxonomy_token function contains a redundant .casefold() because callers (notably tokenize_text) already casefold tokens; remove the .casefold() call from normalize_taxonomy_token so it only trims and applies suffix rules, and ensure tokenize_text continues to pass a casefolded token to normalize_taxonomy_token (or else move casefolding to tokenize_text consistently); update any other callers of normalize_taxonomy_token to either pre-casefold or accept the new expectation to avoid double lowercasing.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/data_enrichment/shopify_catalog.py around lines 166 - 171, The scoring weights (1.0 implicit for primary, 0.35, 0.15, 0.3) used when computing `score` in shopify_catalog.py should be moved to a config constant and consumed from there; add a config entry DATA_ENRICHMENT_TAXONOMY_SCORE_WEIGHTS in app/services/config/data_enrichment.py with keys "primary","secondary","tertiary","attribute", import that constant into the module that defines `score`, and replace the hardcoded multipliers in the `score` expression with lookups like weights["secondary"], weights["tertiary"], weights["attribute"] (use weights.get(..., <current literal>) as a safe fallback) so tuning happens via config rather than inline literals.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/data_enrichment/shopify_catalog.py around lines 196 - 214, The code sorts source_tokens alphabetically then joins into joined_source which breaks multi-word phrase matching in the context_terms check (see joined_source, source_tokens, DATA_ENRICHMENT_TAXONOMY_CONTEXT_BLOCKS and the if not any(term in joined_source ...) conditional). Fix by not alphabetically sorting tokens: either preserve original token order when building joined_source (join source_tokens in their original sequence) so phrase substring checks work, or switch to a bag-of-words check: for each context_term in context_terms split into words, casefold and ensure every word exists in the source_tokens set (casefolded) instead of using substring membership; alternatively implement n-gram sliding-window matching over the original token list if exact phrase adjacency is required. Ensure you update the code paths around context_terms/path_terms checks accordingly.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/detail_extractor.py around lines 1123 - 1124, The code creates a second full BeautifulSoup parse (raw_soup) duplicating memory already held in soup from primary_dom_context; instead, remove the extra parse and reuse the existing soup (or dom_parser) where raw_soup is used, or defer creating raw_soup until actually needed (lazy init) by assigning None and parsing on first access; update references to raw_soup to use soup (or the lazy initializer) and keep the primary_dom_context/dom_parser usage intact.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/detail_extractor.py around lines 957 - 963, The equality check between record.get("category") and breadcrumb_category can trigger unnecessary DOM completion because it compares raw strings; normalize both sides (e.g., lowercasing, trimming, collapsing whitespace, and normalizing separators like "/" "|" ">" to a single delimiter, or tokenizing and comparing category segments for prefix/partial matches) before comparing. Update the logic around normalized_surface, breadcrumb_category_from_dom, breadcrumb_soup and record.get("title") to compute a normalized_category = normalize_category(record.get("category")) and normalized_breadcrumb = normalize_category(breadcrumb_category) (or perform segment-wise comparison) and only return True when those normalized values are not equivalent; keep the breadcrumb DOM fetch path the same but avoid forcing DOM tier when normalized values match. Ensure the helper name (e.g., normalize_category) is used so reviewers can find the change.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/detail_identity.py around lines 617 - 623, Extract the magic number 8 used as the minimum identity code length into a named config constant (e.g., DETAIL_IDENTITY_CODE_MIN_LENGTH) under the app/services/config module and use that constant in _normalized_detail_identity_code as well as the other occurrences noted (the other functions that reference the same threshold). Update _normalized_detail_identity_code to reference the config constant instead of the literal 8 (function name: _normalized_detail_identity_code) and import the constant from the config module so the threshold is centralized and easily tunable.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/detail_identity.py around lines 140 - 148, The hardcoded set detail_roots in detail_identity.py should be moved into the config package and referenced by a clear constant name (e.g., JOB_LISTING_DETAIL_PATH_MARKERS) so service code contains no static tokens; create or add to the existing app/services/config module a constant containing {"job","jobs","opening","position","posting","career","careers"}, export it, then update detail_identity.py to import and use that constant (replace the local detail_roots symbol with the imported config symbol) and ensure any tests or callers reference the new config constant.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/detail_identity.py around lines 28 - 50, The hardcoded frozenset _DETAIL_IDENTITY_STOPWORDS in detail_identity.py should be moved into the configuration layer: create DETAIL_IDENTITY_STOPWORDS in app/services/config/extraction_rules.py (as a frozenset containing the same tokens) and then remove the local _DETAIL_IDENTITY_STOPWORDS and import DETAIL_IDENTITY_STOPWORDS in backend/app/services/extract/detail_identity.py wherever _DETAIL_IDENTITY_STOPWORDS is referenced (preserve name usage or alias if needed), ensuring any tests or callers still reference the imported symbol and updating imports accordingly.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/detail_raw_signals.py around lines 33 - 39, The parameter current_title in breadcrumb_category_from_dom is typed too broadly as object; change its annotation to str | None = None to reflect that string-like values are expected (since clean_text() is applied downstream), and update any related signatures or callers such as breadcrumb_labels_from_dom to accept str | None consistently so type checkers and callers get correct hints.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/detail_raw_signals.py around lines 54 - 59, The if labels: check is incorrectly indented outside the inner for container loop so results from earlier containers get overwritten; inside the loop that iterates containers for each selector (the loop using DETAIL_BREADCRUMB_CONTAINER_SELECTORS and container in soup.select(...)), after calling _breadcrumb_labels_from_container(container) and _trim_breadcrumb_labels(labels, current_title=current_title) immediately check if labels and return them (i.e., move the if labels: return labels into the inner loop scope) so a non-empty breadcrumb from any container is returned instead of only the last one.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/detail_raw_signals.py around lines 97 - 108, The _trim_breadcrumb_labels function is using .strip().lower() for the root-label check but .casefold() for title comparison; update the first comparison to use clean_text(...) .casefold() (or at least .casefold() instead of .lower() and drop the redundant .strip()) so both branches use consistent Unicode-aware case normalization; also ensure you compare against DETAIL_BREADCRUMB_ROOT_LABELS values that have been casefolded (or apply .casefold() to those constants at comparison time) so the root-label check remains correct.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/field_value_core.py around lines 475 - 480, The ampersand check in coerce_text is too broad and flags normal text like "AT&T"; instead detect real HTML entities before calling html_to_text by looking for patterns such as an ampersand followed by alphanumeric or numeric character references and a semicolon (i.e., an entity pattern) — update the condition in coerce_text to use a precise entity detection (e.g., a regex search) and only call html_to_text when that entity pattern is present; keep use of text_or_none and html_to_text unchanged and reference coerce_text, html_to_text, and text_or_none when making the change.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/field_value_dom.py around lines 490 - 501, The function _variant_option_node_text currently deletes the unused parameter via del field_name; instead rename the parameter to _field_name in the function signature (def _variant_option_node_text(node: Tag, _field_name: str) -> str:) and remove the del line, or if renaming is invasive, assign _ = field_name at the top and remove del; update any internal references if present and ensure callers remain compatible.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/field_value_dom.py around lines 49 - 53, The tuple comprehension that builds VARIANT_OPTION_CHILD_DROP_RE currently calls re.compile on every entry of VARIANT_OPTION_TEXT_CHILD_DROP_PATTERNS at import time and will raise re.error for malformed patterns; change the logic in field_value_dom.py to iterate the patterns, skip blank strings, attempt re.compile(str(pattern), re.I) inside a try/except re.error block, log the invalid pattern and continue (do not let the exception bubble), and collect only successfully compiled regex objects into VARIANT_OPTION_CHILD_DROP_RE so the module can import even if some patterns are invalid.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/normalizers/__init__.py around lines 170 - 172, The current check "if mapped:" in the availability URL lookup will skip falsy but valid mapped values (e.g., "", 0, False); change the conditional in the block that computes mapped from AVAILABILITY_URL_MAP (the mapped variable computed from (AVAILABILITY_URL_MAP or {}).get(lowered.rstrip("/"))) to explicitly test for None (e.g., "if mapped is not None:") so legitimate falsy mappings are returned, or alternatively add a clear comment next to AVAILABILITY_URL_MAP explaining that falsy values are intentionally ignored if that is desired.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/product_intelligence/discovery.py around lines 415 - 420, The helper _google_native_blocked currently calls classify_blocked_page(html, 200) with a hardcoded 200 status which can mislead classification; update _google_native_blocked to accept and forward the real HTTP status when available (e.g., add an optional status parameter to _google_native_blocked or retrieve the response.status from the caller) and pass that actual status into classify_blocked_page instead of 200, or if the real status truly isn’t available, document in the _google_native_blocked docstring why 200 is intentionally used and consider passing None/0 to classify_blocked_page so the classifier knows status is unknown; reference the functions _google_native_blocked and classify_blocked_page when making the change.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/product_intelligence/service.py around lines 436 - 438, The loop currently calls session.flush() per iteration to get source.id, causing N+1 DB round-trips; instead collect created ProductIntelligenceSourceProduct instances (e.g., append (index, source) to a local sources_to_add list while still calling session.add(source) or use session.add_all), remove the per-iteration await session.flush(), then call a single await session.flush() after the loop so SQLAlchemy populates all source.id values, and finally populate source_product_ids_by_index from the collected sources_to_add; keep calls to _resolve_source_snapshot and _resolved_source_url unchanged but do their uses while collecting sources.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/product_intelligence/service.py around lines 181 - 182, Replace the hardcoded role string used in the authorization check with a config constant: add ADMIN_ROLE = "admin" in a config module (e.g. app/services/config/product_intelligence.py or a shared roles config) and update the conditional that currently checks user.role != "admin" in the service (referencing user.role and ProductIntelligenceJob.user_id) to use that ADMIN_ROLE constant instead.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/product_intelligence/service.py around lines 633 - 634, Extract the hardcoded final-status strings into a config constant (e.g., FINAL_CRAWL_STATUSES or CRAWL_RUN_FINAL_STATUSES) under the app/services/config package, export it as a set containing "completed", "failed", "killed", "proxy_exhausted", then replace the inline set used with candidate_run.status not in CRAWL_RUN_FINAL_STATUSES by importing that constant into service.py; ensure the config name is unique (e.g., CRAWL_RUN_FINAL_STATUSES) and referenced where candidate_run.status is checked so all status literals live in app/services/config.

- Verify each finding against the current code and only fix it if needed.

In @backend/tests/services/test_data_enrichment.py around lines 397 - 399, The function test_data_enrichment_variant_dict_values_do_not_pollute_sizes_or_availability has a redundant parentheses in its return annotation; change the annotation from "-> (None)" to the conventional "-> None" on the function definition (or shorten the function name if line length is a concern) so the signature reads with a plain None return type.

- Verify each finding against the current code and only fix it if needed.

In @backend/tests/services/test_product_intelligence.py around lines 571 - 577, Move the helper function _fake_search_url so it is defined before any tests that call it; locate the tests that invoke _fake_search_url and cut/paste the def _fake_search_url(query: str, limit: int) -> str block above the first such test, preserving the internal import from urllib.parse and the function signature to keep behavior unchanged so reading flows top-to-bottom.

- Verify each finding against the current code and only fix it if needed.

In @backend/tests/services/test_product_intelligence.py around lines 1233 - 1234, The fake_search_results coroutine currently suppresses unused-parameter warnings with "del provider, limit"; make this consistent by applying the same unused-parameter suppression to the other fake_search_results variants in this test file (the other functions that accept provider, query, and optional limit), i.e., add "del provider, limit" at the top of each of those fake_search_results implementations so all mocks use the same pattern and avoid linter warnings consistently.

- Verify each finding against the current code and only fix it if needed.

In @backend/tests/services/test_product_intelligence.py around lines 492 - 493, The assertion for second and third is too weak; replace the truthiness check with explicit content assertions matching what you did for first: assert the expected properties (e.g., .url or other fields) and lengths of second and third (and/or their first elements) to verify exact values and ordering—locate the variables first, second, third in this test and add assertions like comparing second[0].url and third[0].url (or their full dict/object content) to the expected URLs/values.

- Verify each finding against the current code and only fix it if needed.

In @backend/tests/services/test_selectolax_css_migration.py around lines 94 - 96, Several test functions (e.g., test_listing_extractor_prefers_row_detail_link_and_name_over_breadcrumb_links and the others at the noted occurrences) use the non-idiomatic return annotation "-> (None)"; change each signature to use the standard "-> None" (remove the redundant parentheses) so annotations are conventional; if line breaks caused by long function names are forcing the formatter to produce "(None)", collapse the closing parenthesis and return annotation onto the same line (or shorten the function name) and update the formatter settings so future auto-formatting preserves "-> None".

- Verify each finding against the current code and only fix it if needed.

In @backend/tests/services/test_structure.py around lines 241 - 245, The test test_private_service_imports_do_not_drift currently asserts equality between offenders and ALLOWED_PRIVATE_SERVICE_IMPORTS, which checks both missing and stale allowlist entries; rename the test to reflect the bidirectional nature (for example test_private_service_imports_match_allowlist or test_private_service_imports_allowlist_is_exact) and update its docstring or comment accordingly, and keep the assertion and references to _private_service_imports and ALLOWED_PRIVATE_SERVICE_IMPORTS unchanged so reviewers understand the intent.

- Verify each finding against the current code and only fix it if needed.

In @backend/tests/services/test_structure.py around lines 228 - 238, The test test_data_enrichment_taxonomy_matching_does_not_use_manual_category_alias_maps currently does a raw string search which can hit comments/docstrings; change it to parse the config file with Python's ast (ast.parse) and walk the module nodes to detect actual symbol usage (e.g., check ast.Assign targets, ast.Name, ast.Attribute, or ast.Constant keys) for the forbidden names ("DATA_ENRICHMENT_TAXONOMY_TOKEN_ALIASES", "DATA_ENRICHMENT_TAXONOMY_CONTEXTUAL_TOKEN_ALIASES") so comments/docstrings are ignored and the assertion fails only when those symbols are truly defined or referenced.

- Verify each finding against the current code and only fix it if needed.

In @docs/INVARIANTS.md at line 221, The sentence "If safe cookies exist for the saved engine, curl handoff may be tried first; on drift/block/empty output, fallback must use the proven browser engine before normal auto policy." is hard to parse—replace it with a 3-item bullet list to clarify the three-tier flow: (1) try curl handoff first when safe cookies exist for the saved engine, (2) on drift/block/empty output, fallback to the proven browser engine, and (3) on further failure, revert to the normal auto policy; update the INVARIANTS.md paragraph that contains this sentence to use those three concise list items in place of the single sentence.

- Verify each finding against the current code and only fix it if needed.

In @docs/INVARIANTS.md at line 222, Specify a numeric threshold for "repeated quality failures" by either replacing the ambiguous phrase in the invariant with an explicit value (e.g., "3 consecutive failures" or "5 failures within 24 hours") or by referencing a config key (for example ACQUISITION_CONTRACT_STALE_THRESHOLD) from app/services/config/ and documenting that key here; update the INVARIANTS.md sentence "Repeated quality failures mark the acquisition contract stale" to include the chosen quantitative threshold or the config key reference so implementations use a single authoritative value.

- Verify each finding against the current code and only fix it if needed.

In @docs/INVARIANTS.md at line 173, The phrase "stale-contract fallback" in the violation signature should be clarified: update the sentence containing "stale-contract fallback" to either append an explicit cross-reference "(see Rule 9)" or rephrase to "after the contract has been marked stale" (or both), so readers clearly understand you mean the stale contract behavior defined in Rule 9; modify the same sentence that currently reads "A learned real Chrome success causes a later run to launch Patchright first without explicit user override or stale-contract fallback" to include the chosen clarification and ensure it references "Rule 9" and the phrase "stale contract" to match the rule terminology.

- Verify each finding against the current code and only fix it if needed.

In @docs/INVARIANTS.md at line 218, The phrase "Risky detail browser fetches may warm the site origin..." in INVARIANTS.md uses ambiguous terms; update that sentence (or add a glossary entry) to define "risky detail browser fetches" and "warm the site origin" or replace them with precise wording such as "detail browser fetches to hosts with recent challenge history" and "establish connections or cache resources on the target origin prior to navigation"; include 1–2 concrete examples of warmup actions (e.g., preflight/cached DNS, TCP/TLS handshake, or resource prefetch) and, if helpful, add a short glossary section in INVARIANTS.md referencing the original sentence so implementations interpret it consistently.

- Verify each finding against the current code and only fix it if needed.

In @frontend/app/admin/users/page.tsx at line 136, The Dropdown component currently may not accept or forward an ariaLabel prop and the status filter Dropdown is missing an accessible label; update the Dropdown component in ui/primitives to accept an ariaLabel prop (or ariaLabel?: string) and ensure it is applied to the interactive element as aria-label (e.g., forwarded to the root button/input element), and then add an ariaLabel prop to the status filter Dropdown instance (the Dropdown that renders status options) so both role and status filter Dropdowns consistently expose an accessible label.

- Verify each finding against the current code and only fix it if needed.

In @frontend/app/globals.css around lines 1268 - 1275, Replace the hardcoded font-size in the .metric-pulse-value rule with a design token: change font-size: 32px to use an existing token such as var(--text-2xl) or var(--text-3xl), or if 32px is deliberate create and use a new token like --text-metric (and add it to your design tokens) so .metric-pulse-value references the token instead of a raw pixel value.

- Verify each finding against the current code and only fix it if needed.

In @frontend/app/globals.css around lines 1054 - 1058, The .compact-data-table CSS rule hardcodes font-size: 14px; replace that hardcoded value with the design token variable (e.g., use var(--table-font-size) or var(--font-mono-size)) so the table follows the global typography tokens; update the .compact-data-table selector to reference the chosen CSS variable and remove the literal 14px value to ensure consistency with the design system.

- Verify each finding against the current code and only fix it if needed.

In @frontend/components/crawl/crawl-run-screen.tsx at line 859, The anchor rendering run.url in the CrawlRunScreen component uses the utility class "text-accent" but a similar anchor elsewhere uses "link-accent"; update the className for the anchor with "className=\"font-mono text-sm font-medium text-accent underline-offset-2 hover:underline\"" to use "link-accent" instead (i.e., replace text-accent with link-accent) so the link color styling for the run.url anchor in crawl-run-screen.tsx matches the other link rendering.

- Verify each finding against the current code and only fix it if needed.

In @frontend/components/ui/patterns.tsx around lines 689 - 696, Replace the raw <div className="skeleton"> elements in MetricPulseSkeleton with the shared Skeleton component to match MetricSkeleton's implementation: update MetricPulseSkeleton to render two <Skeleton /> instances with equivalent sizing/spacing props or className values (matching the current "h-3 w-16" and "mt-2 h-8 w-24" styles) so the visual/behavioral pattern is consistent with the existing MetricSkeleton component.

- Verify each finding against the current code and only fix it if needed.

In @frontend/components/ui/patterns.tsx around lines 676 - 682, The decorative elements in the MetricPulse UI need to be hidden from assistive tech: add aria-hidden="true" to the empty div with className "metric-pulse-accent" and to the pulse indicator div with className "pulse-dot" inside the MetricPulse rendering (frontend/components/ui/patterns.tsx) so they match the treatment used by StatusDot; keep these attributes on those elements only (do not change the Icon or label elements).

- Verify each finding against the current code and only fix it if needed.

In @backend/alembic/versions/20260501_0021_llm_cost_log_outcome.py around lines 43 - 45, Replace the full index creation for ix_llm_cost_log_outcome on table llm_cost_log with a PostgreSQL partial index that only covers error outcomes to reduce index size and speed error lookups: keep the existing index-existence check (indexes = {index["name"] for index in inspector.get_indexes("llm_cost_log")}), and when creating the index use op.create_index("ix_llm_cost_log_outcome", "llm_cost_log", ["outcome"], postgresql_where=sa.text("outcome = 'error'")) (ensure sa is imported from sqlalchemy); if you need cross-DB portability keep the current full index path as an alternative.

These are comments left during a code review. Please review all issues and provide fixes.

1. possible bug: Google unusual-traffic blocks can still slip through because only text signatures were added.
   Path: backend/app/services/config/block_signatures.py
   Lines: 26-26

2. logic error: Availability normalization can fail when the source uses URL variants not covered by the new map
   Path: backend/app/services/config/extraction_rules.py
   Lines: 268-268

3. logic error: Breadcrumb parsing can misread separator text as category content
   Path: backend/app/services/config/extraction_rules.py
   Lines: 75-75

4. logic error: _normalize_materials() skips fallback fields when primary fields are present but unusable.
   Path: backend/app/services/data_enrichment/service.py
   Lines: 718-718

5. logic error: _normalize_sizes() can suppress valid sizes whenever the category match says size is unsupported.
   Path: backend/app/services/data_enrichment/service.py
   Lines: 628-628

Validate the correctness of each issue sequentially. For each issue that is correct, implement a fix. Please make the fixes concise and address all issues comprehensively and don't impact anything else.