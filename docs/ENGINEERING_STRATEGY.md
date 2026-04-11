# CrawlerAI: Project Health Audit & Engineering Strategy

> **Created:** 2026-04-11
> **Based on:** Codebase audit of 38,918 LOC across 127 Python files, 41 commits, and current test suite health.

---

## Diagnosis: Why Every Day Feels Like Firefighting

This isn't a tools problem. It's a **structural complexity** problem that has compounded over ~40 commits.

### The Numbers

| Metric | Value | Healthy Target |
|--------|-------|---------------|
| Total backend Python LOC | 38,918 | — |
| Largest file (`extract/service.py`) | 4,697 lines | < 500 |
| 2nd largest (`listing_extractor.py`) | 2,989 lines | < 500 |
| 3rd largest (`acquirer.py`) | 2,362 lines | < 500 |
| 4th largest (`browser_client.py`) | 2,329 lines | < 500 |
| Test-to-code ratio | 43% | > 80% |
| Failing tests right now | 11 + 1 error | 0 |
| Collection errors (broken imports) | 2 files | 0 |
| Commit messages that say "bug fixes" | 10 of 41 (24%) | 0% |
| CLAUDE.md lines (before cleanup) | 402 | < 150 |

### Root Cause Loop

```
God Files (4 files > 2000 LOC, 32% of backend)
  → Hard to reason about changes
    → Every edit has blast radius across concerns
      → Bugs in unrelated features
        → Firefighting cycle

No pre-commit gates
  → Broken tests merge to main
    → Test suite unreliable
      → Changes ship untested → more bugs

Vague commits ("bug fixes")
  → Can't bisect regressions
    → More firefighting
```

**The core loop:** 4 god files (service.py, listing_extractor.py, acquirer.py, browser_client.py) collectively hold 12,377 lines — 32% of the entire backend — in just 4 files. Every change to extraction, acquisition, or browser logic touches these files, and because they're enormous, it's nearly impossible to hold the full context in one session (human or AI). Bugs ripple across concerns that should be isolated.

---

## Phase 1: Immediate Stabilization (This Week)

> Don't add features until these are done. Every hour spent here saves 5 hours of firefighting next week.

### 1.1 Fix or Quarantine All Broken Tests

Current state: **11 failed, 1 error, 2 collection errors**. A test suite you can't trust is worse than no tests.

```powershell
# Step 1: Fix the 2 collection errors (broken imports)
# tests/e2e/test_smoke_crawl.py
# tests/services/test_batch_runtime_summary_merge.py

# Step 2: For each of the 11 failures, either:
#   a) Fix the test (if it reveals a real bug)
#   b) Mark as xfail with a ticket reference (if it's a stale test)
#   c) Delete it (if it tests removed functionality)

# Step 3: Make green suite the law
pytest tests -q --tb=short  # Must pass with 0 failures
```

### 1.2 Add a Pre-Commit Gate

```powershell
# pre-commit-check.ps1
$env:PYTHONPATH='.'
Write-Host "Running linter..."
ruff check backend/app --select E,W,F --quiet
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host "Running tests..."
pytest tests --ignore=tests/e2e -q --tb=line -x
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host "All checks passed"
```

### 1.3 Enforce Commit Conventions

**Stop committing as "bug fixes".** Every commit message should answer: *what changed* and *why*.

| Bad | Good |
|-----|------|
| `bug fixes` | `fix(extract): prevent variant axis pollution from JSON-LD @type keys` |
| `bug fixes and improvements` | `feat(traversal): add infinite-scroll detection to abort false pagination` |
| `improvements` | `refactor(acquirer): extract DNS resolution into url_safety module` |

Format: `type(scope): imperative description`

Types: `fix`, `feat`, `refactor`, `test`, `docs`, `chore`

### 1.4 Fix the `\d` SyntaxWarning in traversal.py

This warning fires on every test run and every import. 10-second fix that eliminates noise from every log. Change the JS string at line 122 to use `\\d` or a raw string.

---

## Phase 2: Structural Debt Reduction (Next 2 Weeks)

### 2.1 Decompose the God Files

This is the single highest-leverage change. Each file should be split into focused modules under 500 lines.

#### `extract/service.py` (4,697 lines) → 6-8 modules

