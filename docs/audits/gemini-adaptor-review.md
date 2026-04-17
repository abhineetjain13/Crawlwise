
Phase 4 Duplication Review
Scope
Target slice or concern: Adapter and platform strategy duplication
Files reviewed: app/services/adapters/*.py, app/services/adapters/base.py, app/services/platform_policy.py, platforms.json
Duplicate cluster being reviewed: Platform fingerprinting and domain routing rules.
Executive Decision
Verdict: MINOR DUPLICATION
Primary reason: The primary architectural move to centralize platform-family routing behind _matches_platform_family is successfully complete. However, stale domains arrays were left behind as dead code in the job adapter classes, duplicating the configurations now exclusively owned by platforms.json.
Is canonical-home action required now? YES
Duplication Findings
Cluster 1
Severity: low
Rule or helper: Hardcoded domains lists in family-aware adapter classes.
Files involved: adp.py, icims.py, jibe.py, oracle_hcm.py, paycom.py, saashr.py, indeed.py, linkedin.py, greenhouse.py, remotive.py, remoteok.py, base.py.
Why this is real duplication: These adapters now correctly delegate their can_handle() routing to self._matches_platform_family(url, html), which reads domain patterns dynamically from platforms.json. The class-level domains = [...] attributes are no longer read by the registry or the adapters themselves, resulting in stale duplicated state.
Why it is harmful or acceptable: Harmful because future updates to ATS domain rules in platforms.json will leave the adapter classes out of sync, causing confusion for maintainers about where routing is actually defined.
Canonical home: platforms.json (via app.services.platform_policy).
Action: delete
What must not be generalized: Do not delete the domains arrays from the commerce adapters (amazon.py, ebay.py, walmart.py, shopify.py), as they still actively rely on them for their local can_handle() routing logic.Cluster 2
Severity: low
Rule or helper: Commerce adapter manual routing heuristics.
Files involved: shopify.py, amazon.py, ebay.py, walmart.py.
Why this is real duplication: These adapters manually inspect domains and HTML tokens in can_handle() instead of delegating to the central platform registry.
Why it is harmful or acceptable: Acceptable. This deliberately respects Invariant 29 (generic paths stay generic; platform behavior minimized to required families). Commerce platforms do not currently require complex, cross-stage browser fallback or pacing policies, so centralizing them into platforms.json would violate the boundary by bloating the core registry unnecessarily.
Canonical home: The respective adapter classes.
Action: keep as-is
What must not be generalized: Do not force these commerce adapters into the central platform family detector.
Canonical-Home Table
Rule/helper: ATS / Job Board Domain Routing
Chosen home: platforms.json (consumed via app.services.platform_policy)
Why this owner is correct: Complex job boards require coordinated acquisition strategies (e.g., browser-first rendering, readiness evaluations). Centralizing their domains allows the acquisition layer to apply policies before the adapter is instantiated.
Files that should stop owning it: app/services/adapters/adp.py, greenhouse.py, icims.py, indeed.py, jibe.py, linkedin.py, oracle_hcm.py, paycom.py, remoteok.py, remotive.py, saashr.py, and base.py (which should drop the empty default array).
Refactor Guardrails
Duplication that should wait until a later slice: N/A.
Duplication that must be resolved before implementation: Deletion of the stale domains attributes in family-aware adapters to cleanly finalize the current deduplication slice.
Anti-patterns to avoid during cleanup: Do not remove extraction-specific URL parsing (e.g., saashr.py matching /ta/([^/?#]+)\.careers) or narrowing constraints (e.g., linkedin.py checking "/jobs/" after the family match) from the adapters. These represent internal extraction safety checks, not global platform routing.
Final Recommendation
CONSOLIDATE IN CURRENT SLICE
Reason:
The heavy lifting of centralizing the detector is already complete. Deleting the leftover domains properties requires minimal effort, prevents future state-sync confusion, and fully closes out the "Adapter and platform strategy deduplication" track cleanly.