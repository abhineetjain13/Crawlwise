# Batch D Findings — Unify Leakage Audit

> **Source:** Gemini audit of 7 unify/publish files, run 2026-04-17 per [01-gemini-audit-prompt-pack.md](./01-gemini-audit-prompt-pack.md) Batch D template. Raw deliverables pasted to chat; this file is the curated read.
> **Status:** Accepted. Feeds Slice 4 (Invariant 12 repair + unify leak repatriation).

## Executive summary

1. **Leak count is low but concentrated.** 8 leaks total across the 7 files. `pipeline/stages.py` (4), `pipeline/utils.py` (3), `publish/metadata.py` (1). Three files are clean: `pipeline/core.py`, `pipeline/runner.py`, `pipeline/field_normalization.py`, `publish/verdict.py`.
2. **The most damaging leaks are in `pipeline/stages.py`.** `_discover_child_listing_candidate_from_soup` (L48, L74, L75) and `_looks_like_category_tile_listing` (L101) run discovery + classification inside the pipeline stage layer — they bypass extract's noise policy and quality gates, so whatever they find is not noise-filtered and not scored.
3. **Invariant 12 probe returned clean.** Gemini found no page-native-to-canonical force-fit, no invented canonical fields, and no residual-bucket overflow *in these 7 files*. The Invariant 12 damage lives elsewhere — specifically in noise-rule rejections flagged by the Slice 2 closing note (rules that drop page-native labels like `select size`, `availability`). Batch D clears the unify/publish layer; the repair target is noise-policy tables in `config/extraction_rules.py`, not these 7 files.
4. **Text-cleaning leaks are mechanical and easy to move.** `pipeline/utils.py` (`_clean_page_text`, `_normalize_committed_field_name`, `_review_bucket_fingerprint`) and `publish/metadata.py::_clean_candidate_text` are small helpers that belong in `extract/` candidate processing. Low risk, small wins.

## Leak inventory (8 leaks)

