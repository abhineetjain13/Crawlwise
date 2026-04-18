# Final Audit + Simplification Roadmap

> **Purpose.** Last planning pass before Codex executes Slices 3/4 and the subsequent LOC-reduction slices. Grounds the plan in verified code truth, catches Gemini hallucinations, and names the real blocker: test-to-implementation coupling, not missing audits.
> **Date.** 2026-04-17. **Status.** Governs Slices 5+ until superseded.

## What I verified myself (against every Gemini claim before trusting it)

| Claim source | Claim | Reality | Action |
|---|---|---|---|
| Slice 0/1/2 closing notes | `run_extraction_smoke.py` fails with `ModuleNotFoundError: app.services.semantic_detail_extractor` | **Phantom.** `semantic_detail_extractor` appears in zero `.py` files across `backend/app/` and `backend/tests/`. The smoke runner imports `extract_semantic_detail_data` from `semantic_support.py:75` — that function exists. | **Remove the Step 0 prerequisite from Slice 4.** Run the smoke runner once before Slice 4; if it fails, the error will be something else entirely. |
| Batch A | Three price regexes in three files | **Four files.** `config/extraction_rules.py`, `listing_card_extractor.py`, `listing_structured_extractor.py`, `detail_extractor.py`. | Extract registry work (Slice 5) uses the four-file reality, not three. |
| Batch A | `shared_logic.normalized_field_token`, `coerce_nested_text` are dead exports | **Correct** — Slice 0 deleted them. | — |
| Batch B | Several flagged "unused" symbols | **Partially wrong.** Slice 0 found `CANDIDATE_PROMO_ONLY_TITLE_PATTERN`, `EMPTY_SENTINEL_VALUES`, `REQUIRED_FIELDS_BY_SURFACE`, `NESTED_*_KEYS`, `field_value_contains_noise` were all live in `normalizers/`, `publish/`, `pipeline/`. Gemini missed dynamic/indirect references. | **Rule:** any future Gemini "unused" claim must be grep-gated by Codex before deletion, per the Slice 0 safety rule. Keep it. |
| Batch C | Detail flow (`pipeline/detail_flow.py`) has 26 token hits but Gemini marked it "N" for branches | **Likely a miss.** 26 hits with zero branches is implausible. Re-read if Slice 3 scope ever extends to detail_flow. | Flag in Slice 3 snapshot; not urgent. |
| Batch C | Cross-reference to Batch A Deliverable 3 has "unknown" upstream lines | **Accurate.** Gemini didn't have Batch A loaded in Batch C. Cross-refs are directional only. | Codex verifies each echo manually in Slice 3 Step 1. |

**Hallucination budget.** Gemini is reliable on shape (what files exist, what branches exist, what kind of leak occurs). It is **not** reliable on "unused," "dead," or cross-batch references. Every deletion stays grep-gated. This rule carries forward.

## What I measured directly

| Area | Files | LOC | Notes |
|---|---|---|---|
| `backend/app/services/` | — | **46,596** | Total implementation surface area. |
| `backend/tests/` | **94** | **18,074** | Test-to-implementation ratio 39%. |
| `extract/` | 27 | **13,788** | Top 7 files = 7,951 LOC = 58% of extract. `variant_builder.py` (1,738), `listing_card_extractor.py` (1,516), `service.py` (1,343), `semantic_support.py` (942), `detail_extractor.py` (915), `listing_quality.py` (791), `listing_structured_extractor.py` (706). |
| `acquisition/` | — | 9,802 | Slice 3 scope. |
| `adapters/` | 15+ | 2,790 | Slice 6 scope. |
| `pipeline/` | — | 3,298 | Slice 4 + Slice 9 scope. |
| `normalizers/` | — | 2,071 | Slice 8 scope. |
| `discover/` | — | 1,855 | Slice 7 scope. |

## The real blocker — confirmed

You named it: *stale tests tightly couple files; Codex can't refactor because tests pin the current shape*. I verified:

