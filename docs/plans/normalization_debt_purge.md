# Normalization Debt Purge Tracker

Status: in progress
Updated: 2026-04-12

Implementation status
- Done: explicit `Commerce` / `Jobs` surface selection in the frontend, with surface derived only from the user toggle plus the existing listing/detail module.
- Done: backend `create_crawl_run()` now requires `surface`; URL-based inference is removed.
- Done: pipeline listing surface remap stage is deleted; acquisition no longer emits requested/effective/suggested surface remap diagnostics.
- Done: `field_mappings.py` is now the active surface fence owner for alias scoping and commerce/job-only field exclusions, including job-detail leakage fields such as `image_url`, `additional_images`, `part_number`, `currency`, and `product_attributes`.
- Done: `get_surface_field_aliases()` now returns detached alias lists and `COLLECTION_KEYS` is narrowed.
- Done: DOM selector ownership now stays in `selectors.py`; duplicate `DOM_PATTERNS` export was removed from `extraction_rules.py`.
- Done: settings path normalization now happens during `Settings()` construction instead of after instantiation.
- Done: deleted the dead duplicate alias payload from `EXTRACTION_RULES`; alias ownership now lives only in `field_mappings.py`.

🔴 Critical Issues (Active Bug Risk)
1. Two diverging field alias dictionaries
EXTRACTION_RULES["field_aliases"] in extraction_rules.py and FIELD_ALIASES in field_mappings.py are separate, maintained independently, and have already drifted. Notable divergences:

field_mappings.py:url has "workUrl", "listingUrl", "positionURI" — absent from extraction_rules.py
extraction_rules.py:price includes "sale_price" as an alias for price — this is a circular alias. If a candidate is keyed sale_price, it could be resolved as price first, defeating the dedicated sale_price field entirely
extraction_rules.py:category lists "job_type" and "employment_type" as aliases — these are job surface fields leaking into a universal alias map. This is almost certainly contributing to the output schema leakage you've been chasing
field_mappings.py has job_id, salary_min, salary_max, salary_currency, employment_type, experience_level, work_model, stock_quantity, color_variants — all absent from extraction_rules.py

Whichever of these two gets used in a given code path determines what fields get resolved, and there's no guarantee they're consistent.
2. Two diverging "ecommerce-only" field sets
ECOMMERCE_ONLY_JOB_LISTING_FIELDS in extraction_rules.py:
price, sale_price, original_price, currency, sku, part_number,
availability, rating, review_count, image_url, additional_images
ECOMMERCE_ONLY_FIELDS in field_mappings.py:
availability, brand, color, color_variants, condition, currency,
exterior_color, interior_color, part_number, price, price_original,
original_price, sku, stock_quantity
brand, color, image_url, rating, review_count, sale_price are contested — in one set but not the other. Code paths using different constants will produce different filtering behavior on job surfaces.
3. LLM_TUNING dict bypasses env-configurable settings
extraction_rules.py defines:
pythonLLM_TUNING = {
    "html_snippet_max_chars": 12000,
    "anthropic_max_tokens": 3000,
    ...
}
These are hardcoded duplicates of fields in LLMRuntimeSettings (in llm_runtime.py), which reads from env. Any consumer of LLM_TUNING directly will silently ignore whatever you've set in the environment. There's no link between the two.
4. Unresolvable placeholder regex in NORMALIZATION_RULES
python"salary_range_regex": r"(?:(?:__CURRENCY_SYMBOL_CLASS__| ...)"
This raw string sits in NORMALIZATION_RULES with unexpanded sentinel tokens. _expand_salary_range_regex() is supposed to expand them, and SALARY_RANGE_REGEX at the bottom of the file is the correctly compiled result. But NORMALIZATION_RULES["salary_range_regex"] accessed directly by any consumer would yield an invalid regex that silently matches nothing — no error thrown.

🟠 Structural Problems
5. extraction_rules.py is a ~1500-line god module
It does all of the following in one file:

Defines the EXTRACTION_RULES mega-dict (raw data)
Defines NORMALIZATION_RULES (raw data for a different concern)
Imports from crawl_runtime.py and re-exports two constants via __all__
Imports DOM_PATTERNS from selectors.py and copies it
Defines LLM_TUNING, COOKIE_POLICY, VERDICT_RULES, HYDRATED_STATE_PATTERNS
Immediately post-processes all the dicts into ~80 typed module-level constants
Defines regex compilation helpers and _expand_salary_range_regex
Calls known_ats_domains() at import time (triggers platform_registry.py init)

