# Simplification Program — Mid-Flight Audit (2026-04-17)

> **Purpose.** Honest assessment of what Slices 0/1/2 actually delivered, what the user hasn't yet felt, and why. Written before Slices 3 and 4 so they're scoped to produce user-visible outcomes instead of more internal tidying.
> **Scope.** Everything in `docs/simplification/` plus the acquisition refactors Codex landed outside the slice program (`daa72f7`, `15f5d61`).

## What landed

| Slice | Shipped | Code delta |
|-------|---------|-----------|
| Slice 0 — Dead-code kill | 5 symbols removed (`normalized_field_token`, `coerce_nested_text`, `SignalInventory` class, `VERDICT_RULES`, `requested_field_alias_map`, `requested_field_terms`); TODOs on `HYDRATED_STATE_PATTERNS`/`KNOWN_ATS_PLATFORMS` | Small. Most flagged symbols were still live in normalizers/publish/pipeline — Slice 0 couldn't touch them. |
| Slice 1 — Break circular import | `config/field_mappings.py` ↔ `field_alias_policy.py` cycle broken; `excluded_fields_for_surface` rederived from `CANONICAL_SCHEMAS`; re-export bridges deleted | Medium restructure, zero behavior change. Parity test added. |
| Slice 2 — Consolidate noise data | All noise tables moved to `config/extraction_rules.py`; `noise_policy.py` left with functions + compiled caches; parity test added | Mostly moves, no behavior change. Flagged Invariant 12 concern: noise rules reject page-native labels (`select size`, `availability`, etc.). |
| Acquisition (Codex, outside slice program) | `refactor(acquisition): split browser client support modules`; `stabilize acquisition and runtime refactors` | Module split. Strategy decisions remained scattered across `policy.py`, `acquirer.py`, `browser_client.py`, `browser_readiness.py`, `traversal.py`, `recovery.py`. |

## What the user hasn't seen (and why)

1. **No code reduction.** Slices 0-2 were structural: move, rename, break cycles. The duplication Batch A uncovered (5 canonical fields extracted across 4-6 files) is untouched. That's Phase 2 work, gated on Phase 5's quality scorer per rewritten Invariant 6.
2. **No output improvement.** User acquires full HTML but sees partial records. Two concrete causes now proven:
   - **Slice 2 finding (Invariant 12 concern):** noise rules in `extraction_rules.py` reject values like `select size`, `availability`, generic nav/UI labels. Some of those are page-native labels — the page exposes them and the noise filter drops them. Invariant 12 (rewritten) forbids this.
   - **Batch D finding:** `pipeline/stages.py::_discover_child_listing_candidate_from_soup` and `_looks_like_category_tile_listing` parse and classify outside the extract stage. Decisions there contaminate retry logic instead of feeding a single extraction output.
3. **No speed improvement.** Hot paths (acquisition waterfall, extraction) weren't touched. Nothing Slices 0-2 did would reduce CPU or wall time.
4. **Acquisition strategy confusion is real.** Batch C confirms: `acquirer.py` (33 hits), `policy.py` (25), `browser_client.py` (16), `browser_readiness.py` (12), `traversal.py` (13) all read `surface` / `page_type` to pick a strategy. Most branches are ESSENTIAL (46 of 54 in the 23-file sweep), so the fix is **not** to delete branches — it's to centralize the *decision* so every file consumes one `AcquisitionPlan` instead of each redeciding.

## Verification status (red)

- `run_extraction_smoke.py` fails with `ModuleNotFoundError: app.services.semantic_detail_extractor` — **blocks extraction verification end-to-end**. Predates the slice program. Must be fixed before Slice 3/4 can claim green.
- Pre-existing failures in `tests/services/adapters/test_base_adapter.py`, `tests/services/config/test_field_mappings_collisions.py`, `tests/services/extract/test_listing_extractor.py`, `tests/services/test_batch_runtime_retry_update.py`, `tests/services/test_llm_runtime.py` — inherited. Suite is not green.
- `run_acquire_smoke.py commerce` is the only end-to-end check passing.

**Implication:** Slices 3/4 must treat "unblock `run_extraction_smoke.py`" as a prerequisite step, not an afterthought. Without it no behavior claim is verifiable.

## What Slices 3 and 4 have to deliver

Based on this audit, Slices 3/4 are scoped for **user-visible outcomes**, not tidying:

- **Slice 3 — Acquisition Strategy Consolidation.** One decision owner (`policy.py`) produces an `AcquisitionPlan`; every consumer in `acquirer.py` / `browser_client.py` / `browser_readiness.py` / `traversal.py` / `recovery.py` reads the plan instead of reading `surface`/`page_type` themselves. Collapses the 8 accidental branches Batch C ranked. Targets "confusion in acquisition strategies on what to use when." User-visible: one file to read to understand acquisition behavior.
- **Slice 4 — Invariant 12 Repair + Unify Leak Repatriation.** Fix the noise-filter false-positives that drop page-native labels (from Slice 2 closing note), and repatriate the 8 unify leaks Batch D found (especially `pipeline/stages.py` listing-discovery code and the text-cleaning leaks in `pipeline/utils.py` / `publish/metadata.py`). Prerequisite: restore `run_extraction_smoke.py`. User-visible: fields that were silently dropped now appear in records.

## Items deferred (NOT in Slices 3/4)

- **Phase 2 — Collapse duplicate extractors.** Batch A's field × file map says 5 canonical fields are each extracted in 4-6 files. Collapsing requires the quality scorer (new Invariant 6), which is Phase 5 per roadmap. Deferring is correct; the scorer is a dependency.
- **Platform-family adapter consolidation.** Batch C dropped 15 adapter files from scope because their branches are definitionally essential. Revisit when Phase 2 lands.
- **The 15 pre-existing test failures** that are not in Slice 3/4 scope stay on the backlog.

## Acceptance criteria for this audit

Audit is accepted when the user agrees: (a) the gap between "slices shipped" and "user impact felt" is explained by missing Phase 2 and by the Invariant 12 / unify-leak damage, (b) Slices 3 and 4 as scoped above are the right next step, (c) `run_extraction_smoke.py` must be restored first.
