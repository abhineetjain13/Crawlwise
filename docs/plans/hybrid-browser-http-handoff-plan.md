# Plan: Hybrid Browser-HTTP Session Handoff

**Created:** 2026-04-26
**Agent:** Codex
**Status:** DONE 2026-04-29
**Touches buckets:** acquisition, orchestration, config, tests, docs

## Goal

Design and later implement a guarded hybrid mode where a browser session clears challenge/setup steps, then hands trusted session state to the HTTP transport layer for bulk fetches. Done will mean this mode is explicit, observable, reversible, and only used where session drift and JS token churn are understood well enough to avoid poisoning acquisition.

## Acceptance Criteria

- [x] Browser handshake can export only safe session state needed for HTTP reuse.
- [x] Browser runtime has one primary engine contract: Patchright for acquisition, with no legacy stealth stack or silent Chromium fallback.
- [x] Browser dependency list matches runtime imports and tests.
- [x] HTTP handoff reuses the same engine-scoped cookie/session state on the same proxy identity, or is skipped when proxy affinity cannot be proven.
- [x] The system detects drift or challenge re-entry and falls back to browser cleanly.
- [x] Host/domain memory never persists challenge-poisoned handoff state.
- [x] Targeted tests cover happy path, drift fallback, and poisoned-state rejection.
- [x] `python -m pytest tests -q` exits 0 when implementation work lands.

## Do Not Touch

- `publish/*` — no downstream compensation.
- `detail_extractor.py` — hybrid mode is acquisition/runtime work.
- Generic LLM paths — unrelated.

## Slices

### Slice 0: Legacy Stealth Overlap Reduction
**Status:** DONE
**Files:** `backend/app/services/acquisition/browser_identity.py`, `backend/app/services/acquisition/browser_runtime.py`, `backend/app/services/config/runtime_settings.py`, focused tests, architecture docs
**What:** Treat the old Chromium-focused JS spoof bundle as technical debt. Keep it for `chromium`, keep `real_chrome` close to native, and make `patchright` default to a minimal/no-legacy-init-script lane so we stop stacking JS wrappers on a patched engine.
**Verify:** Focused browser identity/runtime tests.

