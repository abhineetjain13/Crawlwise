# CrawlerAI — Forensic Architecture Audit

## System Context

CrawlerAI is a Python/FastAPI web crawling and data extraction platform. It uses a
hybrid acquisition pipeline (curl_cffi default → Playwright fallback), selectors/domain-
memory feedback loops, provenance-aware record responses, admin-managed LLM runtime/config,
and supports ecommerce, jobs, automobiles, and tabular targets. Audit shared/generic paths
against all supported surfaces. Surface-specific deep checks should focus on the surfaces
the active plan or recent regressions currently emphasize.

Pipeline stages: ACQUIRE → EXTRACT → PUBLISH.

Extraction source hierarchy is authoritative-first and quality-gated, not blind merge:
adapter → XHR/JSON / network payload mapping → JSON-LD / microdata / Open Graph →
hydrated state (`__NEXT_DATA__`, `__NUXT_DATA__`) → DOM → LLM fallback.
Audit whether stronger sources retain precedence and whether lower-quality sources are only
used when higher tiers are absent, thin, noisy, or explicitly quality-gated by the owning logic.

The codebase is post-refactor. Treat `AGENTS.md` and `INVARIANTS.md` as the authoritative
intent. Every place where code contradicts these docs is a violation.

Ownership buckets (from `ENGINEERING_STRATEGY.md`):
1. API + Bootstrap
2. Crawl Ingestion + Orchestration
3. Acquisition + Browser Runtime
4. Extraction
5. Publish + Persistence
6. Review + Selectors + Domain Memory
7. LLM Admin + Runtime

Recent implementation areas to verify for quality/regression only
(cross-check with `docs/plans/ACTIVE.md` and the linked plan; do not assume this list is exhaustive):
structured-source expansion (microdata/Open Graph/Nuxt revival), network payload specs,
declarative JMESPath JS-state mappings, browserforge identity, URL tracking-param stripping,
selector self-heal with improvement gating, domain memory scoped by (domain, surface),
provenance/review-bucket-aware responses, selectors API, LLM admin/config surfaces,
acquisition plan normalization through `AcquisitionPlan → URLProcessingConfig → AcquisitionRequest`.

---

## REQUIRED PREFLIGHT

Before auditing, explicitly read these files in this order and state that you did:

1. `AGENTS.md`
2. `docs/CODEBASE_MAP.md`
3. `docs/BUSINESS_LOGIC.md`
4. `docs/ENGINEERING_STRATEGY.md`
5. `docs/INVARIANTS.md`
6. `docs/plans/ACTIVE.md`
7. The plan file currently pointed to by `docs/plans/ACTIVE.md` if one exists

Start the audit output with a short preflight block:

```
Preflight:
- Read: AGENTS.md, CODEBASE_MAP.md, BUSINESS_LOGIC.md, ENGINEERING_STRATEGY.md, INVARIANTS.md
- Active plan: [path or NONE]
- Audit scope emphasis: [surfaces / subsystem emphasis inferred from active plan or FIRST RUN]
```

If you did not read these files, do not continue.

---

## LONGITUDINAL MODE — REQUIRED INPUT

**Paste the previous session's top findings and prior scores below before running this audit.**
If this is the first session, write `FIRST RUN` and skip the delta step.

```
PREVIOUS TOP FINDINGS:
[paste previous audit's Critical Path findings here, one per line with their IDs]

PREVIOUS SCORES:
D1: X.X
D2: X.X
D3: X.X
D4: X.X
D5: X.X
D6: X.X
D7: X.X
D8: X.X
OVERALL: X.X
```

Finding IDs must be stable across sessions.
Use:
- `F-###` for audit findings
- `RC-#` for root causes
- `LN-#` for leaf-node fixes

If a previous finding has no stable ID, mark it `NOT FOUND` and exclude it from score deltas.

Before auditing any dimension, evaluate each previous finding as:
- **FIXED** — code evidence confirms the fix is in place (cite the file/function)
- **PERSISTS** — still present (re-cite exact location)
- **REGRESSED** — was fixed, is broken again (cite what changed)
- **NOT FOUND** — cannot confirm either way (mark as unverifiable, do not score)

Output this delta table first, before any dimension scores.

---

## AUDIT ROLE

You are a senior principal engineer conducting a forensic code audit.
Do not summarize what the code does. Do not be diplomatic. Do not praise effort.
Your job: find violations, score dimensions honestly, surface production risks, and
output structured remediation work orders that can be handed directly to Codex.

---

## VERIFICATION REQUIREMENT — ENFORCED FOR EVERY FINDING

For every violation you cite, you must provide:

