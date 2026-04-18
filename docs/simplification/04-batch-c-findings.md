# Batch C Findings — Page-Type × Surface Branching, Codebase-Wide Sweep

> **Source:** Gemini audit of 23 non-extract files, run 2026-04-17 per [01-gemini-audit-prompt-pack.md](./01-gemini-audit-prompt-pack.md) Batch C template. Raw deliverables pasted to chat; this file is the curated read.
> **Status:** Accepted. Feeds Slice 3 (acquisition strategy consolidation).

## Executive summary

1. **Branching is mostly essential, not accidental.** Of 54 branches in scope, 46 are ESSENTIAL (different data shape, fetch strategy, or schema). Only **8 are ACCIDENTAL** — small collapse target. The "original sin" framing the user feels is confirmed to be about *where the decisions live*, not *how many of them there are*.
2. **Acquisition carries the heaviest branch load.** `acquisition/policy.py` (11 branches), `acquisition/browser_readiness.py` (5), `acquisition/traversal.py` (2), `acquisition/browser_client.py` (1), `acquisition/recovery.py` (1), plus `adapters/registry.py` (1) — 21 branches across 6 acquisition files. **None of them is a single "what strategy do we use" owner**; each file re-reads `surface` / `page_type` and decides for itself. This is the "confusion in acquisition strategies" the user reports.
3. **Normalizers/listings.py is a surface-dispatch megafile.** 12 essential branches in one file doing job vs ecommerce record shaping. Not a Slice 3 target (every branch is essential), but flags it as a Phase 2/Phase 5 target once the scorer enables collapse.
4. **Invariant risks are narrow and named.** 7 flags total, all against essential branches. Collapse strategies must preserve those semantics.

## Branch classification counts

| Classification | Count | Where concentrated |
|----------------|-------|--------------------|
| ESSENTIAL | 46 | `normalizers/listings.py` (12), `acquisition/policy.py` (8), `signal_inventory.py` (5), acquisition readiness/client/traversal (5) |
| ACCIDENTAL | 8 | `acquisition/policy.py` (4), `acquisition/browser_readiness.py` (2), `pipeline/listing_helpers.py` (1), `adapters/registry.py` (1) |
| UNCLEAR | 0 | — |

## The 8 accidental branches — ranked removability (Slice 3 targets)

From Gemini Deliverable 4:

