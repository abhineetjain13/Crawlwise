# Crawler Backend — Systematic Implementation Plan
> Generated from audit report: UPDATED_AUDIT_REPORT_2026-04-08.md  
> Last updated: 2026-04-08  
> Deployment context: Single instance  
> Infrastructure upgrades (Postgres / Redis / Celery): **Phase 7 — last, do not touch until Phase 6 is complete**

---

## HOW TO USE THIS PLAN

- **Work phases in strict order.** Each phase is safe to implement independently only after the previous phase is complete and tests pass.
- **Within a phase**, tasks are grouped by module/file. An agent should complete all tasks in a file group before moving to the next file group.
- **Every task has an Acceptance Check** — do not mark a task done until its check passes.
- **Never skip Phase 0.** It adds the safety net that makes all later changes verifiable.
- Track status with: `[ ]` not started → `[~]` in progress → `[x]` done → `[!]` blocked

---

## EXECUTION LOG (Swarm-Driven)

- **2026-04-08 / Phase 0:** Added Task `0-A` through `0-E` regression tests and ran the phase slice.
- **2026-04-08 / Phase 1:** Completed `1-A` traversal contract fix (`advanced_enabled=False` now hard-disables traversal mode in resolver).
- **2026-04-08 / Phase 5:** Completed hardcode removal in `_requires_browser_first` by switching to config/platform-family policy (no ADP hostname literals in function body).
- **2026-04-08 / Phase 3:** Product decision `B` selected and implemented (`3-A`/`3-B`) — arbitration now uses source ranking for winner selection and downstream override.
- **2026-04-08 / Verification:** Phase 0 regression slice passes end-to-end (`13 passed`).
- **2026-04-08 / Phase 6:** Completed `6-A` through `6-D` (traversal diagnostics propagated + run-level traversal counters added + `batch.py` wrapper removed + dead-code sweep completed).
- **2026-04-08 / Phase 3-4:** Completed `3-C` and implemented sanitizer chain (`4-A`/`4-B`/`4-C`) with config-driven `field_pollution_rules`, `sanitize_field_value`, and pre-ranking candidate sanitization.
- **2026-04-08 / Phase 1-2:** Completed `1-B`/`1-C`/`1-D`/`1-E` plus pending Phase 2 correctness checks (`2-A`/`2-B`): traversal mode fallback-to-auto warning, runtime traversal routing logs, delayed-scroll settle guard, explicit traversal fallback diagnostics, and verified no listing fallback records / no surface mutation.

---

## PHASE MAP (overview)

| Phase | Name | Goal | Risk if skipped |
|---|---|---|---|
| **0** | Safety Net First | Add regression fixtures before touching any logic | All subsequent changes are unverifiable |
| **1** | Traversal Contract Fix | Fix broken advanced traversal modes | Users can't use view_all / auto / scroll |
| **2** | Pipeline Contract Correctness | Stop surface mutation + listing fallback writes | Silent wrong data in every listing run |
| **3** | Schema Pollution — Arbitration | Fix field winner selection (first-row bias) | Garbage values win over valid values |
| **4** | Schema Pollution — Field Sanitizers | Block consent/tracking/UI strings per field | Pollution still passes after Phase 3 |
| **5** | Hardcoded Hacks — Move to Config | Remove tenant domains + vendor hacks from generic code | Config drift accelerates, untestable |
| **6** | Observability + Code Simplification | Propagate diagnostics, collapse dead wrappers | Silent failures, maintainability debt |
| **7** | Infrastructure Upgrades | Postgres, Redis, Celery | ← DO NOT START until Phase 6 is done |

---

---

# PHASE 0 — Safety Net First
> **Goal:** Write the test fixtures and regression tests that will verify every subsequent phase.  
> **Why first:** Without these, you cannot confirm that Phase 1–6 fixes work and don't regress.  
> **Risk to system:** Zero — these are additive test files only.

---

### SWARM EXECUTION: Task 0 (`0-A` through `0-E`)

Use this when you want to execute Phase 0 with parallel agents while keeping commits clean and verifiable.

**Team setup (leader):**

1. Create one team for Phase 0:
   - `phase0-safety-net`
2. Create 5 explicit tasks in the shared queue:
   - Task 1: implement `0-A` (`test_traversal_modes.py`)
   - Task 2: implement `0-B` (`test_listing_no_fallback.py`)
   - Task 3: implement `0-C` (`test_surface_control.py`)
   - Task 4: implement `0-D` (`test_field_arbitration.py`)
   - Task 5: implement `0-E` (`test_acquirer_policy.py`)
3. Add dependency gates:
   - Task 5 blocked by Task 1 (both are acquisition-facing and reduce overlap churn)
   - No other blockers (Tasks 1–4 can run in parallel)

**Recommended teammate roles:**

- `traversal-tester` → owns Task 1 (`0-A`)
- `pipeline-guard` → owns Task 2 and Task 3 (`0-B`, `0-C`)
- `schema-fixture-writer` → owns Task 4 (`0-D`)
- `policy-checker` → owns Task 5 (`0-E`) after unblocked

**Worker prompt contract (all teammates):**

1. Claim only unowned pending tasks assigned to your role.
2. Implement tests only (Phase 0 must not modify runtime logic).
3. Run targeted pytest for touched files and fix only test/setup failures.
4. Mark task `completed` only when:
   - tests execute (not import-broken),
   - failures match the documented acceptance reason.
