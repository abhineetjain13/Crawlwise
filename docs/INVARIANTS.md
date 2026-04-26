# Invariants

These are the backend contracts. Violations are bugs, not style issues.
**Each rule below includes what a violation looks like so there is no ambiguity.**

---

## HOW TO USE THIS FILE

Before writing any code, read each rule that touches your subsystem.
If your change would produce an output matching a VIOLATION signature below, stop and redesign.
These rules override any plan doc, any inline comment, and any agent reasoning about "exceptions."

---

## 1. Config and Constants — Zero Tolerance

**Rule:** Every string token, timeout value, threshold, field name, URL pattern, and numeric constant
that controls runtime behavior lives in `app/services/config/`. Nowhere else.

**VIOLATION signatures — if your code matches any of these, it is wrong:**
- A `.py` file outside `app/services/config/` contains a string like `"shopify"`, `"greenhouse"`, `"DataDome"`, a URL pattern, a timeout integer, or a field name as a bare constant
- A new `constants.py`, `config.py`, or `settings.py` file is created inside any bucket folder
- The same threshold or token appears in two different files
- A dict or constant inside a service module silently overrides what `app/core/config.py` controls via env

**Fix:** Move the constant to the appropriate file in `app/services/config/` and import it. If no appropriate file exists, extend the nearest one. Do not create a new config file without confirming no existing config file can absorb it.

---

## 2. No Duplication Before Search

**Rule:** Before creating any function, class, constant, or file, run a grep to confirm it does not already exist.
If it exists, extend it. If a similar version exists, consolidate — do not create a parallel copy.

**VIOLATION signatures:**
- Two functions in different files do the same normalization (e.g., price cleaning in both `detail_extractor.py` and `listing_extractor.py`)
- A field alias defined in both `config/field_mappings.py` and a bucket-local dict
- A new adapter that reimplements logic already in `field_value_core.py`
- A plan doc that proposes the same fix as a closed plan that was never verified

**Fix:** Grep first. Consolidate to the canonical owner. Delete the duplicate.

---

## 3. Extraction Model — How It Actually Works + 3 Known Bugs

**How the candidate system works (correct, do not change):**
All tiers (adapter, structured data, JS state, DOM) write into a shared `candidates` dict via `_add_sourced_candidate`. Field selection in `_materialize_record` is per-field independently — `_winning_candidates_for_field` picks the best source for each field slot separately. This means price can come from js_state while sku comes from DOM. This architecture is correct. Do not replace it with a record-level merge.

**Source priority order (enforced by `SOURCE_PRIORITY` / `_SOURCE_PRIORITY_RANK`):**
1. Platform adapter
2. JSON-LD / Microdata
3. Network payload intercept
4. JS state
5. DOM selector / heuristics
6. LLM (opt-in gap-fill only)

**Exception for structured object fields:** `variants`, `variant_axes`, `selected_variant` use `finalize_candidate_value` across ALL source candidates, not just the winner's. This is intentional — do not change it to winner-only.

---

**3 known bugs causing missing variants and missing prices. Fix these, do not work around them.**

**Bug 1 — Early exit skips DOM variant collection. Owner: `build_detail_record` / `_requires_dom_completion`.**

When JSON-LD produces a confident record (good title, price, images), the confidence threshold check exits before the DOM tier runs. `_extract_variants_from_dom` only runs during the DOM tier. Variants that live in DOM option controls (selects, chip groups) are never collected.

Fix: `_requires_dom_completion` must return `True` when surface is `ecommerce_detail` AND `candidates` has no `variant_axes` AND `variant_dom_cues_present(soup)` is True. `variant_dom_cues_present` already exists in `extract/shared_variant_logic.py`.

```python
# Add to _requires_dom_completion:
if (
    surface == "ecommerce_detail"
    and not candidates.get("variant_axes")
    and variant_dom_cues_present(soup)
):
    return True
```

**Bug 2 — JS state returns on first matching object, discarding variant data in later objects. Owner: `_map_ecommerce_detail_state`.**

