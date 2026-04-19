# Invariants

These rules are the backend contract. Refactors may change structure, not these outcomes.

## 1. User control ownership

1. User-selected crawl controls are authoritative. Do not silently rewrite `surface`, traversal intent, `proxy_list`, or `llm_enabled`.
2. Surface remains explicit and user-owned even when heuristics or adapters suggest something else.
3. Browser rendering escalation and traversal authorization are separate decisions. Rendering may escalate automatically; traversal only runs when settings allow it.

## 2. Acquisition and runtime

4. Acquisition returns observational facts only: URL, final URL, status, method, headers, blocked state, network/browser diagnostics, and artifacts. Do not fabricate blocker causes or hidden retries.
5. Preserve usable content over brittle anti-bot heuristics. Vendor markers alone are not enough to classify a page as blocked.
6. Respect safety and policy boundaries: SSRF/public-target checks, robots handling when enabled, and policy-driven cookie reuse.
7. Shared runtime behavior must remain config-driven. Tunables belong in `app/services/config/*`, not hardcoded service constants.

## 3. Extraction and records

8. Listing and detail extraction stay separate. Listing pages do not fall back into synthetic single-record detail behavior.
9. A listing run with zero records produces `listing_detection_failed`, not a false success.
10. Persisted `record.data` contains only populated logical fields. Empty values, `_` internals, and raw manifest containers do not belong in the user-facing payload.
11. `source_trace` and `discovered_data` must preserve provenance and reviewable metadata without leaking obsolete raw-container noise into normal API responses.
12. Commerce/job extraction must filter page chrome and metadata noise before persistence.

## 4. Selectors, review, and memory

13. Domain memory is scoped by normalized `(domain, surface)`. Generic fallback may supplement a surface-specific rule set, not override the scoping model.
14. Selector CRUD, review saves, and selector self-heal may improve future extraction, but they must remain explicit, diagnosable flows.
15. Automatically synthesized selectors must be validated before they are saved or reused.

## 5. LLM and snapshots

16. LLM use is opt-in at run time through settings and active config. It must not silently activate itself.
17. Run snapshots are stable within a run. `llm_config_snapshot` and `extraction_runtime_snapshot` should prevent mid-run config drift.
18. LLM failures should degrade gracefully and remain visible in diagnostics rather than corrupting extraction state.

## 6. Codebase shape

19. Generic crawler paths stay generic. Do not hardcode tenant- or site-specific behavior in shared runtime or extraction code.
20. Pipeline boundaries should use typed objects and explicit contracts rather than growing positional argument sprawl.
21. CPU-bound parsing and sync third-party calls must not block async hot paths.
22. If a rule is important enough to preserve, it should have a clear owning test.