5. Send completion note to team lead with:
   - files changed,
   - exact pytest command,
   - pass/fail summary and why.

**Leader runbook:**

1. Spawn all teammates in background.
2. Monitor inbox; when all tasks complete, run full Phase 0 test slice:
   - `pytest backend/tests/services/acquisition/test_traversal_modes.py -q`
   - `pytest backend/tests/services/pipeline/test_listing_no_fallback.py -q`
   - `pytest backend/tests/services/pipeline/test_surface_control.py -q`
   - `pytest backend/tests/services/extract/test_field_arbitration.py -q`
   - `pytest backend/tests/services/acquisition/test_acquirer_policy.py -q`
3. Confirm each test file fails for the intended regression reason (not tooling or import issues).
4. Shutdown teammates gracefully, then cleanup team resources.
5. Commit Phase 0 as test-only changes.

**Done criteria for swarm execution:**

- All five Phase 0 test files exist and run.
- Failures are intentional and match documented bugs.
- No runtime/service production code changed in this phase.

---

### MODULE: `tests/` (new test files)

---

#### TASK 0-A — Traversal mode contract tests
```
File: tests/services/acquisition/test_traversal_modes.py (create new)
Priority: P0
Effort: S
```

**What to write:**

1. Test: `advanced_mode=True` + `traversal_mode="auto"` → resolver must return `"auto"`, not `None`
2. Test: `advanced_mode=True` + `traversal_mode="view_all"` → resolver must return `"load_more"` (or `"view_all"` if first-class token added in Phase 1)
3. Test: `advanced_mode=False` → traversal mode must be `None` regardless of requested mode
4. Test: explicit `"paginate"` → must remain `"paginate"` through the full resolver chain
5. Test: explicit `"scroll"` → must remain `"scroll"` through the full resolver chain

**Files under test:**  
`backend/app/services/crawl_utils.py:resolve_traversal_mode`  
`backend/app/services/crawl_crud.py` (wherever mode is passed to runtime)

**Acceptance check:** All 5 tests fail on current code (they should — this documents the bugs). Commit them failing.

---

#### TASK 0-B — Listing fallback absence test
```
File: tests/services/pipeline/test_listing_no_fallback.py (create new)
Priority: P0
Effort: S
```

**What to write:**

1. Test: simulate `_extract_listing` where zero records are found → output must contain no synthetic/fallback records, only an explicit failure verdict
2. Test: simulate same with `ecommerce_listing` surface → same, no fallback records

**Files under test:**  
`backend/app/services/pipeline/core.py:_extract_listing`

**Acceptance check:** Test fails on current code (fallback record is currently written). Commit failing.

---

#### TASK 0-C — Surface mutation test
```
File: tests/services/pipeline/test_surface_control.py (create new)
Priority: P0
Effort: S
```

**What to write:**

1. Test: user requests `ecommerce_listing` surface → after `_resolve_listing_surface`, surface must still be `ecommerce_listing`
2. Test: user requests `job_listing` surface → surface must still be `job_listing`
3. Test: job-like heuristics detected on an `ecommerce_listing` request → surface must NOT be mutated, only a diagnostic hint logged

**Files under test:**  
`backend/app/services/pipeline/core.py:_resolve_listing_surface`

**Acceptance check:** Tests 1 and 2 fail on current code (mutation happens). Commit failing.

---

#### TASK 0-D — Schema pollution arbitration fixtures
```
File: tests/services/extract/test_field_arbitration.py (create new)
Priority: P0
Effort: M
```

**What to write — one fixture per polluted field:**

For each field (`title`, `category`, `brand`, `availability`, `color`), create a candidate set that contains:
- A garbage string (e.g. `"Cookie Consent Manager"` for title, `"undefined"` for availability, `"Add to Cart - Shop Now"` for category)
- A valid string (e.g. a real product title, a real category name, a real availability status)

Assert the valid string wins after arbitration.

Use real captured artifact strings from `backend/artifacts/html/dashingdiva-com-aa3b220907-run_5.html` and other known noisy sites for maximum realism.

**Files under test:**  
`backend/app/services/extract/service.py:_finalize_candidates`  
`backend/app/services/pipeline/core.py:_reconcile_detail_candidate_values`

**Acceptance check:** All fixtures fail on current code (garbage wins). Commit failing.

---

#### TASK 0-E — Control ownership + no-hardcode smoke test
```
File: tests/services/acquisition/test_acquirer_policy.py (create new)
Priority: P1
Effort: S
```

**What to write:**

1. Test: `_requires_browser_first` must not contain any hardcoded tenant hostname strings
2. Test: `careers.clarkassociatesinc.biz` host → behavior should be driven by config, not code branch
3. Test: ADP hosts → behavior should be driven by platform-family config, not hardcoded if/elif

**Acceptance check:** Tests 1 and 2 fail on current code (hostname is hardcoded). Commit failing.

---

> **Phase 0 done when:** All new test files exist, all tests fail for the documented reason (not for import errors or test setup bugs), and CI runs them.

---

---

# PHASE 1 — Traversal Contract Fix
> **Goal:** Fix the three broken traversal modes: `auto`, `view_all`, and the silent fallback to single-page.  
> **Why now:** Traversal is user-visible and completely broken for these modes — highest urgency after safety nets.  
> **Risk to system:** Low — changes are contained to `crawl_utils.py`, `crawl_crud.py`, `_batch_runtime.py`. No schema changes.  
> **Verify with:** Phase 0 Task 0-A tests must all pass after this phase.

