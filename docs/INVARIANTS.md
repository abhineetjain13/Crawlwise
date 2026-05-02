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

## 3. Extraction Model — Field Quality and Repair

**How the candidate system works (correct, do not change):**
All tiers (adapter, structured data, JS state, DOM) write into a shared `candidates` dict via `_add_sourced_candidate`. Field selection in `_materialize_record` is per-field independently — `_winning_candidates_for_field` picks the best source for each field slot separately. This means price can come from js_state while sku comes from DOM. This architecture is correct. Do not replace it with a record-level merge.

**Source priority order (enforced by `SOURCE_PRIORITY` / `_SOURCE_PRIORITY_RANK`):**
1. Platform adapter
2. JSON-LD / Microdata
3. Network payload intercept
4. JS state
5. DOM selector / heuristics
6. LLM field repair when the user enabled LLM

**Exception for structured object fields:** `variants`, `variant_axes`, `selected_variant` use `finalize_candidate_value` across ALL source candidates, not just the winner's. This is intentional — do not change it to winner-only.

---

**Active known bugs:** none. Keep this section for active extraction bugs only. Do not document already-fixed bugs here.

**Visible detail prices are extraction-owned. Owner: `detail_extractor.py` + `config/extraction_rules.py`.**

When structured data lacks price but the rendered detail DOM exposes a product display-price block, `extract/detail_price_extractor.py` may fill `price` and `original_price` from configured detail price selectors. This is still upstream extraction. Do not add price repair in `publish/` or `pipeline/`.

**Definitions:**
- **Requested fields**: Fields explicitly listed in run settings via `requested_fields`
- **Default canonical repair fields for ecommerce detail**: `price`, `title`, `image_url` (as defined in config)
- **High-value fields**: The union of requested fields and default canonical fields for the active surface
- **Missing-field diagnostic**: A structured reason why a field could not be extracted (non-public, requires authentication, dynamically loaded only, etc.)

**Canonical field quality is extraction-owned.**
For ecommerce detail, missing high-value fields such as `price`, `title`, and `image_url` are not acceptable just because one source tier had high total confidence. If the run requested deeper fields such as `brand`, `sku`, `variants`, or `availability`, those requested fields join the contract. Extraction must either repair contract fields, mark a diagnostic reason they are not public/extractable, or leave a visible missing-field diagnostic before persistence.

**Enrichment is not extraction cleanup.**
Data enrichment consumes persisted `record.data` as the upstream extraction contract. It must not add blocklists, URL-token cleanup, UI-title suppression, category/source correction, or field-specific compensations for polluted canonical fields. If enrichment output exposes garbage such as URL tokens in `brand`, UI copy in `title`, impossible `size` values, or breadcrumb/category pollution, fix the acquisition/extraction candidate, coercion, ranking, or finalization path before persistence.

**Shopify taxonomy and attributes are the enrichment source of truth.**
Data enrichment must use `shopify_categories.json` for product category paths and category attribute handles, and `shopify_attributes.json` for Shopify-defined attribute values such as colors, sizes, fabrics, materials, and target gender. Do not build local product-universe dictionaries for categories, colors, materials, sizes, or category synonyms. Small local rules are allowed only for generic parsing mechanics such as token singularization, UI noise stripping, source-field lookup, and availability wording that Shopify does not model.

**LLM is an explicit repair tier, not forbidden.**
When `llm_enabled=True` and active config allows the relevant LLM workflow, LLM must be considered for missing requested/default canonical fields after deterministic/browser evidence has been used. It may fill empty fields with provenance and validation. It must not silently overwrite populated deterministic values.

---

**VIOLATION signatures — do not introduce these:**
- Replacing the per-field `candidates` + `_winning_candidates_for_field` system with a record-level merge or a single `winner` variable
- Adding a new tier or source that writes directly to `record` instead of going through `_add_sourced_candidate`
- Accepting a partial ecommerce detail record with missing requested/default high-value fields and no repair attempt or diagnostic
- Treating `requested_fields=[]` as permission to ignore ecommerce detail quality
- Forcing optional deep ecommerce fields such as `brand`, `sku`, or `variants` when the user did not request them
- Fixing missing variants by adding hidden browser-side extraction that bypasses normal field provenance
- Calling `backfill_detail_price_from_html` only at the end of the full tier sequence but not after early exit paths
- Fixing missing visible PDP prices in persistence/export instead of `detail_extractor.py`
- Suppressing LLM repair when `llm_enabled=True`, config allows it, high-value fields are missing, and deterministic/browser evidence did not fill them
- Letting LLM replace a populated adapter / structured / network / JS / DOM value without an explicit conflict-review workflow
- Adding enrichment-side blocklists or cleanup to hide polluted extracted `title`, `brand`, `category`, `size`, `material`, or other canonical source fields
- Adding local category synonym maps such as "matching sets -> outfit sets" instead of improving Shopify-backed taxonomy matching
- Adding hand-maintained material/color/category lists when Shopify attributes or category metadata already contain the vocabulary

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

