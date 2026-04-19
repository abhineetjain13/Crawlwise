You have been given the full backend source of CrawlerAI — a Python/FastAPI web crawling
and data extraction platform. It uses a hybrid acquisition pipeline (curl_cffi default →
Playwright fallback), selectors/domain-memory feedback loops, provenance-aware record
responses, admin-managed LLM runtime/config, and handles primary extraction surfaces such as
ecommerce PDPs/listings and job listings/detail pages.

Pipeline stages: ACQUIRE → EXTRACT → PUBLISH.
Extraction source hierarchy: adapter → XHR/JSON / network payload mapping → JSON-LD /
microdata / Open Graph → hydrated state (e.g. `__NEXT_DATA__`, `__NUXT_DATA__`) → DOM
→ LLM fallback.
Current code is deterministic and source-ordered, with selector self-heal and review /
provenance flows layered around the extraction core.

You are acting as a senior principal engineer conducting a forensic code audit.
Do not summarize what the code does. Do not be diplomatic. Do not praise effort.
Your only job is to find violations, assign honest scores, and surface production risks,
then provide expert improvement recommendations grounded in competitor analysis.

---

## AUDIT DIMENSIONS

Evaluate each dimension below as a deep, file-level audit. For every violation found,
cite the exact filename, function name, and line range. Generic statements like
"error handling could be improved" are unacceptable — name the specific function,
the specific failure mode, and the first-principles rule it violates.

### 1. SOLID / DRY / KISS — Core Software Principles

Deep audit. Penalise hard.

- **SRP:** Does any class or function have more than one reason to change? God classes,
  god functions, functions over 50 lines that do 3+ conceptually distinct things.
- **OCP:** Are new surfaces/adapters added by modification rather than extension?
- **DIP:** Are high-level modules directly importing from low-level concrete modules
  (layer violations)?
- **DRY:** Duplicated logic across files — field resolution, URL normalisation, score
  calculation, retry logic. Exact or near-exact function duplication.
- **KISS:** Indirection, abstraction, or configuration where a direct call or constant
  would suffice. Complexity that solves no real problem.

### 2. Configuration Hygiene — No Site-Specific Hacks

Very important. Penalise any magic buried in logic.

- Hardcoded domain strings, URL fragments, or selector strings inside business logic
  (not in config/constants files).
- Magic numbers (timeouts, retry counts, score thresholds, page limits) scattered inline
  rather than named constants in one place.
- Site-specific conditional branches (`if "amazon" in url`, `if "linkedin"`) inside
  generic pipeline functions — generic crawler paths must stay generic; tenant/site
  hardcodes in shared runtime or extraction code are violations.
- Config values defined in multiple places (env, constants.py, config.py, inline defaults)
  that could contradict each other.
- Per-site overrides that have no corresponding config schema entry — pure hacks.

### 3. Scalability, Maintainability & Resource Management

- Blocking I/O in async code paths. Sync third-party calls and CPU-heavy parsing must not
  block async hot paths.
- Unbounded data structures (lists that grow without cap, caches without eviction).
- Missing connection pool limits or session reuse failures.
- Memory leaks: Playwright browser/context/page objects not closed in `finally` blocks.
- Async tasks or threads spawned without tracking or cancellation.
- Functions or modules so large that a new engineer cannot safely modify them in < 30 min.
- Circular imports or import-time side effects.

### 4. Extraction & Normalisation Pipeline Audit

This is the most critical dimension. Be exhaustive.

- **Surface bleed:** Are ecommerce fields (brand, sku, color, currency, specifications)
  able to appear in job listing records, or vice versa? Trace the field alias resolution
  path. Cross-surface pollution is a contract violation.
- **Schema pollution:** Does any extractor emit fields outside the canonical field
  namespace? Are unknown fields silently passed through to output?
- **Hydrated state extraction:** Is `__NEXT_DATA__` / `window.__PRELOADED_STATE__` /
  `__APOLLO_STATE__` / `__NUXT_DATA__` extraction implemented as a first-class source in
  the hierarchy, or is it incomplete / bolted-on? Audit mapper completeness and fallback
  quality, not just existence.
- **XHR/API interception:** Is Playwright request interception used to capture background
  JSON API calls before DOM rendering completes, and are captured payloads actually mapped
  into canonical fields? Or does the pipeline fall back to raw post-render DOM scraping?
  Audit both interception and mapping completeness.
- **Structured-source coverage:** Microdata and Open Graph support may already exist.
  Audit whether they are first-class, correctly normalised, and actually contribute
  useful candidate data rather than treating them as absent by default.
- **Source ranking integrity:** Does the pipeline enforce first-match-wins with early
  exit / deterministic source ordering, or does it collect from all sources and then
  sort/merge (which allows lower-quality sources to pollute)?
