# Remaining Services + Config Bucket Audit

Scope: `backend/app/services/` files outside acquisition/extraction/adapters, and `backend/app/services/config/` files not previously audited.

## S1. `dashboard_service.py` — Repetitive Reset Boilerplate (~100 LOC)

**Status:** DONE. Verified 2026-04-29 — helpers extracted.

**Fix applied:** `_reset_bucket_db()` and `_reset_bucket_tables()` helpers extracted. ~100 lines recovered.

---

## S2. `record_export_service.py` — Inline Constants (INVARIANTS Rule 1 / AP-1)

**Status:** DONE. Verified 2026-04-29 — moved to config.

**Fix applied:** `_IMAGE_URL_SUFFIXES`, `_MARKDOWN_HIDDEN_FIELDS`, `_FALLBACK_INTERNAL_FIELDS`, and HTML fragment regex moved to `config/`. ~15 lines recovered.

---

## S3. `xpath_service.py` — Inline Regex Constants (INVARIANTS Rule 1)

**Status:** DONE. Verified 2026-04-29 — moved to config.

**Fix applied:** `_XPATH_ALLOWED_FUNCTIONS`, `_XPATH_DISALLOWED_PATTERNS`, `_XPATH_FUNCTION_PATTERN` moved to `config/xpath_rules.py`. ~10 lines recovered.

---

## S4. `platform_policy.py` — Inline Tokens Overlapping with Config

**Status:** DONE. Verified 2026-04-29 — imports from config.

**Fix applied:** `_GENERIC_JOB_TOKENS` and `_GENERIC_COMMERCE_TOKENS` now import from `config/surface_hints.py`. ~15 lines recovered.

---

## S5. `selector_self_heal.py` — Inline Frozensets (INVARIANTS Rule 1)

**Status:** DONE. Verified 2026-04-29 — moved to config.

**Fix applied:** `_SELECTOR_SYNTHESIS_ALLOWED_ATTRS`, `_SELECTOR_SYNTHESIS_DROP_TAGS`, `_SELECTOR_SYNTHESIS_LOW_VALUE_TAGS` moved to `config/extraction_rules.py`. ~15 lines recovered.

---

## S6. `selectors_runtime.py` — Inline Field Selector Dict (INVARIANTS Rule 1)

**Status:** DONE. Verified 2026-04-29 — moved to config.

**Fix applied:** `_LISTING_FIELD_SELECTORS` moved to `config/selectors.exports.json` / `config/extraction_rules.py`. ~35 lines recovered.

---

## S7. `extract/detail_dom_extractor.py` — Inline Compiled Regex from Config

**Status:** DONE. Verified 2026-04-29 — moved to config.

**Fix applied:** `_detail_variant_size_value_patterns` and `_variant_option_value_suffix_noise_patterns` compilation moved to `config/extraction_rules.py`. ~8 lines recovered.

---

## S8. `shared_variant_logic.py` — Inline Frozenset/Pattern Proliferation from Config

**Status:** DONE. Verified 2026-04-29 — moved to config.

**Fix applied:** All frozensets, token sets, and pre-compiled patterns moved to `config/extraction_rules.py`. `shared_variant_logic.py` imports compiled patterns directly. ~60 lines recovered.

---

## S9. `js_state_mapper.py` — Inline Glom Field Specs (~135 LOC)

**Status:** DONE. Verified 2026-04-29 — specs moved to config.

**Fix applied:** `PRODUCT_FIELD_SPEC` and `_VARIANT_FIELD_SPEC` moved to `config/field_mappings.exports.json` / `config/field_mappings.py`. `js_state_mapper.py` imports spec dicts. ~135 lines recovered.

---

## S10. `config/extraction_rules.py` + `field_mappings.py` + `selectors.py` — Identical Loader Pattern

**Status:** NO CHANGE. Acceptable pattern — each file loads a different JSON export. Structural repetition, not behavioral.

---

## S11. `config/product_intelligence.py` — Inline String Status Constants

**Status:** NO CHANGE. Low priority. Product-intelligence-specific; field tuple centralization deferred.

---

## S12. `config/network_payload_specs.py` — 480-Line Inline Spec Dict

**Status:** NO CHANGE. Config data inherently large. Split to JSON deferred as low priority.

---

## Summary: Remaining Services + Config LOC Reduction Targets

| File | Current | Target | Savings |
|------|---------|--------|---------|
| `dashboard_service.py` | ~500 | ~400 | ~100 |
| `record_export_service.py` | ~700 | ~685 | ~15 |
| `xpath_service.py` | ~430 | ~420 | ~10 |
| `platform_policy.py` | ~430 | ~415 | ~15 |
| `selector_self_heal.py` | ~440 | ~425 | ~15 |
| `selectors_runtime.py` | ~850 | ~815 | ~35 |
| `extract/detail_dom_extractor.py` | ~1,000 | ~992 | ~8 |
| `extract/shared_variant_logic.py` | ~700 | ~640 | ~60 |
| `js_state_mapper.py` | ~1,200 | ~1,065 | ~135 |
| **Total** | **~6,250** | **~5,857** | **~393** |

*Savings are conservative. The real win is moving field specs and token sets to config so they are centralized and reusable.*
