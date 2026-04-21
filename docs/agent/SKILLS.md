# Agent Skills — CrawlerAI

Look up the relevant skill before starting a task. Follow it exactly.
Skills use real file paths. If something has moved, check `docs/CODEBASE_MAP.md` and update this file.

---

## SKILL: Run Tests

```powershell
cd backend
$env:PYTHONPATH='.'

# Full suite
.\.venv\Scripts\python.exe -m pytest tests -q

# By subsystem
.\.venv\Scripts\python.exe -m pytest tests/services/test_crawl_engine.py -q          # extraction
.\.venv\Scripts\python.exe -m pytest tests/services/test_crawl_fetch_runtime.py -q   # fetch/runtime
.\.venv\Scripts\python.exe -m pytest tests/services/test_selector_pipeline_integration.py -q
.\.venv\Scripts\python.exe -m pytest tests/services/test_selectors_api.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_harness_support.py -q

# Smoke runners (against real URLs, use sparingly)
.\.venv\Scripts\python.exe run_acquire_smoke.py commerce
.\.venv\Scripts\python.exe run_extraction_smoke.py
.\.venv\Scripts\python.exe run_test_sites_acceptance.py
```

---

## SKILL: Fix an Extraction Bug

1. Write a failing test first if possible (in `tests/services/test_crawl_engine.py` or surface-specific file).
2. Trace the field's source — which of these produces the bad value?
   - Structured source: `structured_sources.py`
   - Platform adapter: `adapters/[platform].py`
   - JS state: `js_state_mapper.py`
   - Network payload: `network_payload_mapper.py` + `config/network_payload_specs.py`
   - DOM selector: `detail_extractor.py` or `listing_extractor.py`
   - Field alias: `config/field_mappings.py`
   - Normalization: `field_value_core.py` or `field_value_*.py`
3. Fix it at the **earliest** point in that chain. Do not add a fallback downstream.
4. Run: `pytest tests/services/test_crawl_engine.py -q`
5. Run: `pytest tests -q` to check for regressions.
6. Update the plan slice.

**Never fix extraction bugs in:** `pipeline/core.py`, `publish/verdict.py`, `publish/metrics.py`.
These are downstream of extraction and must not compensate for upstream failures.

---

## SKILL: Add a New Extraction Field

1. Identify the surface: `ecommerce_detail | ecommerce_listing | job_detail | job_listing | automobile_listing | automobile_detail | tabular`
2. Add the field alias to `services/config/field_mappings.py` — in the surface-specific section. **One place, always.**
3. Add field eligibility to `services/field_policy.py:canonical_fields_for_surface()` if it should appear in user-facing output.
4. Add extraction logic in the right file:
   - Structured source field → `structured_sources.py`
   - DOM field on detail page → `detail_extractor.py`
   - DOM field on listing page → `listing_extractor.py`
   - Platform-specific → `adapters/[platform].py`
5. Add normalization to `field_value_core.py` if coercion is needed (price, URL, date, image).
6. Add a focused test in `tests/services/test_crawl_engine.py` that asserts the field value from a fixture.
7. Update `docs/backend-architecture.md` Section 4 if the field is user-facing and significant.

---

## SKILL: Add a New Platform Adapter

1. Add the platform entry to `services/config/platforms.json`:
   - adapter name, URL/domain signatures for detection, JS-state mappings if applicable, listing-readiness selectors
2. Create `services/adapters/[platform].py`:
   - `class [Platform]Adapter` with `can_handle(url, html) -> bool` and `extract(html, url) -> list[AdapterRecord]`
3. Register in `services/adapters/registry.py:_ADAPTER_MAP` (or `registered_adapters()` — check how existing adapters register).
4. Add network payload spec to `services/config/network_payload_specs.py` if the platform has a known JSON API endpoint.
5. Test: `python run_acquire_smoke.py [platform_keyword]`
6. **Do NOT** put the platform name anywhere in: `crawl_fetch_runtime.py`, `crawl_engine.py`, `_batch_runtime.py`, or any generic path.

---

## SKILL: Add a New API Route

