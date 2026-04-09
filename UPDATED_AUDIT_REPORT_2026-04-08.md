# Updated Backend Audit (Revised)

This revision incorporates your clarifications:
- Deployment context: **single instance**
- Listing fallback on listing pages: **not intentional**
- Advanced traversal semantics: when advanced mode is enabled, `auto` should detect all; explicit selection should run only selected mode
- Pollution focus confirmed on: `category`, `title`, `availability`, `color`, `brand`

Phase 6 note (2026-04-08): This document is an audit and backlog assessment, not an implementation changelog. Claims about telemetry wiring, module removals, or dead-code sweeps should be verified against the repository at the cited paths; the bullets below are **findings and recommendations**, not assertions that a specific PR shipped them.

---

## 1) EXECUTIVE SUMMARY

Health scores (0-10):
- Architecture: **5.2**
- Correctness: **5.3**
- Reliability: **5.1**
- Maintainability: **4.7**
- Security: **6.6**
- Test maturity: **6.1**

Top 5 existential risks:
1. Field arbitration is still first-available/first-row driven (`extract/service.py`, `pipeline/core.py`), so polluted non-empty values can become canonical.
2. Advanced traversal contract is partially mismatched (`auto` normalized away in run settings despite implementation in traversal engine).
3. User-owned surface can still be rewritten in pipeline (`pipeline/core.py:_resolve_listing_surface`), violating mode-authority.
4. Generic acquisition contains tenant-specific hardcoding (`acquirer.py:_requires_browser_first` includes `careers.clarkassociatesinc.biz`).
5. Listing fallback behavior contradicts intended contract (partial fallback record still written in `pipeline/core.py:_extract_listing`).

Top 5 strengths:
1. SSRF/public-target validation is robust and fail-closed (`url_safety.py`).
2. Diagnostics artifacts are strong and actionable (`acquirer.py` diagnostics + artifact persistence).
3. Browser lifecycle cleanup is explicit (`browser_client.py` closes context/browser in `finally`).
4. Traversal primitives are substantial and have meaningful tests (`acquisition/traversal.py`, `tests/services/acquisition/test_browser_client.py`).
5. Config centralization via typed modules is mostly good (`pipeline_config.py` + config submodules).

Production readiness:
This is a strong POC and close to production mechanics, but not yet production-safe for data integrity at scale. The biggest remaining gap is canonical field correctness under noisy pages/scripts. Traversal behavior is mostly implemented, but mode normalization/contract wiring still causes silent surprises. Reliability is acceptable for single-node usage, but correctness and contract invariants need P0 fixes first.

---

## 2) ARCHITECTURE FINDINGS (Ranked by Severity)

### Finding 1
- Severity: **Critical**
- Confidence: **High**
- Category: **Schema / Correctness**
- Evidence: `backend/app/services/extract/service.py:_collect_candidates`, `_finalize_candidates`; `backend/app/services/pipeline/core.py:_reconcile_detail_candidate_values`
- Problem: Source short-circuit + `rows[:1]` + first accepted candidate means arbitration is order-biased, not quality-biased.
- Production impact: Polluted values can beat valid JSON-LD/structured values.
- Minimal fix: keep top-N candidates through reconciliation and rank by source + field quality.
- Ideal fix: centralized arbitration engine with per-field validators and confidence scoring.
- Effort: **M**
- Regression risk if unchanged: **Critical**

### Finding 2
- Severity: **High**
- Confidence: **High**
- Category: **Traversal**
- Evidence: `backend/app/services/crawl_utils.py:resolve_traversal_mode`; `backend/app/services/acquisition/traversal.py:apply_traversal_mode`
- Problem: `auto` path exists in traversal but is mapped to `None` at settings normalization.
- Production impact: advanced auto-detect intent silently disabled.
- Minimal fix: preserve `auto` when advanced traversal is enabled.
- Ideal fix: typed traversal enum + explicit mode matrix (`auto`, `paginate`, `scroll`, `view_all/load_more`).
- Effort: **S**
- Regression risk if unchanged: **High**

