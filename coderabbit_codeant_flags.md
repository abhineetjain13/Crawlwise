Fix the following issues. The issues can be from different files or can overlap on same lines in one file.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/config/browser_fingerprint_profiles.py around lines 34 - 35, The platform mapping dictionaries are inconsistent: WEBGL_PROFILE_BY_PLATFORM and FONT_ALLOWLIST_BY_PLATFORM include a "mobile" key while HOST_OS_PLATFORM_LABELS and NAVIGATOR_PLATFORM_BY_PLATFORM_LABEL do not, risking KeyError when code assumes uniform keys; update the mappings so they are consistent by adding a "mobile" entry to HOST_OS_PLATFORM_LABELS and NAVIGATOR_PLATFORM_BY_PLATFORM_LABEL (or, if intended, explicitly document and centralize special handling for "mobile" in the code paths that use WEBGL_PROFILE_BY_PLATFORM and FONT_ALLOWLIST_BY_PLATFORM) — locate and modify the dictionaries named WEBGL_PROFILE_BY_PLATFORM, FONT_ALLOWLIST_BY_PLATFORM, HOST_OS_PLATFORM_LABELS, and NAVIGATOR_PLATFORM_BY_PLATFORM_LABEL to either add appropriate "mobile" mappings or add a shared comment/function that ensures "mobile" is handled safely.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/config/llm_runtime.py around lines 10 - 13, Update the class/module docstring to remove the stale reference to "LLM_* exports strip the LLM_ prefix" and instead describe the current behavior and exports: state that this module defines LLMRuntimeSettings (with model_config using env_prefix="CRAWLER_LLM_"), the SUPPORTED_LLM_PROVIDERS constant, and the llm_runtime_settings instance; ensure the docstring briefly explains that environment variables are prefixed with CRAWLER_LLM_ and that derived LLM_* constants were removed.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/config/network_payload_specs.py around lines 45 - 69, The function _payload_mapping_specs currently declares a return type of tuple[PayloadMappingSpec, ...] but actually returns tuple(normalized_specs.items()) i.e. tuple[tuple[str, tuple[PayloadMappingSpec, ...]], ...]; update the function signature to the correct type (tuple[tuple[str, tuple[PayloadMappingSpec, ...]], ...]) and adjust any consumers if necessary to match the new shape, keeping the body (normalized_specs population and return) as-is and ensuring any imports/aliases for PayloadMappingSpec remain valid.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/crawl_events.py around lines 29 - 31, The module-level asyncio.Semaphore (_DETACHED_LOG_WRITE_SEMAPHORE) and the captured _COUNTER_TTL_SECONDS are created at import time which triggers warnings/fails on newer Python and prevents runtime config changes; change to lazy initialization by replacing the module-level semaphore with a factory/getter (e.g., get_detached_log_write_semaphore) that creates and caches asyncio.Semaphore using _DETACHED_LOG_WRITE_CONCURRENCY on first use (ensuring creation happens inside an event loop), and replace direct uses of _COUNTER_TTL_SECONDS with a small accessor (e.g., get_counter_ttl_seconds) that reads crawler_runtime_settings.crawl_event_counter_ttl_seconds at call time so runtime changes take effect.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/shared_variant_logic.py around lines 928 - 948, The current return unconditionally prefixes all passthrough_rows, breaking original ordering from deduped_rows; instead iterate deduped_rows and emit either the passthrough row as-is when variant_semantic_identity(row) is falsy or the merged semantic object (from merged_by_semantic) the first time you encounter that semantic_identity, tracking emitted semantic ids to avoid duplicates; use the existing merged_by_semantic and semantic_order results and functions variant_semantic_identity, variant_row_richness, and merge_variant_pair to build the final list while preserving original interleaving.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/normalizers/__init__.py around lines 110 - 111, The length check using len(candidate) incorrectly counts a leading sign; update the conditional that gates interpreting integrals as cents (the branch using interpret_integral_as_cents, candidate, and decimal) to count only digit characters (e.g., use candidate.lstrip("+-") or count c.isdigit() chars) instead of raw len(candidate) so negative values like "-99" are treated as two digits and not divided by 100; keep the division logic (decimal = decimal / Decimal("100")) the same but only execute it when the digit-count threshold is met.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/product_intelligence/discovery.py around lines 315 - 323, The setup block logging failure for page.goto(GOOGLE_NATIVE_HOME_URL) and emit_browser_behavior_activity currently only warns and allows _run to continue; change this to return early (or yield None) on exception so downstream callers in _run/shared_query_runner don't operate on a broken page. Specifically, inside the try/except around page.goto and emit_browser_behavior_activity in discovery.py, after catching Exception as exc, log the error then either return (or yield None) from the surrounding function/method so _run does not proceed; mirror the behavior used for Chrome-unavailable handling in shared_query_runner to ensure callers can detect and skip queries when setup failed.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/url_safety.py around lines 40 - 50, In ensure_public_crawl_targets, deduplication currently uses the raw candidate which allows distinct raw inputs (e.g., "example.com" vs "https://example.com") to normalize to the same URL and produce duplicates; change the flow to call validate_public_target and _rebuild_url first for each unique non-empty candidate, compute the normalized_url, then check and track seen against that normalized_url (instead of the raw candidate) before appending to normalized; keep the async validate_public_target call and only add normalized_url to the seen set and normalized list when it’s not already present.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/config/security_rules.py around lines 23 - 25, Add the cloud metadata link-local address to the blocked set: update the BLOCKED_IPS constant to include ip_address("169.254.169.254") (and optionally include the broader link-local network by adding a BLOCKED_NETWORKS constant such as ip_network("169.254.0.0/16") alongside existing CGNAT_NETWORK usage); locate BLOCKED_IPS in security_rules.py and append the metadata IP (or create BLOCKED_NETWORKS tuple with the link-local /16) so SSRF attempts to 169.254.169.254 (and optionally 169.254.0.0/16) are rejected.

These are comments left during a code review. Please review all issues and provide fixes.

1. logic error: Patchright contexts no longer receive the browser-fingerprint init script.
   Path: backend/app/services/acquisition/browser_identity.py
   Lines: 140-140

2. possible bug: Non-timeout Playwright snapshot failures now abort markdown generation instead of being ignored.
   Path: backend/app/services/acquisition/browser_page_flow.py
   Lines: 1219-1219

3. integration bug: Proxied fetches ignore the injected runtime provider and always use the default runtime.
   Path: backend/app/services/acquisition/browser_runtime.py
   Lines: 1204-1204

4. logic error: Alias expansion can double-count the same field and overstate requested-field coverage.
   Path: backend/app/services/confidence.py
   Lines: 80-80

5. logic error: TIMEZONE_ALIASES only maps the lowercase key "asia/calcutta", so common capitalized timezone input will not normalize.
   Path: backend/app/services/config/browser_fingerprint_profiles.py
   Lines: 28-28

6. possible bug: Lazily exposing exported constants can break access to symbols during initialization.
   Path: backend/app/services/config/extraction_rules.py
   Lines: 231-231

Validate the correctness of each issue sequentially. For each issue that is correct, implement a fix. Please make the fixes concise and address all issues comprehensively and don't impact anything else.