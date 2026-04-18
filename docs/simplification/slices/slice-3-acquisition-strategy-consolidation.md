# Slice 3 — Acquisition Strategy Consolidation

> **Owner:** Codex. **Prerequisite:** Slices 0/1/2 landed. **Parallelizable with Slice 4?** Yes — different files.
> **Evidence basis:** [04-batch-c-findings.md](../04-batch-c-findings.md) — 21 `surface` / `page_type` branches across 6 acquisition files with no central decision owner. 8 accidental branches ranked for collapse. Supplementary context: [00-program-audit-2026-04-17.md](../00-program-audit-2026-04-17.md) naming "confusion in acquisition strategies on what to use when" as the user-visible pain this slice must fix.
> **Goal:** One file decides acquisition strategy (`acquisition/policy.py`); every other file consumes a decided `AcquisitionPlan` instead of re-reading `surface` / `page_type`. Collapse the 8 accidental branches at the same time. Net result: a reader opens `policy.py` and understands the full decision tree without jumping between 6 files.

## What this slice is NOT

- **Not** a rewrite of acquisition. The curl-first → Playwright-fallback waterfall stays. The family-based platform routing stays.
- **Not** a behavior change. Every decision that currently fires must still fire under the consolidated plan.
- **Not** a Phase 2 extractor consolidation. Essential branches in `normalizers/listings.py`, `signal_inventory.py`, etc. are OUT OF SCOPE.
- **Not** an Invariant 12 repair (Slice 4).

## Principle

`policy.py` is the strategy decision owner. Every other acquisition file is a consumer. The contract is explicit and typed.

```
acquirer.py           ─┐
browser_client.py      ├─ consume AcquisitionPlan
browser_readiness.py   │  (no direct reads of surface/page_type
traversal.py           │   for strategy decisions)
recovery.py            │
adapters/registry.py  ─┘
                                  ▲
                                  │ one call site
                                  │
                          policy.py::plan_acquisition(request) -> AcquisitionPlan
```

## Target shape

```python
# backend/app/services/acquisition/policy.py

@dataclass(frozen=True)
class AcquisitionPlan:
    # user-owned, passthrough (Invariants 16-19)
    surface: str                  # "ecommerce_listing" | "ecommerce_detail" | "job_listing" | "job_detail"
    page_type: str                # "category" | "pdp"

    # strategy decisions (computed once, here, by policy)
    require_browser_first: bool               # Inv. 29 family-based escalation
    allow_browser_escalation: bool            # Inv. 16 user-directed boundary
    browser_escalation_reasons: frozenset[str]
    readiness_profile: Literal["listing", "detail"]
    readiness_selectors: tuple[str, ...]      # picked by surface+platform family
    traversal_enabled: bool                   # Inv. 18 — detail always False
    traversal_card_selectors: tuple[str, ...]
    retry_profile: Literal["standard", "listing_low_value"]
    adapter_recovery_enabled: bool
    diagnostic_payload_kind: Literal["listing_completeness", "variant_completeness", "none"]


def plan_acquisition(request: CrawlRequest) -> AcquisitionPlan:
    """Single source of truth for acquisition strategy. All surface/page_type
    reads for strategy selection happen here. Consumers receive the plan."""
    ...
```

**Rules the new code must follow:**

1. **Only `policy.py::plan_acquisition` reads `surface` / `page_type` for strategy selection.** Other files may still log them, include them in telemetry payloads, or pass them through — but they must not use them to pick between code paths.
2. **Every existing branch either (a) moves into `plan_acquisition`, or (b) is deleted because it was ACCIDENTAL per Batch C Deliverable 4.**
3. **No new behavior.** The consolidated `plan_acquisition` returns the same decisions the scattered code was making, just computed once.

## Concrete steps

### Step 1 — Snapshot current decisions

Before moving any code, produce `scratch/slice-3-decision-snapshot.md`: for each of the 21 Batch C acquisition branches, one line recording (a) current file:line, (b) current decision logic (≤20 words), (c) target `AcquisitionPlan` field it maps to. This is the traceability log — every row must land as a `plan_acquisition` rule or be deleted as ACCIDENTAL.

Use the 21 branches from [04-batch-c-findings.md](../04-batch-c-findings.md) Deliverable 2 and the invariant-risk flags. Do not add new decisions.

### Step 2 — Define `AcquisitionPlan` + `plan_acquisition`

