# Job Platform Fix Review

Date: 2026-04-19
Scope: current local diff related to job-platform extraction fixes and adjacent runtime/config changes
Mode: Architecture review in progress

## Open Decisions

### Issue 1
- Title: Adapter layer now owns transport recovery
- Status: completed
- Selected option: A
- Outcome: moved JSON-specific request semantics into `acquisition/http_client.py` via `expect_json`, removed adapter-local recovery logic from `BaseAdapter`

### Issue 2
- Title: Readiness config is split across multiple owners
- Status: completed
- Selected option: A
- Outcome: consolidated readiness selectors and wait values into `platforms.json`, removed `platform_readiness.json` and its loader module

### Issue 3
- Title: Atlas recovery duplicates extraction passes instead of fixing the owner
- Status: completed
- Selected option: A
- Outcome: fixed the cleanup owner by narrowing `NOISE_CONTAINER_REMOVAL_SELECTOR`, removed cookie-noise heuristics and the raw-DOM second extraction pass

## Deferred

- None in this pass

## Notes

- The working tree is dirty outside this patch set, so the review distinguishes direct findings from broader diff hygiene where possible.
- Code quality follow-up applied:
  - extracted duplicated localized-path parsing in `workday.py`
  - replaced opaque inline UltiPro search-filter literals with named module constants
- Test follow-up applied:
  - added coverage for acquisition-layer JSON parsing on wrapped payloads
  - added coverage for readiness overrides sourced from `platforms.json`
- Performance follow-up applied:
  - collapsed readiness waiting to one combined selector wait instead of sequential waits