`_map_ecommerce_detail_state` iterates `js_state_objects` and returns on the first `mapped` result. Sites with multiple hydration objects (one with base fields, one with full variant arrays) lose the variant data from the second object.

Fix: iterate all objects; backfill variant fields from subsequent objects into the base record before returning.

```python
# Replace early return with:
for field in ("variants", "variant_axes", "selected_variant", "variant_count"):
    if base_record.get(field) in (None, [], {}) and mapped.get(field) not in (None, [], {}):
        base_record[field] = mapped[field]
```

**Bug 3 — `_backfill_detail_price_from_html` and variant backfill not called after early exit. Owner: `build_detail_record`.**

The early exit return path (end of structured_data tier) bypasses the post-tier backfill calls. Any record that exits early is missing these safety nets.

Fix: call `_backfill_detail_price_from_html` and `_backfill_variants_from_dom_if_missing` before every return point in `build_detail_record`, including the early exit.

**Visible detail prices are extraction-owned. Owner: `detail_extractor.py` + `config/extraction_rules.py`.**

When structured data lacks price but the rendered detail DOM exposes a product display-price block, `_backfill_detail_price_from_html` may fill `price` and `original_price` from configured detail price selectors. This is still upstream extraction. Do not add price repair in `publish/` or `pipeline/`.

---

**VIOLATION signatures — do not introduce these:**
- Replacing the per-field `candidates` + `_winning_candidates_for_field` system with a record-level merge or a single `winner` variable
- Adding a new tier or source that writes directly to `record` instead of going through `_add_sourced_candidate`
- Fixing missing variants by adding browser interaction before verifying Bug 1 and Bug 2 are fixed
- Calling `_backfill_detail_price_from_html` only at the end of the full tier sequence but not after early exit paths
- Fixing missing visible PDP prices in persistence/export instead of `detail_extractor.py`

---

## 4. Delete Before Adding

**Rule:** When fixing a bug or adding a feature, the first question is always:
"What existing code can I delete or simplify?" Adding more code to compensate for broken existing code is a violation.

**VIOLATION signatures:**
- A new normalization pass added in `publish/` to fix values that `detail_extractor.py` already should have cleaned
- A new fallback branch added in `pipeline/core.py` to handle a case that should be rejected upstream
- A helper function added that duplicates logic in a file that was "too complex to refactor right now"
- A plan that adds 3 new files without deleting any

**Fix:** Trace the bad value upstream. Fix it at the source. Delete the downstream compensation if it existed.

---

## 5. User Control Ownership

**Rule:** User-selected controls are authoritative. Do not silently rewrite `surface`, traversal intent, `proxy_list`, or `llm_enabled`.

**VIOLATION signatures:**
- Heuristics or adapters silently change the run's `surface` after creation
- Traversal runs without settings authorizing it
- LLM activates without both run settings AND active config enabling it

---

## 6. Acquisition — Observe, Do Not Fabricate

**Rule:** Acquisition returns observational facts only: URL, final URL, status, method, headers, blocked state, diagnostics, and artifacts. It does not invent blocker causes, insert retries not in policy, or escalate without evidence.

Diagnostics controls are user controls. If `diagnostics_profile.capture_screenshot` is `False`, browser acquisition must not capture any screenshots, regardless of outcome.

**VIOLATION signatures:**
- Block detection classifies a page as blocked based on a vendor header alone when useful content is present and extractable
- Block detection classifies a page as blocked from generic `captcha` text or `recaptcha` / `hcaptcha` provider markers alone when the page still has real extractable listing/detail content and no stronger challenge evidence such as challenge-title hits, active challenge markers, or challenge elements
- A retry happens that is not logged and visible in diagnostics
- Browser escalation triggers for a URL that returned 200 with extractable content
- Browser acquisition captures a screenshot when `capture_screenshot=False`

---

## 7. Listing and Detail Stay Separate

**Rule:** Listing extraction never falls back into single-record detail behavior. A listing run with zero records produces `listing_detection_failed`. It never produces a fake success with one row of page metadata.