```
rg -n "exact_symbol_or_pattern" backend/app/services/[file]
```

or an equivalent search that would confirm the finding in the actual codebase.

When a single grep is not enough because the violation is structural
(for example SRP, DRY, layering, or precedence/ranking behavior), provide:
- 1–3 machine-runnable searches (`rg`, `grep`, or equivalent), and
- a 1–2 sentence evidence trace connecting those search hits to the finding.

If you cannot construct a grep that would find it, do not report the finding.
"I believe this pattern exists" is not a citation. Line numbers that you are not
confident are accurate must be marked `(approx)`. Fabricated line numbers that are
off by more than 20 lines in either direction are worse than no citation.

---

## SCORING MODEL

**Do not use the rule "a single CRITICAL caps the dimension at 5/10."**
That rule punishes progress and inflates perceived stagnation.

Use this model instead:

Each dimension is scored 1–10 on two axes:

| Axis | Meaning |
|------|---------|
| **Floor** | Set by the worst single violation. CRITICAL = floor of 4. HIGH = floor of 6. MEDIUM = floor of 7. LOW = floor of 8. No violations = floor of 9. |
| **Ceiling** | Set by overall dimension quality — test coverage, consistency, structural integrity. Maximum ceiling is 10. |

**Final score = (floor + ceiling) / 2**, rounded to one decimal.

This means: a dimension with one CRITICAL but otherwise excellent code scores (4 + 8) / 2 = 6.
A dimension with three CRITICALs and no redeeming quality scores (4 + 3) / 2 = 3.5.
A dimension with no violations and excellent patterns scores (9 + 10) / 2 = 9.5.

Show both the floor and ceiling, then the final score, for every dimension.

**Longitudinal note:** If the previous session's score is provided, you must explain in
one sentence why the score changed (or did not change) relative to the previous run.
Do not allow scores to decrease without citing a new finding. Do not allow scores to
increase without citing what was fixed.

---

## AUDIT DIMENSIONS

Evaluate each dimension with file-level forensic depth. Generic statements are
unacceptable. Name the specific function, the specific failure mode, and the
first-principles rule or INVARIANTS.md clause it breaks.

### D1. SOLID / DRY / KISS

- **SRP:** Functions over 50 lines doing 3+ conceptually distinct things. Classes with
  more than one reason to change. Cite function name and line range.
- **OCP:** New surfaces or adapters added by modifying generic paths rather than extending
  adapter/config owned slots.
- **DIP:** High-level modules importing from low-level concrete modules (layer violations).
  Example anti-pattern: `pipeline/core.py` importing from `detail_extractor.py` internals.
- **DRY:** Exact or near-exact function duplication across files. Field resolution,
  URL normalisation, retry logic written twice.
- **KISS:** Indirection or abstraction where a direct call or constant would suffice.
  Anti-patterns AP-1 through AP-10 from `ENGINEERING_STRATEGY.md`.

### D2. Configuration Hygiene

- Hardcoded domain strings, URL fragments, or selector strings inside business logic
  (not in `services/config/*`). Search for string literals that look like hostnames
  inside `acquisition/`, `crawl_engine.py`, `detail_extractor.py`, `listing_extractor.py`.
- Magic numbers (timeouts, retry counts, thresholds) scattered inline rather than
  named constants in `services/config/`.
- `if "amazon" in url`, `if "shopify"`, `if "linkedin"` — platform conditionals in
  generic paths. These are AP-4 violations.
- Config defined in multiple places (env + `config.py` + inline defaults) that can contradict.
- AP-10: inline dicts or constants that bypass env-controlled settings.

### D3. Scalability & Resource Management

- Blocking I/O or sync third-party calls on async hot paths (especially in
  `crawl_fetch_runtime.py`, `pipeline/core.py`, `structured_sources.py`).
- Playwright browser/context/page objects not closed in `finally` blocks.
  Search: `browser_runtime.py`, `browser_page_flow.py` — every context acquisition
  must have a matching release in a `finally` or `async with`.
- Unbounded data structures: lists that grow without cap in traversal or extraction loops.
- Async tasks spawned without tracking or cancellation (bare `asyncio.create_task`
  without storing the result).
- Shared HTTP client pool — confirm `runtime.py` `get_shared_http_client()` is truly
  shared and `http_client.py` does not maintain a second pool.

### D4. Extraction & Normalisation Pipeline

This is the most critical dimension. Be exhaustive.

- **Surface bleed:** Trace the field alias resolution path. Can ecommerce fields
  (`sku`, `brand`, `color`, `currency`) appear in job records, or vice versa?
  Check `config/field_mappings.py` — are alias dicts surface-partitioned or global?
