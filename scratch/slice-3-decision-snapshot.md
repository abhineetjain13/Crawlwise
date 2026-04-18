# Slice 3 Decision Snapshot

Traceability log for the 21 acquisition branches called out in Batch C before consolidation. Each row maps the old branch to an `AcquisitionPlan` field or an explicit deletion.

| # | Source | Previous decision logic | Plan mapping / disposition |
|---|---|---|---|
| 1 | `policy.py:225` | Missing-data browser escalation only ran for recognized surfaces | `allow_browser_escalation` |
| 2 | `policy.py:239` | Strong listing signals suppressed listing browser escalation | `browser_escalation_reasons` with listing safeguard |
| 3 | `policy.py:254` | Detail JS shells with requested fields forced browser | `page_type` + `allow_browser_escalation` |
| 4 | `policy.py:276` | Structured data overrode browser fallback on non-detail pages | `page_type` branch inside `browser_escalation_decision()` |
| 5 | `policy.py:341` | Ecommerce listing payload expected `listing_completeness` | `diagnostic_payload_kind` |
| 6 | `policy.py:343` | Ecommerce detail payload expected `variant_completeness` | `diagnostic_payload_kind` |
| 7 | `policy.py:374` | Detail surfaces disabled traversal | `traversal_enabled` |
| 8 | `policy.py:380` | Job surfaces used job card selectors, else commerce selectors | `traversal_card_selectors` |
| 9 | `policy.py:487` | Listing surfaces used the low-value browser retry profile | `retry_profile` |
| 10 | `policy.py:617` | Commerce diagnostics aborted unless surface was ecommerce | Deleted into generic surface diagnostic profile |
| 11 | `policy.py:688` | Job diagnostics aborted unless surface was job | Deleted into generic surface diagnostic profile |
| 12 | `browser_readiness.py:24` | `_is_listing_surface()` alias wrapped the listing suffix check | Deleted; replaced by `plan.readiness_profile` |
| 13 | `browser_readiness.py:83` | Listing readiness returned early for non-listing surfaces | Deleted; consumer passes listing plans only |
| 14 | `browser_readiness.py:86` | Listing readiness selectors split job vs commerce | `readiness_selectors` |
| 15 | `browser_readiness.py:275` | Job detail readiness used title/company/salary selectors | `readiness_selectors` |
| 16 | `browser_readiness.py:281` | Ecommerce detail readiness used title/price/sku selectors | `readiness_selectors` |
| 17 | `browser_client.py:830` | Browser readiness split listing vs detail waits | `readiness_profile` |
| 18 | `traversal.py:899` | Traversal resolved a surface policy object from surface at entry | `AcquisitionPlan` passed in directly |
| 19 | `traversal.py:977` | Targeted fragment capture only ran for listing surfaces | `plan.is_listing_surface` + `traversal_card_selectors` |
| 20 | `recovery.py:42` | Blocked recovery only ran for listing surfaces | `adapter_recovery_enabled` |
| 21 | `registry.py:91` | Adapter recovery aborted for unrecognized surfaces | Deleted; replaced by `adapter_recovery_enabled` gate |

Accidental branches deleted directly in this slice: `policy.py:617`, `policy.py:688`, `browser_readiness.py:24`, `browser_readiness.py:83`, `registry.py:91`, `listing_helpers.py:36`.