---

### MODULE: `backend/app/services/crawl_utils.py`

---

#### TASK 1-A — Fix `resolve_traversal_mode` to preserve `auto` and map `view_all`
```
Bug ref: B-002, TODO-001, Finding 2
Priority: P0
Effort: S
```

**Current behavior (broken):**  
`auto` → mapped to `None`, disabling advanced traversal entirely.  
`view_all` → has no explicit mapping, dropped silently.

**Action:**

1. Open `crawl_utils.py:resolve_traversal_mode`
2. Find the branch/mapping where `"auto"` is normalized — change it so:
   - When `advanced_mode=True` AND requested mode is `"auto"` → return `"auto"` (do not convert to `None`)
   - When `advanced_mode=False` → return `None` (existing behavior, keep)
3. Add explicit mapping: `"view_all"` → `"load_more"` (until Phase 1-C adds a first-class token)
4. Add mapping: any unrecognized mode string when `advanced_mode=True` → log a warning and fall back to `"auto"` rather than silently dropping
5. The function must handle this mode matrix without ambiguity:

| advanced_mode | requested_mode | expected output |
|---|---|---|
| False | any | None |
| True | "auto" | "auto" |
| True | "paginate" | "paginate" |
| True | "scroll" | "scroll" |
| True | "view_all" | "load_more" |
| True | "load_more" | "load_more" |
| True | unrecognized | "auto" + warning log |

**Acceptance check:** Phase 0 Task 0-A tests all pass. No other test regressions.

---

### MODULE: `backend/app/services/crawl_crud.py`

---

#### TASK 1-B — Ensure mode flows through run creation without re-normalization
```
Bug ref: B-002, TODO-001
Priority: P0
Effort: S
```

**Current behavior:**  
`crawl_crud.py` may apply its own mode normalization before passing to `_batch_runtime`, causing the mode to be re-resolved and potentially broken again.

**Action:**

1. Find all locations in `crawl_crud.py` that touch `traversal_mode` or `advanced_mode`
2. Confirm that `resolve_traversal_mode` from `crawl_utils.py` is called exactly once — at the run creation boundary
3. After the resolver runs, the resolved mode must be stored and passed forward as-is — no second normalization downstream
4. If any code in `crawl_crud.py` re-applies its own mode logic, remove it and use the shared resolver

**Acceptance check:** Add a log line at the point the mode enters `_batch_runtime`. In a test run, confirm `auto` is logged, not `None`.

---

### MODULE: `backend/app/services/_batch_runtime.py`

---

#### TASK 1-C — Confirm `_batch_runtime` routes `auto` to the traversal engine correctly
```
Bug ref: B-002, TODO-001
Priority: P0
Effort: S
```

**Action:**

1. Find where `_batch_runtime` consumes `traversal_mode`
2. Confirm `"auto"` is handled: it should trigger `apply_traversal_mode` in `traversal.py` with mode=`"auto"`
3. Confirm `"load_more"` / `"view_all"` triggers `LOAD_MORE_SELECTORS`-based traversal
4. If `None` short-circuits traversal (no-op), confirm this only happens when `advanced_mode=False`
5. Add a log at this routing point: `"[traversal] mode={mode}, advanced={advanced_mode}, url={url}"`

**Acceptance check:** Integration test with a known paginated URL + `advanced_mode=True` + `auto` actually calls the traversal path (verify via log or mock assert).

---

### MODULE: `backend/app/services/acquisition/traversal.py`

---

#### TASK 1-D — Fix infinite scroll early exit under delayed rendering
```
Bug ref: Finding 5, Section 5 (Infinite Scroll)
Priority: P1
Effort: M
```

**Current behavior:**  
`scroll_to_bottom` uses a height-stability heuristic that can exit too early on virtualized or delayed-render pages.

**Action:**

1. Find the loop termination condition in `scroll_to_bottom`
2. Add one adaptive retry cycle before declaring scroll complete:
   - After stable height is detected, wait an additional `500ms` and re-check height
   - If height changed in retry window → continue scrolling
   - If height stable for two consecutive checks → stop
3. Add a max scroll iteration guard (e.g. `max_iterations=50`) to prevent infinite loops on infinite feeds
4. Log each scroll iteration: `"[scroll] iteration={n}, height_before={h1}, height_after={h2}, stable={bool}"`

**Acceptance check:** Test against a known lazy-loading listing page. Confirm more items are collected compared to before. Confirm it terminates.

---

### MODULE: `backend/app/services/acquisition/browser_client.py`

---

#### TASK 1-E — Confirm traversal is not silently falling back to single-page on failure
```
Bug ref: Finding 5, Section 5
Priority: P1
Effort: S
```

**Action:**

1. Find `_apply_traversal_mode` in `browser_client.py`
2. Confirm: if traversal fails (exception, timeout, or zero results after traversal), the code must log a warning with the reason — it must NOT silently return the single-page HTML as if traversal succeeded
3. Add explicit log: `"[traversal] fallback to single-page, reason={reason}, url={url}"`
4. The `BrowserResult` returned in fallback should carry a flag or note in `diagnostics` indicating traversal was attempted but fell back