## 6. Acquisition — Observe, Render, Diagnose

**Rule:** Acquisition returns observational facts only: URL, final URL, status, method, headers, blocked state, diagnostics, and artifacts. It does not invent blocker causes, insert retries not in policy, or escalate without evidence.

Browser acquisition may use Patchright or real Chrome to produce better observations: rendered HTML, network payloads, page markdown, visible text, accessibility text, readiness probes, screenshots when enabled, and explicit detail-expansion artifacts (HTML/JSON from clicked size/color variant controls, expanded accordion sections, etc.). These are observation artifacts. They are allowed inputs to extraction and LLM repair.

Browser acquisition must not fabricate fields. It must not run hidden page scripts that directly assign `price`, `brand`, `variants`, or other logical fields outside the normal extraction/repair provenance path.

Field-aware browser retry is allowed when policy and diagnostics justify it. A non-browser fetch that produces a low-quality ecommerce detail record missing requested/default high-value fields may retry browser. Default ecommerce detail retry targets stay limited to `price`, `title`, and `image_url`; user-requested fields are added explicitly. A Patchright result with usable content may escalate once to real Chrome only when high-value fields remain missing and diagnostics show weak rendered evidence. Every retry must be logged.

Diagnostics controls are user controls. If `diagnostics_profile.capture_screenshot` is `False`, browser acquisition must not capture any screenshots, regardless of outcome.

Browser-driver disconnects are URL-local failures. If a shared browser dies during `new_context`, page bootstrap, or content serialization, the runtime may recycle that browser once, but `_batch_runtime.py` must keep the failure scoped to the current URL and continue the batch.

**Usable content beats provider noise. This is a hard contract.**
If browser diagnostics report `browser_outcome == "usable_content"`, provider telemetry such as `provider:*`,
`active_provider:*`, `challenge_provider_hits`, vendor headers, Akamai/DataDome/Cloudflare script markers,
or challenge iframe markers is diagnostic evidence only. It must not by itself set `blocked=True`,
`failure_reason=challenge_shell`, host hard-block memory, or real-Chrome retry.

Only these can override `usable_content`:
- explicit blocked outcome (`challenge_page`, `low_content_shell`)
- challenge-title evidence (`title:*`)
- strong visible blocker text evidence (`strong:*`, for example real CAPTCHA/access-denied copy)
- HTTP-forced hard block status where no usable browser content was recovered

This rule exists because modern commerce pages often load normal PDP content while bot-defense scripts,
cookies, iframes, or Akamai/DataDome/Cloudflare markers remain present. Treating those markers as a block
is a crawler bug, not stricter security detection.

**VIOLATION signatures:**
- Block detection classifies a page as blocked based on a vendor header alone when useful content is present and extractable
- Block detection classifies a page as blocked from generic `captcha` text or `recaptcha` / `hcaptcha` provider markers alone when the page still has real extractable listing/detail content and no stronger challenge evidence such as challenge-title hits, active challenge markers, or challenge elements
- `browser_outcome == "usable_content"` plus only `provider:*`, `active_provider:*`, `challenge_provider_hits`, vendor headers, or challenge iframe markers becomes `challenge_shell`
- A usable detail page retries from Chromium to real Chrome solely because Akamai/DataDome/Cloudflare provider markers are present
- Host protection memory records a hard block from a usable browser page with provider markers but no title/strong blocked evidence
- A retry happens that is not logged and visible in diagnostics
- Browser escalation triggers for a URL that returned 200 with complete requested/default high-value fields
- Browser-side code writes logical extraction fields directly into the record instead of returning observation artifacts
- Browser acquisition captures a screenshot when `capture_screenshot=False`
- A learned real Chrome success causes a later run to launch Patchright first without explicit user override or after the contract has been marked stale (see Rule 9)