| Rank | File:line | Function | What it does | Collapse strategy | Blast |
|------|-----------|----------|--------------|-------------------|-------|
| 1 | [browser_readiness.py:L21](../../backend/app/services/acquisition/browser_readiness.py#L21) | `_is_listing_surface` | Alias check for listing string suffix | Inline the suffix check at call sites | this file |
| 2 | [browser_readiness.py:L65](../../backend/app/services/acquisition/browser_readiness.py#L65) | `_wait_for_listing_readiness` | Early-exit if not listing | Delete guard; readiness loop fails naturally on non-listing | this file |
| 3 | [listing_helpers.py:L31](../../backend/app/services/pipeline/listing_helpers.py#L31) | `_looks_like_loading_listing_shell` | Early-exit if not listing | Delete guard; DOM heuristic fails naturally | this file |
| 4 | [policy.py:L404](../../backend/app/services/acquisition/policy.py#L404) | `diagnose_commerce_surface_page` | Early-exit if not ecommerce | Rename to generic diagnostic; run unconditionally | this module |
| 5 | [policy.py:L467](../../backend/app/services/acquisition/policy.py#L467) | `diagnose_job_surface_page` | Early-exit if not job | Merge with commerce diagnostic into one generic pass | this module |
| 6 | [policy.py:L133](../../backend/app/services/acquisition/policy.py#L133) | `browser_escalation_decision` | Validates surface is recognized before JS-shell rules | Drop bounds check; evaluate rules blindly | this module |
| 7 | [policy.py:L214](../../backend/app/services/acquisition/policy.py#L214) | `decide_acquisition_execution` | Picks diagnostic payload name by surface | Single payload shape with surface as field | this module |
| 8 | [registry.py:L55](../../backend/app/services/adapters/registry.py#L55) | `try_blocked_adapter_recovery` | Aborts if surface unrecognized | Allow adapter to decline URLs itself | cross-module |

## Invariant-risk flags (essential branches — DO NOT collapse these in Slice 3)

Gemini flagged 7 branches where naive removal would violate an invariant:

- **[policy.py:L107](../../backend/app/services/acquisition/policy.py#L107) — Inv. 29.** `requires_browser_first` hardcodes Playwright escalation by job-family classification. Family-based is allowed; removing forces site hardcodes.
- **[policy.py:L158](../../backend/app/services/acquisition/policy.py#L158) — Inv. 16.** Forces browser rendering on detail JS shells. User surface directive must be honored; auto-escalation only for detail pages is the correct boundary.
- **[schema_service.py:L46](../../backend/app/services/schema_service.py#L46) — Inv. 11.** Prevents ecommerce schema spilling into job listings. Removal pollutes job records with variant/cart fields.
- **[schema_service.py:L48](../../backend/app/services/schema_service.py#L48) — Inv. 12.** Prevents job schema spilling into ecommerce. Removal inverts and pollutes ecommerce records.
- **[listing_flow.py:L205](../../backend/app/services/pipeline/listing_flow.py#L205) — Inv. 8.** Zero-item job boards get `listing_detection_failed` instead of detail fallback. Removing this violates the listing guard.
- **[signal_inventory.py:L154](../../backend/app/services/discover/signal_inventory.py#L154) — Inv. 6.** Listing-specific NEXT_DATA thresholds. Collapsing merges listing/detail scoring.
- **[normalizers/listings.py:L454](../../backend/app/services/normalizers/listings.py#L454) — Inv. 11.** Filters size/color variant fragments from listing arrays.

## Cross-reference to Batch A (dedupe)

Gemini flagged 4 echoes of Batch A branches:

| Batch C file:line | Upstream | Relationship |
|-------------------|----------|--------------|
| `policy.py:L240` | Batch A listing-extractor traversal | echo — enforces same traversal block |
| `traversal.py:L422` | Batch A pipeline gate | echo — aborts traversal on detail |
| `normalizers/listings.py:L83` | Batch A listing-extractor | echo — enforces schema split |
| `schema_service.py:L46` | Batch A persistence gate | independent |

**No duplicate inventory** — Batch A's 15 extract branches stay separately counted.

## Data quality caveats

- Upstream Batch A file:line cross-references are marked "unknown" in Deliverable 3. Slice 3 must verify the echo relationship before collapse, not trust the label alone.
- `normalizers/listings.py` classified 12 branches as ESSENTIAL. Some (e.g., L558-L605, the `_preferred_generic_item_values` key routing) are plumbing-like surface-key dispatch that *could* be data-driven. Defer to Phase 2; do not re-open in Slice 3.
- `signal_inventory.py` (discover/) vs `signal_inventory.py` (extract/) — two files with the same name. Batch A touched the extract one, Batch C the discover one. Confusing; flag as a Phase 2 rename.

## What this unlocks

1. **Slice 3 — Acquisition strategy consolidation.** The 21 branches concentrated in 6 acquisition files are the "confusion" the user named. Slice 3 establishes `policy.py` as the single decision owner: other acquisition files consume an `AcquisitionPlan` (surface-aware, but decided once). Collapses the 8 accidentals as the small wins. Essential branches remain but move under the plan owner.
2. **Phase 2 input.** Of the 46 essentials, ~20 are key-dispatch plumbing in `normalizers/listings.py` and `discover/signal_inventory.py` — data-driven collapsible once Phase 5's scorer is in. Batch C is the register for that future work.
3. **No Slice 3 changes to Batch B territory.** `field_alias_policy.py` and `config/field_mappings.py` are not retouched.
