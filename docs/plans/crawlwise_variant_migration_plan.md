# Crawlwise — Variant Architecture Migration Plan

**Status:** Confirmed technical debt audit. All file references, function names, line numbers, and structural facts are verified from direct source reads.
**Files covered:** `variant_dom_cues.py`, `detail_dom_extractor.py` (1392 lines), `shared_variant_logic.py` (1562 lines), `variant_record_normalization.py` (1472 lines), `detail_materializer.py` (45k), `extraction_rules.py` (53k), `variant_policy.py`.
**Test coverage:** One variant test file found: `test_shared_variant_logic.py` (22k). No test for `variant_record_normalization.py`, `detail_dom_extractor.py`, or `detail_materializer.py` variant paths.

---

## Part 1 — Verified Technical Debt Inventory

This section documents every confirmed structural flaw before any fix is proposed. Nothing here is inferred.

---

### Debt 1 — Fail-Open Scope Fallback (`variant_dom_cues.py:72`)

```python
# variant_dom_cues.py:72
return roots or [soup]
```

When `DETAIL_VARIANT_SCOPE_SELECTOR` finds no matching product-form container, the entire page document is used as the variant mining root. This is the single highest-risk line in the codebase for causing the Lowes-class leak: tabs, review sections, footers, financing widgets, and navigation rails all become eligible scope roots.

The fallback exists as a safety net for sites that don't have identifiable product-form containers. But it costs more in correctness than it saves in recall — a missed variant extraction can be reported and fixed; a leaked navigation bar in the variants array ships silently to users.

**Scope:** `variant_dom_cues.py`, 1 line.

---

### Debt 2 — Broad Selector in `_collect_variant_choice_entries` (`detail_dom_extractor.py:716`)

```python
# detail_dom_extractor.py:716-722
for node in container.select(
    "[role='radio'], [role='option'], button, a[href], "
    "[data-value], [data-option-value], "
    "[aria-pressed], [aria-selected], [data-state], [data-selected]"
)[:24]:
```

The selector `a[href]` and `button` are completely unconstrained. Every navigational anchor and every generic button inside any candidate container is treated as a potential variant option. The only rejection at this stage is `variant_option_value_is_noise(cleaned)`, a string-based filter. The BH Photo "Share", "Print", "Show More" and Lowes "View More", "Return Policy", "Overview" bugs are direct consequences of this selector being too broad.

**Scope:** `detail_dom_extractor.py`, the `_collect_variant_choice_entries` function.

---

### Debt 3 — Group Admission on Weak Evidence (`detail_dom_extractor.py:1000, 1016`)

```python
# Admission rule for select groups:
if len(deduped_values) >= 2:
    option_groups.append(...)

# Admission rule for choice groups:
if len(deduped_values) >= 2:
    option_groups.append(...)
```

A group with two or more non-noise values is admitted as a variant group. "Two clickable values" is not a reliable signal that a container represents a purchasable SKU dimension. There is no requirement for:
- Semantic axis label (just `cleaned_name` which can be inferred from values alone)
- Product-local URLs (URLs can point to reviews, listings, help pages)
- Buy-box or add-to-cart proximity
- DOM structural indicators of a variant widget (e.g. `fieldset`, `[data-option]`, `[name]` consistency)

**Scope:** `detail_dom_extractor.py`, `extract_variants_from_dom`.

---

### Debt 4 — Context Evidence Discarded After Extraction

After `extract_variants_from_dom` and `_collect_variant_choice_entries` run, the resulting `option_groups` dicts contain only:
```
{"name": str, "values": [str], "entries": [{value, url, availability, selected, variant_id}]}
```

All of the following are discarded at this point:
- Container node reference (tag name, class attrs, id, role, data-testid)
- Ancestor class hierarchy
- Which extractor path found this group (`select`, `radio`, `swatch_fallback`, `input_inference`)
- Whether the group was found inside a validated scope root or fell through to whole-page
- Option node types (whether options were `<button>`, `<a>`, `<input type=radio>`, `<option>`)

By the time `normalize_variant_record` runs in `variant_record_normalization.py`, all these signals are gone. The normalizer can only inspect string values — it cannot distinguish "View More" from a real color swatch that happens to have a short label, without a token list.

**Scope:** Architecture-wide. Affects `detail_dom_extractor.py`, `variant_record_normalization.py`.

---