Add the dataclass and function to `backend/app/services/acquisition/policy.py`. Implement the decisions from the snapshot. Do not wire consumers yet.

Add unit tests in `backend/tests/services/acquisition/test_plan_acquisition.py` covering every `(surface, page_type, platform_family)` combination that currently appears in the 21 branches. Each test asserts one `AcquisitionPlan` field.

### Step 3 — Migrate consumers, one file per commit

For each consumer, in order:

1. **`acquisition/acquirer.py`** — call `plan_acquisition` once at entry, pass the plan down. Replace internal `surface` / `page_type` reads for strategy with `plan.<field>` reads.
2. **`acquisition/browser_client.py`** — accept plan argument (or receive it on the existing context struct). Replace the L323 listing-vs-detail hydration branch with `plan.readiness_profile`.
3. **`acquisition/browser_readiness.py`** — this is where the accidental branches are densest. Delete `_is_listing_surface` (rank 1) and the early-exit in `_wait_for_listing_readiness` (rank 2). Switch to `plan.readiness_profile == "listing"` and `plan.readiness_selectors`. The essential job-vs-ecommerce selector choice at L197 becomes `plan.readiness_selectors` at `plan_acquisition` time.
4. **`acquisition/traversal.py`** — replace `_card_selectors_for_surface` reads with `plan.traversal_card_selectors`. Replace the detail-abort at L422 with `plan.traversal_enabled`.
5. **`acquisition/recovery.py`** — replace L29 surface check with `plan.adapter_recovery_enabled`.
6. **`adapters/registry.py`** — replace L55 surface bounds check with `plan.adapter_recovery_enabled`. This is the cross-module accidental (Batch C rank 8).
7. **`pipeline/listing_helpers.py`** — `_looks_like_loading_listing_shell` early exit (rank 3) is only partially an acquisition concern. If the plan reaches this file, delete the guard. If not, collapse unconditionally in this commit.

Per commit: the consumer's `surface` / `page_type` strategy-reads drop to zero. `grep -n "page_type\|surface" <file>` should only show passthrough / telemetry hits.

### Step 4 — Collapse the 8 accidental branches

Verify all 8 (Batch C Deliverable 4) are dead after Step 3. Any that survive are converted to `plan.<field>` reads or deleted. List the disposition in the closing note per branch:
- rank 1, 2, 3 (listing-suffix guards): deleted
- rank 4, 5 (diagnose_commerce/job early-exit): collapsed into one generic diagnostic, surface becomes a payload field
- rank 6 (escalation bounds check): deleted; rules run unconditionally
- rank 7 (diagnostic payload name branch): single payload shape with `plan.diagnostic_payload_kind` as field
- rank 8 (registry recovery bounds): handled in Step 3.6

### Step 5 — Preserve the 7 invariant-risk essentials

Batch C Deliverable 5 names 7 essentials that carry invariant risk. Each must appear inside `plan_acquisition` with a comment citing the invariant:
```python
# Inv. 16 — user surface directive: browser escalation only on detail JS shells
# policy.py L158 origin
if surface.endswith("_detail") and js_shell_detected:
    allow_browser_escalation = True
```
These are not collapses. They are moves. The test added in Step 2 must include a case for each of the 7.

### Step 6 — Verify directional reads

From repo root:
```
grep -n "page_type\|surface\|is_listing\|is_detail" backend/app/services/acquisition/ backend/app/services/adapters/registry.py
```
Every remaining hit must be one of:
- inside `policy.py::plan_acquisition`
- a field on `AcquisitionPlan`
- a passthrough (logging, telemetry, being forwarded to another call)
- a docstring / comment

Record the expected vs actual hit count in the closing note.

### Step 7 — Tests

```
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests/services/acquisition -q
.\.venv\Scripts\python.exe -m pytest tests/services/test_plan_acquisition.py -q
.\.venv\Scripts\python.exe run_acquire_smoke.py commerce
.\.venv\Scripts\python.exe run_acquire_smoke.py job   # if exists; otherwise skip with note
```

Full suite is not a gate for Slice 3 acceptance (the pre-existing failures from Slices 0-2 still exist). Slice 3 acceptance requires acquisition-focused tests and both acquire smokes passing.

## Acceptance criteria