### Finding 3
- Severity: **High**
- Confidence: **High**
- Category: **Design / Correctness**
- Evidence: `backend/app/services/pipeline/core.py:_resolve_listing_surface`
- Problem: backend rewrites requested `surface` (`ecommerce_listing` -> `job_listing`).
- Production impact: violates user-owned control contract and causes non-obvious runtime behavior.
- Minimal fix: do not mutate surface; log diagnostic suggestion only.
- Ideal fix: strict control ownership and explicit validation warnings pre-run.
- Effort: **S**
- Regression risk if unchanged: **High**

### Finding 4
- Severity: **High**
- Confidence: **High**
- Category: **HardcodedHack**
- Evidence: `backend/app/services/acquisition/acquirer.py:_requires_browser_first`
- Problem: hardcoded company domain in generic acquisition policy.
- Production impact: hidden behavior drift and non-portable runtime policy.
- Minimal fix: move to explicit config policy record.
- Ideal fix: platform-family strategy hooks only; no tenant domains in generic code.
- Effort: **S**
- Regression risk if unchanged: **High**

### Finding 5
- Severity: **Medium**
- Confidence: **High**
- Category: **Traversal / Observability**
- Evidence: `backend/app/services/acquisition/browser_client.py:_apply_traversal_mode`
- Problem: shared traversal returns `TraversalResult(summary=...)` but wrapper returns only `html`; summary detail is discarded.
- Production impact: silent fallback/stop reasons not visible in run diagnostics.
- Minimal fix: propagate traversal summary into `BrowserResult.diagnostics`.
- Ideal fix: persist traversal step telemetry in run summary per URL.
- Effort: **S**
- Regression risk if unchanged: **Medium**

### Finding 6
- Severity: **Medium**
- Confidence: **High**
- Category: **Correctness / Contract**
- Evidence: `backend/app/services/pipeline/core.py:_extract_listing`
- Problem: listing fallback record is still written as partial despite intended no-fallback listing contract.
- Production impact: listing failures can be masked by pseudo-records.
- Minimal fix: remove fallback write path for listing runs.
- Ideal fix: explicit separate artifact for fallback diagnostics, never in canonical records.
- Effort: **S**
- Regression risk if unchanged: **High**

---

## 3) SITE-SPECIFIC HACKS REGISTER

| ID | Location (file:function) | Domain/Pattern Matched | Classification | Risk | Consolidation Action |
|---|---|---|---|---|---|
| H-001 | `acquisition/acquirer.py:_requires_browser_first` | `careers.clarkassociatesinc.biz` | DANGEROUS | Tenant-specific behavior in generic path | Move to config strategy and remove hardcode |
| H-002 | `acquisition/acquirer.py:_requires_browser_first` | ADP hosts | SMELL | Duplicates adapter/platform-family concern | Consolidate to platform policy map |
| H-003 | `extract/listing_extractor.py:_synthesize_job_detail_url` | `recruiting.ultipro.com` | SMELL | Vendor-specific URL synthesis in generic extractor | Move to adapter strategy |
| H-004 | `llm_integration/page_classifier.py:_url_surface` | host token checks (`ats`, `workday`, `greenhouse`) | SMELL | Loose host token logic can misclassify | Use platform-family classification only |
| H-005 | `config/extraction_rules.py:PIPELINE_TUNING` | `browser_first_domains=["reverb.com"]` | SMELL | Domain policy embedded in broad tuning config | Move to dedicated site policy registry |
| H-006 | `config/selectors.py:PLATFORM_LISTING_READINESS_*` | platform URL/selector overrides | JUSTIFIED | Centralized per-platform readiness tuning | Keep centralized with owner/expiry metadata |

Consolidation strategy:
- Move to site config: browser-first, readiness wait overrides, traversal quirks.
- Move to strategy/adapter: vendor URL synthesis and platform-specific extraction glue.
- Delete: tenant domain hardcoding in generic acquirer.
- Safe order: introduce config registry -> mirror behavior -> add tests -> delete hardcoded branches.

---

## 4) SCHEMA POLLUTION TRACE REPORT

### Evidence from captured artifacts
- `backend/artifacts/html/dashingdiva-com-aa3b220907-run_5.html` contains heavy script/data-layer/cookie-consent instrumentation (`window.dataLayer`, cookie event handlers, tracking code) mixed with product metadata.
- This matches your reported pollution profile and confirms contamination opportunities are real in raw HTML inputs.