This should be split across at minimum: noise_rules.py, normalization_rules.py, listing_rules.py, cookie_policy.py.
6. DOM_PATTERNS defined twice
selectors.py defines DOM_PATTERNS. extraction_rules.py imports it and also has "dom_patterns" verbatim inside EXTRACTION_RULES as a literal dict. Then at the bottom it does DOM_PATTERNS = dict(_DOM_PATTERNS) re-exporting from selectors. So there are two authoritative copies. Any edit to selectors.py doesn't update EXTRACTION_RULES["dom_patterns"] and vice versa.
7. __all__ in extraction_rules.py is misleading
python__all__ = [
    "DYNAMIC_FIELD_NAME_MAX_TOKENS",
    "MAX_CANDIDATES_PER_FIELD",
]
These two constants are not defined in extraction_rules.py — they're imported from crawl_runtime.py. Declaring them in __all__ implies they're native to this module; any reader will hunt in vain.
8. crawl_runtime.py is pure boilerplate
~100 lines of X = crawler_runtime_settings.x assignments. This pattern is fine in isolation, but at this scale it means every new setting field requires two edits (class + re-export). There's no test protection that these stay in sync, and no linter will catch a missing re-export.
9. CrawlerRuntimeSettings.coerce_url_timeout_seconds is a method, not a method
It's an instance method that uses self.url_process_timeout_seconds and self.max_url_process_timeout_seconds, making CrawlerRuntimeSettings a hybrid of a data bag and utility. The method gets re-exported as coerce_url_timeout_seconds at module level in crawl_runtime.py — a module-level function that's actually a bound method.

🟡 Design Smells
10. COLLECTION_KEYS is dangerously broad
field_mappings.py lists "response", "values", "data", "content", "objects", "documents" as collection keys. These are too generic and will cause false-positive collection detection on non-listing JSON blobs. "data" especially will fire on almost any API response.
11. _apply_profile_defaults validator logic is inverted
In CrawlerRuntimeSettings, the profile override condition is:
pythonif (self.performance_profile != "BALANCED" and "field" not in explicitly_set) 
   or self.field is None:
This means: apply the BALANCED profile dict values only when field is None, but apply other profiles only when the field isn't explicitly set. The BALANCED case never reads from PERFORMANCE_PROFILES["BALANCED"] unless the value is None. The intent is that BALANCED defaults are baked into the class field defaults directly, which works, but is undocumented and makes PERFORMANCE_PROFILES["BALANCED"] a dead entry for most fields.
12. platform_readiness.py builds a redundant dict at import time
LISTING_READINESS_OVERRIDES is built from listing_readiness_domains() which itself iterates platform_configs(). This is an O(n²) loop over platforms at import time, and the result overlaps heavily with PLATFORM_LISTING_READINESS_SELECTORS. The two dicts contain almost identical information in different shapes.
13. get_surface_field_aliases mutates lists in-place for automobile surface
pythonmake_aliases = automobile_aliases.setdefault("make", [])
if "manufacturer" not in make_aliases:
    make_aliases.append("manufacturer")
automobile_aliases is a fresh dict (from a dict comprehension), but its values are references to the same lists in FIELD_ALIASES. The append call mutates those shared lists. Subsequent calls to get_surface_field_aliases for automobile surfaces would see doubled entries. The setdefault line with "make" is also fragile — make is already in FIELD_ALIASES, so setdefault is a no-op and the existing list is mutated.
14. config.py path resolution happens after settings instantiation
pythonsettings = Settings()
# ...
settings.artifacts_dir = _resolve_project_path(settings.artifacts_dir, ...)
Between settings = Settings() and the path resolution block, any import that reads settings.artifacts_dir early gets an unresolved path. The resolution should happen inside a model_validator or __init_subclass__.
15. CANDIDATE_NOISY_PRODUCT_ATTRIBUTE_KEY_TOKENS double-defined
In extraction_rules.py, NORMALIZATION_RULES has noisy_product_attribute_key_tokens and so does EXTRACTION_RULES["candidate_cleanup"]. The constant CANDIDATE_NOISY_PRODUCT_ATTRIBUTE_KEY_TOKENS reads from _CANDIDATE_CLEANUP, but NORMALIZATION_RULES has its own copy that nested_field_rules.py would encounter if it traversed there.

🟢 What's Working Well

The PlatformConfig / PlatformRegistryDocument Pydantic models with JSON backing are clean and extensible — the right architecture for platform-specific config.
Security guard in config.py (_check_secret_defaults) with dev/prod branching is solid.
_settings_config() helper as a shared factory for SettingsConfigDict is clean and DRY across all the runtime settings classes.
ECOMMERCE_ONLY_FIELDS / JOB_ONLY_FIELDS / INTERNAL_ONLY_FIELDS partition in field_mappings.py with get_surface_field_aliases() is exactly the right design for preventing schema leakage — the problem is that not all code paths use it.
_expand_salary_range_regex with the ReDoS hardening comment and bounded repetition is thoughtful.
frozenset used consistently for membership-tested collections throughout.
block_signatures.py is clean, focused, and properly separated.


Priority Fix Order
Given your known bugs, I'd tackle in this order:

Delete EXTRACTION_RULES["field_aliases"] and route all alias lookups through field_mappings.FIELD_ALIASES + get_surface_field_aliases(). Fix the "category" alias to remove "job_type" and "employment_type", and remove "sale_price" from the "price" alias list.
Unify ECOMMERCE_ONLY_* sets — pick one and delete the other.
Delete LLM_TUNING dict and have its consumers read from llm_runtime.* constants.
Delete EXTRACTION_RULES["dom_patterns"] and make selectors.py the single source.
Add a note/assertion on NORMALIZATION_RULES["salary_range_regex"] making clear it's a template, not a valid regex.