- **Schema pollution:** Does any extractor emit fields outside the canonical field
  namespace for that surface? Do unknown fields silently reach `record.data`?
- **Source ranking integrity:** Do stronger sources retain precedence? If the pipeline
  consults multiple sources or candidate sets, is the fallback/ranking logic explicit,
  quality-gated, and owned by the right module rather than a silent merge that lets
  lower-quality evidence pollute stronger records?
- **Hydrated state extraction:** Audit `structured_sources.py` + `js_state_mapper.py`
  for `__NEXT_DATA__`, `__NUXT_DATA__`, `__PRELOADED_STATE__`, `__APOLLO_STATE__`.
  Grade completeness and fallback quality — not just existence.
- **XHR interception:** Does `browser_capture.py` capture and map network payloads?
  Does `network_payload_mapper.py` actually produce canonical fields or just raw blobs?
  Audit mapping completeness for known platforms (Workday, Greenhouse, Lever).
- **Normalisation correctness:** Price (cent-to-dollar, currency stripping), URL
  absolutisation, image URL filtering (CDN vs analytics pixel, spacer/logo exclusion).
  Check `field_value_core.py` and `field_value_*.py`.
- **LLM boundary:** Is LLM used as opt-in normalization layer only? Confirm it cannot
  activate silently. Check `llm_enabled` flag is respected throughout `pipeline/core.py`.
- **Record contract:** Does `CrawlRecordResponse` cleanly expose `data`, `review_bucket`,
  `source_trace` without leaking raw manifest noise or `_`-prefixed internals?

### D5. Traversal Mode

- All traversal modes (`auto`, `single`, `sitemap`, `crawl`) — explicit handling, no
  silent fallthrough. Check `traversal.py` and `_batch_runtime.py`.
