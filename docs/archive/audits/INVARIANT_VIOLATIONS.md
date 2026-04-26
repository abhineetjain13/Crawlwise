# INVARIANT_VIOLATIONS.md — CrawlerAI Backend Invariant Violation Scan

> Audit date: 2025-04-25  
> Scope: Violations of invariants defined in `docs/INVARIANTS.md`  
> Method: grep + code reading against each invariant rule and its violation signature  

---

## INV-1: Config and Constants Integrity

**Rule**: All runtime string tokens, timeouts, thresholds, field names, URL patterns, and numeric constants must live in `app/services/config/`.

### Violations Found

| ID | File | Lines | Violation | Severity |
|----|------|-------|-----------|----------|
| INV-1-01 | `services/xpath_service.py` | 228 | `timeout=0.05` regex timeout not in config | MEDIUM |
| INV-1-02 | `services/field_value_dom.py` | 515, 546 | `timeout=0.05` regex timeout not in config | MEDIUM |
| INV-1-03 | `services/acquisition/traversal.py` | 624, 677, 790 | `timeout=250` Playwright visibility not in config | HIGH |
| INV-1-04 | `services/acquisition/traversal.py` | 839 | `timeout=2000` scroll_into_view not in config | HIGH |
| INV-1-05 | `services/acquisition/traversal.py` | 1025-1026 | `timeout=200` / `timeout=1000` consent buttons not in config | MEDIUM |
| INV-1-06 | `services/acquisition/browser_runtime.py` | 785 | `timeout=10` shutdown future not in config | LOW |
| INV-1-07 | `api/crawls.py` | 675 | `asyncio.sleep(0.25)` WS poll interval not in config | MEDIUM |
| INV-1-08 | `services/detail_extractor.py` | 227, 354, 442-448, 757, 1044, 1061-1081, 1213-1220, 1255, 1480, 1496-1518, 1554-1556 | Field name strings (`"price"`, `"title"`, `"sku"`, etc.) not from config constants | HIGH |
| INV-1-09 | `services/listing_extractor.py` | 106, 129-133, 286, 330, 341-343, 365, 479, 703, 794, 809-811, 1202, 1217-1238 | Field name strings not from config constants | HIGH |
| INV-1-10 | `services/field_value_dom.py` | 57-72 | `_CDN_IMAGE_QUERY_PARAMS` frozenset defined inline | MEDIUM |
| INV-1-11 | `services/config/runtime_settings.py` | 9-10 | Duplicate `_PROJECT_ROOT` resolution vs `core/config.py` | MEDIUM |

**Note**: Platform/vendor strings (`"shopify"`, `"greenhouse"`, `"DataDome"`, `"perimeterx"`, etc.) are correctly confined to `config/` files (`platforms.json`, `block_signatures.py`, `network_capture.py`, `browser_surface_probe.py`). No leaked platform strings found in generic pipeline code.

---

## INV-2: Extraction Source Priority

**Rule**: Extraction follows adapter → structured source → DOM. No source tier may be skipped.

### Violations Found

| ID | File | Lines | Violation | Severity |
|----|------|-------|-----------|----------|
| INV-2-01 | `services/detail_extractor.py` | 2770-2795 | Early exit after js_state tier when confidence ≥ threshold AND `_requires_dom_completion` returns False. This skips the DOM tier entirely. | HIGH |
| INV-2-02 | `services/detail_extractor.py` | 2781-2787 | `_backfill_detail_price_from_html` and `_backfill_variants_from_dom_if_missing` are called on the early-exit path, but these are limited backfills — not full DOM tier extraction. Variant DOM cues may still be missed. | HIGH |

**Context**: INVARIANTS.md §3 explicitly documents this as a known root cause: "early exit before DOM tier when variant DOM cues exist." The `_requires_dom_completion` function (lines 2622-2690) attempts to guard against this, but its checks may be insufficient when:
- `variant_dom_cues_present(soup)` returns False for subtle DOM cues
- High confidence from js_state masks missing variant data

---

## INV-3: Field-by-Field Source Selection

**Rule**: Each field is independently sourced from the best available tier.

### Violations Found

| ID | File | Lines | Violation | Severity |
|----|------|-------|-----------|----------|
| INV-3-01 | `services/extraction_runtime.py` | 104, 113 | `"listing" in surface` — substring match for surface routing instead of field-by-field | HIGH |
| INV-3-02 | `services/extraction_runtime.py` | 823 | `"listing" in surface` — same pattern in JSON record path | HIGH |
| INV-3-03 | `services/acquisition/browser_readiness.py` | 131-132 | `"detail" in surface` / `"listing" in surface` — readiness probe uses substring | MEDIUM |
| INV-3-04 | `services/pipeline/direct_record_fallback.py` | 112-113 | `"listing" in surface` — fallback scoring uses substring | MEDIUM |