- [ ] `AcquisitionPlan` dataclass defined. `plan_acquisition` function implemented and tested.
- [ ] `scratch/slice-3-decision-snapshot.md` records the traceability of all 21 Batch C branches.
- [ ] The 8 accidental branches from Batch C Deliverable 4 are gone.
- [ ] The 7 invariant-risk essentials are moved into `plan_acquisition` with invariant-citing comments.
- [ ] `grep page_type\|surface` on the 6 consumer files returns only passthrough / telemetry hits (zero strategy branches).
- [ ] `tests/services/acquisition/test_plan_acquisition.py` covers every observed `(surface, page_type, platform_family)` combination.
- [ ] `run_acquire_smoke.py commerce` passes. Acquisition-focused pytest green.
- [ ] Closing note appended with: code-reduction delta (files touched, lines removed), acceptance-of-8-accidentals disposition, expected-vs-actual grep counts.

## Out of scope

- `normalizers/listings.py`, `discover/*`, `schema_service.py`, extract/ branches — Phase 2.
- Invariant 12 noise-rule repair — Slice 4.
- Unify leak repatriation — Slice 4.
- Fixing `run_extraction_smoke.py` (`ModuleNotFoundError: app.services.semantic_detail_extractor`) — prerequisite for Slice 4, not Slice 3.
- The 15 platform-family adapters — they are definitionally surface-specific; revisit in Phase 2.

## Rollback

Per-file-per-commit means per-file revert. If `run_acquire_smoke.py commerce` regresses after any migration commit, revert that commit and document in `## Revival log`. If the snapshot shows a branch that doesn't map cleanly into `AcquisitionPlan`, stop and escalate — the decision may be essential in a way Batch C missed, and a Slice 3.5 may be needed before continuing.

## User-visible outcome this targets

From [00-program-audit-2026-04-17.md](../00-program-audit-2026-04-17.md): "confusion in acquisition strategies on what to use when." After Slice 3, the answer lives in one file: `policy.py::plan_acquisition`. That is the win to narrate in the closing note.

## Closing note

- Status: implemented. `backend/app/services/acquisition/policy.py` now owns the acquisition strategy decision tree through `AcquisitionPlan` and `plan_acquisition()`. `acquirer.py` computes the plan once and passes it into browser readiness, traversal, recovery, and adapter recovery.
- Decision traceability: recorded in `scratch/slice-3-decision-snapshot.md`.
- Code delta: tracked patch diff across `16` files with `279` lines removed and `464` lines added, plus the new `backend/tests/services/acquisition/test_plan_acquisition.py` file and `scratch/slice-3-decision-snapshot.md`.
- Accidental branch disposition:
  - rank 1 `_is_listing_surface`: deleted
  - rank 2 listing-readiness early exit: deleted
  - rank 3 listing-shell early exit in `listing_helpers.py`: deleted
  - rank 4 commerce-only diagnostic guard: deleted into generic diagnostic profile handling
  - rank 5 job-only diagnostic guard: deleted into generic diagnostic profile handling
  - rank 6 escalation bounds check: moved out of consumer logic into the centralized `AcquisitionPlan.allow_browser_escalation` decision
  - rank 7 diagnostic payload name split: collapsed into `plan.diagnostic_payload_kind`
  - rank 8 registry recovery bounds check: deleted from `registry.py`; recovery now keys off `plan.adapter_recovery_enabled`
- Grep counts:
  - expected: raw `surface/page_type` hits remain only as plan fields, passthroughs, telemetry, or comments
  - actual: `96` raw hits across the six consumer files; `0` direct raw-surface/page-type strategy branches remain; the only strategy-shaped reads left are `plan.is_listing_surface` field accesses in `acquirer.py` and `traversal.py`
- Verification:
  - `backend\.venv\Scripts\python.exe -m compileall backend/app/services/acquisition backend/app/services/adapters/registry.py backend/app/services/pipeline/listing_helpers.py backend/app/services/pipeline/listing_flow.py`
  - `backend\.venv\Scripts\python.exe -m pytest backend/tests/services/acquisition -q` -> `152 passed`
  - `backend\.venv\Scripts\python.exe backend/run_acquire_smoke.py jobs` -> `5/5 ok`
  - `backend\.venv\Scripts\python.exe backend/run_acquire_smoke.py commerce` -> `5/6 ok`; the single failure was `https://www.converse.com/shop/mens-shoes` resolving failure (`AcquisitionFailureError` after host resolution failure), which is an external smoke input issue rather than a Slice 3 regression