```
extract/
├── service.py              # Public API: extract_candidates(), ~200 lines
├── candidate_collection.py # _collect_*_candidates(), ~400 lines
├── candidate_finalization.py # _finalize_candidates(), ~400 lines
├── variant_resolution.py   # Variant merging, axis detection, ~400 lines
├── field_sanitization.py   # _sanitize_detail_field_value(), noise filters, ~300 lines
├── dynamic_fields.py       # Dynamic field name validation, intelligence rows, ~300 lines
├── structured_source.py    # _structured_source_candidates(), deep-get, ~400 lines
├── dom_extraction.py       # DOM selector candidates, label-value, ~400 lines
└── coercion.py             # coerce_field_candidate_value(), normalization, ~400 lines
```

#### `listing_extractor.py` (2,989 lines) → 4-5 modules

```
extract/listing/
├── __init__.py             # Public API: extract_listing_records()
├── structured_sources.py   # JSON-LD, Next.js, hydrated state extraction
├── dom_cards.py            # Card detection, scoring, auto-detect
├── record_merge.py         # Record deduplication, identity keys
└── field_enrichment.py     # Buy-box, image, spec extraction
```

#### `acquirer.py` (2,362 lines) and `browser_client.py` (2,329 lines)

```
acquisition/
├── acquirer.py             # Public API: acquire(), ~300 lines  
├── http_client.py          # curl_cffi logic (exists)
├── browser_client.py       # Playwright launch + context, ~500 lines
├── browser_expansion.py    # expand_all_interactive_elements(), consent, ~400 lines
├── browser_network.py      # XHR interception, response capture, ~300 lines
├── traversal.py            # Pagination/scroll/load-more (exists)
├── strategies.py           # Strategy chain (exists)
└── session_context.py      # Session affinity (exists)
```

**How to decompose safely:** Extract one function cluster at a time. Move functions, update imports, run full test suite. One PR per module extraction. Never batch 3 extractions into one commit.

### 2.2 CLAUDE.md Cleanup — DONE ✅

Slimmed from 402 lines → ~95 lines. Content moved to:
- `docs/INVARIANTS.md` — all 25 architecture invariants
- `docs/backend-architecture.md` — already had detailed architecture
- Added `Agent Rules` section to CLAUDE.md

---

## Phase 3: Testing Strategy (Ongoing)

### 3.1 Regression Fixtures from Smoke Artifacts

You already have `artifacts/diagnostics/` and `artifacts/html/` from real crawl runs. These are gold for regression testing. Currently they rot on disk.

**Pattern:**
```python
# tests/fixtures/puma_detail.py
PUMA_DETAIL_HTML = (Path(__file__).parent / "html" / "puma_detail.html").read_text()
PUMA_DETAIL_EXPECTED = {
    "title": "PUMA x HYROX Men's Cut-Off Tank",
    "brand": "PUMA",
    "variants": [...]  # Expected variant structure
}
```

```python
# tests/services/extract/test_puma_regression.py
def test_puma_detail_extracts_variants():
    result = extract_candidates(PUMA_DETAIL_HTML, ...)
    assert "variants" in result
    assert len(result["variants"]) > 0
```

**Rule of thumb:** Every bug you fix should add a regression test with real HTML from the site that triggered it.

### 3.2 Property-Based Tests for Normalizers

Normalizers (`normalizers/__init__.py`, 1,079 lines) are pure functions — perfect for Hypothesis:

```python
from hypothesis import given, strategies as st

@given(st.text(min_size=1, max_size=200))
def test_normalize_price_never_crashes(raw_price):
    result = normalize_price(raw_price)
    assert result is None or isinstance(result, str)
```

### 3.3 Extraction Contract Tests

For every field in `_STRUCTURED_CANONICAL_ATTRIBUTE_KEYS`:

```python
@pytest.mark.parametrize("field", [
    "variants", "price", "title", "brand", "availability",
    "color", "size", "sku", "image_url", "description"
])
def test_field_extraction_from_json_ld_product(field):
    html = build_json_ld_product_html(...)
    result = extract_candidates(html, ...)
    assert field in result
```

---

## Phase 4: Agent Workflow Improvements

### 4.1 Session Scoping

One session = one concern.

| Current | Better |
|---------|--------|
| "audit the variant feature and fix polluted data and missing variants" | Session 1: "Audit variant output for Puma — show me what's wrong" |
| | Session 2: "Fix the JSON-LD variant parser to capture hasVariant arrays" |
| | Session 3: "Add regression test for Puma variant extraction" |