**Acceptance check:** Trigger a traversal failure (e.g. provide a selector that doesn't exist). Confirm the fallback log appears and `diagnostics` reflects it.

---

> **Phase 1 done when:** All Phase 0 Task 0-A tests pass. Traversal logs show correct mode routing. Manual smoke test on a paginated listing, an infinite scroll listing, and a "View All" page all collect more results than single-page.

---

---

# PHASE 2 — Pipeline Contract Correctness
> **Goal:** Stop two silent contract violations: surface mutation and listing fallback writes.  
> **Why now:** Both cause wrong data to appear in output without any error signal.  
> **Risk to system:** Low — both are removals. Removing a rewrite and removing a fallback write path.  
> **Verify with:** Phase 0 Tasks 0-B and 0-C must pass after this phase.

---

### MODULE: `backend/app/services/pipeline/core.py`

---

#### TASK 2-A — Remove listing fallback record write path
```
Bug ref: B-004, TODO-003, TODO-SIMP-001, Finding 6
Priority: P0
Effort: S
Estimated LoC delta: ~-45
```

**Current behavior:**  
`_extract_listing` writes a partial/synthetic record when zero real records are found. This masks real failures and contradicts the intended no-fallback contract.

**Action:**

1. Open `pipeline/core.py:_extract_listing`
2. Find the block that creates a fallback/partial record when `len(records) == 0`
3. Delete this block entirely
4. Replace with: return an explicit failure verdict only — e.g. `VERDICT_LISTING_FAILED` or `VERDICT_BLOCKED` (whichever is semantically correct)
5. Confirm the calling code handles these verdicts without crashing
6. Do NOT write any record to output/persistence when zero real records are found

**Acceptance check:** Phase 0 Task 0-B tests pass. Run against a URL that returns zero listings — confirm no record in output, only a failure verdict in run status.

---

#### TASK 2-B — Remove surface mutation from `_resolve_listing_surface`
```
Bug ref: B-003, TODO-004, Finding 3
Priority: P0
Effort: S
```

**Current behavior:**  
`_resolve_listing_surface` rewrites the user-requested surface (e.g. `ecommerce_listing` → `job_listing`) based on heuristics. This violates user control authority.

**Action:**

1. Open `pipeline/core.py:_resolve_listing_surface`
2. Find the code block that overwrites the requested surface with a heuristic-detected surface
3. Remove the overwrite assignment
4. Keep the heuristic detection code, but change its output: log a diagnostic hint only
   - e.g. `logger.info("[surface] requested=%s, detected=%s — using requested (no override)", requested, detected)`
5. Return the original requested surface unchanged
6. Do not remove the detection logic — it's useful for diagnostics and future validation warnings

**Acceptance check:** Phase 0 Task 0-C tests all pass. A run requesting `ecommerce_listing` on a job-like page remains `ecommerce_listing` throughout.

---

> **Phase 2 done when:** Both Phase 0 tasks 0-B and 0-C pass. No synthetic listing records appear in output for zero-result pages. Surface value in run traces matches user request.

---

---

# PHASE 3 — Schema Pollution: Fix Arbitration (Root Cause)
> **Goal:** Fix the root cause of schema pollution — first-row / first-available winner selection.  
> **Why now:** Field sanitizers in Phase 4 are a layer on top of this. Fix the arbitration engine first so the sanitizers don't have to compensate for a broken ordering.  
> **Risk to system:** Medium — this changes the core field selection logic. Validate with Phase 0 Task 0-D fixtures before and after.  
> **Verify with:** Phase 0 Task 0-D fixtures must all pass after this phase.

---

### MODULE: `backend/app/services/extract/service.py`

---

#### TASK 3-A — Replace `rows[:1]` first-row winner with ranked candidate selection
```
Bug ref: B-001, TODO-002, Finding 1
Priority: P0
Effort: M
```

**Current behavior:**  
`_finalize_candidates` takes `rows[:1]` — the first row from whichever source populated first. A polluted non-empty value from an early source (e.g. datalayer, GTM push) beats a valid JSON-LD value.

**Action:**

1. Open `extract/service.py:_finalize_candidates`
2. Replace `rows[:1]` with a ranked selection:
   - Keep ALL candidate rows for each field through finalization
   - Rank by source priority (define this order in `config/extraction_rules.py`):
     ```
     Rank 1 (highest trust): contract / adapter
     Rank 2: json_ld / embedded/next/hydrated
     Rank 3: og / meta tags
     Rank 4: selector/dom/semantic/text
     Rank 5 (lowest trust): datalayer / network / analytics pushes
     ```
   - Within the same source rank, prefer non-empty, non-noise strings
3. Select the highest-rank non-empty candidate that passes the field's quality check (Phase 4 adds quality checks — for now, just rank by source)
4. The ranking config must be in `config/extraction_rules.py` as a named constant (not inline in the function)

**Do not change** the interface of `_finalize_candidates` — same inputs, same output type. Only the internal selection logic changes.

**Acceptance check:** Phase 0 Task 0-D fixtures: valid strings from `json_ld` source now win over garbage strings from `datalayer` source. No other field extraction tests regress.

---

### MODULE: `backend/app/services/pipeline/core.py`

---

#### TASK 3-B — Fix sticky early-source bias in `_reconcile_detail_candidate_values`
```
Bug ref: B-005, TODO-002, Finding 1
Priority: P0
Effort: M
```

**Current behavior:**  
`_reconcile_detail_candidate_values` allows an adapter/early-source value to remain sticky — a better downstream candidate cannot replace it because the override condition is too narrow.

**Action:**

1. Open `pipeline/core.py:_reconcile_detail_candidate_values`
2. Find the merge/override condition
3. Change the rule: if a higher-ranked-source candidate exists AND is non-empty AND passes quality check → it MUST replace the current value regardless of position
4. The rule in plain terms: **source rank beats arrival order**
5. Use the same source rank table defined in Task 3-A (reference it from `config/extraction_rules.py`)
6. Log when an override occurs: `"[reconcile] field={field}, replaced={old_val[:30]} (rank={old_rank}) with {new_val[:30]} (rank={new_rank})"`

**Acceptance check:** Phase 0 Task 0-D `brand` fixture passes (better downstream brand now replaces sticky early-source brand). No other reconciliation tests regress.

---

### MODULE: `backend/app/services/pipeline/field_normalization.py`

---

#### TASK 3-C — Allow higher-quality override in `_merge_record_fields` for brand/category
```
Bug ref: B-005, Finding 1
Priority: P1
Effort: S
```

**Current behavior:**  
`_merge_record_fields` has a narrow override policy — adapter brand/category values remain sticky even when a materially better candidate is available.

**Action:**

1. Open `field_normalization.py:_merge_record_fields`
2. Find the merge condition for `brand` and `category` specifically
3. Add quality-override rule: if the incoming candidate's source rank is higher than the current value's source rank, allow the override
4. "Quality override" condition: `incoming_rank < current_rank` (lower number = higher trust)
5. Do not apply this override to fields where adapter authority is absolute (e.g. product ID, URL — check if any such fields exist and explicitly exclude them)

**Acceptance check:** Unit test: merge with adapter brand (rank 5 / datalayer) + json_ld brand (rank 2) → json_ld wins.

---

> **Phase 3 done when:** Phase 0 Task 0-D arbitration fixtures all pass. Source rank config is in one place. No production field tests regress.

---

---

# PHASE 4 — Schema Pollution: Field Sanitizers
> **Goal:** Add a field-specific pollution filter layer that blocks consent/tracking/UI strings from ever becoming canonical.  
> **Why after Phase 3:** Arbitration fix removes the main cause. Sanitizers are defense-in-depth for edge cases and new sites.  
> **Risk to system:** Low — additive filter layer. Worst case: a false-positive filter discards a valid value (make filters conservative).  
> **Verify with:** Phase 0 Task 0-D fixtures still pass. Smoke test on known noisy sites (Adorama, DashingDiva artifacts).

---

### MODULE: `backend/app/services/config/extraction_rules.py`

---

#### TASK 4-A — Add field-specific pollution reject config
```
Bug ref: TODO-005, Section 4 (all fields)
Priority: P1
Effort: S
```

**Action:**

Add a new config block `FIELD_POLLUTION_RULES` to `extraction_rules.py` with per-field rules:

```python
FIELD_POLLUTION_RULES = {
    "title": {
        "reject_phrases": [
            "cookie", "consent", "privacy policy", "terms of use",
            "sign in", "log in", "add to cart", "subscribe", "newsletter",
            "javascript", "undefined", "null", "n/a", "loading"
        ],
        "max_length": 300,
        "min_length": 2,
    },
    "category": {
        "reject_phrases": [
            "cookie", "consent", "privacy", "tracking", "analytics",
            "undefined", "null", "n/a", "schema.org", "http"
        ],
        "max_length": 150,
        "reject_if_contains_url": True,
        "reject_if_only_numbers": True,
    },
    "brand": {
        "reject_phrases": ["undefined", "null", "n/a", "unknown"],
        "max_length": 100,
        "min_length": 1,
    },
    "availability": {
        "allowed_values": [
            "in stock", "instock", "in_stock",
            "out of stock", "outofstock", "out_of_stock",
            "preorder", "pre-order", "pre_order",
            "discontinued", "available", "unavailable",
            "limited", "backorder", "on backorder",
        ],
        "reject_if_not_in_allowed_values": True,  # strict enum after normalization
    },
    "color": {
        "max_tokens": 5,       # color strings should be short
        "max_length": 60,
        "reject_phrases": [
            "cookie", "consent", "undefined", "null", "n/a",
            "add to cart", "loading", "javascript"
        ],
    },
}
```

These rules are config — no logic here. Logic is in the sanitizer (Task 4-B).

**Acceptance check:** Config loads without error. All existing tests still pass.

---

### MODULE: `backend/app/services/extract/service.py` (or `normalizers/__init__.py`)

---

#### TASK 4-B — Implement `sanitize_field_value(field, value)` using `FIELD_POLLUTION_RULES`
```
Bug ref: TODO-005, Section 4
Priority: P1
Effort: M
```

**Action:**

1. Create function `sanitize_field_value(field: str, value: str) -> str | None` in `extract/service.py` (or a new `extract/sanitizers.py` — keep it close to the extraction layer)
2. Logic:
   - Load the rules for `field` from `FIELD_POLLUTION_RULES`
   - If no rules exist for field → return value unchanged (safe default)
   - Apply `min_length` / `max_length` checks → return `None` if fails
   - Apply `reject_phrases` (case-insensitive substring match) → return `None` if any phrase found
   - Apply `reject_if_contains_url` → return `None` if value contains `http://` or `https://`
   - For `availability`: normalize to lowercase, strip whitespace, check against `allowed_values` → return `None` if not found
   - For `color`: count whitespace-separated tokens → return `None` if `> max_tokens`
3. Return `None` (not empty string) when a value is rejected — `None` signals "no value" cleanly
4. Log every rejection at DEBUG level: `"[sanitize] field={field}, rejected={value[:50]}, rule={rule_name}"`

**Acceptance check:** Unit tests for each field with garbage input → `None`. Unit tests for each field with valid input → original value returned unchanged.

---

#### TASK 4-C — Apply sanitizer in the arbitration chain (before winner selection)
```
Bug ref: TODO-005, Section 4
Priority: P1
Effort: S
```

**Action:**

1. In `_finalize_candidates` (modified in Task 3-A), apply `sanitize_field_value(field, candidate_value)` to each candidate before ranking
2. Candidates that return `None` from sanitizer are removed from the ranked pool
3. If ALL candidates for a field are sanitized away → field value is `None` (not empty string, not garbage) — this is the correct outcome
4. The sanitizer must run **before** source-rank comparison, so garbage values are eliminated from ranking entirely

**Acceptance check:** Phase 0 Task 0-D fixtures still pass. Known noisy artifact from `dashingdiva-com-aa3b220907-run_5.html` — re-extract and confirm no consent/cookie strings in `title`, `category`.

---

> **Phase 4 done when:** Field sanitizer exists, is configured, and is applied in the arbitration chain. Smoke test on Adorama + DashingDiva artifacts shows no pollution. All Phase 0 fixtures pass.

---

---

# PHASE 5 — Hardcoded Hacks: Move to Config
> **Goal:** Remove tenant domain hardcoding from generic code and move to governed config.  
> **Why now:** Safe to do in isolation. No logic changes — just relocating policy.  
> **Risk to system:** Low-Medium — ensure behavior is preserved via config before deleting hardcodes.  
> **Verify with:** Phase 0 Task 0-E tests must pass. Smoke test the affected domains.

---

### MODULE: `backend/app/services/acquisition/acquirer.py`

---

#### TASK 5-A — Remove `careers.clarkassociatesinc.biz` hardcode
```
Bug ref: H-001, B-007, Finding 4, TD-005
Priority: P1
Effort: S
```

**Current behavior:**  
`_requires_browser_first` contains a hardcoded tenant hostname. This is a DANGEROUS classification — a generic function containing tenant-specific behavior.

**Action:**

1. Open `acquirer.py:_requires_browser_first`
2. Find the hardcoded `careers.clarkassociatesinc.biz` check
3. Before deleting it: check if this domain has an entry in `config/extraction_rules.py` or any site config registry
   - If NO: add an entry to a `BROWSER_FIRST_DOMAINS` list in `config/extraction_rules.py` first (preserve behavior)
   - If YES: confirm it's there, then delete the hardcode
4. Delete the hardcoded hostname check from the function body
5. Replace with: `return domain in settings.BROWSER_FIRST_DOMAINS` (or equivalent config lookup)

**Acceptance check:** Phase 0 Task 0-E test passes. The domain still gets browser-first treatment (via config). No hostname literals remain in `_requires_browser_first`.

---

#### TASK 5-B — Consolidate ADP platform-family policy
```
Bug ref: H-002
Priority: P1
Effort: S
```

**Current behavior:**  
ADP host handling is done via hardcoded checks in `_requires_browser_first` rather than through a platform-family policy.

**Action:**

1. Add `"adp"` (or equivalent platform family token) to a `PLATFORM_BROWSER_FIRST` map in config
2. The map should be: `{ "platform_family": ["adp", "workday", "greenhouse", ...], "policy": "browser_first" }`
3. Replace the inline ADP host check with a platform-family lookup
4. This makes future platforms configurable without code changes

**Acceptance check:** ADP pages still route to browser-first acquisition. No ADP-specific code remains in `acquirer.py`.

---

### MODULE: `backend/app/services/extract/listing_extractor.py`

---

#### TASK 5-C — Move `recruiting.ultipro.com` URL synthesis to adapter strategy
```
Bug ref: H-003
Priority: P1
Effort: S
```

**Current behavior:**  
`_synthesize_job_detail_url` contains vendor-specific URL construction logic for UltiPro inside a generic listing extractor.

**Action:**

1. Open `listing_extractor.py:_synthesize_job_detail_url`
2. Find the UltiPro-specific branch
3. Create a config entry: `VENDOR_URL_PATTERNS["recruiting.ultipro.com"] = { "synthesis": "ultipro_detail_url" }`
4. Move the synthesis logic to a named strategy function (same file is fine, but it must be dispatch-table driven)
5. The generic function becomes: `return VENDOR_URL_STRATEGIES.get(detected_vendor, default_synthesis)(base_url, job_id)`

**Acceptance check:** UltiPro job detail URLs still synthesize correctly. No vendor name literal remains in generic function body.

---

### MODULE: `backend/app/services/llm_integration/page_classifier.py`

---

#### TASK 5-D — Replace loose host token checks with platform-family classification
```
Bug ref: H-004
Priority: P1
Effort: S
```

**Current behavior:**  
`_url_surface` does loose substring checks on host tokens (`ats`, `workday`, `greenhouse`) which can misclassify unrelated domains.

**Action:**

1. Find the host-token check block in `page_classifier.py:_url_surface`
2. Replace substring checks with exact-match or suffix-match against `KNOWN_ATS_PLATFORMS` list in config
3. The config list should contain full domain patterns, not tokens: e.g. `["myworkday.com", "greenhouse.io", "lever.co", ...]`
4. If a host matches a known ATS platform → classify accordingly
5. If a host is unknown → do not guess from token; return `None` / `unknown` and let the classifier handle it

**Acceptance check:** A domain containing `"ats"` in its name but not a known ATS platform is not misclassified. Known ATS platforms still classify correctly.

---

### MODULE: `backend/app/services/config/extraction_rules.py`

---

#### TASK 5-E — Move `browser_first_domains=["reverb.com"]` to policy registry
```
Bug ref: H-005
Priority: P1
Effort: S
```

**Action:**

1. Find `PIPELINE_TUNING` in `extraction_rules.py`
2. Move `browser_first_domains` out of generic tuning config into a dedicated `SITE_POLICY_REGISTRY` section
3. Format:
   ```python
   SITE_POLICY_REGISTRY = {
       "reverb.com": {
           "browser_first": True,
           "reason": "SPA with lazy product data",
           "added": "2025-Q3",
       },
   }
   ```
4. The lookup in `acquirer.py` should use `SITE_POLICY_REGISTRY[domain].get("browser_first", False)`

**Acceptance check:** `reverb.com` still routes to browser-first. No domain names remain inside `PIPELINE_TUNING`.

---

> **Phase 5 done when:** Phase 0 Task 0-E tests pass. No tenant hostname literals in generic code. All affected domains still behave correctly (smoke test each). Site policy is in `SITE_POLICY_REGISTRY`.

---

---

# PHASE 6 — Observability + Code Simplification
> **Goal:** Surface hidden failures, propagate traversal diagnostics, and remove dead/wrapper code.  
> **Why now:** Lower risk, high maintainability value. Do after correctness fixes.  
> **Risk to system:** Low — diagnostics are additive. Wrapper removal is mechanical.

---

### MODULE: `backend/app/services/acquisition/browser_client.py`

---

#### TASK 6-A — Propagate `TraversalResult.summary` into `BrowserResult.diagnostics`
```
Bug ref: B-006, TODO-006, Finding 5
Priority: P1
Effort: S
```

**Current behavior:**  
`_apply_traversal_mode` returns a `TraversalResult(summary=...)` but the caller discards `summary` and only uses the HTML.

**Action:**

1. Open `browser_client.py:_apply_traversal_mode`
2. Find where the return value is consumed
3. Extract `traversal_result.summary` and attach it to the `BrowserResult` or `diagnostics` dict
4. `summary` must include: `mode_used`, `pages_collected`, `scroll_iterations` (if scroll), `stop_reason`, `fallback_used`
5. Pass this through to `acquirer.py` diagnostics → run-level summary

**Acceptance check:** Phase 0 implied — add assertion: after any traversal run, `diagnostics["traversal_summary"]` is present and non-empty.

---

### MODULE: `backend/app/services/_batch_runtime.py` + `backend/app/services/acquirer.py`

---

#### TASK 6-B — Roll traversal summary into run-level metrics
```
Bug ref: TODO-006
Priority: P1
Effort: S
```

**Action:**

1. In `_batch_runtime.py`, after each URL is processed, if `result.diagnostics` contains `traversal_summary`, merge it into the run-level summary dict
2. Run-level summary should include (aggregated across all URLs):
   - `traversal_attempted: int`
   - `traversal_succeeded: int`  
   - `traversal_fell_back: int`
   - `traversal_modes_used: dict[mode, count]`
3. Log run summary at the end of each batch run

**Acceptance check:** After a batch run with advanced traversal, the run summary log contains traversal counts.

---

### MODULE: `backend/app/services/batch.py`

---

#### TASK 6-C — Remove thin wrapper over `_batch_runtime`
```
Bug ref: TD-007, TODO-008, TODO-SIMP-003
Priority: P2
Effort: S
Estimated LoC delta: ~-60
```

**Current behavior:**  
`batch.py` is a pure pass-through wrapper over `_batch_runtime.py` with no additional behavior.

**Action:**

1. Open `batch.py` — confirm all functions are pass-through (no logic)
2. Find all import sites of `batch.py` across the codebase
3. Update each import site to import directly from `_batch_runtime`
4. Delete `batch.py`
5. Run the full test suite to confirm no regressions

**Acceptance check:** All tests pass. No imports of `batch.py` remain. `_batch_runtime` is the sole module for batch operations.

---

### MODULE: `backend/app/services/` (cross-cutting)

---

#### TASK 6-D — Audit and remove dead code (functions/classes never called)
```
Bug ref: Section 7 (Code Reduction)
Priority: P2
Effort: M
```

**Action:**

1. Use static analysis (e.g. `vulture` or `pyflakes`) to identify unused functions, classes, and config keys
   ```bash
   pip install vulture
   vulture backend/app/services/ --min-confidence 80
   ```
2. For each reported item: manually verify it's not called via string dispatch or dynamic import
3. Delete confirmed dead code
4. Commit deletions separately from logic changes (clean diff)

**Acceptance check:** `vulture` reports zero high-confidence dead code. All tests pass.

---

> **Phase 6 done when:** Traversal diagnostics appear in run summaries. `batch.py` is deleted. Dead code is removed. All tests pass.

---

---

# PHASE 7 — Infrastructure Upgrades
> **⚠️ DO NOT START THIS PHASE UNTIL PHASES 0–6 ARE COMPLETE AND STABLE.**  
> **Goal:** Replace in-process state management with proper infrastructure (Postgres, Redis, Celery).  
> **Risk to system:** HIGH — full architectural change. Requires dedicated planning, migration strategy, and rollback plan.  
> This phase is intentionally left without detailed task breakdown here.  
> Detailed planning should be done as a separate exercise after Phase 6 is validated in production.

Detailed migration plan document: `docs/phase-7-infrastructure-migration-plan.md`

**When you reach this phase, plan for:**
- Postgres: migrate current persistence layer (define schema from current data model first)
- Redis: replace any in-memory state/queue with Redis-backed equivalent
- Celery: replace current job dispatch with Celery workers (design queue topology first)
- Do these in order: Postgres → Redis → Celery (each is independently deployable)
- Each has its own migration plan, rollback strategy, and smoke test suite before going live

---

---

# QUICK REFERENCE: Master Task Index

| Task | Phase | Priority | Effort | Category | Status |
|---|---|---|---|---|---|
| 0-A | Safety Net | P0 | S | Tests | `[ ]` |
| 0-B | Safety Net | P0 | S | Tests | `[ ]` |
| 0-C | Safety Net | P0 | S | Tests | `[ ]` |
| 0-D | Safety Net | P0 | M | Tests | `[ ]` |
| 0-E | Safety Net | P1 | S | Tests | `[ ]` |
| 1-A | Traversal | P0 | S | Traversal | `[x]` |
| 1-B | Traversal | P0 | S | Traversal | `[x]` |
| 1-C | Traversal | P0 | S | Traversal | `[x]` |
| 1-D | Traversal | P1 | M | Traversal | `[x]` |
| 1-E | Traversal | P1 | S | Traversal | `[x]` |
| 2-A | Pipeline | P0 | S | Correctness | `[x]` |
| 2-B | Pipeline | P0 | S | Correctness | `[x]` |
| 3-A | Arbitration | P0 | M | Schema | `[x]` |
| 3-B | Arbitration | P0 | M | Schema | `[x]` |
| 3-C | Arbitration | P1 | S | Schema | `[x]` |
| 4-A | Sanitizers | P1 | S | Schema | `[x]` |
| 4-B | Sanitizers | P1 | M | Schema | `[x]` |
| 4-C | Sanitizers | P1 | S | Schema | `[x]` |
| 5-A | Hacks | P1 | S | Config | `[x]` |
| 5-B | Hacks | P1 | S | Config | `[x]` |
| 5-C | Hacks | P1 | S | Config | `[x]` |
| 5-D | Hacks | P1 | S | Config | `[x]` |
| 5-E | Hacks | P1 | S | Config | `[x]` |
| 6-A | Observability | P1 | S | Reliability | `[x]` |
| 6-B | Observability | P1 | S | Reliability | `[x]` |
| 6-C | Simplification | P2 | S | Simplification | `[x]` |
| 6-D | Simplification | P2 | M | Simplification | `[x]` |
| 7-* | Infra | P3 | XL | Infrastructure | `[ ]` |

---

## DEPENDENCY GRAPH (critical path)

```
0-A → 1-A → 1-B → 1-C
0-B → 2-A
0-C → 2-B
0-D → 3-A → 3-B → 3-C → 4-A → 4-B → 4-C
0-E → 5-A

# Independent (can run in parallel with above):
5-B, 5-C, 5-D, 5-E  (no deps, any order)
6-A → 6-B           (after Phase 1)
6-C, 6-D            (no deps, any order)

# Gated:
Phase 7 → gated on ALL of Phase 0–6 complete + stable
```

---

## SMOKE TEST CHECKLIST (run after each phase)

After Phase 1:
- [ ] Run with `advanced_mode=True, traversal_mode="auto"` on a paginated listing → multiple pages collected
- [ ] Run with `traversal_mode="view_all"` → triggers load_more selector
- [ ] Run with `traversal_mode="scroll"` on lazy-load page → more items than single page

After Phase 2:
- [ ] Run on a URL that returns zero listings → no synthetic record in output, only failure verdict
- [ ] Run with `ecommerce_listing` surface on a job-like page → surface remains `ecommerce_listing`

After Phase 4:
- [ ] Extract from Adorama artifact → `brand`, `color`, `availability` contain no GA datalayer pollution
- [ ] Extract from DashingDiva artifact → `category`, `title` contain no consent/cookie strings
- [ ] Extract from a clean product page → all fields still populated correctly (no false rejections)

After Phase 5:
- [x] No tenant/site hardcodes in generic crawler paths (policy/config only)
- [x] ADP job listing page → browser-first via family policy (`PLATFORM_BROWSER_POLICIES`)
- [x] ATS host classification uses known family domains (no loose host token matching)
- [x] Family config reduced to bare minimum required by current generic + adapter flow

After Phase 6:
- [ ] Run with advanced traversal → run summary log shows traversal counters
- [ ] Confirm `batch.py` file does not exist
- [ ] Run full test suite → zero regressions