Detail extraction must also reject collection/category URLs that expose product-tile prices. A category URL submitted under `ecommerce_detail` is a bad seed, not a single PDP. Do not turn its first tile or page heading into a detail record.

**VIOLATION signatures:**
- A listing run returns 1 record containing the page title, OG description, or brand name
- `verdict.py` returns `success` for a listing run that extracted zero product rows
- `crawl_engine.py` routes a listing URL through `detail_extractor.py`
- An `ecommerce_detail` run on `/c/...`, `/category/...`, or `/collections/...` persists a fake detail record from a product tile

---

## 8. Persistence — User-Facing Payload Only

**Rule:** `record.data` contains only populated logical fields. No empty values, no `_` internals, no raw manifest containers, no markdown with navigation links, no site chrome.

**VIOLATION signatures:**
- Exported CSV contains fields like `_raw`, `_source`, `__nuxt`, or empty string columns
- `record.data` contains breadcrumb text, footer links, or support page anchors
- Markdown in detail records contains visible-link sections appended after usable body content was already present

---

## 9. Domain Memory Scoping

**Rule:** Domain memory is always scoped by normalized `(domain, surface)`. A selector for `example.com` on `ecommerce_detail` must never apply to `example.com` on `job_detail` or to `other.com` on any surface.

**VIOLATION signatures:**
- A `DomainMemory` lookup uses only `domain` without `surface`
- Self-heal writes a new selector without verifying the target surface
- Generic fallback selectors override a domain-specific rule for the same surface

**Domain cookie memory addendum:**
- Domain cookie memory is acquisition memory, not a raw browser-state dump.
- Challenge-state cookies/localStorage from bot-defense pages must never be persisted or replayed as reusable domain memory.
- A blocked browser run must not promote its storage state into domain memory or run-scoped browser storage.
- Run-scoped and domain-scoped browser storage must stay engine-scoped; `chromium` state must not bleed into `real_chrome`, and `real_chrome` state must not bleed back into `chromium`.
- Host browser-first memory is for repeated hard blocks, not one noisy challenge hit.
- Risky detail browser fetches may warm the site origin before direct PDP navigation; that warmup happens before the target nav, not after a challenge page already landed.

**Why this is here:**
Static cleanup advice to persist/reuse more browser state caused a real regression on 2026-04-23. The crawler started replaying PerimeterX challenge state (`_px*`, `pxcts`, PX localStorage) across runs, which poisoned acquisition on multiple sites. Any future "simplification" of cookie memory must preserve this guard and its regression tests.

---

## 10. LLM — Explicit, Degradable, Non-Primary

**Rule:** LLM runs only when both run settings and active config enable it. LLM fills gaps left by deterministic sources — it is never the primary extractor. LLM failures must be visible in diagnostics and must not corrupt deterministic extraction state.

**VIOLATION signatures:**
- LLM fires on a run where `llm_enabled=False`
- A deterministic field value is replaced by an LLM output without explicit gating
- An LLM timeout or API error silently produces an empty record instead of a diagnostic log entry

---

## 11. Codebase Shape

**Rule:** Generic crawler paths stay generic. Pipeline boundaries use typed objects. CPU-bound parsing does not block async hot paths.

**VIOLATION signatures:**
- `if "shopify" in url` or `if "greenhouse" in host` appears in `crawl_fetch_runtime.py`, `crawl_engine.py`, `_batch_runtime.py`, or any non-adapter file
- A function returns a tuple of 4+ items instead of a typed object
- A sync `requests.get()` or sync parsing call inside an `async def` function without `run_in_executor`

---

## 12. Plans Must Be Verified, Not Just Written

**Rule:** A plan slice is not done until its verify step passes. A plan is not closed until `pytest tests -q` passes. Plans that are not verified are not done — they are abandoned, and their changes must be treated as untrusted.

**VIOLATION signatures:**
- A slice is marked DONE without running the verify command
- A plan doc exists with status IN PROGRESS but no corresponding test run in the last session
- A second plan is created to fix the same issue as a previous plan that was never verified

**Fix:** If a plan was abandoned, treat its changes as potentially broken. Do not build on top of unverified work.