| Test file | Tests | LOC | Implementation | Ratio | Diagnosis |
|-----------|-------|-----|----------------|-------|-----------|
| `tests/services/extract/test_listing_extractor.py` | **95** | **2,667** | `listing_extractor.py` (559 LOC) | **4.77x** | Anchor. 95 tests against a 559-LOC module means many pin intermediate shapes, private helpers, or narrow HTML fixtures. Collapses in Slice 5 will break a majority of these tests not because behavior changed but because internal names did. |
| `tests/services/test_llm_runtime.py` | 12 | 503 | `llm_runtime.py` | — | Listed as pre-existing failing. Low test density (42 LOC/test) suggests heavy mocking. Review for behavior vs. mock-structure coupling. |
| `tests/services/test_batch_runtime_retry_update.py` | — | 237 | — | — | Pre-existing failing. Probably pins retry internals. |
| `tests/services/adapters/test_base_adapter.py` | — | 70 | `adapters/base.py` | — | Small. Likely a contract test that needs a one-line fix, not stale per se. |
| `tests/services/config/test_field_mappings_collisions.py` | 2 | 27 | `FIELD_ALIASES` | — | **Not stale.** Asserts alias collision set — two tests, one expects `{"image": ["image_url", "additional_images"]}`. Probably just needs updating after Slice 1. Fix in-place. |

**Total potentially stale test LOC: ~3,500 across 5 files.** The lion's share — 2,667 lines — is in one file (`test_listing_extractor.py`), testing the 559-LOC `listing_extractor.py` that is a prime Slice 5 target.

**The trap is clear.** Phase 2 (duplicate extractor collapse) cannot land while `test_listing_extractor.py` pins every internal structure in the current shape. Any attempt to merge `listing_extractor.py`, `listing_card_extractor.py`, `listing_structured_extractor.py`, `detail_extractor.py` around a source-hierarchy registry will detonate that test file. Codex then either reverts the refactor or rewrites the tests in-place — which nobody wants to do mid-refactor.

## One remaining Gemini audit to run — Batch F

The only audit that actually unblocks the rest. Scoped tightly.

**Purpose.** Classify each test in `test_listing_extractor.py` (and the other pre-existing failers) as **behavioral** (keep — describes input→output) or **implementation-locking** (rewrite or delete — asserts internal names, private function behavior, specific intermediate dict shapes). Produce a kill/rewrite/keep list.

**Files to upload to AI Studio (5 files, skim-depth friendly):**

```
backend/tests/services/extract/test_listing_extractor.py
backend/tests/services/test_llm_runtime.py
backend/tests/services/test_batch_runtime_retry_update.py
backend/tests/services/adapters/test_base_adapter.py
backend/tests/services/config/test_field_mappings_collisions.py
```

**System instruction:** same auditor framing as Batches A/B/C/D (structured output only, no recommendations beyond the classification).

**Prompt outline (fill in the template structure used for A-D):**

```
You are auditing 5 Python test files. For each individual test function, classify it:

BEHAVIORAL — asserts only on observable inputs and outputs (HTML in, records out; request in, response out). Would survive a structural refactor that preserves behavior.

IMPLEMENTATION-LOCKING — asserts on internal names, private helper returns, specific intermediate shapes, mock call counts, or selector internals. Would break under a structural refactor even when behavior is preserved.

REDUNDANT — asserts what another test in the same file already asserts.

CONTRACT — thin test that asserts a module-level invariant (alias collision set, exported symbols). Small. Usually worth keeping.

Produce exactly these deliverables:

DELIVERABLE 1 — Per-test classification table (file:line, function name, classification, one-line reason).
DELIVERABLE 2 — Rollup counts per file.
DELIVERABLE 3 — Rewrite targets: tests where behavioral intent is good but assertion shape is implementation-locking. One row per test with the rewrite strategy (≤15 words).
DELIVERABLE 4 — Delete targets: tests that are REDUNDANT or pin behavior the invariants now forbid (e.g., first-match arbitration when Inv. 6 now specifies backfill + scorer).
DELIVERABLE 5 — Keep targets: tests that should survive every upcoming slice verbatim.
```

**Expected output.** `test_listing_extractor.py` alone will probably split roughly: 30-40 BEHAVIORAL (keep), 40-50 IMPLEMENTATION-LOCKING (rewrite as behavioral), 10-15 REDUNDANT (delete). Net shrinkage of that file should be 1,500-2,000 LOC.

