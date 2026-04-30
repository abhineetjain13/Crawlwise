# Extraction Bucket Audit

Scope: `backend/app/services/detail_extractor.py`, `listing_extractor.py`, `extraction_runtime.py`, `field_value_core.py`, `field_value_dom.py`, `extraction_context.py`, `pipeline/core.py`

## God Files

| File | Lines | Primary Concern |
|------|-------|----------------|
| `listing_extractor.py` | 1,434 | Listing DOM + structured + visual + card heuristics |
| `detail_extractor.py` | 1,214 | Detail tier orchestration, candidate arbitration, quality gates |
| `field_value_dom.py` | 1,206 | DOM selector extraction, image/asset URL cleanup, section noise |
| `field_value_core.py` | 998 | Text cleaning, price parsing, currency inference, field coercion |
| `extraction_runtime.py` | 879 | Facade that leaks into both extractors' private functions |
| `pipeline/core.py` | 1,128 | Per-URL pipeline orchestration with inline limit resolution |

---

## E1. `field_value_core.py` — Inline Constants / Regexes (INVARIANTS Rule 1 / AP-1)

**Status:** DONE. Verified 2026-04-29 — constants moved to config.

**Finding:** Module-level compiled regexes and field-name sets that should live in `config/extraction_rules.py`.

**Fix applied:** All regex patterns, field-name taxonomies, and noise keys moved to `config/extraction_rules.py` / `config/field_mappings.py`. `field_value_core.py` now imports them. ~80 lines recovered.

---

## E2. `detail_extractor.py` — Inline Config (AP-1)

**Status:** DONE. Verified 2026-04-29 — constants moved to config.

**Finding:** Two module-level constants that duplicated config concepts.

**Fix applied:** `_LOW_SIGNAL_LONG_TEXT_VALUES` and `_LONG_TEXT_SOURCE_RANKS` moved to `config/extraction_rules.py`. ~25 lines recovered.

---

## E3. `detail_extractor.py` — Overlapping Guards in `_requires_dom_completion`

**Status:** DONE. Verified 2026-04-29 — subset guard removed.

**Finding:** Lines 877-888 contain two sequential `if` blocks that overlap. The first block checks `variant_axes missing + variant_dom_cues_present`. The second checks `variant_dom_cues_present + (variant_axes OR variants OR selected_variant missing)`. The first is a strict subset of the second.

**Fix applied:** Deleted the first block; the second covers it. ~5 lines recovered.

---

## E4. `listing_extractor.py` — Inline Config (AP-1)

**Status:** DONE. Verified 2026-04-29 — moved to config.

**Finding:** Module-level selectors and tags.

**Fix applied:** `_PRICE_NODE_SELECTORS`, `_PROMINENT_TITLE_TAGS`, `_REVIEW_TITLE_RE` moved to `config/extraction_rules.py`. ~8 lines recovered.

---

## E5. `extraction_runtime.py` — Cross-Bucket Private Function Imports (Engineering Strategy AP-3)

**Status:** DONE. Verified 2026-04-29 — private imports removed from `extraction_runtime.py`.

**Finding:** The extraction facade imported private (underscore-prefixed) functions from both extractors, leaking their internals into the orchestration layer.

**Fix applied:** `_finalize_listing_price_fields` promoted to `extract/listing_record_finalizer.py`. `_url_is_structural` and `_detail_like_path` promoted to `extract/detail_identity.py`. Imports updated in `extraction_runtime.py`.

---

## E6. `extraction_runtime.py` — Duplicate Block Classification Logic

**Status:** DONE. Verified 2026-04-29 — reimplementation replaced with wrapper.

**Fix applied:** `_html_is_blocked_extraction_shell()` replaced with a lightweight wrapper around `classify_blocked_page(html, 0)`. ~35 lines recovered.

---

## E7. `extraction_runtime.py` — Inline Constant

**Status:** DONE. Verified 2026-04-29 — moved to config.

**Finding:** `_JSON_LIST_KEYS` tuple contained 12 bare strings.

**Fix applied:** Moved to `config/extraction_rules.py`. ~10 lines recovered.

---

## E8. `field_value_dom.py` — Inline Section-Noise Tokens

**Status:** DONE. Verified 2026-04-29 — moved to config.

**Finding:** `_SECTION_LABEL_SKIP_TOKENS` hardcoded 8 strings alongside config-driven tokens.

**Fix applied:** Moved to `config/extraction_rules.py` under `SEMANTIC_SECTION_NOISE.label_skip_tokens`. ~10 lines recoverable.

---

## E9. `extraction_context.py` — Suspicious `None` Pass

**Status:** DONE. Verified 2026-04-29 — `harvest_js_state_objects` signature accepts `None` for soup as intentional overload (raw HTML path).

---

## E10. `pipeline/core.py` — Inline Limit Resolution Logic

**Status:** DONE. Verified 2026-04-29 — `_resolve_run_param()` extracted.

**Finding:** `max_pages`, `max_scrolls`, `max_records`, `sleep_ms` are resolved from 3 sources (plan, config, explicit args) with nested ternary logic.

**Fix applied:** Extracted `_resolve_run_param(plan_value, config_value, default_value)` and reused it for `max_records` and `sleep_ms`.

---

## E11. `pipeline/core.py` — `__all__` Exports Stage Constants But Not Orchestrator

**Status:** DONE. Verified 2026-04-29 — `process_single_url` now exported.

---

## E12. `config/browser_init_scripts.py` — 56KB Inline JS Strings (Acceptable for Config)

**Status:** NO CHANGE. Low priority. Keep as-is unless file becomes >100KB.

---

## E13. `INVARIANTS.md` Documents 3 Bugs That Are Already Fixed (Stale Docs)

**Status:** DONE. Verified 2026-04-29 — stale bug descriptions removed from `INVARIANTS.md` Section 3.

**Finding:** Section 3 describes 3 extraction bugs. Code confirms all 3 are fixed but docs are stale.

**Fix applied:** Section 3 now keeps the extraction model contract and says active known bugs belong there only while active.

---

## E14. `config/extraction_rules.py` — Flat Namespace Dump From JSON

**Status:** NO CHANGE. Low priority. Acceptable pattern for config layer.

---

## Summary: Extraction LOC Reduction Targets

| File | Current | Target | Savings |
|------|---------|--------|---------|
| `field_value_core.py` | 998 | ~850 | ~148 |
| `detail_extractor.py` | 1,214 | ~1,160 | ~54 |
| `listing_extractor.py` | 1,434 | ~1,420 | ~14 |
| `extraction_runtime.py` | 879 | ~780 | ~99 |
| `field_value_dom.py` | 1,206 | ~1,180 | ~26 |
| `pipeline/core.py` | 1,128 | ~1,080 | ~48 |
| **Total** | **6,859** | **~6,470** | **~389** |

*Savings are conservative; the real win is moving constants to config so that future extractors don't duplicate them. The architectural win (E5) is eliminating cross-bucket private imports.*
