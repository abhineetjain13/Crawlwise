# Architectural Violations Review — Zara & Dyson Detail Extraction Failures

> **Date**: 2026-04-21 | **Constraint**: No site-specific hacks — system must move toward agentic

---

## Summary

Four structural gaps cause all observed failures. None need site-specific selectors.

| # | Violation | Symptom | Pattern |
|---|-----------|---------|---------|
| 1 | **Expansion–extraction disconnect** | Clicks succeed but no new data extracted | Stages don't verify handoff |
| 2 | **Carousel = cross-sell assumption** | Zara gallery images excluded | Heuristic conflates UI pattern with intent |
| 3 | **Requested field alias is prefix-hostile** | "product measurements" → unknown | No decomposition of compound keys |
| 4 | **Variant DOM emits garbage when unnamed** | `option1_name: "option1"` | Fallback indistinguishable from real data |

---

## V1: Expansion–Extraction Disconnect

**Flow**: `settle_browser_page()` clicks accordions → `serialize_browser_page_content()` captures HTML → `extract_detail_records(html)` runs extraction.

The HTML IS captured after expansion, so expanded content IS in the DOM. But `extract_heading_sections` (`field_value_dom.py:688-701`) can't find it because it only matches:

1. `aria-controls` → find target by ID
2. `<details>/<summary>` structure
3. Hardcoded container classes: `.accordion__answer`, `.tabs__content`, `.tab-content`, `.panel` (`field_value_dom.py:593-601`)
4. Sibling content (4 siblings, 1000-char cap)

Zara/Dyson use custom accordions matching NONE of these. The sibling fallback fails because content is deeply nested.

**No verification** exists between expansion and extraction — `settle_browser_page` re-probes generic signals (`visible_text_length`) but never confirms specific sections appeared.

**Fix (generic)**:
- Post-expansion HTML diff — extract only the delta, feed as supplementary context
- Goal-driven expansion — only click elements matching missing `requested_fields`, verify after each click
- Use AOM snapshot to locate expanded content in DOM (already captured, not used for extraction)

---

## V2: Carousel = Cross-Sell Assumption

`_CROSS_LINK_CONTAINER_HINTS` at `field_value_dom.py:58-69` includes `"carousel"` and `"slider"`. When `extract_page_images` runs with `exclude_linked_detail_images=True` (detail surfaces), any image inside a carousel `<a>` tag linking to another page is **excluded**.

On Zara detail pages, the main product gallery IS in a carousel, and some gallery images ARE inside `<a>` tags. Result: **product images excluded because carousel = cross-sell**.

This is backwards. On detail pages, a carousel in the primary content area is the product gallery, not cross-sell.

**Fix (generic)**:
- Remove `"carousel"` and `"slider"` from `_CROSS_LINK_CONTAINER_HINTS` — too ambiguous
- Position-aware classification: carousels in `<main>`/`[role='main']` = product gallery; carousels in `[role='complementary']` or after "you may also like" = cross-sell
- Invert default on detail pages: assume carousel images ARE product images

---

## V3: Requested Field Alias Resolution Is Prefix-Hostile

Chain: `"product measurements"` → `normalize_field_key` → `"product_measurements"` → `_ALIAS_TO_CANONICAL` lookup → **no match**.

The alias map has `"measurements"` → `"dimensions"`, but `"product_measurements"` ≠ `"measurements"`. No substring/suffix matching exists.

The unknown field gets added to the fields list but no tier ever produces a value for it.

**Fix (generic)**:
- Suffix stripping: after exact lookup fails, strip common prefixes (`product_`, `item_`, `job_`) and retry
- Token-intersection scoring: `"product_measurements"` shares token `"measurements"` with `dimensions` alias → resolve
- Phase 2: LLM-based field resolution (per VISION.md)

---

## V4: Variant DOM Extraction Emits Garbage When Unnamed

`_extract_variants_from_dom` at `detail_extractor.py:602-606` finds containers via broad selectors like `[class*='swatch' i]`. When these have no `data-option-name`/`aria-label`, `raw_name` = `""`.

Line 666: `axis_key = normalized_variant_axis_key("") or f"option{index}"` → `"option1"`
Line 667: `record["option1_name"] = "" or "option1"` → `"option1"`

Result: `option1_name: "option1"` — circular, conveys nothing.

Additionally, `_variant_fields_are_empty` (line 566-567) exists but is **never called** as a guard in `collect_dom_tier` (`detail_tiers.py:119-149`). DOM variant extraction always runs for `ecommerce_detail`, even when JS state already found variants, potentially overwriting good data with garbage.

**Fix (generic)**:
- Skip unnamed axis groups: if `name` is empty and `normalized_variant_axis_key(name)` returns None, `continue` instead of emitting `f"option{index}"`
- Guard `collect_dom_tier` variant extraction with `_variant_fields_are_empty(state.candidates)` — only run DOM variants when no prior tier found them

---

## Architectural Pattern

All four violations share one pattern: **the pipeline does work but doesn't verify the work produced useful output, and doesn't connect downstream consumers to upstream results**.

| Stage | Does | Doesn't |
|-------|------|---------|
| Expansion | Clicks buttons | Verify content appeared for target fields |
| Image extraction | Filters cross-sell | Distinguish gallery carousel from recommendation carousel |
| Field resolution | Normalizes keys | Decompose compound keys to find semantic matches |
| Variant extraction | Emits fallback values | Guard against garbage indistinguishable from real data |

The agentic refactoring (VISION.md Phase 1) directly addresses this: each agent should have a **goal**, **verify** its output against that goal, and **report** what it found vs. what it was asked for. The current pipeline is a fire-and-forget sequence with no feedback loops.