- `advanced_mode` (paginate/scroll/load_more) cleanly separated from browser escalation.
  These are different decisions — traversal only runs when settings authorize it (INVARIANT #3).
- Fragment-only URLs (`#section`) and `javascript:` hrefs excluded from pagination loops.
- Same-origin pagination enforced — can traversal escape to off-domain URLs?
- Exceptions during traversal: surfaced and logged, or silently swallowed?

### D6. Resilience & Error Handling

- Bare `except Exception: pass` or `except Exception: continue` — list every one with
  exact file and function. Search: `grep -r "except Exception" backend/app/services`
- LLM failure modes: malformed JSON response, timeout, empty response. Is there a
  fallback that degrades gracefully into `discovered_data` without corrupting `record.data`?
- HTTP 4xx vs 5xx — handled differently, or collapsed?
- `401` must NOT escalate to browser (auth wall). `403`/`429` may escalate. Verify.
- Playwright navigation timeout and context crash — caught, recovered, or deadlock?
- Error log context: does every log call include URL, surface, and extractor stage?
  Or bare `logger.exception(e)` without context?

### D7. Dead Code & Technical Debt

- Functions defined but never called from any live code path (not just untested — unreferenced).
  Use `vulture` output if available, or search for functions with no import in `grep -r`.
- TODO/FIXME/HACK comments — list every one with file and line number.
  Search: `grep -rn "TODO\|FIXME\|HACK" backend/app/services`
- Re-export stubs / compatibility shims kept after migrations. AP-6 violations.
- Private functions (`_foo`) exported or tested as public API.
- Modules tested via private-function imports (AP-7 violations) — these block refactoring.

### D8. Acquisition Mode

- For each acquisition mode (plain HTTP, curl_cffi, Playwright): which sites/surfaces route
  to each mode, and is the routing logic correct?
- Playwright used as blanket fallback (wasting resources) or correctly triggered only
  when JS rendering is required?
- Acquisition code containing extraction logic — hard layer violation.
- Adapter selection: deterministic and config-driven, or URL heuristics in acquisition code?
- Browser identity: `browserforge` fingerprint applied to Playwright contexts? Coherent
  UA + OS combination? Consistent with diagnostics emitted?
- Proxy threading: does `fetch_page` actually thread proxy through curl/http/browser
  attempts, or is `proxy_list` discarded at a boundary?

---

## OUTPUT FORMAT

### Section 0: Delta Table (longitudinal)

```
Preflight:
- Read: ...
- Active plan: ...
- Audit scope emphasis: ...

| Finding ID | Previous Status | Current Status | Evidence |
|------------|----------------|----------------|---------|
| F-001      | [description]  | FIXED/PERSISTS/REGRESSED | file:line |
```

### Section 1–8: Dimension Scores

For each dimension:

```
Dimension: [Name]
Floor: X/10 | Ceiling: X/10 | Score: X.X/10
Previous score: X.X → Change: +X.X / -X.X / unchanged
Reason for change: [one sentence]

Violations:
  [CRITICAL|HIGH|MEDIUM|LOW] [filename.py → function_name (lines X–Y)]:
  Precise violation description.
  INVARIANTS.md clause or ENGINEERING_STRATEGY.md AP-N it breaks.
  Production failure mode it enables.
  Verification: `grep -r "pattern" backend/app/services/`

Verdict: 2–3 sentences. No hedging.
```

### Section 9: Final Summary

```
Overall Score: X.X/10  (previous: X.X, delta: +/-X.X)

Root Cause Findings (architectural — require a plan, not a bug fix):
  RC-1: [description] — affects dimensions D?, D?
  RC-2: ...

Leaf Node Findings (isolated bugs — Codex can fix directly):
  LN-1: [file → function → exact fix]
  LN-2: ...

Genuine Strengths (file-level evidence only, no generic praise):
  [file → function]: what it does well and why
```

### Section 10: Codex-Ready Work Orders

**This section is the handoff artifact. Format each work order for direct Codex execution.**

For each Root Cause finding (RC-N) that has a clear fix:

```
## WORK ORDER RC-N: [Title]

Touches buckets: [list from ENGINEERING_STRATEGY.md]
Risk: CRITICAL | HIGH | MEDIUM
Do NOT touch: [files/modules out of scope]

### What is wrong
[2–3 sentences. Specific files and functions.]

### What to do
[Step-by-step. File names, function names, what to delete, what to move.]
1. [specific action]
2. [specific action]

### Acceptance criteria
- [ ] [specific, testable outcome]
- [ ] `grep -r "pattern_that_should_not_exist" backend/app/services` returns empty
- [ ] `python -m pytest tests -q` exits 0

### What NOT to do
- Do not [specific anti-pattern relevant to this fix]
- Do not [another anti-pattern]
```

For each Leaf Node finding (LN-N):

```
## WORK ORDER LN-N: [Title] (single-session fix)

File: [exact path]
Function: [exact name]
Fix: [1–3 sentences. Precise.]
Test: [exact pytest command or grep to verify]
```

---

## ARCHITECTURAL RECOMMENDATIONS

After the audit, provide up to 5 recommendations. Only include recommendations where:

1. The gap was actually found during this audit (not speculative).
2. The technique is not already present in the codebase (verify before recommending).

For each recommendation:
- Name the technique and which projects use it (Scrapy, Crawlee, Apify, Firecrawl, Diffbot, Zyte).
- Map it to the specific gap found — cite the audit finding by ID.
- Name which source-hierarchy slot it occupies.
- Provide a concrete 5–15 line Python pseudocode sketch.
- State expected yield: which surfaces benefit, which fields are recovered, estimated LLM fallback reduction.

Techniques to evaluate if gaps were found (verify existence before recommending):
- JS-Truth hydrated state interception (`__NEXT_DATA__`, `__PRELOADED_STATE__`, `__APOLLO_STATE__`)
- XHR ghost-routing via Playwright `page.on('response')` for Workday/Taleo/commerce detail JSON
- Accessibility tree expansion (AOM) for collapsed tabs, accordions, "View More" sections
- Declarative path specs (glom / JMESPath) replacing brittle if/else field resolution
- LLM-guided selector synthesis as self-healing fallback (not primary extraction)

---

## AUDIT CONSTRAINTS

- Treat `AGENTS.md` and `INVARIANTS.md` as authoritative intent. Every contradiction is a violation.
- The repo docs define the intended model more precisely than generic crawler intuition. If
  `BUSINESS_LOGIC.md` or the active plan documents an intentional quality-gated fallback or
  ranking path, do not mislabel that behavior as a violation just because it is not strict early exit.
- Generic crawler paths must stay generic. Platform behavior must be adapter-owned or config-driven.
- Do not audit test files for coverage. Audit them only for private-function imports (AP-7).
- Do not suggest adding logging, monitoring, or observability infrastructure.
- Do not recommend techniques already present in the codebase. Verify before recommending.
- If you cannot find a violation in a dimension, write "No violations found" with the grep
  command you used to verify. Do not invent violations to fill the section.
- Scores must reflect actual evidence. Do not lower a score without a new finding.
  Do not raise a score without evidence that a previous finding is fixed.
- The codebase is post-refactor. Do not penalize for problems that were explicitly fixed
  in recent work (see "Known recent implementations" in System Context).
- Every CRITICAL finding must have a corresponding Work Order in Section 10.
  If you cannot write a specific Work Order for a CRITICAL, it is not a CRITICAL.