### Field: `title`
- Sources in order: contract -> adapter -> datalayer -> network -> json_ld -> embedded/next/hydrated -> selector/dom/og -> semantic/text (`extract/service.py:_collect_candidates`)
- Arbitration location: `_finalize_candidates` then `_reconcile_detail_candidate_values`.
- Garbage win condition: first non-empty row in an earlier source survives weak title validation.
- Scope: **universal**
- Minimal fix: stronger title quality rules (consent/privacy/login/nav/CTA phrase rejection) before finalization.
- Ideal fix: quality-ranked arbitration across sources.
- Priority: **P0**, Effort: **M**

### Field: `category`
- Arbitration path: same as title.
- Garbage win condition: breadcrumb/navigation/taxonomy strings pass `_coerce_category_field` and generic `validate_value`.
- Scope: **universal**
- Minimal fix: category-specific sanitizer (reject nav trails, tracking semantics, schema-type residue).
- Ideal fix: canonical category normalization gate.
- Priority: **P0**, Effort: **M**

### Field: `brand`
- Arbitration + merge path: candidates in `extract/service.py`; adapter merge dominance in `pipeline/field_normalization.py:_merge_record_fields`.
- Garbage win condition: adapter/early-source non-empty brand remains sticky; better downstream value cannot replace.
- Scope: **universal**
- Minimal fix: allow secondary override for `brand` when candidate quality materially better.
- Ideal fix: confidence-aware merge policy.
- Priority: **P0**, Effort: **S**

### Field: `availability`
- Garbage win condition: `_coerce_availability_field` rejects very little; UI text can pass.
- Scope: **universal**
- Minimal fix: finite availability state normalization + UI phrase reject list.
- Ideal fix: strict enum parser with source-weighted confidence.
- Priority: **P0**, Effort: **S**

### Field: `color`
- Garbage win condition: long/noisy strings from scripts/UI can evade current filters.
- Scope: **universal with site-specific manifestations**
- Minimal fix: max token length + lexical color/variant validation.
- Ideal fix: typed attribute normalizer for variant fields.
- Priority: **P1**, Effort: **S**

---

## 5) BROWSER TRAVERSAL MODE — BUG TRACE & FIX PLAN

### Paginated
- Implemented end-to-end: **Yes**
- Evidence: `crawl_crud.py` -> `_batch_runtime.py` -> `acquirer.py` -> `traversal.py:collect_paginated_html`
- Failure mode: traversal step summary lost in browser wrapper.
- Minimal fix: keep `TraversalResult.summary` in diagnostics.
- Ideal fix: per-step persisted telemetry.
- Priority: **P1**, Effort: **S**

### Infinite Scroll
- Implemented end-to-end: **Yes (heuristic-limited)**
- Evidence: `traversal.py:scroll_to_bottom`
- Failure mode: can stop early on delayed/virtualized rendering (`height_only`/stability heuristic limits).
- Minimal fix: add one adaptive retry cycle before stopping.
- Ideal fix: platform-specific progress strategy.
- Priority: **P1**, Effort: **M**

### View All
- Implemented end-to-end: **Partial/Broken as explicit mode**
- Evidence: `resolve_traversal_mode` lacks explicit `view_all`; `LOAD_MORE_SELECTORS` includes text `"View All"` but only if load_more mode runs.
- Failure mode: explicit `view_all` user intent can be dropped.
- Minimal fix: map `view_all` to `load_more` for advanced traversal mode.
- Ideal fix: first-class `view_all` mode branch.
- Priority: **P0**, Effort: **S**

### Auto mode (per your clarified contract)
- Intended behavior: when advanced enabled and `auto`, detect all available traversal options and apply relevant sequence.
- Current gap: normalization currently nulls `auto` (`crawl_utils.py`).
- Priority: **P0**, Effort: **S**

---

## 6) BUG & DEFECT CANDIDATE LIST