1. Identify the correct router file in `app/api/` by resource ownership.
2. Create a Pydantic schema in `app/schemas/[resource].py` for request/response if needed.
3. Implement business logic in the owning service file (NOT in the route handler — handlers call services).
4. Add the route function to the router with the correct auth dependency (`get_current_user` or admin check).
5. Add the route to the registered surface table in `docs/backend-architecture.md` Section 3.
6. Add a focused test in `tests/api/`.

---

## SKILL: Delete Dead Code

1. Search all callers: `grep -r "symbol_name" backend/app` — confirm zero live callers.
2. Test files that import private internals are not "callers" — they are also candidates for deletion.
3. Delete the symbol (function, class, constant, file).
4. Delete any test that only existed to test that symbol's internals.
5. Run `pytest tests -q` to confirm nothing breaks.
6. If the symbol was documented in any canonical doc, remove the reference.
7. Do NOT leave a re-export stub at the old location. Delete the old location entirely.

---

## SKILL: Modify Selector Self-Heal Behavior

Self-heal lives in `services/selector_self_heal.py`. Key invariants:
- Self-heal only runs when domain-memory selectors fail to satisfy the requested fields.
- Synthesized selectors are only persisted after a rerun confirms they **improve** targeted fields.
- Do not trigger a new synthesis pass if domain-memory rules already cover the requested fields.

Trace: `pipeline/core.py` → `apply_selector_self_heal()` → `selector_self_heal.py:612` → `domain_memory_service.py`

Tests: `tests/services/test_selector_pipeline_integration.py`

---

## SKILL: Modify Review / Domain Memory

Review persistence: `review/__init__.py` — `ReviewPromotion` is the single DB-backed owner of approved schema.
Domain memory: `domain_memory_service.py` — `load_domain_memory()` (SELECT) and `create_domain_memory()` (INSERT/UPDATE).
Scoping: always by normalized `(domain, surface)`. Never global.

If you change the review save flow, verify that `schema_service` loads from `ReviewPromotion.approved_schema`
(not from in-memory state) and that later schema loads read the same stored snapshot.

---

## SKILL: Update Docs After Implementation

Only update canonical docs. Never write to CHANGELOG.

| What changed | Doc to update |
|-------------|---------------|
| A subsystem's behavior, new feature, or contract | `docs/backend-architecture.md` relevant section |
| A file was added or moved to a different bucket | `docs/CODEBASE_MAP.md` |
| A must-preserve runtime rule changed | `docs/INVARIANTS.md` |
| A new anti-pattern was discovered | `docs/ENGINEERING_STRATEGY.md` Anti-Patterns section |
| Ownership buckets changed | `AGENTS.md` ownership table + `docs/CODEBASE_MAP.md` |
| A plan slice is done | `docs/plans/[active-plan].md` — mark slice DONE |
| A plan is fully done | `docs/plans/ACTIVE.md` — mark complete or point to next |

Do NOT add new sections to `backend-architecture.md` for every small change.
Do NOT update `ENGINEERING_STRATEGY.md` with implementation details.

---

## SKILL: Add a New Surface Type

1. Add to `services/field_policy.py:canonical_fields_for_surface()`.
2. Add normalization mapping in `services/field_value_core.py:direct_record_to_surface_fields()`.
3. Update `CrawlCreate` surface validation in `app/schemas/crawl.py`.
4. Add surface-specific field aliases to `services/config/field_mappings.py`.
5. Add surface to the frontend surface selector in `components/crawl/crawl-config-screen.tsx`.
6. Update `docs/backend-architecture.md` Section 4 with the new surface.

---

## SKILL: Modify Run Status / State Machine

Status transitions are enforced in `app/models/crawl_domain.py`:
- `CrawlStatus` enum — add new status here first
- `_ALLOWED_TRANSITIONS` map — add allowed transitions
- `TERMINAL_STATUSES` / `ACTIVE_STATUSES` sets — update membership

Do not add status-transition logic anywhere else.

---

## SKILL: Add a New Export Format

1. Add the export method in `services/record_export_service.py`.
2. Add the route in `app/api/records.py`.
3. Add content-type handling in the export response builder.
4. Add the method to `frontend/lib/api/index.ts` and type it in `lib/api/types.ts`.
5. Update `docs/backend-architecture.md` Section 7 (Export Formats table).