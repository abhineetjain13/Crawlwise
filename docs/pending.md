Architecture-Safe Improvement Plan (No Hacks)
Phase 1 (P0, immediate)
Add “Embedded Source Discovery” as explicit acquisition sub-stage

In ACQUIRE: after primary HTML parse, detect embedded data sources (iframe src, known job/embed endpoints) and enqueue them as child acquisition tasks (bounded and policy-controlled).
Keep parent-child provenance in diagnostics (source_kind, parent_url, embedded_url).
No site hardcoding; use platform-family + generic embedding rules.
Determinize browser-escalation policy

Make curl_needs_browser decision pure and reproducible from stable signals:
content completeness thresholds
surface-aware minimum extractability
explicit anti-bot/challenge signals
Persist decision inputs in diagnostics so repeated runs are explainable.
Contract test set for the two page classes

Add regression fixtures:
cross-origin iframe listing page (lcbhs-style)
complex accordion/tab/dropdown detail page (autotrader-style)
Assert same verdict/path across repeated runs.
Phase 2 (P1, short term)
Acquisition timing ledger (full phase accounting)

Add timings for every wait/retry/backoff bucket so:
sum(phases) ~= acquisition_total_ms
unknown time is near zero.
Include policy sleeps/cooldowns as explicit phases.
State-aware extraction for configured variants

For commerce detail pages with selectable variants/options:
collect both default rendered values and selected-config value tuple from canonical JSON/script sources when present.
Prefer structured state > UI label text for canonical field values.
Cross-origin embedded fetch policy

Introduce safe allowlist policy for embedded host acquisition (public-host validated, bounded depth, bounded count, no credential leakage).
Treat embedded sources as first-class but constrained acquisition units.
Phase 3 (P1/P2, medium term)
Unified source graph in pipeline core

Move from single-html assumption to a source graph:
primary_html
embedded_html[]
xhr_payloads[]
promoted_sources[]
Extraction consumes graph with deterministic source precedence.
Quality arbitration hardening for noisy fields

For title/category/brand/availability/color, add field-level validators + rejectors before canonicalization.
Keep config-driven rules in typed config modules, not service-local literals.
Observability KPIs

Add counters:
embedded_sources_discovered_total
embedded_sources_fetched_total
decision_flip_rate per host (browser escalation instability)
timing_unattributed_ms p95/p99
Bug-Fix Backlog (actionable)
BUG-01: iframe child-source acquisition not guaranteed for cross-origin embeds (P0)
BUG-02: inconsistent browser escalation on identical AutoTrader URL (P0)
BUG-03: incomplete timing attribution in acquisition diagnostics (P1)
BUG-04: variant/state extraction for complex configurators not strongly canonicalized (P1)