| ID | P | Sev | File:Function | Symptom | Trigger | Root Cause | Fix | Test to Add | Status |
|---|---|---|---|---|---|---|---|---|---|
| B-001 | P0 | High | `extract/service.py:_finalize_candidates` | polluted winner | multiple candidates per field | `rows[:1]` | rank candidates | arbitration fixture test | LIKELY BUG |
| B-002 | P0 | High | `crawl_utils.py:resolve_traversal_mode` | `auto` traversal disabled | advanced mode auto | auto -> None mapping | preserve auto | traversal mode normalization test | LIKELY BUG |
| B-003 | P0 | High | `pipeline/core.py:_resolve_listing_surface` | surface rewritten | job-like heuristics | mode mutation | no mutation | control-authority contract test | LIKELY BUG |
| B-004 | P0 | High | `pipeline/core.py:_extract_listing` | fallback partial record on listing | no records | legacy fallback path | remove path | listing no-fallback test | LIKELY BUG |
| B-005 | P1 | Med | `pipeline/field_normalization.py:_merge_record_fields` | brand/category stickiness | adapter + better candidate | narrow override policy | quality override rules | merge-quality unit test | LIKELY BUG |
| B-006 | P1 | Med | `acquisition/browser_client.py:_apply_traversal_mode` | missing traversal reason telemetry | any traversal attempt | summary discarded | persist summary | diagnostics assertion test | LIKELY BUG |
| B-007 | P1 | Med | `acquisition/acquirer.py:_requires_browser_first` | hidden tenant policy | specific host | hardcoded domain | config policy | hardcode removal test | ARCH SMELL |

---

## 7) CODE REDUCTION & SIMPLIFICATION BACKLOG

TODO-SIMP-001: Remove listing fallback branch from pipeline core  
Priority: P0  
Effort: S  
Files affected: `backend/app/services/pipeline/core.py`  
What to remove/merge/collapse: remove listing fallback record write path in `_extract_listing`  
What to keep: explicit verdict-only failure path (`listing_detection_failed`/`blocked`)  
Estimated LoC delta: ~-45  
Bug surface reduction: High (stops contract drift)  
Risk of simplification: medium; validate with listing failure tests

TODO-SIMP-002: Unify traversal mode normalization and runtime resolution  
Priority: P0  
Effort: S  
Files affected: `backend/app/services/crawl_utils.py`, `backend/app/services/crawl_crud.py`, `backend/app/services/_batch_runtime.py`  
What to remove/merge/collapse: duplicate mode handling assumptions  
What to keep: single resolver function with explicit mode matrix  
Estimated LoC delta: ~-30  
Bug surface reduction: High  
Risk: low; validate create+run parity

TODO-SIMP-003: Remove thin `batch.py` wrappers  
Priority: P2  
Effort: S  
Files affected: `backend/app/services/batch.py` and import sites  
What to remove/merge/collapse: pure pass-through wrapper layer  
What to keep: `_batch_runtime.py` implementations  
Estimated LoC delta: ~-60  
Bug surface reduction: Medium  
Risk: low; verify imports/tests

---

## 8) AGENT-EXECUTABLE REMEDIATION BACKLOG

### P0

TODO-001: Preserve and execute `auto` traversal mode when advanced mode is enabled  
Priority: P0  
Effort: S (<2h)  
Category: Traversal  
File(s): `backend/app/services/crawl_utils.py`, `backend/app/services/crawl_crud.py`, `backend/app/services/_batch_runtime.py`  
Problem: `auto` is currently normalized away, breaking intended advanced auto-detection behavior.  
Action:
1. Update resolver to keep `auto` valid.
2. Ensure runtime also resolves mode via same resolver.
3. Add backward-compatible mapping for `view_all` to `load_more` (or explicit mode token).
Acceptance criteria: Runs with advanced `auto` call traversal path; explicit modes execute only requested behavior.  
Depends on: none

TODO-002: Replace first-row winner logic with ranked arbitration  
Priority: P0  
Effort: M (2h-1d)  
Category: Schema  
File(s): `backend/app/services/extract/service.py`, `backend/app/services/pipeline/core.py`, `backend/app/services/config/extraction_rules.py`  
Problem: `rows[:1]` and first-accept semantics let polluted values win.  
Action:
1. Keep multiple candidate rows through reconciliation.
2. Add field-specific ranking and quality checks.
3. Select top valid candidate by rank, not first position.
Acceptance criteria: polluted fixtures resolve to cleaner values for `category`, `title`, `availability`, `color`, `brand`.  
Depends on: none

