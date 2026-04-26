# DEBT_INVENTORY.md — CrawlerAI Backend Technical Debt Audit

> Audit date: 2025-04-25  
> Scope: `backend/app/services/**`, `backend/app/api/**`, `backend/app/models/**`, `backend/app/schemas/**`  
> Method: grep + code reading against INVARIANTS.md, CODEBASE_MAP.md, BUSINESS_LOGIC.md  
> Classification: HIGH / MEDIUM / LOW severity per invariant violation scope  

---

## 1. Leaked Constants and Hardcoded Values (INV-1)

### 1A. Hardcoded timeout integers outside config

| File | Line | Symbol | Value | Canonical Owner | Severity |
|------|------|--------|-------|-----------------|----------|
| `services/xpath_service.py` | 228 | `timeout=0.05` | regex timeout | `config/runtime_settings.py` | MEDIUM |
| `services/field_value_dom.py` | 515, 546 | `timeout=0.05` | regex timeout | `config/runtime_settings.py` | MEDIUM |
| `services/acquisition/traversal.py` | 624, 677, 790 | `timeout=250` | Playwright visibility | `config/runtime_settings.py` | HIGH |
| `services/acquisition/traversal.py` | 839 | `timeout=2000` | scroll_into_view | `config/runtime_settings.py` | HIGH |
| `services/acquisition/traversal.py` | 1025 | `timeout=200` | consent button visibility | `config/runtime_settings.py` | MEDIUM |
| `services/acquisition/traversal.py` | 1026 | `timeout=1000` | consent button click | `config/runtime_settings.py` | MEDIUM |
| `services/acquisition/browser_runtime.py` | 785 | `timeout=10` | shutdown future | `config/runtime_settings.py` | LOW |
| `services/acquisition/browser_capture.py` | 132 | asyncio.sleep(0) yield | worker join yield | N/A (idiomatic) | LOW |
| `api/crawls.py` | 675 | `asyncio.sleep(0.25)` | WS poll interval | `config/runtime_settings.py` | MEDIUM |

**Violation signature**: INV-1 — timeout integers in service files not in `app/services/config/`.

### 1B. Hardcoded field-name strings in extraction logic

| File | Lines | Strings | Canonical Owner | Severity |
|------|-------|---------|-----------------|----------|
| `services/detail_extractor.py` | 227, 354, 442-448, 757, 1044, 1061-1081, 1213-1220, 1255, 1480, 1496-1518, 1554-1556 | `"title"`, `"price"`, `"original_price"`, `"currency"`, `"sku"`, `"variant_id"`, `"barcode"`, `"image_url"`, `"availability"`, `"description"`, `"specifications"`, `"product_details"`, `"product_id"` | `config/field_mappings.py` | HIGH |
| `services/listing_extractor.py` | 106, 129-133, 286, 330, 341-343, 365, 479, 703, 794, 809-811, 1202, 1217-1238 | `"title"`, `"price"`, `"sale_price"`, `"original_price"`, `"url"`, `"image_url"`, `"brand"`, `"description"`, `"rating"`, `"review_count"`, `"salary"`, `"company"`, `"location"` | `config/field_mappings.py` | HIGH |
| `services/extraction_runtime.py` | 104, 113, 823 | `"listing" in surface` | `config/field_mappings.py` (CANONICAL_SCHEMAS) | HIGH |
| `services/acquisition/browser_readiness.py` | 131-132 | `"detail" in surface`, `"listing" in surface` | `config/field_mappings.py` | MEDIUM |
| `services/pipeline/direct_record_fallback.py` | 112-113 | `"listing" in surface` | `config/field_mappings.py` | MEDIUM |

**Violation signature**: INV-1 — field names as bare string literals outside config.

### 1C. Dual `PROJECT_ROOT` / `BASE_DIR` resolution