- **LLM boundary:** Is the LLM used as a non-deterministic cleanup layer only, or is it
  being used as a primary field mapper (making output non-deterministic by design)?
  Run-level LLM config and extraction-runtime snapshots must remain stable within a run.
- **Output efficiency:** Are raw HTML blobs, full DOM trees, or large unstripped payloads
  being passed to the LLM unnecessarily? Is HTML minified before prompt construction?
- **Normalisation correctness:** Price normalisation (cent-to-dollar conversion, currency
  symbol stripping), URL absolutisation for relative hrefs, image URL filtering
  (CDN vs analytics pixel).
- **Accessibility tree / hidden content:** Are tabs, accordions, and "View More" sections
  that hide specs/requirements ever programmatically expanded before extraction?
  Or is content silently missed when it is collapsed?
- **Selector self-heal and domain memory:** Audit whether selector self-heal is snapshot-
  stable, bounded, validated before persistence, and clearly partitioned by normalized
  `(domain, surface)`. If this subsystem exists, evaluate it as production code rather
  than flagging it as dead weight by default.
- **Record contract cleanliness:** Audit whether `record.data`, `discovered_data`,
  `review_bucket`, `source_trace`, and provenance/manifest-trace responses preserve the
  clean user-facing contract without leaking raw manifest noise into normal record APIs.

### 5. Traversal Mode Audit

- Are all traversal modes (auto, single, sitemap, crawl) explicitly handled with no
  silent fallthrough?
- Is `advanced_mode` (paginate/scroll/load_more) cleanly separated from browser
  rendering escalation? Or does escalation accidentally trigger
  traversal behavior?
- Are exceptions during traversal surfaced and logged, or silently swallowed?
- Does the traversal layer correctly respect `max_pages`, `max_depth`, and
  domain-boundary constraints, or can it escape into off-domain crawls?
- Are fragment-only URLs (`#section`) and `javascript:` hrefs correctly excluded?

### 6. Resilience & Error Handling

- Functions with bare `except Exception: pass` or `except Exception: continue` — list
  every one.
- Missing retry logic on network I/O that will cause single-request failures to propagate
  as job failures. Rate-limit behavior should still fail fast rather than sleeping through
  free-tier exhaustion.
- LLM API call failure modes: What happens if the LLM returns malformed JSON, times out,
  or returns an empty response? Is there a fallback?
- Are HTTP 4xx vs 5xx responses handled differently, or treated identically?
- Playwright-specific failures (navigation timeout, context crash) — are they caught
  and does the system recover or deadlock?
- Are errors logged with sufficient context (URL, surface, extractor stage) to debug
  in production, or are bare `print()` / `logger.exception(e)` without context?

### 7. Dead Code & Technical Debt Hotspots

- Unreachable code paths (functions defined but never called from any live code path —
  not just untested, but genuinely unreferenced).
- TODO/FIXME/HACK comments — list every one with file and line.
- Commented-out code blocks that have survived more than one refactor cycle.
- Deprecated function wrappers kept "for compatibility" with no active callers.
- Private functions (`_foo`) exported or tested as public API, indicating structural
  instability in the module boundary.
- Modules that are tested via private-function imports — these block structural
  refactoring.

### 8. Acquisition Mode Audit & Site Coverage

- For each acquisition mode (plain HTTP, curl_cffi, Playwright), identify which sites or
  surface types are routed to each mode and whether the routing logic is correct.
- Are anti-bot / JS-rendering requirements correctly detected, or is Playwright used as
  a blanket fallback (wasting resources) or never triggered when needed?
- Is the acquisition layer cleanly separated from the extraction layer, or does
  acquisition code contain extraction logic (hard layer violation)?
- For known platforms (Shopify, Next.js SPAs, Greenhouse, Lever, Workday, Taleo,
  LinkedIn, Dice, Amazon), is adapter selection deterministic and config-driven, or does
  it depend on URL heuristics buried in acquisition code?
- **JS-truth coverage gap:** Which platforms embed `__NEXT_DATA__` or equivalent hydrated
  state that the pipeline currently fails to extract, causing silent partial records?
- **XHR ghost-routing gap:** Which platforms load detail content via background API calls
  (e.g., `/api/v1/jobs/details/{id}`) that the pipeline is not intercepting?
- **Browser identity quality:** If browser identity / fingerprint generation exists,
  audit whether it is coherent, actually applied to Playwright contexts, and consistent
  with the diagnostics and emitted acquisition behavior.

---

## OUTPUT FORMAT

For each dimension:

```
Score: X/10
Violations:
  [CRITICAL / HIGH / MEDIUM / LOW] filename.py → function_name (lines X–Y):
  Precise description. Which first-principles rule or INVARIANTS.md clause it breaks.
  What production failure mode it enables.
Verdict: 2–3 sentences. No hedging.
```

---

## FINAL SUMMARY