TODO-003: Remove listing fallback record write path  
Priority: P0  
Effort: S (<2h)  
Category: Correctness  
File(s): `backend/app/services/pipeline/core.py`  
Problem: non-intentional fallback path masks listing extraction failures.  
Action:
1. Delete fallback record creation block.
2. Return explicit `VERDICT_LISTING_FAILED`/`VERDICT_BLOCKED` only.
Acceptance criteria: no synthetic listing fallback record persisted on zero-item listing pages.  
Depends on: none

TODO-004: Stop surface mutation in listing extraction  
Priority: P0  
Effort: S (<2h)  
Category: Correctness  
File(s): `backend/app/services/pipeline/core.py`  
Problem: `_resolve_listing_surface` rewrites user-selected mode.  
Action:
1. Bypass mode rewrite.
2. Keep diagnostic hint only when mismatch detected.
Acceptance criteria: requested `surface` remains unchanged in pipeline behavior and output traces.  
Depends on: none

### P1

TODO-005: Add canonical pollution sanitizer for high-risk fields  
Priority: P1  
Effort: M (2h-1d)  
Category: Schema  
File(s): `backend/app/services/extract/service.py`, `backend/app/services/normalizers/__init__.py`, `backend/app/services/config/extraction_rules.py`  
Problem: field gates are too generic for real-world consent/tracking script noise.  
Action:
1. Add field-specific reject rules for `category`, `title`, `availability`, `color`, `brand`.
2. Add phrase/token/length heuristics in config.
3. Apply before canonical winner selection.
Acceptance criteria: known noisy strings are filtered without removing valid values.  
Depends on: TODO-002

TODO-006: Propagate traversal summaries to diagnostics and run metrics  
Priority: P1  
Effort: S (<2h)  
Category: Reliability  
File(s): `backend/app/services/acquisition/browser_client.py`, `backend/app/services/acquisition/acquirer.py`, `backend/app/services/_batch_runtime.py`  
Problem: traversal stop reasons/steps are computed but dropped.  
Action:
1. Return traversal summary from browser wrapper.
2. Store summary in acquisition diagnostics.
3. Roll up key counters in run-level summary.
Acceptance criteria: run diagnostics show mode, attempts, steps, stop_reason for traversed URLs.  
Depends on: TODO-001

TODO-007: Remove tenant domain hardcode from generic acquisition  
Priority: P1  
Effort: S (<2h)  
Category: HardcodedHack  
File(s): `backend/app/services/acquisition/acquirer.py`, `backend/app/services/config/extraction_rules.py`  
Problem: company-specific host in `_requires_browser_first`.  
Action:
1. Remove tenant host from code branch.
2. Add governed config policy for exceptions if still needed.
Acceptance criteria: no tenant hostname literals remain in generic acquirer decision logic.  
Depends on: none

### P2

TODO-008: Collapse wrapper indirection around `_batch_runtime`  
Priority: P2  
Effort: S (<2h)  
Category: Simplification  
File(s): `backend/app/services/batch.py`, dependent imports  
Problem: thin wrapper layer adds cognitive overhead without behavior.  
Action:
1. Point imports to `_batch_runtime` directly.
2. remove wrapper module.
Acceptance criteria: tests pass, no runtime behavior change.  
Depends on: none

---

## 9) TECHNICAL DEBT REGISTER

| ID | Debt Item | Type | Daily Cost | Paydown Effort | Action | Priority |
|---|---|---|---|---|---|---|
| TD-001 | First-row field arbitration | complexity | High | M | ranked arbitration | P0 |
| TD-002 | Advanced mode contract drift (`auto`) | drift | High | S | single resolver contract | P0 |
| TD-003 | Listing fallback contradiction | drift | Medium | S | remove fallback path | P0 |
| TD-004 | Surface mutation in pipeline | hardcoded-hack | High | S | remove rewrite behavior | P0 |
| TD-005 | Tenant hardcode in acquirer | hardcoded-hack | Medium | S | policy registry | P1 |
| TD-006 | Dropped traversal summaries | test-debt | Medium | S | propagate diagnostics | P1 |
| TD-007 | Wrapper indirection | over-abstraction | Low | S | collapse wrapper | P2 |