| File | Lines | Symbol | Method | Severity |
|------|-------|--------|--------|----------|
| `core/config.py` | 9-10 | `BASE_DIR`, `PROJECT_ROOT` | `Path(__file__).resolve().parents[2]` / `.parent` | LOW (canonical) |
| `services/config/runtime_settings.py` | 9-10 | `_BACKEND_DIR`, `_PROJECT_ROOT` | `Path(__file__).resolve().parents[3]` / `.parents[4]` | MEDIUM (duplicate) |

Both resolve the same project root via different `__file__` anchors. If either file moves, the path breaks silently.

### 1D. Hardcoded CDN query params outside config

| File | Lines | Symbol | Severity |
|------|-------|--------|----------|
| `services/field_value_dom.py` | 57-72 | `_CDN_IMAGE_QUERY_PARAMS` frozenset | MEDIUM |

This frozenset of CDN image query parameter names (`"width"`, `"w"`, `"height"`, etc.) is defined inline rather than in `config/extraction_rules.py`.

---

## 2. Duplicated Helper Functions (Patch-as-Pattern)

### 2A. `_object_list` — 4 independent definitions

| File | Line | Signature | Behavior |
|------|------|-----------|----------|
| `services/detail_extractor.py` | 191 | `_object_list(value) -> list` | Returns value if list else `[]` (no copy) |
| `services/review/__init__.py` | 42 | `_object_list(value) -> list` | Returns value if list else `[]` (no copy) |
| `services/record_export_service.py` | 67 | `_object_list(value) -> list` | Returns `list(value)` if list else `[]` (copies) |
| `services/pipeline/persistence.py` | 24 | `_object_list(value) -> list` | Returns `list(value)` if list else `[]` (copies) |
| `services/acquisition/cookie_store.py` | 292 | `_object_list(value) -> list` | Returns `list(value)` if Iterable else `[]` (most defensive) |

**Severity**: HIGH — semantic drift between copies; some return the original reference, some copy.

### 2B. `_object_dict` — 2 independent definitions

| File | Line | Signature | Behavior |
|------|------|-----------|----------|
| `services/detail_extractor.py` | 195 | `_object_dict(value) -> dict` | Returns value if dict else `{}` (no copy) |
| `services/record_export_service.py` | 71 | `_object_dict(value) -> dict` | Returns `dict(value)` if dict else `{}` (copies) |

**Severity**: MEDIUM — same drift pattern as `_object_list`.

### 2C. `_coerce_float` — 2 independent definitions

| File | Line | Signature |
|------|------|-----------|
| `services/detail_extractor.py` | 199 | `_coerce_float(value, default=0.0) -> float` |
| `services/config/runtime_settings.py` | 371 | `coerce_url_timeout_seconds(self, value) -> float` |

**Severity**: LOW — different enough in purpose, but same coercion pattern.

### 2D. `_coerce_int` — 4 independent definitions

| File | Line | Signature | Behavior |
|------|------|-----------|----------|
| `services/acquisition/browser_detail.py` | 28 | `_coerce_int(value, *, fallback=0) -> int` | bool guard, then int check |
| `services/config/runtime_settings.py` | (inline) | `_coerce_int` in domain_run_profile_service | via try/except |
| `services/domain_run_profile_service.py` | 70 | `_coerce_int(value, *, default) -> int` | try/except with default |
| `services/selectors_runtime.py` | 40 | `_coerce_int(value, default=0) -> int` | `int(str(value))` with try/except |

**Severity**: HIGH — four copies with subtly different semantics.

### 2E. `_safe_int` — 4 independent definitions

| File | Line | Signature | Behavior |
|------|------|-----------|----------|
| `services/review/__init__.py` | 35 | `_safe_int(value) -> int \| None` | int(value) if numeric else int(str(value)) |
| `services/domain_memory_service.py` | 34 | `_safe_int(value, *, default) -> int \| None` | None/"" check then int(str(value)) |
| `services/selector_self_heal.py` | 415 | `_safe_int(value, *, default) -> int \| None` | None/"" check then int(str(value)) |
| `services/adapters/remoteok.py` | 67 | `_safe_int(value) -> int \| None` | None/"" check then int(value) |