### 4.2 Mandatory Verification Step

Added to CLAUDE.md:
- Before editing any file > 500 lines, verify changes with `git diff` after editing.
- Every code change session must end with: run affected tests, show results.
- Never batch more than 3 file edits in one session without verification.

### 4.3 Task Artifacts

Before starting any multi-step task, create a task artifact:

```markdown
# Task: Fix Variant Extraction for Non-Shopify Sites

## Problem
Variants not captured for PUMA. Polluted data in output schema.

## Diagnosis
- [ ] Check what sources PUMA's variant data comes from
- [ ] Check what _normalized_variant_rows_payload does with the input
- [ ] Check if coerce_field_candidate_value("variants", ...) is stripping data

## Fix Plan
- [ ] Step 1: ...
- [ ] Step 2: ...

## Verification
- [ ] Re-run extraction smoke on Puma URL
- [ ] Compare before/after variant output
- [ ] Run pytest tests/services/extract/ -q
```

---

## Phase 5: Observability

### 5.1 Structured Field-Level Extraction Logging

Add structured logging to the extraction pipeline:

```python
# In _collect_candidates, after each source strategy:
logger.debug(
    "[EXTRACT] field=%s source=%s candidates=%d values=%s",
    field_name, source_label, len(rows), 
    [str(r.get("value"))[:50] for r in rows[-3:]]
)

# In _finalize_candidates, for the winner:
logger.info(
    "[EXTRACT] field=%s winner_source=%s value_preview=%s rejected=%d",
    field_name, winner.get("source"), str(winner.get("value"))[:80],
    len(all_candidates) - 1
)
```

This turns debugging from "why is this empty?" into `grep EXTRACT | grep variants`.

### 5.2 Extraction Audit Report

Create a diagnostic mode that outputs a per-field audit trail — what sources were tried, what each returned, why the winner was chosen, why losers were rejected. Invaluable for the "it works for site A but not site B" pattern.

---

## Phase 6: Release Discipline

### 6.1 Single Backlog

Consolidate to GitHub Issues. Each issue gets:
- Clear title (not "bug fixes")
- Reproduction steps or failing test
- Affected module/file
- Priority label: `P0-blocker`, `P1-important`, `P2-nice-to-have`

### 6.2 Weekly Stabilization Ritual (2 hours every Monday)

1. **Run full test suite** — any new failures? Fix or quarantine.
2. **Run smoke tests** — `run_acquire_smoke.py` and `run_extraction_smoke.py` on 5 representative sites.
3. **Review `git log --oneline` from past week** — are commits atomic and descriptive?
4. **Check file sizes** — has any file crossed 600 lines? Plan decomposition.
5. **Trim CLAUDE.md** — remove anything that's now documented in code.

---

## Priority Order

| Priority | Task | Effort | Impact |
|----------|------|--------|--------|
| **P0** | Fix/quarantine 11 broken tests | 2-3 hours | Unlocks reliable testing |
| **P0** | Add pre-commit check script | 30 min | Prevents future regressions |
| **P0** | Fix `\d` SyntaxWarning | 10 sec | Eliminates log noise |
| **P1** | Split `extract/service.py` | 2-3 days | Reduces blast radius of extraction changes |
| **P1** | Split `listing_extractor.py` | 1-2 days | Isolates listing concerns |
| **P1** | ~~Slim CLAUDE.md~~ | ~~1 hour~~ | ✅ Done |
| **P2** | Add 5 regression test fixtures from smoke HTML | 1 day | Catches extraction regressions per-site |
| **P2** | Add extraction field audit logging | 2 hours | Makes "missing field" debugging instant |
| **P2** | Enforce commit conventions | Ongoing | Makes git log useful for debugging |
| **P3** | Split `acquirer.py` + `browser_client.py` | 2 days | Isolates acquisition concerns |
| **P3** | Property-based tests for normalizers | 1 day | Catches edge cases in pure functions |

---

## Quick Wins You Can Do Today

1. **Fix the `\d` warning** — 10 seconds, eliminates noise from every log
2. **Add `pytest.ini`** with `testpaths = tests` and `addopts = --ignore=tests/e2e -q --tb=short`
3. **Alias pre-commit check**: `Set-Alias precheck ".\pre-commit-check.ps1"` in PowerShell profile
4. **Start using commit conventions** — costs nothing, compounds value over time