**Impact**: A surface like `"tabular_listing"` would incorrectly match `"listing" in surface`. The current surface set (`ecommerce_listing`, `job_listing`, `ecommerce_detail`, `job_detail`, `automobile_listing`, `automobile_detail`, `tabular`) avoids this, but the contract is fragile.

---

## INV-5: No Silent Failure

**Rule**: Every caught exception must be logged or re-raised. No bare `except Exception: pass` or `return None` without logging.

### Violations Found

See DEBT_INVENTORY.md §4A for the full catalog. Summary:

| Category | Count | Severity |
|----------|-------|----------|
| `except Exception:` with silent return (no logging) | 8 | HIGH |
| `except Exception:` with `logger.debug` only | 12 | MEDIUM |
| `except Exception:` with `logger.warning` or higher | 4 | LOW (acceptable) |
| `except Exception: continue` in selector loops | 5 | MEDIUM |

**Highest-risk instances**:
- `services/js_state_mapper.py:747,910` — glom failures silently return `{}`, potentially losing entire product/variant mappings
- `services/adapters/registry.py:112` — adapter failure returns `None`, masking extraction errors
- `services/listing_extractor.py:550` — CSS parse failure returns partial score silently

---

## INV-7: Listing vs Detail Separation

**Rule**: Listing extraction produces cards; detail extraction produces a single record. No mixing.

### Violations Found

| ID | File | Lines | Violation | Severity |
|----|------|-------|-----------|----------|
| INV-7-01 | `services/extraction_runtime.py` | 113-184 | `if "listing" in surface` branch calls `extract_listing_records`; else branch calls `extract_detail_records`. Surface string determines extraction path. | HIGH (fragile) |
| INV-7-02 | `services/listing_extractor.py` | 341 | `payload.get("price") or payload.get("offers") or payload.get("sale_price")` — listing extractor checks detail-like fields (offers) | LOW |

---

## INV-9: Domain Memory Scoping

**Rule**: Domain memory is scoped by (domain, surface). No cross-surface leakage.

### Violations Found

| ID | File | Lines | Violation | Severity |
|----|------|-------|-----------|----------|
| INV-9-01 | `services/domain_memory_service.py` | 152 | `load_domain_selector_rules` falls back to `surface="generic"` when the specific surface has no memory. This means generic selectors are applied to all surfaces for a domain. | MEDIUM (by design, but documented) |
| INV-9-02 | `services/selectors_runtime.py` | 153-156 | Same generic fallback pattern in selector loading | MEDIUM |

**Note**: The generic fallback is intentional per CODEBASE_MAP.md, but it means a selector learned on `ecommerce_listing` could leak to `job_detail` via the generic bucket if the domain has no surface-specific memory.

---

## INV-10: LLM Gating

**Rule**: LLM only runs when enabled by both run settings and active config. It fills gaps; it does not replace deterministic extraction.

### Violations Found

| ID | File | Lines | Violation | Severity |
|----|------|-------|-----------|----------|
| INV-10-01 | `services/llm_config_service.py` | 17-18 | `_LEGACY_PROMPTS_DIR` still checked as fallback — if a prompt file exists only in the legacy path, LLM could run with stale prompts | MEDIUM |
| INV-10-02 | `services/pipeline/core.py` | 49-52 | `extract_missing_fields` and `extract_records_directly_with_llm` are called unconditionally from pipeline core; the gating happens inside `llm_runtime.py` | LOW (correctly gated internally) |

No violations of the "LLM replaces deterministic extraction" rule were found. The LLM is always opt-in and degrades gracefully.

---

## Acceptance Grep Commands

```bash
# INV-1: leaked timeouts
cd backend && grep -rn "timeout=[0-9]" app/services/ --include="*.py" | grep -v "app/services/config/"

# INV-2: early exit paths
cd backend && grep -n "early_exit" app/services/detail_extractor.py

# INV-3: string-based surface dispatch
cd backend && grep -rn '"listing" in surface' app/ --include="*.py"

# INV-5: silent exception swallowing
cd backend && grep -rn "except Exception:" app/services/ --include="*.py" | grep -v "logger\."

# INV-9: generic surface fallback
cd backend && grep -rn '"generic"' app/services/domain_memory_service.py app/services/selectors_runtime.py
```