**Severity**: HIGH — four copies with different None-handling semantics.

### 2F. `normalize_price` — wrapper-only duplication

| File | Line | Symbol | Delegates To |
|------|------|--------|-------------|
| `services/js_state_helpers.py` | 130 | `normalize_price()` | `normalizers.normalize_decimal_price()` |
| `services/normalizers/__init__.py` | 99 | `normalize_decimal_price()` | actual implementation |

**Severity**: LOW — thin wrapper, but adds an unnecessary indirection layer.

---

## 3. Defensive Coercion in Serialization Layer (INV-2)

### 3A. Dual `isinstance` guards on same fields

| File | Lines | Pattern | Severity |
|------|-------|---------|----------|
| `schemas/crawl.py` | 63-66 | `@field_validator _coerce_dict_payload` — converts non-dict to `{}` | MEDIUM |
| `schemas/crawl.py` | 69-76 | `@model_validator _normalize_record_payloads` — re-checks same 4 fields with identical isinstance | HIGH |
| `schemas/crawl.py` | 346-353 | `CrawlRecordProvenanceResponse._expand_provenance` — third isinstance guard on raw_data/discovered_data/source_trace | HIGH |

The `field_validator` already coerces; the `model_validator` re-checks the same fields. The provenance response adds a third layer. This masks a contract breach: the ORM layer is producing non-dict values for declared dict columns.

---

## 4. Silent Exception Swallowing (INV-5)

### 4A. `except Exception: return <default>` — data-loss risk

| File | Line | Pattern | Default | Severity |
|------|------|---------|---------|----------|
| `services/listing_extractor.py` | 175 | `except Exception:` | returns `False` (structural URL check) | MEDIUM |
| `services/listing_extractor.py` | 550 | `except Exception:` | returns `score` (link extraction) | MEDIUM |
| `services/listing_extractor.py` | 598 | `except Exception:` | returns `images=[]` | MEDIUM |
| `services/listing_extractor.py` | 615 | `except Exception:` | returns `""` (_node_html) | LOW |
| `services/js_state_mapper.py` | 747 | `except Exception:` | `base = {}` (glom product fields) | HIGH |
| `services/js_state_mapper.py` | 910 | `except Exception:` | `base = {}` (glom variant fields) | HIGH |
| `services/extract/listing_card_fragments.py` | 50 | `except Exception:` | returns `-100` (score) | MEDIUM |
| `services/extract/listing_card_fragments.py` | 144 | `except Exception:` | `matches = []` | LOW |
| `services/adapters/registry.py` | 112 | `except Exception:` | returns `None` (adapter extract) | HIGH |
| `services/adapters/linkedin.py` | 19 | `except Exception:` | returns `""` | LOW |
| `services/adapters/indeed.py` | 19 | `except Exception:` | returns `""` | LOW |
| `services/adapters/ebay.py` | 19 | `except Exception:` | returns `""` | LOW |
| `services/adapters/amazon.py` | 25 | `except Exception:` | returns `""` | LOW |
| `services/adapters/belk.py` | 224, 374, 388, 412 | `except Exception: continue` | skips selector | MEDIUM |
| `services/adapters/base.py` | 170 | `except Exception:` | returns `None` | MEDIUM |
| `services/structured_sources.py` | 367 | `except Exception:` | logs warning, continues | MEDIUM |
| `services/acquisition/browser_capture.py` | 204, 483 | `except Exception:` | logs debug, continues | LOW |
| `services/acquisition/browser_detail.py` | 294, 400, 576, 586 | `except Exception:` | returns `""` / continues | LOW |
| `services/crawl_service.py` | 201, 219, 240 | `except Exception:` | logs + continues | MEDIUM |
| `services/crawl_events.py` | 251 | `except Exception:` | rollback + skip | LOW |

**Violation signature**: INV-5 — broad `except Exception` with silent default return masks real failures.

---

## 5. `# type: ignore` Suppressions

