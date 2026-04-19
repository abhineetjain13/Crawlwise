# Gemini Audit Remediation Tracker

Purpose: track the current-state review of `docs/audits/gemini-audit.md` and the independent implementation slices used to remediate live issues only.

## Source Documents

- Audit: [docs/audits/gemini-audit.md](../audits/gemini-audit.md)
- Governing strategy: [docs/ENGINEERING_STRATEGY.md](../ENGINEERING_STRATEGY.md)

## Slice Status

| Slice | Title | Status | Notes |
| --- | --- | --- | --- |
| Slice 1 | Acquisition hot-path hardening | completed | Runtime parsing moved off async hot paths; payload read outcomes made explicit. |
| Slice 2 | Traversal and detail interaction safety | completed | Same-origin pagination enforced; transition waits and expansion actionability checks added. |
| Slice 3 | Platform config hygiene | planned | Move runtime family signatures out of generic service code. |
| Slice 4 | Pipeline orchestration split | completed | `_process_single_url` now delegates through typed stage helpers with focused per-URL outcome tests. |
| Slice 5 | Extraction priority and selector safety | completed | Detail record materialization now sorts by explicit source priority; selector self-heal uses DOM-aware HTML reduction. |
| Slice 6 | Operational cleanup and boundaries | completed | Local task lifecycle cleanup, robots tightening, static config export simplification, and record-response shaping moved behind explicit serializers. |

## Audit Matrix

| Finding | Repo status | Action | Slice | Notes |
| --- | --- | --- | --- | --- |
| `pipeline/core.py` monolithic `_process_single_url` | fixed-now | implemented | Slice 4 | `_process_single_url` now uses typed orchestration stages while preserving verdict, persistence, and run-state behavior. |
| `js_state_mapper.py` schema bleed from Greenhouse-specific job mapping | active | implement | Slice 3 | Move platform-specific selectors/specs behind config-owned data. |
| Adapter `_clean_text` duplication | fixed-now | implemented | Slice 6 | ADP, Greenhouse, and iCIMS now reuse the shared field-value text cleaner. |
| Dynamic config module export indirection | fixed-now | implemented | Slice 6 | Static selector and field-mapping exports now load directly without lazy wrapper indirection. |
| Hardcoded endpoint families in `crawl_fetch_runtime.py` | active | implement | Slice 3 | Family signatures belong to platform config, not the interceptor body. |
| Hardcoded `REMIX_GREENHOUSE_SPEC` in generic JS mapper | active | implement | Slice 3 | Replace with config-owned platform-specific lookup. |
| Standard port stripping in `normalize_domain()` | no-op | no-change | none | Current behavior matches normalization intent and does not justify churn. |
| Sync BeautifulSoup parsing in async blocked-page and JS-shell checks | fixed-now | implemented | Slice 1 | Async hot paths now offload parser-heavy checks to worker threads. |
| Sync script parsing on async path via JS-state harvesting | fixed-now | implemented | Slice 1 | Async usage is now thread-offloaded; helper also exposes explicit async wrapper. |
| Payload body reads risk silent failure | fixed-now | implemented | Slice 1 | Read outcomes now distinguish `read`, `too_large`, `response_closed`, and `read_error`. |
| Payload decode failures swallowed too broadly | fixed-now | implemented | Slice 1 | Narrowed to `JSONDecodeError` with explicit diagnostics counters. |
| Candidate priority materialization relies on implicit ordering | fixed-now | implemented | Slice 5 | Detail record materialization now orders candidates by explicit source priority before finalizing field values. |
| Blind detail-expansion clicks | fixed-now | implemented | Slice 2 | Expansion now filters non-actionable handles before click/evaluate fallback. |
| Naive selector self-heal HTML truncation | fixed-now | implemented | Slice 5 | Selector synthesis now removes low-value DOM branches and reduces on subtree boundaries to preserve valid HTML. |
| Pydantic display scrubbing in `CrawlRecordResponse` | fixed-now | implemented | Slice 6 | Display shaping now happens through explicit response serializers while preserving payload behavior. |
| Off-domain pagination leaks | fixed-now | implemented | Slice 2 | Paginate traversal now blocks cross-origin targets before navigation. |
| Pagination click/goto lifecycle races | fixed-now | implemented | Slice 2 | Paginate and load-more traversal now wait for transition settlement before snapshotting. |
| Traversal mode normalization tangle | defer | optional cleanup | Slice 6 | Keep out unless needed while touching traversal/runtime boundaries. |
| Broad browser goto fallback may hide page-closed failures | active | implement | Slice 1 | Improved runtime diagnostics is the first step; deeper navigation handling stays in later slices if needed. |
| robots fetch behavior too broad / operationally weak | fixed-now | implemented | Slice 6 | Fetch internals are narrowed while allowed, disallowed, missing, and failure outcomes remain explicit. |
| `crawl_service.py` local task globals and recovery flow | fixed-now | implemented | Slice 6 | Local task bookkeeping now prunes stale entries and clears task ids consistently across kill and recovery flows. |
| Event publishing TODO in `crawl_state.py` | no-op | no-change | none | No failing behavior or product requirement currently depends on it. |
| `log_for_pytest` production stub | fixed-now | implemented | Slice 6 | Removed the unused production stub from pipeline runtime helpers. |
| Empty `BrowserPool` stub | fixed-now | implemented | Slice 6 | Collapsed to a thin proxy over the real browser runtime operations. |
| Missing declarative specs for XHR-heavy platforms | closed-now | no-change | none | Generic payload specs already exist; further coverage can be additive later. |
| Browser escalation heuristic brittleness | active | monitor/implement | Slice 1 | Thread offloading lands now; heuristic tuning can follow with evidence. |
| Browser identity mismatch claim | no-op | no-change | none | Current `browserforge` wiring is already live; no failing evidence found. |
| Shared HTML helper dedupe | closed-now | no-change | none | `extraction_html_helpers.py` already owns the shared behavior. |
| `__NEXT_DATA__` / Nuxt ecommerce field coverage | closed-now | no-change | none | Covered by existing JS-state mapper tests. |
| extruct microdata / Open Graph support | closed-now | no-change | none | Already live with focused extractor tests. |
| Pre-fetch robots gate | closed-now | no-change | none | Already enforced in `pipeline/core.py`. |

## Maintenance Rule

After each slice lands:

1. Update this tracker’s slice status and the relevant audit rows.
2. Append a dated entry to [CHANGELOG.md](../../CHANGELOG.md).
3. Update canonical architecture docs only if ownership or contracts changed.
