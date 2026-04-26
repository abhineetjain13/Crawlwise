# Master Backend Consolidation and Technical Debt Reduction Plan

**Date:** 2026-04-26
**Status:** IN PROGRESS
**Scope:** backend maintainability, duplicate removal, architecture boundaries, test hardening
**ACTIVE policy:** promoted to `docs/plans/ACTIVE.md` after fingerprint/schema remediation completed.

## Goal

Cut backend growth rate by moving shared behavior to single owners, deleting duplicated heuristics, and preventing new hacks from landing without a boundary owner and tests.

Success means:

- net negative LOC in backend implementation slices
- no selector/token/domain hacks in pipeline, publish, or adapters when a shared owner exists
- orchestration files shrink; domain logic moves to typed helpers
- private test coupling is removed over time
- fixture-backed tests are deterministic and do not silently skip core regressions

## Decisions

| Issue | Decision |
|---|---|
| 1. Detail extractor bloat | A: split variant record normalization into a dedicated owner |
| 2. Listing fragment duplication | A: one shared listing-card scorer/selector owner |
| 3. Pipeline orchestration bloat | A: extract retry, LLM fallback, diagnostics, and failure persistence helpers |
| 4. Runtime settings bloat | A: split init script builders and static fingerprint profiles out of settings |
| 5. Variant/listing contracts | A: public contract tests first, then remove private imports |
| 6. Schema firewall ownership | A: public persisted-data firewall is the only final surface gate |
| 7. Config debt | A: keep thresholds/tokens in `app/services/config/*`, grep before adding |
| 8. Plan activation | B, then promoted after prerequisite fingerprint plan completed |
| 9. Fixture skips | A: convert missing artifact skips to committed minimal fixture corpus |
| 10. Structure guard | A: expand module-size and owner guardrails |
| 11. LLM tests | A: LLM remains explicit gap-fill behind deterministic extraction and firewall |
| 12. Regression tests | A: each consolidation slice keeps behavior tests green |
| 13. Browser runtime phase split | A: split navigation/settle/serialize/finalize helpers later |
| 14. Page evidence object | A: introduce typed evidence object before adding more heuristics |
| 15. Crawl fetch policy | A: split host memory, retry policy, and escalation decision from fetch body |
| 16. Adapter cleanup | A: move shared adapter utilities to one helper owner |

## Completed Slice 1: LOC-Negative Owner Split

Implemented now:

- moved variant record normalization out of `detail_extractor.py` into `extract/variant_record_normalization.py`
- removed listing-local fragment scoring and routed listing/traversal counting through `extract/listing_card_fragments.py`
- moved direct-record LLM fallback out of `pipeline/core.py` into `pipeline/direct_record_fallback.py`
- moved browser diagnostics, screenshot checks, failure persistence, and failure-state helpers into `pipeline/runtime_helpers.py`
- moved empty-extraction browser retry decision into `pipeline/extraction_retry_decision.py`
- moved public persisted-data firewall into `public_record_firewall.py`
- moved tracking URL cleanup into `field_url_normalization.py`
- moved browser init scripts into `config/browser_init_scripts.py`
- moved static fingerprint profiles into `config/browser_fingerprint_profiles.py`
- collapsed JS mapper spacing noise

Measured file-size reductions:

| File | Before | After | Result |
|---|---:|---:|---:|
| `detail_extractor.py` | ~3300 LOC | ~2721 LOC | -579 |
| `pipeline/core.py` | ~1534 LOC | ~1179 LOC | -355 |
| `runtime_settings.py` | ~1617 LOC | ~424 LOC | -1193 |
| `field_value_core.py` | ~1127 LOC | ~962 LOC | -165 |
| `acquisition/traversal.py` | ~2053 LOC | ~1897 LOC | -156 |
| `listing_extractor.py` | ~1530 LOC | ~1466 LOC | -64 |
| `js_state_mapper.py` | ~1154 LOC | ~1114 LOC | -40 |

Hotspot implementation files are substantially negative. Whole-repo net is not yet negative when new owner modules and tests are counted; later slices must delete compatibility aliases, private-test coupling, and duplicate browser/acquisition policy to make the final branch net negative.

