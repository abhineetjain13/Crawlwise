# Architecture Invariants

> **Canonical reference.** These MUST be preserved across all changes.
> Violations should be caught in code review before merge.
> See also: `docs/backend-architecture.md` § 12 for architecture-level invariants.

---

## Configuration & Code Hygiene

1. **No magic values in service code.** Shared tunables live in typed config modules imported through `pipeline_config.py`. Do not duplicate them in service code.
2. **Async-safe adapters.** All HTTP calls in async adapter methods MUST use `asyncio.to_thread()` for synchronous libraries (curl_cffi). Blocking the event loop causes visible user-facing latency.
3. **Pipeline config is the single source of truth** for: field aliases, collection keys, DOM patterns, card selectors, block signatures, consent selectors, verdict core fields, normalization rules.
4. **Pipeline boundaries must use typed objects.** `_process_single_url` and its sub-functions return `URLProcessingResult`, not raw tuples. New pipeline config parameters should be added to `URLProcessingConfig`, not as additional positional arguments.
5. **CPU-bound parsing stays off the event loop.** Shared BeautifulSoup parsing in async hot paths must go through the off-thread helpers rather than inline DOM construction.

## Extraction & Field Resolution

6. **Field extraction is first-match, not score-based.** For each field, resolution order is adapter → XHR/JSON payload → JSON-LD → hydrated state → DOM selector defaults → LLM fallback. First valid hit wins.
7. **Verdict based on core fields only.** `_compute_verdict()` determines success/partial based on VERDICT_CORE_FIELDS presence. Requested field coverage is metadata, not a verdict input.
8. **Listing fallback guard.** Listing pages with 0 item records MUST get `listing_detection_failed` verdict. Never fall back to detail-style single-record extraction for listings.
9. **Dynamic field names must pass quality gates.** Single-char keys, JSON-LD type names, day-of-week patterns, and sentence-like labels (5+ underscores) are filtered from `record.data`. Zero-quality candidates are filtered from dynamic/intelligence fields. Candidate rows per field are capped at 5. New noise patterns should be added to config, not hardcoded.
10. **JSON-LD structural keys must not produce candidates.** `@type`, `@context`, `@id`, `@graph` are metadata, not data fields. Network payload noise (geo, tracking, widget APIs) must be filtered by URL pattern before entering the candidate pipeline.

## Record & API Contract

11. **Clean record API responses.** `CrawlRecordResponse.data` strips empty/null values and `_`-prefixed internal keys. `discovered_data` strips raw manifest containers. Users see only populated logical fields.
12. **Review shows only actionable fields.** `discovered_fields` in review payloads excludes container keys and empty-valued fields.

## User Control Ownership

13. **User-owned crawl controls are never rewritten by the backend.** Do not normalize or reclassify `surface`, auto-enable LLM, auto-enable traversal, or auto-switch hidden proxy policy. If the user chose poorly, fail visibly instead of mutating the request.
14. **JS-shell detection may trigger Playwright rendering, not traversal.** Browser escalation is allowed for rendering blocked/empty/JS-shell pages, but pagination, infinite scroll, and load-more remain explicit `advanced_mode` actions only.
15. **Playwright expansion is generic, not field-routed.** No code path may use requested field names to decide what to click before capture; the browser path runs the same interactive expansion pass on every session.

## Acquisition Safety

16. **Preserve usable content over brittle anti-bot heuristics.** Anti-bot signatures should only block when the page actually behaves like a challenge page, not merely because vendor markup exists in otherwise rich HTML.
17. **HTTP pinning must not break TLS identity.** Preserve the original hostname URL whenever using DNS pinning or SSRF hardening.
18. **Acquisition regressions must be diagnosable from artifacts.** Successful phase-1 runs should emit HTML/JSON artifacts plus per-URL diagnostics and smoke-run summaries so failures can be compared across batches without relying on transient logs.
19. **Cookie reuse must be policy-driven.** Do not commit site cookies. Persist only policy-approved cookies via `cookie_policy.json`, and treat challenge/session cookies as ephemeral unless explicitly allowed.
20. **Diagnostics must be observational.** Acquisition diagnostics should report only what actually happened during the fetch/render path; do not fabricate blocker causes, fallback reasons, or retry metadata.

## Runtime & Infrastructure

21. **Database pool must be pre-ping enabled for Postgres.** `pool_pre_ping=True` catches stale connections before use. Engine must be disposed on application shutdown via `dispose_engine()`.
22. **LLM config must be snapshot-stable within a run.** Once a run starts, `llm_config_snapshot` is stamped into `run.settings`. Mid-run config changes must not affect in-flight extraction.
23. **LLM calls must fail fast on rate limits.** No retry/backoff on 429 errors — let the free API tier fail gracefully rather than blocking the pipeline with sleeps. The per-provider circuit breaker handles repeated non-rate-limit failures separately.

## Deletion Policy

24. **Deleted subsystems stay deleted.** Do not reintroduce site memory, selector CRUD, discovery manifests, evidence buckets, or runtime-editable per-domain extraction logic under new names.
25. **Generic crawler paths stay generic.** No tenant/site hardcodes; platform behavior is family-based and minimized to the required families.