---

## 7. Listing and Detail Stay Separate

**Rule:** Listing extraction never falls back into single-record detail behavior. A listing run with zero records produces `listing_detection_failed`. It never produces a fake success with one row of page metadata.

Detail extraction must also reject collection/category URLs that expose product-tile prices. A category URL submitted under `ecommerce_detail` is a bad seed, not a single PDP. Do not turn its first tile or page heading into a detail record.

**VIOLATION signatures:**
- A listing run returns 1 record containing the page title, OG description, or brand name
- `verdict.py` returns `success` for a listing run that extracted zero product rows
- `crawl_engine.py` routes a listing URL through `detail_extractor.py`
- An `ecommerce_detail` run on `/c/...`, `/category/...`, or `/collections/...` persists a fake detail record from a product tile
- Detail expansion clicks header/nav/footer chrome and navigates a PDP request onto a marketing or utility page

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
- Run-scoped and domain-scoped browser storage must stay engine-scoped; `chromium`, `patchright`, and `real_chrome` state must not bleed across engines.
- Browser-to-HTTP handoff may only reuse sanitized engine-scoped session state on the same proxy identity. If proxy affinity cannot be proven, skip handoff and stay browser-first.
- Host browser-first memory is for repeated hard blocks, not one noisy challenge hit.
- Detail browser fetches to hosts with recent challenge history may warm the site origin (e.g., preflight DNS, TCP/TLS handshake, or resource prefetch) before direct PDP navigation; that warmup happens before the target nav, not after a challenge page already landed.
- Learned acquisition contracts live in editable `DomainRunProfile` memory scoped by normalized `(domain, surface)`. They may prefer a proven browser engine and safe engine-scoped cookie handoff, but explicit run settings always override them.
- Future crawls must reuse the successful acquisition/data-extraction path and learned selectors for the domain/surface without fresh experimentation unless the user explicitly changes settings, enables experimentation, resets learned memory, or the contract becomes stale.
- When safe cookies exist for the saved engine:
  1. Try curl handoff first.
  2. On drift/block/empty output, fallback to the proven browser engine.
  3. On further failure, revert to the normal auto policy.
- After 3 consecutive quality failures the acquisition contract is marked stale. Stale contracts must not keep forcing browser engine or curl handoff choices.

**Why this is here:**
Static cleanup advice to persist/reuse more browser state caused a real regression on 2026-04-23. The crawler started replaying PerimeterX challenge state (`_px*`, `pxcts`, PX localStorage) across runs, which poisoned acquisition on multiple sites. Any future "simplification" of cookie memory must preserve this guard and its regression tests.

---

## 10. LLM — Explicit, Degradable, Validated

**Rule:** LLM runs only when both run settings and active config enable it. When enabled, LLM is a normal repair path for missing requested/default canonical fields after deterministic/browser evidence has been used. For ecommerce detail, default canonical LLM repair is limited to `price`, `title`, and `image_url`; deeper fields are repaired only when explicitly requested. LLM failures must be visible in diagnostics and must not corrupt deterministic extraction state.

**VIOLATION signatures:**
- LLM fires on a run where `llm_enabled=False`
- A deterministic field value is replaced by an LLM output without explicit gating
- An LLM timeout or API error silently produces an empty record instead of a diagnostic log entry
- A missing requested/default high-value field is left unrepaired without recording that LLM was disabled, unavailable, rejected, or unnecessary

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

---

## 13. Google Search Mimicry Footprint

**Rule:** Google native search discovery must mimic human behavior to avoid immediate blocks. 
- **No random mouse jitter:** Never call `emit_browser_behavior_activity` on Google Search pages; erratic, high-speed mouse trajectories are a strong bot signal.
- **Natural input:** Use `page.locator(...).fill()` and `Enter` rather than direct `goto` or slow character-by-character typing. 
- **Natural syntax:** Queries must not use strict boolean dorking (e.g., exact match quotes around every word) unless explicitly required for specific repair.

**VIOLATION signatures:**
- `emit_browser_behavior_activity(page)` is called inside `_google_native_session`.
- `_quoted` wraps every search token in double quotes.
- `page.goto` is used for search execution instead of interacting with the search box.
