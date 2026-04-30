Finding 1: Widespread Constants Hidden Outside config/
File(s): url_safety.py, browser_identity.py, browser_capture.py, crawl_events.py, llm_tasks.py
Line range: Varies (e.g., url_safety.py lines 23-35, browser_capture.py lines 35-44, llm_tasks.py lines 587-590)
Severity: HIGH (Rule 1 Violation)
Problem description: Critical runtime rules—such as blocked hostnames, proxy schemas, payload streaming types, TTLs, and HTML pruning patterns (_STRIP_ATTR_PATTERNS in llm_tasks.py)—are hardcoded as private variables inside service modules.
Recommended fix: Move security/URL sets to a new config/security_rules.py (or network_capture.py), browser identity tokens to browser_fingerprint_profiles.py, TTLs to CrawlerRuntimeSettings, and HTML strip patterns to extraction_rules.py.
Benefit: Ensures a single source of truth for runtime behavior and prevents fragmented configuration sprawl.
Finding 2: Duplicated Extraction/Block Config
File(s): field_url_normalization.py, listing_candidate_ranking.py, field_value_dom.py, normalizers/__init__.py
Line range: Varies
Severity: HIGH (Rule 2 Violation)
Problem description: Service files redefine constants that overlap with config/ exports. field_url_normalization.py TRACKING_PARAM_EXACT_KEYS overlaps CANDIDATE_TRACKING_PARAM_PREFIXES (not exact keys). listing_candidate_ranking.py _EDITORIAL_TITLE_REGEXES is a separate local editorial filter, not a direct duplicate of LISTING_EDITORIAL_TITLE_PATTERNS, but both serve similar purposes and should be consolidated. cookie_store.py line 54 loads _CHALLENGE_ELEMENT_CONFIG from BLOCK_SIGNATURES correctly (not a duplicate).
Recommended fix: Consolidate tracking param rules into canonical config keys. Merge editorial title patterns into a single source in extraction_rules.exports.json. cookie_store.py is already correct; no change needed.
Benefit: ~30 LOC savings and prevents divergent behavior where updating a config file fails to affect isolated services.
Finding 3: JSON Loading Boilerplate Sprawl
File(s): extraction_rules.py, field_mappings.py
Line range: 13-339 (extraction_rules.py), 12-20 and 154-168 (field_mappings.py)
Severity: MEDIUM
Problem description: extraction_rules.py manually assigns and declares __all__ for every single key loaded from extraction_rules.exports.json (e.g., ACTION_ADD_TO_CART = _EXPORTS['ACTION_ADD_TO_CART']), whereas selectors.py cleanly solves this with a dynamic globals() injection loop. field_mappings.py has a smaller manual assignment block (~20 lines) but still repeats the pattern; note that JS_STATE_PRODUCT_FIELD_SPEC and JS_STATE_VARIANT_FIELD_SPEC contain Coalesce expressions that cannot be JSON-exported and must stay as code.
Recommended fix: Replace extraction_rules.py's massive explicit assignment block with the for _name, _value in _STATIC_EXPORTS.items(): globals()[_name] = _value pattern used in selectors.py. Apply the same pattern to field_mappings.py for its JSON-loaded keys only.
Benefit: ~320 LOC savings in extraction_rules.py, ~15 LOC in field_mappings.py, dramatically reducing maintenance overhead when adding new keys to the JSON exports.
Finding 4: Schema/Normalizer Types Hardcoded in Logic
File(s): app/services/normalizers/__init__.py
Line range: 10-51
Severity: MEDIUM (Rule 1 Violation)
Problem description: The logic mapping which fields are decimals, integers, lists, or booleans (_DECIMAL_FIELDS, _INTEGER_FIELDS, etc.) is hardcoded inside the normalizer package rather than being part of the field mapping configuration.
Recommended fix: Move these schema definitions into config/field_mappings.exports.json and load them dynamically in the normalizer.
Benefit: Consolidates all field identity, alias, and schema-type knowledge into a single field_mappings configuration source.
Finding 5: network_payload_specs.py is Pure JSON Data
File(s): network_payload_specs.py
Line range: 86-461 (NETWORK_PAYLOAD_SPECS)
Severity: LOW
Problem description: NETWORK_PAYLOAD_SPECS is a massive ~370-line inline Python dictionary consisting purely of declarative path mappings, which is harder to read and share than actual JSON.
Recommended fix: Extract this dictionary into config/network_payload_specs.json and add a small loader, aligning it with extraction_rules, selectors, and field_mappings.
Benefit: ~370 LOC migrated from Python logic to declarative data, making the configuration layer uniform.
Finding 6: Residual Re-Export Wrappers
File(s): runtime_settings.py
Line range: 22-30
Severity: LOW
Problem description: Although the bulk of dead wrappers was removed in a previous audit, lines 22-30 still contain redundant re-assignments (e.g., build_audio_fingerprint_init_script = _build_audio_fingerprint_init_script).
Recommended fix: Delete lines 22-30 completely; update browser_identity.py imports to pull directly from browser_init_scripts.py.
Benefit: 9 LOC savings; ensures downstream modules import directly from the true owner (browser_init_scripts.py).