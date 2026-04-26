# CODEX EXECUTION SESSION — CrawlerAI Debt Remediation
# All findings verified. Execute in order. Do not reorder.
# Do not add comments, docstrings, helpers, or new files.
# Every WO must produce a net line reduction.
# Run `pytest tests/ -q` after ALL WOs complete, not between each.

---

## WO-1: Fix Bug 3 — Backfills Not Called on Normal DOM Return Path

**Files:** `services/detail_extractor.py`

In `build_detail_record()`, find the normal DOM-tier return path at approximately lines 2835–2841. This return path does NOT call `_backfill_detail_price_from_html` or `_backfill_variants_from_dom_if_missing`.

The early-exit return at ~2781–2795 already calls both. The normal DOM return must do the same.

Before the `return` statement on the normal DOM return path, add the same two calls that exist on the early-exit path:
```python
_backfill_detail_price_from_html(record, soup, page_url)
_backfill_variants_from_dom_if_missing(record, soup)
```

Do not add them anywhere else. Do not change the early-exit path. Do not change the function signature.

**Acceptance:**
```bash
grep -n "_backfill_detail_price_from_html\|_backfill_variants_from_dom_if_missing" \
  app/services/detail_extractor.py
# Both calls must appear on both return paths (early-exit AND normal DOM return).
# Count must be exactly 4 hits total (2 per function).
```

---

## WO-2: Consolidate `_object_list` — 5 copies → 1

**Files:** `services/field_value_core.py`, `services/detail_extractor.py`, `services/review/__init__.py`, `services/pipeline/persistence.py`, `services/record_export_service.py`, `services/acquisition/cookie_store.py`

In `field_value_core.py`, add this definition (copying variant — safest across all callers):
```python
def _object_list(value: object) -> list:
    return list(value) if isinstance(value, list) else []
```

**Important:** `cookie_store.py`'s copy also accepts non-list iterables. Before deleting it, grep cookie_store for every call site of `_object_list`. If any call site passes a non-list iterable, replace that specific call with `list(value)` inline. Then delete the cookie_store copy.

Delete `_object_list` from: `detail_extractor.py`, `review/__init__.py`, `pipeline/persistence.py`, `record_export_service.py`, `acquisition/cookie_store.py`.

Add to each of those files: `from services.field_value_core import _object_list`

**Acceptance:**
```bash
grep -rn "def _object_list" app/ --include="*.py"
# Exactly 1 hit — field_value_core.py only
```

---

## WO-3: Consolidate `_object_dict` — 2 copies → 1

**Files:** `services/field_value_core.py`, `services/detail_extractor.py`, `services/record_export_service.py`

In `field_value_core.py`, add (copying variant):
```python
def _object_dict(value: object) -> dict:
    return dict(value) if isinstance(value, dict) else {}
```

Delete `_object_dict` from `detail_extractor.py` and `record_export_service.py`.

`detail_extractor.py`'s copy returned the original reference — callers that relied on mutation of the returned dict will now get a copy instead. Grep `_object_dict` call sites in `detail_extractor.py` — if any result is immediately mutated (e.g., `_object_dict(x)["key"] = val`), that is fine (the copy is assigned back). If the caller expects the original dict to be mutated, that is a pre-existing bug — do not work around it, flag it in a comment and proceed.

Add to each deleted file: `from services.field_value_core import _object_dict`

**Acceptance:**
```bash
grep -rn "def _object_dict" app/ --include="*.py"
# Exactly 1 hit — field_value_core.py only
```

---

## WO-4: Consolidate `_safe_int` — 4 copies → 1

**Files:** `services/field_value_core.py`, `services/domain_memory_service.py`, `services/selector_self_heal.py`, `services/review/__init__.py`, `services/adapters/remoteok.py`

In `field_value_core.py`, add:
```python
def _safe_int(value: object, *, default: int | None = None) -> int | None:
    if value is None or value == "":
        return default
    try:
        return int(str(value))
    except (ValueError, TypeError):
        return default
```

`review/__init__.py` and `remoteok.py` have no `default` parameter — their callers receive `None` on failure. The canonical above defaults to `None`, so call sites need no changes.

Delete `_safe_int` from: `domain_memory_service.py`, `selector_self_heal.py`, `review/__init__.py`, `adapters/remoteok.py`.

Add to each: `from services.field_value_core import _safe_int`

**Acceptance:**
```bash
grep -rn "def _safe_int" app/ --include="*.py"
# Exactly 1 hit — field_value_core.py only
```

---

## WO-5: Consolidate `_coerce_int` — 4 copies → 2

**Files:** `services/field_value_core.py`, `services/acquisition/browser_detail.py`, `services/selectors_runtime.py`, `services/models/crawl_settings.py`, `services/domain_run_profile_service.py`

`_coerce_int` has two distinct semantics that cannot share one signature:
- **Simple parse** (browser_detail, selectors_runtime): `(value, *, default=0) -> int`
- **Clamped parse** (crawl_settings, domain_run_profile_service): `(value, default, minimum, maximum) -> int`

**Step A — Simple canonical in `field_value_core.py`:**
```python
def _coerce_int(value: object, *, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return default
```
The bool guard and bytes/float handling from `browser_detail.py` is the most complete version — use it.

Delete `_coerce_int` from `acquisition/browser_detail.py` and `selectors_runtime.py`.

`browser_detail.py` uses `fallback=` kwarg — update its call sites to `default=` before deleting.

Add to both deleted files: `from services.field_value_core import _coerce_int`

**Step B — Clamped version: consolidate the two identical copies:**
`crawl_settings.py:13` and `domain_run_profile_service.py:70` have identical signatures and behavior. Delete the copy in `domain_run_profile_service.py`.