### Slice 0.5: Patchright Runtime Consolidation + Review Flag Cleanup
**Status:** DONE
**Files:** `backend/pyproject.toml`, `backend/uv.lock`, `backend/app/services/acquisition/browser_runtime.py`, `backend/app/services/acquisition/browser_identity.py`, `backend/app/services/acquisition/browser_page_flow.py`, `backend/app/services/acquisition/browser_readiness.py`, `backend/app/services/acquisition/traversal.py`, `backend/app/services/acquisition/cookie_store.py`, `backend/app/services/acquisition/host_protection_memory.py`, `backend/app/services/crawl_fetch_runtime.py`, `backend/app/services/pipeline/core.py`, `backend/app/services/product_intelligence/discovery.py`, `backend/app/services/config/runtime_settings.py`, focused tests
**What:** Collapse browser acquisition onto Patchright as the explicit default. Remove `playwright-stealth`, legacy init-script toggles for Patchright, and automatic Chromium fallback. Keep any Real Chrome use only where explicitly owned, such as Product Intelligence native Google discovery, or remove it if no remaining caller needs it. Convert Playwright exception/type imports to the selected package so dependency and code agree.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests\services\test_browser_context.py tests\services\test_crawl_fetch_runtime.py tests\services\test_browser_expansion_runtime.py tests\services\test_traversal_runtime.py -q`

Audit decisions for `coderabbit_codeant_flags.md`:

- Dependency flag is valid. `backend/pyproject.toml` currently keeps `patchright`, `playwright`, and `playwright-stealth`. Choose Patchright for acquisition; remove stealth and generic Playwright unless a remaining explicit owner needs it.
- Patchright docs describe it as a Playwright drop-in replacement for Chromium and list built-in runtime/flag patches, so stacking `playwright-stealth` is redundant risk.
- Init-script flag is partially valid. Patchright no-init-script behavior is intentional after Slice 0, but the contract must be named and tested so engine switches do not silently change identity behavior.
- Engine availability flag is valid. `patchright_browser_available()` only checks importability. Add a bounded launch/runtime smoke probe or lazy-start failure classification so availability means "can start".
- Generic Chromium launch flag is mostly stale. Patchright still exposes `p.chromium.launch()` by design. The bug is not the property name; the bug is ambiguous manager/dependency selection. Tests should prove Patchright manager is used.
- Cookie-store Patchright metadata flag appears already covered. `browser_runtime` passes `browser_engine` to load/persist and `cookie_store` scopes `patchright`. Keep a regression test because handoff depends on this.
- Host-protection Patchright classification appears mostly covered through `browser_diagnostics["browser_engine"] -> browser:patchright`. Add blocked-host regression before deleting fallback lanes.
- Forced Real Chrome unavailable flag becomes moot if Real Chrome escalation is deleted. If Real Chrome stays for explicit Product Intelligence only, keep fail-fast behavior and do not downgrade to Chromium.
- `asyncio.wait_for(_browser_fetch(...))` flag is valid risk. Browser runtime already has staged timeouts and teardown. Remove outer `wait_for` or replace it with the same cooperative stage-cancel pattern so cancellation cannot leak contexts.
- Frontend flags are out of this backend slice. Frontend is treated as complete by user; only handle them if frontend closeout asks for it.

### Slice 1: Session Export Contract
**Status:** DONE 2026-04-29
**Files:** `backend/app/services/acquisition/cookie_store.py`, `backend/app/services/acquisition/browser_runtime.py`, config owners
**What:** Define safe browser-to-HTTP export payload and strip challenge-local poison. Use the consolidated Patchright engine label for handoff state; do not support legacy cross-engine replay except for existing Chromium state migration/ignore rules.
**Verify:** Cookie/session contract tests.

### Slice 2: HTTP Handoff Runtime
**Status:** DONE 2026-04-29
**Files:** `backend/app/services/crawl_fetch_runtime.py`, `backend/app/services/acquisition/runtime.py`
**What:** Add explicit handoff lane from browser success into HTTP transport reuse with proxy affinity.
**Verify:** Focused fetch/runtime tests.

### Slice 3: Drift Detection + Fallback
**Status:** DONE 2026-04-29
**Files:** acquisition runtime and host protection memory owners
**What:** Detect token/session drift, challenge return, or API mismatch and bounce back to browser.
**Verify:** Drift regression tests.

### Slice 4: Operator Controls + Docs
**Status:** DONE 2026-04-29
**Files:** config owners, docs, optional API/schema surface if exposed
**What:** Add explicit control flags, diagnostics, and operator guidance.
**Verify:** Contract tests and doc review.

## Doc Updates Required

- [x] `docs/INVARIANTS.md` — browser/HTTP handoff and poisoned-state rules.
- [x] `docs/backend-architecture.md` — acquisition runtime flow update.
- [x] `docs/ENGINEERING_STRATEGY.md` — added AP-16 for detail-expansion site-chrome clicks discovered during live handoff-quality debugging.

## Notes

- Risky by design. Do later, not now.
- Main known risks: JS-minted short-lived tokens, challenge-state replay, session drift, and engine/proxy mismatch.
- 2026-04-26: user requested immediate technical-debt work before hybrid handoff proper. Active slice is engine-specific stealth reduction for `patchright`.
- 2026-04-26: `patchright` now defaults to context-options-only shaping. Legacy JS spoof injection remains available behind `CRAWLER_RUNTIME_BROWSER_PATCHRIGHT_USE_LEGACY_INIT_SCRIPT=true` for experiments.
- Verify: `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests\services\test_browser_context.py -q`
- Result: `78 passed, 11 warnings` on 2026-04-26.
- 2026-04-27: Slice 0.5 removed `playwright`/`playwright-stealth`, removed Patchright legacy init-script/stealth toggles, made Patchright the primary acquisition engine, kept Real Chrome as explicit escalation, removed outer browser `wait_for`, and updated focused tests/docs.
- Verify: `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests\services\test_browser_context.py tests\services\test_crawl_fetch_runtime.py tests\services\test_browser_expansion_runtime.py tests\services\test_traversal_runtime.py -q`
- Result: `283 passed, 11 warnings` on 2026-04-27.
- Verify: `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests\services\test_pipeline_core.py tests\test_browser_surface_probe.py -q`
- Result: `55 passed, 11 warnings` on 2026-04-27.
- Full suite check: `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests -q`
- Result: `971 passed, 4 skipped, 6 failed, 11 warnings` on 2026-04-27; failures are missing artifact fixtures under `tests/fixtures/artifact_html`.
- 2026-04-29: Partial Slice 1-3 work landed. Cookie memory now de-dupes same name/domain/path cookies and exports a safe Cookie header for HTTP handoff. Browser-first host memory now treats HTTP 403/429 as immediate browser-first signals, not only vendor headers. Browser-first fetch can try direct curl_cffi with exported real_chrome/patchright cookies before browser, but skips proxied handoff because domain cookie memory is not proxy-scoped yet. Drift/block from handoff falls back to browser.
- Verify: `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests\services\test_browser_context.py tests\services\test_crawl_fetch_runtime.py tests\services\test_config_imports.py -q`
- Result: `165 passed, 11 warnings` on 2026-04-29.
- 2026-04-29: Closeout finished. Shared browser runtimes now recycle once after
  driver disconnect during context bootstrap, per-URL browser failures stay
  isolated inside `_batch_runtime.py`, and detail expansion is fenced away from
  header/nav/footer chrome so PDP requests do not pivot into Lowe's-style
  marketing pages. Full verification: `1057 passed, 4 skipped` on
  `pytest tests -q`. Live acceptance report:
  `backend/artifacts/test_sites_acceptance/20260429T025621Z__full_pipeline__test_sites_tail.json`
  with 5/5 `Quality: good` for Nike, Kith, Nordstrom, Costco, and Lowes.
