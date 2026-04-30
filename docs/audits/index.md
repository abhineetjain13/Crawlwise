# Backend Technical Debt Audit Index

## Audit Files

| File | Status | Buckets | Key LOC Savings |
|------|--------|---------|----------------|
| `acquisition_audit.md` | Complete (13 findings) | acquisition | ~2,015 |
| `extraction_audit.md` | Complete (14 findings) | extraction, pipeline | ~389 + boundary fixes |
| `adapters_config_audit.md` | Complete (7 findings) | adapters, config | ~159 + lazy imports |
| `remaining_services_config_audit.md` | Complete (12 findings) | remaining services, config | ~393 |
| `test_audit.md` | Complete (18 findings) | tests | ~576 |

## Remediation Status

2026-04-29: Active P0/P1 findings were remediated under `docs/plans/v6-crawl-quality-remediation-plan.md` Slice 6/7.

- Fixed: cross-bucket private imports from `extraction_runtime.py`.
- Fixed: lazy adapter registry imports and adapter result boilerplate.
- Fixed: dashboard reset boilerplate.
- Fixed: generic platform URL tokens moved to config.
- Fixed: generic extraction/acquisition constants in `runtime.py`, `traversal.py`, `field_value_core.py`, `detail_extractor.py`, `listing_extractor.py`, `field_value_dom.py`, `selectors_runtime.py`, `selector_self_heal.py`, `xpath_service.py`, `record_export_service.py`, and `js_state_mapper.py`.
- Fixed: `PRODUCT_FIELD_SPEC` / `_VARIANT_FIELD_SPEC` moved to config-owned field mappings.
- Fixed: Oracle HCM adapter regex/facet constants moved to config.
- Fixed: browser accessibility snapshot timeout moved to runtime config.
- Fixed: browser fingerprint clone boilerplate deduplicated.
- Fixed: overlapping detail DOM-completion guard removed.
- Fixed: pipeline run-param resolver extracted.
- Fixed: stale active-bug wording removed from `INVARIANTS.md`.
- Fixed: runtime settings validator boilerplate collapsed into helper checks.
- Fixed: test helper extraction for fetch context, page fetch result, test run creation, fake acquire result, and browser fingerprint mocks.
- Fixed: direct runtime settings mutation in tests; `patch_settings` fixture now covers listed cases.
- Fixed: low-value/private-import test findings listed in test audit.
- Fixed: duplicated artifact text loader in tests.
- Fixed: thin wrappers deleted from `crawl_fetch_runtime.py`, `browser_detail.py`, `browser_identity.py`.
- Fixed: dead init-script re-exports removed from `runtime_settings.py`.
- Fixed: `_JSON_LIST_KEYS` moved to config from `extraction_runtime.py`.
- Guarded: private service import allowlist, service config-constant allowlist, and LOC budgets in `backend/tests/services/test_structure.py`.
- Remaining lower-priority debt: browser pool/lifecycle split and adapter-specific HTTP mock cleanup.

## Master Action Priority

| Priority | Item | Estimated Impact |
|----------|------|-----------------|
| DONE | Delete thin wrappers (`crawl_fetch_runtime.py`, `browser_detail.py`, `browser_identity.py`) | ~395 LOC, zero risk |
| DONE | Move inline constants from `runtime.py` to `config/` | ~50 LOC + prevents future duplication |
| DONE | Resolve cross-bucket private imports (E5) | Architectural boundary fix |
| PARTIAL | Split `browser_runtime.py` into 3 files | Proxy config + diagnostics + stage runner moved out; pool/lifecycle split remains |
| DONE | Extract `_safely_clone_fingerprint` in `browser_identity.py` | ~35 LOC + prevents drift |
| DONE | Move `PRODUCT_FIELD_SPEC` + `_VARIANT_FIELD_SPEC` to config | ~135 LOC moved, prevents drift |
| DONE | Merge repetitive reset boilerplate in `dashboard_service.py` | ~100 LOC |
| DONE | Move token/regex frozensets from `shared_variant_logic.py` to config | ~60 LOC |
| DONE | Move `_LISTING_FIELD_SELECTORS` from `selectors_runtime.py` to config | ~35 LOC |
| DONE | Merge overlapping guards in `detail_extractor.py` | ~5 LOC |
| DONE | Update `INVARIANTS.md` stale bugs | Doc hygiene |
| DONE | Switch `registry.py` to lazy adapter imports | Faster cold start |
| DONE | Add `BaseAdapter._result()` + `_dispatch()` helpers | ~80 LOC across 20 adapters |
| DONE | Move Oracle HCM adapter config into `config/extraction_rules.py` | ~10 LOC + config placement |
| DONE | Simplify `runtime_settings.py` validator boilerplate | ~60 LOC |
| DONE | Extract `_create_test_run` helper for pipeline tests | ~150 LOC, 7 files |
| DONE | Extract `_default_fetch_context` + `_page_fetch_result` in `test_crawl_fetch_runtime.py` | ~130 LOC |
| DONE | Extract `_make_fingerprint` in `test_browser_context.py` | ~100 LOC |
| DONE | Extract `_fake_acquire_result` + `_no_adapter` in `test_pipeline_core.py` | ~75 LOC |
| PARTIAL | Centralize `_read_optional_artifact_text` + `_FakeResponse` in `tests/fixtures/` | Artifact loader + reusable HTTP mocks done; adapter-specific mocks remain local |

## Total Estimated Savings

| Category | LOC Savings |
|----------|-------------|
| Acquisition | ~2,015 |
| Extraction + Pipeline | ~389 |
| Adapters + Config | ~159 |
| Remaining Services + Config | ~393 |
| Tests | ~576 |
| **Total** | **~3,532** |