| File | Line | Directive | Severity |
|------|------|-----------|----------|
| `services/structured_sources.py` | 23 | `# type: ignore[import-untyped]` (extruct) | LOW (legitimate) |
| `services/structured_sources.py` | 30 | `# type: ignore[assignment]` (get_base_url) | LOW (legitimate) |
| `services/js_state_mapper.py` | 7 | `# type: ignore[import-untyped]` (glom) | LOW (legitimate) |
| `services/extraction_runtime.py` | 9 | `# type: ignore[import-untyped]` (defusedxml) | LOW (legitimate) |
| `services/acquisition/traversal.py` | 17 | `# type: ignore[no-redef]` (PlaywrightError stub) | LOW (legitimate) |
| `services/acquisition/browser_runtime.py` | 112 | `# type: ignore[import-untyped]` (playwright_stealth) | LOW (legitimate) |
| `services/acquisition/browser_identity.py` | 17, 23, 33 | `# type: ignore[assignment,misc]` (browserforge) | MEDIUM (3 suppressions for optional deps) |
| `core/celery_app.py` | 6-7, 16 | `# type: ignore[import-untyped,no-redef]` (celery stub) | LOW (legitimate) |

All `type: ignore` instances are for optional/untyped third-party dependencies. No internal type contract is being suppressed.

---

## 6. Legacy/Compat Shims

| File | Lines | Symbol | Purpose | Severity |
|------|-------|--------|---------|----------|
| `models/crawl_domain.py` | 31-56 | `_LEGACY_STATUS_MAP`, `normalize_status` | Maps old status strings ("cancelled"→KILLED, "degraded"→FAILED) | LOW (still needed for DB migration) |
| `schemas/crawl.py` | 456-478 | `_LEGACY_MANIFEST_KEYS`, `_LEGACY_REVIEW_KEYS` | Filters old provenance keys from response | MEDIUM (growing exclusion list) |
| `services/llm_config_service.py` | 17-18 | `_LEGACY_PROMPTS_DIR` | Falls back to old `knowledge_base/prompts` path | MEDIUM (dead path after migration) |
| `services/dashboard_service.py` | 373-376 | `_legacy_artifact_paths()` | Cleans up `backend/backend/artifacts` double-nesting | LOW (one-time cleanup) |
| `core/migrations.py` | 32-72 | `_resolve_legacy_start_revision` | Stamps alembic on pre-migration DBs | LOW (one-time migration) |

---

## 7. String-Based Surface Dispatch (INV-3 / INV-7)

| File | Lines | Pattern | Severity |
|------|-------|---------|----------|
| `services/extraction_runtime.py` | 104, 113 | `if "listing" in surface` | HIGH |
| `services/extraction_runtime.py` | 823 | `if "listing" in surface` | HIGH |
| `services/acquisition/browser_readiness.py` | 131-132 | `is_detail = "detail" in surface` / `is_listing = "listing" in surface` | MEDIUM |
| `services/pipeline/direct_record_fallback.py` | 112-113 | `if "listing" in surface` | MEDIUM |

**Violation signature**: INV-3 — surface dispatch by substring match instead of enum or config-driven routing. `"tabular_listing"` would match `"listing" in surface` incorrectly if such a surface existed.

---

## Acceptance Grep Commands

```bash
# Leaked timeouts
cd backend && grep -rn "timeout=[0-9]" app/services/ --include="*.py" | grep -v "app/services/config/"

# Duplicated _object_list
cd backend && grep -rn "def _object_list" app/ --include="*.py"

# Duplicated _coerce_int
cd backend && grep -rn "def _coerce_int" app/ --include="*.py"

# Duplicated _safe_int
cd backend && grep -rn "def _safe_int" app/ --include="*.py"

# Silent exception swallowing
cd backend && grep -rn "except Exception:" app/services/ --include="*.py"

# String-based surface dispatch
cd backend && grep -rn '"listing" in surface' app/ --include="*.py"
```
