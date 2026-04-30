# Adapters + Config Bucket Audit

Scope: `backend/app/services/adapters/*`, `backend/app/services/config/*`

## Adapters

| File | Lines | Primary Concern |
|------|-------|----------------|
| `icims.py` | 394 | HTML regex + pagination + embedded board discovery |
| `oracle_hcm.py` | 279 | REST API pagination + requisition normalization |
| `greenhouse.py` | 305 | HTML parsing + JSON API fallback + pay range normalization |
| `adp.py` | 236 | HTML DOM parsing with selectolax |
| `workday.py` | 237 | REST API pagination + locale context |
| `jibe.py` | ~200 | HTML + JSON API |
| `paycom.py` | ~150 | HTML parsing |
| `ultipro.py` | ~100 | HTML parsing |
| `registry.py` | 184 | Eager import of all 20 adapters |

---

## AC1. `registry.py` — Eager Import of All 20 Adapters

**Status:** DONE. Verified 2026-04-29 — switched to lazy imports via `import_module`.

**Fix applied:** Top-level eager imports replaced with lazy `import_module` calls inside `registered_adapters()`. Cold-start penalty eliminated for unused adapters.

---

## AC2. `AdapterResult` Boilerplate Repeated 20×

**Status:** DONE. Verified 2026-04-29 — `BaseAdapter._result()` added.

**Fix applied:** `_result(self, records)` helper added to `BaseAdapter`. Boilerplate removed from all 20 adapters. ~60 lines recovered.

---

## AC3. Job Adapters — Duplicated `detail` / `listing` Branch Pattern

**Status:** DONE. Verified 2026-04-29 — `_dispatch()` helper added to `BaseAdapter`.

**Fix applied:** `BaseAdapter._dispatch_detail_or_listing()` template method added. Adapters now only override `_extract_detail` and `_extract_listing`. ~24 lines recovered.

---

## AC4. Oracle HCM — Inline Regexes and Constants

**Status:** DONE. Verified 2026-04-29 — migrated to `config/extraction_rules.py`.

**Fix applied:** Moved regexes, facets, and location-list keys to `ORACLE_HCM_*` config exports in `config/extraction_rules.py`.

---

## AC5. ICIMS — Inline Exception Tuple

**Status:** NO CHANGE. Adapter-specific, acceptable.

---

## AC6. Greenhouse — Pay Normalization Duplicated with Other Adapters

**Status:** NO CHANGE. Not duplicated across adapters.

---

## AC7. Adapter Base — Missing `BaseAdapter._result()` and `_dispatch()` Helpers

**Status:** DONE. Verified 2026-04-29 — helpers added to `BaseAdapter`.

**Fix applied:** `_result()` and `_is_detail_surface()` helpers added to `BaseAdapter`.

---

## Config

## CC1. `runtime_settings.py` — Dead Wrapper Re-Exports (lines 9-30)

**Status:** DONE. Verified 2026-04-29 — dead re-exports removed.

**Fix applied:** Import + re-export block deleted. `browser_identity.py` already imports directly from `browser_init_scripts.py`. ~16 lines recovered.

---

## CC2. `runtime_settings.py` — Repetitive Validator Pattern

**Status:** DONE. Verified 2026-04-29 — helper validation extracted.

**Finding:** Lines 332-457 contain ~45 separate `if x <= 0: raise ValueError(...)` checks. This is ~90 lines of mechanical validation.

**Fix applied:** Added `_require_positive()`, `_require_non_negative()`, and `_require_unit_interval()` helpers; repeated validator branches now use grouped loops.

---

## CC3. `adapter_runtime_settings.py` — Clean, No Issues

**Status:** NO CHANGE. Well-factored. Keep as-is.

---

## Summary: Adapters + Config LOC Reduction Targets

| File | Current | Target | Savings |
|------|---------|--------|---------|
| `registry.py` | 184 | ~170 | ~14 (dynamic imports) |
| `adapters/*` (20 files) | ~3,500 | ~3,420 | ~80 (AdapterResult + _dispatch boilerplate) |
| `runtime_settings.py` | 495 | ~430 | ~65 (dead wrappers + validator simplification) |
| **Total** | **~4,179** | **~4,020** | **~159** |

*Savings are modest (~4%) because adapters are inherently platform-specific and correctly isolated. The main architectural win is registry eager imports (AC1) and BaseAdapter helpers (AC2, AC3).*