**Paste-back protocol.** Same as A-D. Claude writes `07-batch-f-findings.md`. Codex works from it.

This is the only Gemini audit left to run. No Batches G/H/I.

## Revised roadmap — slices 3-9, honest about what each produces

| Slice | Owner | Target | User-visible outcome | Net LOC |
|-------|-------|--------|----------------------|---------|
| 3 — Acquisition strategy consolidation | Codex, in-flight | `policy.py` becomes single decision owner; 8 accidentals deleted | Confusion about "which strategy when" ends | ~500 |
| 4 — Inv. 12 repair + 8 unify leaks | Codex, in-flight | Noise rules stop rejecting page-native labels; 8 leaks repatriated | Records expose fields that were silently dropped | ~200 + behavior |
| **4.5 — Stale test triage** | Codex, after Batch F | Apply Batch F: delete REDUNDANT, rewrite IMPLEMENTATION-LOCKING as BEHAVIORAL. Goal: `test_listing_extractor.py` ≤ 800 LOC. | Test suite unpins the refactor target | ~1,500-2,500 tests LOC |
| 5 — Extract source-hierarchy registry | Codex, gated on 4.5 | Replace parallel extractors with `FIELD_SOURCE_REGISTRY`; merge 14 extract files into ~6 | "Code is bloat + patches" becomes "one file per source type" | ~5,000-6,000 |
| 6 — Adapter family collapse | Codex | 15 adapters → 5-6; boilerplate shells become config | Fewer places to touch when a platform changes | ~1,500-1,800 |
| 7 — Discover/state/signal merge | Codex | Two `signal_inventory.py` files → one; `discover/` and `extract/` discovery overlap collapses | One discovery module | ~1,000-1,500 |
| 8 — Normalizer data-driven dispatch | Codex | `normalizers/listings.py` surface-key dispatch becomes config tables | Less branch logic per surface | ~800-1,200 |
| 9 — Duplicate `trace_builders` + pipeline cleanup | Codex | Merge `pipeline/trace_builders.py` and `publish/trace_builders.py` (same filename, related content); remove remaining dead paths | Single trace builder | ~400-800 |

**Expected total.** 10-14k LOC removed *if* Slice 4.5 unpins the tests. Without Slice 4.5, Slice 5 stalls or reverts and the ceiling is ~3-4k.

**LOC numbers are estimates.** Do not commit to 10k as a gate. Commit to the *order* — 4.5 must land before 5, and 5 must land before 6/7/8/9 because it establishes the module shape the others will fit into.

## Order of operations (what Codex does next, in words)

1. **Finish Slice 3 and Slice 4.** Confirm `run_acquire_smoke.py commerce` and `run_extraction_smoke.py` both pass. If either fails with `ModuleNotFoundError`, the error will be something other than `semantic_detail_extractor`; diagnose from the actual traceback.
2. **Run Batch F in Google AI Studio.** Upload the 5 test files. Paste the five deliverables back.
3. **Claude writes `07-batch-f-findings.md`** from the pasted output.
4. **Codex executes Slice 4.5.** Delete REDUNDANT tests. Rewrite IMPLEMENTATION-LOCKING tests as behavioral (given-HTML → expect-records shape). One commit per test group. `test_listing_extractor.py` lands under 800 LOC.
5. **Claude drafts Slice 5** against the post-4.5 test suite. The registry design depends on what behavior the remaining tests assert.
6. **Codex executes Slice 5.** Registry lands. Extract file count drops from 27 to ~13-15. This is where LOC reduction becomes visible.
7. **Slices 6, 7, 8, 9** in that order, each producing visible file-count and LOC reductions.

## Acceptance of this plan

You accept this plan when:
- You agree the phantom `semantic_detail_extractor` prerequisite comes out of Slice 4.
- You agree Batch F (stale-test triage) is the last Gemini audit and runs *after* Slices 3/4 land.
- You agree Slice 4.5 (test triage) must land before Slice 5 (extract registry).
- You accept that 10k LOC reduction is the realistic ceiling, not a gate. The gate is "each slice produces a visible reduction in file count or LOC; no more moves-pretending-to-be-reductions."

If any of those don't fit, say which one and we adjust before Codex starts Slice 5.