Add to `domain_run_profile_service.py`:
```python
from services.models.crawl_settings import _coerce_int as _coerce_int_clamped
```
Update the 1–3 call sites in `domain_run_profile_service.py` to use `_coerce_int_clamped`.

Do not move the clamped version to `field_value_core.py` — it is settings-domain logic.

**Acceptance:**
```bash
grep -rn "def _coerce_int" app/ --include="*.py"
# Exactly 2 hits:
# 1. field_value_core.py (simple)
# 2. models/crawl_settings.py (clamped)
```

---

## WO-6: Remove Dead `_FIELD_ALIASES` isinstance Guards

**Files:** `services/field_value_core.py`, `services/field_policy.py`

In both files, find and replace:
```python
_FIELD_ALIASES = FIELD_ALIASES if isinstance(FIELD_ALIASES, dict) else {}
```
with:
```python
_FIELD_ALIASES = FIELD_ALIASES
```

**Acceptance:**
```bash
grep -rn "FIELD_ALIASES if isinstance" app/ --include="*.py"
# 0 hits
```

---

## WO-7: Gut `pipeline/__init__.py` — 6 dead re-exports

**Files:** `services/pipeline/__init__.py`

All 6 re-exports (`STAGE_ACQUIRE`, `STAGE_EXTRACT`, `STAGE_NORMALIZE`, `STAGE_PERSIST`, `URLProcessingConfig`, `URLProcessingResult`) have 0 external importers.

Before deleting, confirm with:
```bash
grep -rn "from services.pipeline import\|from app.services.pipeline import" app/ tests/ --include="*.py"
```
If this returns 0 hits, delete the entire body of `pipeline/__init__.py`, leaving an empty file (do not delete the file itself).

If any hits appear, list them — do not proceed. Report back.

**Acceptance:**
```bash
cat app/services/pipeline/__init__.py
# Empty file (or only a module docstring if one existed)
grep -rn "from services.pipeline import" app/ tests/ --include="*.py"
# 0 hits
```

---

## WO-8: Remove Duplicate model_validator in `schemas/crawl.py`

**Files:** `schemas/crawl.py`

Find `_normalize_record_payloads` — the `@model_validator` that re-checks `data`, `raw_data`, `discovered_data`, `source_trace` as dicts.

The `@field_validator` `_coerce_dict_payload` already handles all four fields with `mode="before"`. The model_validator is redundant.

Delete the entire `_normalize_record_payloads` method and its decorator.

Do not touch `_coerce_dict_payload`. Do not touch `_expand_provenance` in `CrawlRecordProvenanceResponse`.

**Acceptance:**
```bash
grep -n "_normalize_record_payloads" app/schemas/crawl.py
# 0 hits
pytest tests/ -q
# must pass
```

---

## WO-9: Delete Dead Modules

**Files:** `knowledge_base/store.py`, `services/semantic_detail_extractor.py`

Both confirmed DEAD — path absent, 0 importers.

Delete both files.

```bash
rm backend/app/services/semantic_detail_extractor.py
rm -rf backend/app/knowledge_base/  # only if store.py is the only file; otherwise delete store.py only
```

Run:
```bash
grep -rn "semantic_detail_extractor\|knowledge_base.store" app/ tests/ --include="*.py"
# 0 hits
pytest tests/ -q
# must pass
```

If any test fails, report the exact failure — do not restore the files, do not add compat stubs.

---

## WO-10: Harden PerimeterX Guard — Add Blocked-Run Gate

**Files:** `services/acquisition/cookie_store.py`

**Context:** The current persist path filters challenge cookies/localStorage via `_cookie_is_challenge_state()` and `_local_storage_entry_is_challenge_state()` at the item level. However, there is no gate on the blocked-run level — a blocked run that has no challenge-flagged items could still persist its full browser state.

Find the function in `cookie_store.py` that writes to `DomainCookieMemory`. It receives or has access to the acquisition result (blocked/unblocked state).

Add a guard at the top of the persist function:
```python
if acquisition_result.blocked:
    return  # never persist state from a blocked run
```

The exact parameter name for the blocked state depends on what the function signature already receives. Grep for `blocked` in `cookie_store.py` to find the right attribute name. Do not change the function signature — use whatever blocked-state indicator is already in scope.

If no blocked-state indicator is in scope at the persist call site, do not add one — instead report the function signature and its call sites so this can be properly scoped.

**Acceptance:**
```bash
grep -n "def.*persist.*storage\|def.*save.*cookie\|def.*write.*domain" \
  app/services/acquisition/cookie_store.py
# Find the persist function. Verify the early-return guard is present.
pytest tests/services/test_browser_context.py -q
# must pass (existing PerimeterX test must still pass)
```

---

## Final Acceptance — Run After All WOs

```bash
# Helper consolidation
grep -rn "def _object_list\|def _object_dict\|def _safe_int" app/ --include="*.py"
# _object_list: 1 hit, _object_dict: 1 hit, _safe_int: 1 hit

grep -rn "def _coerce_int" app/ --include="*.py"
# Exactly 2 hits (field_value_core.py, models/crawl_settings.py)

# Dead guards
grep -rn "FIELD_ALIASES if isinstance" app/ --include="*.py"
# 0 hits

grep -rn "_normalize_record_payloads\|LLMCommit" app/ --include="*.py"
# 0 hits

# Dead modules
grep -rn "semantic_detail_extractor\|knowledge_base.store" app/ tests/ --include="*.py"
# 0 hits

# Bug 3 fix
grep -n "_backfill_detail_price_from_html\|_backfill_variants_from_dom_if_missing" \
  app/services/detail_extractor.py
# 4 hits total (2 per function, on both return paths)

# Test suite
pytest tests/ -q
# green
```