Verification passed:

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests -q
```

Result: `939 passed, 10 skipped, 11 warnings`.

Known remaining skips:

- artifact-backed regression tests with missing local fixture directories
- one structured-source optional dependency skip
- one selectolax migration optional dependency skip

## Completed Slice 2: Public Contracts, No Private Imports

Problem:

- tests still import compatibility aliases from private detail/traversal functions
- this makes refactors brittle and keeps internals frozen

Implementation:

- added public names for tested traversal contracts: `click_with_retry`, `locator_still_resolves`, `wait_for_load_more_card_gain`, `looks_like_paginate_control`, and `is_same_origin`
- added public names for tested detail contracts: `variant_option_availability` and `detail_identity_codes_match`
- migrated tests away from private detail/traversal imports
- deleted temporary compatibility aliases for variant normalization and weak listing selector checks

Verify:

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests/services/test_crawl_engine.py tests/services/test_traversal_runtime.py -q
```

Result:

- `rg "from app\.services\.acquisition\.traversal import _|from app\.services\.detail_extractor import _|traversal_module\._|detail_extractor\._" backend/tests -n` returns no matches
- focused verify passed: `39 passed, 11 warnings`

## Remaining Slice 3: Acquisition Policy Boundary

Problem:

- `crawl_fetch_runtime.py` still mixes host memory, escalation, retry, block classification, and fetch body
- this invites one-off protected-site patches

Implementation:

- create or extend existing policy helpers only after grep confirms no owner exists
- split into:
  - host protection memory
  - retry budget and lane sequencing
  - browser escalation decision
  - acquisition result diagnostics assembly
- keep browser runtime focused on page execution only

Verify:

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests/services/test_crawl_fetch_runtime.py tests/services/test_browser_context.py -q
```

Done when:

- `crawl_fetch_runtime.py` is orchestration, not policy storage
- no domain-specific protected-site force rules are added

## Remaining Slice 4: Page Evidence Object

Problem:

- extractability, challenge detection, listing evidence, and detail evidence are passed around as loose diagnostics maps
- this causes repeated key checks and inconsistent retry decisions

Implementation:

- introduce a typed `PageEvidence` object near acquisition/extraction boundary
- populate it once from HTML, browser diagnostics, network payloads, and blocker classification
- make retry/extractability decisions consume this object
- do not move persistence/export behavior into this object

Verify:

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests/services/test_crawl_fetch_runtime.py tests/services/test_pipeline_core.py -q
```

Done when:

- retry/challenge decisions stop re-parsing the same loose dictionaries
- diagnostics remain serializable and stable

## Remaining Slice 5: Fixture Corpus, No Silent Skips

Problem:

- artifact-backed tests skip when local artifacts are absent
- this hides regressions in schema pollution, variant axes, detail retries, and listing extraction

Implementation:

- commit small sanitized fixtures under `backend/tests/fixtures/`
- rewrite artifact tests to use fixtures first
- keep live artifact replay optional, not required for CI determinism

Verify:

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests/services/test_crawl_engine.py -q
```

Done when:

- no core regression test skips because `backend/artifacts/*` is absent
- fixture payloads are small and reviewable

## Remaining Slice 6: Config Guardrails

Problem:

- new thresholds, selectors, tokens, and path markers can still appear in service code

Implementation:

- extend structure tests to flag obvious inline selector/token/path-marker additions in service files
- allow exceptions only for parser-local regexes whose owner is documented
- require new config constants under `app/services/config/*`

Verify:

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests/services/test_structure.py -q
```

Done when:

- structure tests fail on new service-level config debt

## Remaining Slice 7: Browser Runtime Phase Split

Problem:

- browser runtime still owns multiple phases and can grow into another god file

Implementation:

- split low-level phase helpers only where file-size or duplication demands it
- candidate owners:
  - navigation phase
  - settle/readiness phase
  - serialization phase
  - artifact/finalize phase
- keep `SharedBrowserRuntime` as the public facade

Verify:

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests/services/test_browser_context.py tests/test_browser_surface_probe.py -q
```

Done when:

- public runtime API stays stable
- phase code is testable without adding duplicate browser policy

## Remaining Slice 8: Adapter Shared Utilities

Problem:

- adapters risk duplicating URL, variant, and payload helper logic

Implementation:

- grep adapters before adding any helper
- move truly shared adapter utilities into one existing helper owner or a single new owner if no owner exists
- keep platform-specific behavior in adapters

Verify:

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests/services -q
```

Done when:

- no shared helper is copy-pasted across adapters

## Guardrails For All Slices

- delete before adding
- grep before adding
- keep config under `app/services/config/*`
- fix upstream, not publish/export
- LLM remains explicit gap-fill only
- each slice must show LOC movement and verify command result
- do not change frontend during backend consolidation