```
Overall Score: X/10

Critical Path: Top 5 findings that will cause production failures or data corruption
if left unfixed. Ranked by impact. One sentence each: what breaks, when, and why.

Genuine Strengths: Specific things this system does well, with file-level evidence.
No generic praise. If you cannot find file-level evidence for a strength, do not list it.
```

---

## TOP 5 ARCHITECTURAL RECOMMENDATIONS

Each recommendation must:
1. Name the specific files and functions affected.
2. Describe the current structure and why it is wrong.
3. Describe the target structure concisely (pseudocode or a 3-line sketch is acceptable).
4. Include a code simplification angle — how the refactor reduces total lines of code
   or removes an abstraction layer, not just reorganises it.
5. State the measurable outcome: what bug class disappears, what dimension score improves.

Default bias is deletion and consolidation, not new patterns.
Do not recommend adding new abstractions unless they replace two or more existing ones.

---

## EXTRACTION ENHANCEMENT RECOMMENDATIONS

After the audit, provide 3–5 expert-level improvement recommendations drawn from
competitor analysis and modern scraping best practices. Each recommendation must:

- Name the technique, which competitor crawler engines or open-source projects use it
  (e.g., Scrapy, Crawlee, Apify, Firecrawl, Diffbot, Zyte/Scrapy-Playwright).
- Map it to a specific gap found during the audit — do not recommend techniques that
  are already present in the codebase.
- Reference the relevant source-hierarchy slot (adapter / XHR/JSON / structured sources /
  hydrated state / DOM / LLM) to show where it would slot in.
- Provide a concrete implementation sketch (5–15 lines of Python pseudocode).
- State the expected yield improvement: which surface types benefit, what fields are
  recovered, what the estimated reduction in LLM fallback rate would be.

### Techniques to evaluate (select those that address actual gaps found):

**JS-Truth / Hydrated State Interception**
Target: `__NEXT_DATA__`, `window.__PRELOADED_STATE__`, `__APOLLO_STATE__`, Nuxt hydration.
Slot: hydrated-state source.
Reference: Crawlee's `infiniteScroll` + state capture; Diffbot's structured data layer.

**XHR Ghost-Routing / Playwright Request Interception**
Target: Workday, Taleo, and commerce sites that load detail JSON via background API calls.
Slot: XHR/JSON source (between adapter and JSON-LD).
Reference: Apify's `RequestQueue` + `page.on('response')` pattern; Zyte's HTTP layer.

**Accessibility Tree Expansion (AOM)**
Target: collapsed tabs, accordions, "View More" / "Full Description" patterns on specs
and job requirement sections.
Slot: pre-DOM-parse browser expansion step.
Reference: Playwright `accessibility.snapshot()` + heuristic click expansion.

**Schema Healing via Declarative Path Specs (glom / JMESPath)**
Target: replace brittle `if/else` field resolution chains with a declarative multi-path
spec that tries fallback paths without code branching.
Slot: normalisation step after candidate collection.
Reference: `glom` (Python), JMESPath; used in Diffbot's field normalization layer.

**LLM-Guided Selector Synthesis (Self-Healing Fallback)**
Target: bespoke sites that break every deterministic rule; triggers only when
deterministic confidence falls below threshold.
Slot: LLM fallback (current last resort), but repurposed for selector generation
rather than raw-text extraction.
Reference: Firecrawl's AI selector mode; Zyte's AutoExtract.
Constraint: must not rewrite user-owned crawl controls, and config/persistence ownership
must remain explicit and diagnosable.

Before recommending any technique above, verify whether the repo already implements it
in some form. If it exists, audit completeness, correctness, and integration quality
instead of presenting it as a missing capability.

---

## AUDIT CONSTRAINTS

- You are auditing a post-refactor codebase. Treat `CLAUDE.md` and `INVARIANTS.md`
  as the authoritative intent. Flag every place where the code contradicts these docs.
- Generic crawler paths must stay generic. No tenant/site hardcodes in shared runtime
  or extraction code. Platform behavior should be family-based or adapter-owned.
- Do not audit test files for coverage — audit them only for private-function imports
  that indicate structural instability.
- Do not suggest adding logging, monitoring, or observability infrastructure.
- If you cannot find a violation in a dimension, say "No violations found — [reason]."
  Do not invent violations.
- Your score must reflect the worst violation in the dimension, not an average.
  A single CRITICAL violation caps the dimension at 5/10 or below.
- Enhancement recommendations in the final section must address gaps found in the audit.
  Do not recommend techniques already present in the codebase.
- Be especially careful with recently implemented areas: structured-source expansion
  (microdata / Open Graph / Nuxt revival), network payload specs, browser identity,
  URL tracking-param stripping, selector self-heal, domain memory, provenance APIs,
  selectors API, and LLM admin/config surfaces. These should be audited for quality
  and remaining gaps, not assumed absent.