| # | File:line | Function | Field | Kind | Evidence (≤15 words) | Extract-side owner |
|---|-----------|----------|-------|------|----------------------|--------------------|
| 1 | [pipeline/stages.py:L48](../../backend/app/services/pipeline/stages.py#L48) | `_discover_child_listing_candidate_from_soup` | url / child_listing_url | RE-PARSE | `for anchor in soup.select("a[href]"):` | discover or extract module |
| 2 | [pipeline/stages.py:L74](../../backend/app/services/pipeline/stages.py#L74) | same | title / anchor text | RE-CLEAN | `" ".join(anchor.get_text(" ", strip=True).split()).lower()` | extract text normalizers |
| 3 | [pipeline/stages.py:L75](../../backend/app/services/pipeline/stages.py#L75) | same | title / anchor text | RE-DERIVE | keyword-token scoring for category anchors | extract or discover heuristic |
| 4 | [pipeline/stages.py:L101](../../backend/app/services/pipeline/stages.py#L101) | `_looks_like_category_tile_listing` | url, title, image_url | RE-DERIVE | image/title heuristics for category tile classification | extract listing quality |
| 5 | [pipeline/utils.py:L26](../../backend/app/services/pipeline/utils.py#L26) | `_clean_page_text` | generic text | RE-CLEAN | `unescape(str(value or "")).replace("\u00a0", " ")` | extract candidate processing |
| 6 | [pipeline/utils.py:L39](../../backend/app/services/pipeline/utils.py#L39) | `_normalize_committed_field_name` | field names | RE-CLEAN | camel-to-snake `re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)` | extract or normalize schema mapper |
| 7 | [pipeline/utils.py:L50](../../backend/app/services/pipeline/utils.py#L50) | `_review_bucket_fingerprint` | review_bucket values | RE-CLEAN | fingerprint normalization for dedup | extract or normalize review formatter |
| 8 | [publish/metadata.py:L16](../../backend/app/services/publish/metadata.py#L16) | `_clean_candidate_text` | generic text | RE-CLEAN | `" ".join(str(value).split()).strip()` | extract candidate processing |

## Leak concentration

| File | RE-PARSE | RE-CLEAN | RE-DERIVE | RE-ARBITRATE | Inv. 12 | Total |
|------|----------|----------|-----------|--------------|---------|-------|
| `pipeline/core.py` | 0 | 0 | 0 | 0 | 0 | 0 |
| `pipeline/stages.py` | 1 | 1 | 2 | 0 | 0 | **4** |
| `pipeline/runner.py` | 0 | 0 | 0 | 0 | 0 | 0 |
| `pipeline/field_normalization.py` | 0 | 0 | 0 | 0 | 0 | 0 |
| `pipeline/utils.py` | 0 | 3 | 0 | 0 | 0 | **3** |
| `publish/metadata.py` | 0 | 1 | 0 | 0 | 0 | **1** |
| `publish/verdict.py` | 0 | 0 | 0 | 0 | 0 | 0 |
| **TOTAL** | 1 | 5 | 2 | 0 | 0 | **8** |

## Invariant flags (non-12)

Gemini flagged one:

- **[pipeline/stages.py:L48](../../backend/app/services/pipeline/stages.py#L48) — Inv. 13 (noise filtering).** `_discover_child_listing_candidate_from_soup` selects `a[href]` tags from the raw soup without respecting the container noise policy the extract stage enforces. Navigation/footer chrome anchors leak into retry logic.

No Inv. 6 arbitration leaks. No Inv. 7 verdict contamination. No Inv. 11 detail-fallback leaks. No Inv. 14 clean-record violations.

## Invariant 12 probe — clean in Batch D scope, damaged elsewhere

Gemini returned "None" for Invariant 12 in these 7 files. Good news for unify/publish. But the user's "full HTML acquired, partial records delivered" complaint points to Invariant 12 damage **at the noise-filter boundary**, not in these 7 files. From the Slice 2 closing note:

> Rules that reject values such as `select size`, `select color`, `select colour`, `availability`, and generic navigation/UI labels remain in place after consolidation. Those rules may be filtering page-native labels rather than purely synthetic noise.

**This is the Invariant 12 repair target.** It lives in `config/extraction_rules.py` (noise-rule data) and `extract/noise_policy.py` (rejection functions). Slice 4 must include a targeted audit of those rules, not just the 8 unify leaks.

## Data quality caveats

- Deliverable 2 cites line numbers without showing the conditional chains around them. Slice 4 must re-read each site before moving code — a "re-clean" may actually be a necessary contract enforcement (e.g., if extract emits `None` for some sources).
- Gemini did not enumerate how often the leak sites fire. A RE-CLEAN in `pipeline/utils.py` that handles one rare case is different from one that processes every record. Codex profiles each before repatriation.
- `publish/metadata.py::_clean_candidate_text` may be defensive for upstream-broken data. Before moving, verify no non-extract path writes into metadata.

## What this unlocks

1. **Slice 4 Part A — Invariant 12 noise-rule audit.** Walk the consolidated noise tables in `config/extraction_rules.py`. Every rule that rejects a value because it *looks like a page-native label* needs to be re-classified: is it noise (page chrome) or data (page-native attribute)? The latter must be preserved. This is the user-visible output win.
2. **Slice 4 Part B — Repatriate 8 leaks.** `pipeline/stages.py` discovery code moves to `discover/` or `extract/`. Text helpers move to `extract/candidate_processing.py` (or wherever extract's normalizer home is). `publish/metadata.py` trivial cleaner moves too.
3. **Slice 4 prerequisite.** `run_extraction_smoke.py` must be restored (fix `ModuleNotFoundError: app.services.semantic_detail_extractor`) before Slice 4 can claim verified output improvements. Without it, any "extra fields now surface" claim is unverifiable.