---

## 10) RELIABILITY & INCIDENT READINESS

- Hidden failure modes:
  - advanced traversal auto silently disabled by normalization drift
  - zero-listing extraction masked by fallback partial (until removed)
  - canonical field quality regressions not reflected by status alone
- Observability gaps:
  - traversal stop reasons currently not consistently surfaced to run-level summary
  - no explicit alerting on schema pollution signatures
- Top 10 alerts:
  1. spike in `listing_detection_failed` by domain
  2. spike in `blocked` verdict by provider
  3. runs with advanced traversal requested but no traversal diagnostics
  4. ratio of completed runs with low core-field completeness
  5. repeated `proxy_exhausted`
  6. high browser retry rate
  7. high extraction duration p95 by platform_family
  8. high rate of normalized `category/title` dropped as noise
  9. repeated run restarts on same URL set
  10. stuck `running` with no stage/progress movement
- Browser zombie risk:
  - lower than previously suspected; `browser_client.py` does explicit `context.close()` and `browser.close()` in `finally`.
- Stuck run detection:
  - still needs stronger heartbeat/alerting despite control checkpoints.

---

## 11) SECURITY AUDIT SNAPSHOT

- High: redirect-chain trust boundaries for crawled URLs should be stricter on final host policy.
- Medium: recursive candidate extraction can be abused for CPU overhead without strict payload limits.
- Medium: extracted PII policy is not explicit; persistence is broad by default.
- Low-Medium: regex/XPath contract inputs need runtime guardrails against pathological patterns.

Crawler-specific risks reviewed:
- SSRF: good controls present (`url_safety.py`).
- Path traversal: artifact path uses slug+hash, low risk.
- Injection: no immediate SQL injection evidence in sampled paths; maintain strict ORM patterns.

---

## 12) PERFORMANCE & SCALABILITY AUDIT

- Top bottlenecks:
  - repeated deep alias scans and source traversals in `listing_extractor.py` and `extract/service.py`
  - multiple parse passes of the same HTML/source containers
- Browser inefficiency:
  - readiness/traversal heuristics can over-wait or under-wait depending on site render timing
- Profiling plan:
  1. instrument per-field extraction time in `extract/service.py`
  2. instrument source traversal counts in listing/detail extractors
  3. compare p95 by traversal mode and platform family
- High ROI optimizations:
  1. source traversal caching/indexing
  2. arbitration early-pruning
  3. reduce duplicate parsing across helper paths

---

## 13) TEST COVERAGE GAP ANALYSIS

- P0: advanced auto traversal end-to-end contract test (`advanced_mode=auto` should execute traversal path)
- P0: explicit `view_all` mode behavior test
- P0: pollution arbitration fixtures for `category/title/availability/color/brand`
- P0: listing fallback absence test (no synthetic records)
- P1: adapter-vs-candidate merge quality override tests
- P1: traversal summary persistence assertions in diagnostics/run summary

---

## 14) "IF I OWNED THIS CODEBASE" — TOP 12 ACTIONS

1. Fix traversal mode contract (`auto` + `view_all`) first.
2. Remove listing fallback pseudo-record writes.
3. Remove surface mutation.
4. Implement ranked candidate arbitration.
5. Add field-specific pollution sanitizer.
6. Propagate traversal summary telemetry.
7. Remove tenant hardcode from acquirer.
8. Add P0 regression tests for pollution and traversal.
9. Add quality-focused alerts.
10. Unify normalization ownership.
11. Collapse wrapper indirection.
12. Re-run extraction smoke on known noisy sites and compare before/after deltas.

---

## 15) CLARIFYING QUESTIONS

1. Should explicit `view_all` be a distinct mode in API contract, or normalized to `load_more` permanently?
2. Do you want strict failure when advanced mode is enabled but requested traversal control is absent on page?
3. Should polluted field rejection prefer `null` over weak fallback value (strict mode)?
4. Is per-domain policy metadata (owner/expiry) acceptable in config for temporary overrides?
5. Do you want run status to remain `completed` when core fields are weak but non-empty, or move to stricter verdicting?