### Debt 5 — `_variant_option_url` Resolves the Nearest Anchor Unconditionally (`detail_dom_extractor.py:613`)

```python
# Checks in order: node, label_node, parent anchor, label parent anchor,
# child anchor, label child anchor, container anchor
if hasattr(container, "find"):
    anchor = container.find("a", href=True)
    if anchor is not None:
        candidates.append(anchor)
```

As the last resort, the function takes the first anchor found anywhere inside the container. This means if a variant container is a `<div>` that contains both real variant options and a "Shop the Collection" link, the collection link URL gets assigned to options. The Lowes case produces nine variants all sharing `https://www.lowes.com/pl/ceiling-lights/...` because the category anchor is the first (and only) `href` found in the container.

There is no check that the resolved URL is a product detail page (contains `/pd/`, ends in a product ID, matches the current URL's host + path structure). There is also no deduplication guard that says "if all variant URLs are identical, drop the URL field from all variants."

**Scope:** `detail_dom_extractor.py`, `_variant_option_url`.

---

### Debt 6 — `_should_collect_dom_variants` Can Prefer Noisy DOM Output (`detail_materializer.py:711`)

```python
def _should_collect_dom_variants(...) -> bool:
    ...
    dom_strength = _variant_signal_strength(dom_variants.get("variants"))
    return dom_strength > existing_strength
```

`_variant_signal_strength` returns a 4-tuple: `(price_covered_rows, axis_covered_rows, axis_count, total_rows)`. DOM variants can outrank existing variants purely by having more rows and more axes, even if those rows are polluted with navigation labels. A noisy DOM extraction that produces 9 rows with color axes will score higher than a sparse upstream extraction with 2 clean rows and no price data, and the noisy DOM set will be published.

**Scope:** `detail_materializer.py`, `_should_collect_dom_variants`.

---

### Debt 7 — `VARIANT_OPTION_LABEL_MAX_WORDS` Is Dead Code in the Normalizer

```python
# extraction_rules.py:
VARIANT_OPTION_LABEL_MAX_WORDS = 6

# variant_record_normalization.py:21 — imported
from app.services.config.extraction_rules import ... VARIANT_OPTION_LABEL_MAX_WORDS ...

# variant_record_normalization.py:109 — assigned
_VARIANT_OPTION_LABEL_MAX_WORDS = max(1, int(VARIANT_OPTION_LABEL_MAX_WORDS))

# variant_record_normalization.py:344 — ONLY usage
if len(color_tokens) < max(3, _VARIANT_OPTION_LABEL_MAX_WORDS - 1):
```

The word-count limit exists in config and is imported, but it is **only used** inside `_variant_row_looks_like_foreign_product` to gate color token count in a very narrow context. It is never called from `_normalize_variant_axis_value`, which is the function that validates every axis value before accepting it. This is why Back Market's 17-word condition sentence and Wayfair's "5 Year Protection Plan" pass normalization.

**Scope:** `variant_record_normalization.py`, `_normalize_variant_axis_value`.

---

### Debt 8 — Single Test File for All Variant Logic

Only `test_shared_variant_logic.py` (22k) tests variant behavior. There are no dedicated tests for:
- `variant_record_normalization.py` (1472 lines, 50+ functions)
- `detail_dom_extractor.py` variant paths (1392 lines)
- `detail_materializer.py` variant collection decision
- `variant_dom_cues.py` scope root logic

Every confirmed user-facing bug arrived in production without a regression test. There is no fixture pinning the Lowes, BH Photo, Wayfair, or Back Market cases.

---

## Part 2 — Root Cause Summary

All four user-facing leak classes trace to two compounding root causes:

**Root Cause A — Permissive admission with no group-level proof.**
The pipeline asks "does this container have ≥2 non-noise values?" rather than "is this container provably a purchasable variant control?" Admission is optimistic; rejection is reactive (token lists). Every new site with non-standard layout produces a new category of false positives.

**Root Cause B — Provenance erasure before validation.**
The DOM context that distinguishes a tab-bar anchor from a variant swatch (ancestor classes, container tag, extractor path, option node type, URL domain/path structure) is discarded during extraction. The downstream normalizer therefore has no basis for a structural decision and falls back to string heuristics. This is why the token list grows forever — it is compensating for lost evidence.

---

## Part 3 — Target Architecture

The target design is a four-stage pipeline with typed evidence objects and explicit group validation. No stage discards evidence that a later stage needs.

```
DOM HTML
  │
  ▼
[Stage 1] Scoped Candidate Discovery
  variant_dom_cues.py → VariantCandidateGroup[]
  • Fails closed (no whole-page fallback)
  • Preserves: container tag, class, id, role, ancestor classes,
    extractor path, scope root source
  │
  ▼
[Stage 2] Group Validation
  variant_group_validator.py (new) → ValidatedVariantGroup[]
  • Evidence-based scoring (positive + negative signals)
  • Explicit rejection reasons (inspectable in dev/test)
  • Confidence threshold: below threshold → emit nothing
  │
  ▼
[Stage 3] Row Materialization
  detail_dom_extractor.py (refactored)
  • Cartesian product only from validated groups
  • URL quality enforced per-option
  │
  ▼
[Stage 4] Light Normalization
  variant_record_normalization.py (trimmed)
  • Value cleaning only (no structural decisions)
  • Word-count gate wired into _normalize_variant_axis_value
  • Tokens remain as last-resort residual filter
```

---

## Part 4 — Migration Phases

Each phase is independently deployable, backward-compatible until cut-over, and adds regression tests before any code change ships.

---

### Phase 0 — Regression Wall (prerequisite, 1–2 days)

**No code changes to logic. Pin current behavior so we can measure regressions during migration.**

Create `backend/tests/services/extract/test_variant_regression.py`:

```python
# One fixture per confirmed leak class.
# Each fixture: minimal HTML + expected output contract.

FIXTURES = [
    {
        "id": "lowes_nav_as_color",
        "html": "...",  # Lowes Minka Lavery PDP minimal repro
        "assert_variants_empty": True,
    },
    {
        "id": "bhphoto_review_controls",
        "html": "...",
        "assert_no_color_values": ["Share", "Print", "2 reviews", "Show More"],
    },
    {
        "id": "wayfair_protection_plan",
        "html": "...",
        "assert_no_color_values": ["5 Year Protection Plan", "See Details Details"],
    },
    {
        "id": "backmarket_condition_prose",
        "html": "...",
        "assert_condition_max_words": 6,
    },
]
```

Also create `backend/tests/services/extract/test_variant_scope.py`:
```python
# Test variant_scope_roots() fail-closed behavior
# Test variant_node_in_noise_context() with known contaminating class names
# Test select_variant_nodes() does not traverse whole-page when scope fails
```

These tests will initially fail on the current codebase (confirming the bugs are real), and must pass after each subsequent phase.

---

### Phase 1 — Fix Immediate Leaks Without Architecture Change (1–2 days)

**Goal:** Stop the four active bug classes from reaching users now, while the structural refactor is in progress. These are targeted patches, not the long-term design.

**1a. Wire word-count gate into `_normalize_variant_axis_value`**

File: `backend/app/services/extract/variant_record_normalization.py`, function `_normalize_variant_axis_value` (line 533)

```python
# BEFORE
def _normalize_variant_axis_value(field_name: str, value: object) -> str:
    cleaned = _strip_variant_option_suffix_noise(value)
    if (
        not cleaned
        or _value_is_placeholder(cleaned)
        or _value_is_ui_noise(cleaned)
        or _value_is_axis_header_noise(field_name, cleaned)
        or _variant_axis_value_is_header(field_name, cleaned)
    ):
        return ""
    return cleaned

# AFTER — add word-count gate before returning
def _normalize_variant_axis_value(field_name: str, value: object) -> str:
    cleaned = _strip_variant_option_suffix_noise(value)
    if not cleaned:
        return ""
    if len(cleaned.split()) > _VARIANT_OPTION_LABEL_MAX_WORDS:
        return ""
    if (
        _value_is_placeholder(cleaned)
        or _value_is_ui_noise(cleaned)
        or _value_is_axis_header_noise(field_name, cleaned)
        or _variant_axis_value_is_header(field_name, cleaned)
    ):
        return ""
    return cleaned
```

Kills: Back Market condition prose, Wayfair "5 Year Protection Plan", any future long-sentence values.
Risk: Audit test corpus for legitimate 7+ word variant values before deploying. The threshold is config-controlled via `VARIANT_OPTION_LABEL_MAX_WORDS`.

**1b. Add URL path-suffix and listing-path rejection**

File: `backend/app/services/extract/variant_record_normalization.py`, function `_drop_invalid_variant_urls` (line 613)

```python
# Add to extraction_rules.py:
VARIANT_URL_BLOCKED_PATH_SUFFIXES = frozenset({
    "/reviews", "/review", "/print", "/share", "/overview",
    "/specifications", "/specs", "/wishlist", "/cart",
    "/returns-policy", "/credit", "/payment", "/help",
})
VARIANT_URL_BLOCKED_PATH_PREFIXES = frozenset({
    "/pl/", "/c/", "/collections/", "/category/",
    "/browse/", "/search/", "/l/",
})

# In variant_record_normalization.py:
def _variant_url_is_product_like(value: str) -> bool:
    if not _variant_url_is_public_http(value):
        return False
    parsed = urlparse(value)
    path = parsed.path.rstrip("/").lower()
    if any(path.endswith(s) for s in _VARIANT_URL_BLOCKED_PATH_SUFFIXES):
        return False
    if any(path.startswith(p) for p in _VARIANT_URL_BLOCKED_PATH_PREFIXES):
        return False
    return True
```

Add to `_dedupe_and_prune_variant_rows`: if all variant URLs are identical and none pass `_variant_url_is_product_like`, null out the URL field on all rows.

**1c. Add 16 confirmed missing noise phrases**

File: `backend/app/services/config/extraction_rules.py`, `VARIANT_OPTION_VALUE_UI_NOISE_PHRASES`

Add:
```python
# Navigation / tab labels
"view more", "view all", "view all images", "view all photos",
"overview", "specifications", "description", "features",
# Social / share controls
"share", "print", "save", "bookmark",
"show more", "more details", "see details",
# Navigation CTAs
"return policy", "returns policy", "payment options",
"shop the collection", "shop all",
# Protection / upsell
"year protection plan", "protection plan", "extended warranty",
# Quantity controls (additional forms)
"increment or decrement number", "increment or decrement",
```

Add to `VARIANT_OPTION_VALUE_NOISE_PATTERNS["fullmatch"]`:
```python
r"\d+\+?\s+reviews?",
r"\d+\+?\s+ratings?",
r"(\b\w+\b)(?:\s+\1)+",       # doubled-token artifact: "See Details Details"
r"shop\s+\w+(?:\s+\w+){0,2}", # "Shop Minka Lavery", "Shop Brand Name"
```

Add to `DETAIL_VARIANT_CONTEXT_NOISE_TOKENS`:
```python
"tabs", "tab-list", "tablist", "tab-nav",
"reviews", "review-section", "ratings",
"social", "share-bar", "protection", "warranty",
```

**Deliverable:** All regression tests from Phase 0 pass. Deploy to production.

---

### Phase 2 — Fix `variant_scope_roots` Fail-Open (`variant_dom_cues.py`) (2–3 days)

**Goal:** Eliminate the whole-page fallback without breaking legitimate scope-miss recovery.

**Current behavior:**
```python
return roots or [soup]   # falls back to entire document
```

**Target behavior:**
```python
# If no strong scope root found, attempt a broader but bounded fallback
# before giving up, then fail closed.
```

**Implementation:**

Introduce a two-tier scope strategy:

*Tier 1 (trusted scope):* Current `DETAIL_VARIANT_SCOPE_SELECTOR` — product forms with clear signals.

*Tier 2 (soft scope):* A broader selector for sites that don't use form-based product containers, but bounded to regions that contain explicit variant signals (at least one `input[type=radio]`, `[data-option]`, or `[role=radio]` that is not inside a noise-context ancestor).

```python
# extraction_rules.py — add:
DETAIL_VARIANT_SOFT_SCOPE_SELECTOR = (
    "[class*='variant' i], [class*='option' i], "
    "[id*='variant' i], [id*='option' i], "
    "[data-component*='variant' i]"
)
VARIANT_SOFT_SCOPE_MIN_RADIO_INPUTS = 2
```

```python
# variant_dom_cues.py — replace:
return roots or [soup]

# With:
if roots:
    return roots
soft_roots = _variant_soft_scope_roots(soup)
if soft_roots:
    return soft_roots
return []   # FAIL CLOSED — caller gets empty list, no variants extracted
```

In `select_variant_nodes`, handle `[]` gracefully:
```python
def select_variant_nodes(soup: Any, selector: str) -> list[Any]:
    scope_roots = variant_scope_roots(soup)
    if not scope_roots:
        return []   # fail closed
    ...
```

In `extract_variants_from_dom`, return empty dict when no scope roots:
```python
if not iter_variant_choice_groups(soup) and not iter_variant_select_groups(soup):
    return {}
```

**Monitoring:** Add a counter metric `variant_scope_miss` that increments when `variant_scope_roots` returns an empty list, so you can track how many PDPs are affected by the strict mode. Start at 0, watch the rate per site, add site-specific selectors to `DETAIL_VARIANT_SCOPE_SELECTOR` for sites with high miss rates.

**Regression risk:** Sites where the whole-page fallback was producing correct output will now produce empty variants. Use the `variant_scope_miss` metric to identify and add those sites' selectors to the config. This is acceptable because those sites are currently also at risk of pollution.

**Deliverable:** All Phase 0 regression tests still pass. Scope miss rate metric deployed.

---

### Phase 3 — Restrict `a[href]` and `button` as Option Candidates (`detail_dom_extractor.py`) (2–3 days)

**Goal:** Stop anchors and generic buttons from being treated as first-class option candidates unless they have explicit variant-option signals.

**Current selector in `_collect_variant_choice_entries`:**
```python
container.select(
    "[role='radio'], [role='option'], button, a[href], "
    "[data-value], [data-option-value], "
    "[aria-pressed], [aria-selected], [data-state], [data-selected]"
)[:24]
```

**Problem:** `button` and `a[href]` match everything. They should only be used when they carry explicit variant-option semantics.

**New selector strategy:**

Split into two passes:

*Pass 1 — Strongly typed variant nodes (use directly):*
```python
VARIANT_STRONG_OPTION_SELECTOR = (
    "[role='radio'], [role='option'], "
    "input[type='radio'], input[type='checkbox'], "
    "[data-option-value], [data-value], [data-variant-id], "
    "[aria-pressed][aria-pressed!=''], "
    "button[data-option], button[data-value], button[data-variant]"
)
```

*Pass 2 — Weakly typed nodes (use only if Pass 1 yields < 2 candidates):*
```python
VARIANT_WEAK_OPTION_SELECTOR = (
    "button:not([data-dismiss]):not([type='submit']):not([type='reset']), "
    "a[href][data-option], a[href][data-variant]"
)
```

For `a[href]` without data-option attributes, require that the URL differs from page_url before accepting the node as an option candidate:
```python
def _anchor_is_variant_candidate(node: Any, *, page_url: str) -> bool:
    href = text_or_none(node.get("href"))
    if not href:
        return False
    # Must differ from current page URL in path (not just fragment/query)
    parsed_href = urlparse(absolute_url(page_url, href))
    parsed_page = urlparse(page_url)
    return parsed_href.path != parsed_page.path
```

**Deliverable:** All Phase 0 regression tests pass. Parametrized test added to `test_variant_regression.py` confirming that navigation anchors are no longer collected as options.

---

### Phase 4 — Introduce `VariantCandidateGroup` and Group Validator (1–2 weeks)

**Goal:** Add a structured validation step between DOM extraction and materialization. This is the core architectural change.

**New file:** `backend/app/services/extract/variant_group_validator.py`

**New dataclass:** `VariantCandidateGroup`

```python
from dataclasses import dataclass, field

@dataclass
class VariantCandidateGroup:
    name: str                    # resolved axis label
    axis_key: str                # normalized axis key
    values: list[str]            # deduped option values
    entries: list[dict]          # {value, url, availability, selected, variant_id}
    # Provenance fields — NEW
    container_tag: str           # div, fieldset, form, nav, ...
    container_classes: list[str] # raw class tokens
    container_id: str | None
    container_role: str | None
    ancestor_class_tokens: list[str]  # top 6 ancestor class/id tokens
    extractor_path: str          # "select", "choice_radio", "choice_button", "swatch_fallback"
    scope_source: str            # "trusted_scope", "soft_scope", "full_page"
    option_node_types: list[str] # "button", "a", "input_radio", "role_radio", ...
    # Validation fields — set by validator
    confidence: float = 0.0
    rejection_reasons: list[str] = field(default_factory=list)
```

**Group Validator — scoring logic:**

```python
class VariantGroupValidator:
    """
    Evidence-based scoring. Groups must score above VARIANT_GROUP_MIN_CONFIDENCE
    to be materialized. Below threshold: no variants emitted (fail closed).
    """

    def validate(self, group: VariantCandidateGroup, *, page_url: str) -> bool:
        score = 0.0
        reasons = []

        # --- POSITIVE SIGNALS ---
        # Axis is recognized and semantic
        if group.axis_key in PUBLIC_VARIANT_AXIS_FIELDS:
            score += 0.3

        # Container is a fieldset (strong variant signal)
        if group.container_tag == "fieldset":
            score += 0.25

        # Options are strongly-typed (radio, checkbox, role=radio)
        strong_types = {"input_radio", "input_checkbox", "role_radio", "role_option"}
        if any(t in strong_types for t in group.option_node_types):
            score += 0.2

        # Multiple options with variant-specific data attributes
        if any(e.get("variant_id") for e in group.entries):
            score += 0.2

        # Options have product-like URLs that differ from each other
        urls = {e.get("url") for e in group.entries if e.get("url")}
        if len(urls) >= 2 and all(_variant_url_is_product_like(u) for u in urls):
            score += 0.15

        # Container is inside trusted scope root
        if group.scope_source == "trusted_scope":
            score += 0.1

        # Extractor used structured path (not swatch fallback)
        if group.extractor_path in {"select", "choice_radio"}:
            score += 0.05

        # --- NEGATIVE SIGNALS ---
        # Container is in known noise context
        noise_tokens = _DETAIL_VARIANT_CONTEXT_NOISE_TOKENS
        combined = " ".join(
            group.container_classes + group.ancestor_class_tokens
        ).lower()
        if any(t in combined for t in noise_tokens):
            score -= 0.5
            reasons.append(f"noise_context:{combined[:80]}")

        # All options share the same URL
        if len(urls) == 1:
            url = next(iter(urls))
            if not _variant_url_is_product_like(url):
                score -= 0.4
                reasons.append(f"all_urls_identical_listing:{url[:80]}")

        # Container tag is nav, header, footer
        if group.container_tag in {"nav", "header", "footer", "aside"}:
            score -= 0.4
            reasons.append(f"nav_container:{group.container_tag}")

        # Options are all generic anchors
        if set(group.option_node_types) == {"a"}:
            score -= 0.3
            reasons.append("all_options_are_anchors")

        # Option values don't fit the claimed axis semantically
        if group.axis_key == "color" and all(
            _value_is_navigation_phrase(v) for v in group.values
        ):
            score -= 0.3
            reasons.append("color_values_are_navigation_phrases")

        # Scope miss — came from soft scope or full page
        if group.scope_source == "soft_scope":
            score -= 0.1
        elif group.scope_source == "full_page":
            score -= 0.3
            reasons.append("full_page_scope")

        group.confidence = max(0.0, min(1.0, score))
        group.rejection_reasons = reasons
        return group.confidence >= VARIANT_GROUP_MIN_CONFIDENCE
```

Add to `extraction_rules.py`:
```python
VARIANT_GROUP_MIN_CONFIDENCE = 0.35   # config-controlled threshold
```

**Integration point:** In `extract_variants_from_dom`, replace current group dict emission with `VariantCandidateGroup` construction, run groups through `VariantGroupValidator.validate()`, and only proceed to Cartesian product materialization for groups that pass.

**Deliverable:** All Phase 0 regression tests pass. Validator confidence scores are logged (not just binary pass/fail) so you can tune thresholds per-site. New test file `test_variant_group_validator.py` covers all scoring branches.

---

### Phase 5 — Trim `variant_record_normalization.py` to Value-Only Scope (3–4 days)

Once the group validator owns structural decisions, `normalize_variant_record` should only do value-level work. Specifically, these functions currently make structural decisions that belong in the validator and should be either moved or removed:

| Function | Current role | Target |
|---|---|---|
| `_enforce_variant_axis_contract` | Drops rows with no axis value | Keep (value-level) |
| `_drop_cross_product_variant_rows` | Structural group decision | Move to validator |
| `_drop_parent_shared_variant_axes` | Structural axis decision | Move to validator |
| `_prune_axisless_rows_when_axisful_rows_exist` | Structural row decision | Move to validator |
| `_drop_subset_variants_when_richer_alternative_exists` | Structural deduplication | Move to validator |
| `_drop_invalid_variant_urls` | URL quality | Move to Phase 1 URL check |
| `_normalize_variant_axis_value` | Value cleaning | Keep, add word-count gate |
| `_clean_variant_rows` | Value cleaning | Keep |
| `_backfill_variant_context` | Context enrichment | Keep |
| `_dedupe_variant_rows` | Row deduplication | Keep |

This separation means `normalize_variant_record` becomes a pure value sanitizer, predictable and fast, while the validator owns all binary admission decisions.

---

### Phase 6 — Fix `_should_collect_dom_variants` Publication Policy (`detail_materializer.py`) (1 day)

Current:
```python
dom_strength = _variant_signal_strength(dom_variants.get("variants"))
return dom_strength > existing_strength
```

Problem: DOM strength is computed from row count and axis coverage, which a polluted extraction maximizes. Noisy DOM output routinely beats sparse but clean upstream data.

New policy:
```python
def _should_collect_dom_variants(...) -> bool:
    dom_rows = dom_variants.get("variants") or []
    # Only consider DOM if it came from validated groups
    if not all(
        isinstance(row, dict) and row.get("_validated")
        for row in dom_rows
    ):
        return False
    ...
    dom_strength = _variant_signal_strength(dom_rows)
    return dom_strength > existing_strength
```

Tag each variant row with `_validated: True` during Phase 4 materialization. `_validated` is stripped from public output in `_finalize_variant_contract`. This gives the publication policy a trustworthy signal without changing the strength comparison logic.

---

### Phase 7 — Observability (1 day, parallel with any phase)

Add structured logging at each decision point so you can trace why a variant group was accepted or rejected for any URL without running the full crawler:

```python
# In variant_group_validator.py
logger.debug(
    "variant_group_decision",
    extra={
        "url": page_url,
        "axis": group.axis_key,
        "values": group.values[:5],
        "confidence": group.confidence,
        "accepted": accepted,
        "rejection_reasons": group.rejection_reasons,
        "extractor_path": group.extractor_path,
        "scope_source": group.scope_source,
        "container": f"{group.container_tag}.{' '.join(group.container_classes[:3])}",
    }
)
```

This replaces the current invisible failure mode (bad variants silently published) with an inspectable, debuggable audit trail. Pair with a dev-mode flag that surfaces rejection reasons in the output record for local QA.

---

## Part 5 — Execution Order and Risk Profile

| Phase | Files Changed | Risk | Days | Prerequisite |
|---|---|---|---|---|
| 0 — Regression wall | Tests only | None | 1–2 | — |
| 1 — Immediate patches | `variant_record_normalization.py`, `extraction_rules.py` | Low | 1–2 | Phase 0 |
| 2 — Fail-closed scope | `variant_dom_cues.py`, `extraction_rules.py` | Medium | 2–3 | Phase 0, 1 |
| 3 — Restrict selectors | `detail_dom_extractor.py` | Low-Medium | 2–3 | Phase 0, 1 |
| 4 — Group validator | New `variant_group_validator.py`, `detail_dom_extractor.py` | Medium | 5–10 | Phases 0–3 |
| 5 — Trim normalizer | `variant_record_normalization.py` | Medium | 3–4 | Phase 4 |
| 6 — Publication policy | `detail_materializer.py` | Low | 1 | Phase 4 |
| 7 — Observability | `variant_group_validator.py`, logging | None | 1 | Phase 4 |

**Total for full migration: ~3–4 weeks of sequential work.**
Phases 0–3 can ship as a fast-track set in ~1 week and stop the active leaks immediately.
Phases 4–7 are the structural change that eliminates the root cause.

---

## Part 6 — What Tokens Are Still For (Post-Migration)

After the migration, the token lists in `extraction_rules.py` remain but serve a demoted role:

- `VARIANT_OPTION_VALUE_UI_NOISE_PHRASES` → last-resort residual filter inside `_normalize_variant_axis_value`, for values that pass group validation but are still textual garbage
- `DETAIL_VARIANT_CONTEXT_NOISE_TOKENS` → negative signal in `VariantGroupValidator`, not the primary gate
- `VARIANT_OPTION_VALUE_EXACT_NOISE_TOKENS` → same, residual filter

You will still add tokens occasionally for long-tail edge cases, but you will not be adding them to compensate for a missed structural decision. Each new token should have a clear answer to: "why did this pass group validation?" If the answer is "it shouldn't have", fix the validator, not the token list.

