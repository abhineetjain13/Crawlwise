# Slice 1 — Break Circular Policy Import, Establish Single Surface Contract

> **Owner:** Codex. **Prerequisite:** Slice 0 landed. **Parallelizable with Slice 2?** Yes, after this slice lands — Slice 2 depends on the directional imports this slice establishes.
> **Evidence basis:** [03-batch-b-findings.md](../03-batch-b-findings.md) — circular dependency between `config/field_mappings.py` and `field_alias_policy.py`, and the two-shape surface contract (`CANONICAL_SCHEMAS` allowlist vs `excluded_fields_for_surface` blocklist).
> **Goal:** Enforce **config holds data, services hold policy** directionality. One surface contract, one direction of imports.

## Target shape

```
backend/app/services/config/field_mappings.py
    — DATA only: FIELD_ALIASES, CANONICAL_SCHEMAS, ECOMMERCE_ONLY_FIELDS,
      JOB_ONLY_FIELDS, INTERNAL_ONLY_FIELDS, DATALAYER_ECOMMERCE_FIELD_MAP,
      COLLECTION_KEYS. No imports from app.services.*.

backend/app/services/field_alias_policy.py
    — POLICY functions: get_surface_field_aliases, excluded_fields_for_surface,
      field_allowed_for_surface, requested-field alias builder.
      Imports data from config.field_mappings. No re-exports from config.

Every other file that needs policy functions imports directly from
field_alias_policy (NOT via config.field_mappings).
```

**No circular import. No re-exports. Config is leaf; policy is branch; extract/pipeline are consumers.**

## Design decisions

1. **`CANONICAL_SCHEMAS` (allowlist) is the single source of truth for per-surface field sets.** `ECOMMERCE_ONLY_FIELDS` / `JOB_ONLY_FIELDS` / `INTERNAL_ONLY_FIELDS` stay as-is for now — they serve a distinct purpose (cross-surface exclusion). But `excluded_fields_for_surface` is REDERIVED from `CANONICAL_SCHEMAS`, not declared independently. If a field appears in the commerce schema but not the job schema, it's excluded for jobs. This collapses the "define twice" problem.
2. **The `__getattr__` lazy loader for `REQUESTED_FIELD_ALIASES` is removed.** If Slice 0 didn't already delete it (because someone imports it from `field_mappings`), update those importers to import from `field_alias_policy` directly.
3. **Re-exports from `field_mappings` to `field_alias_policy` are removed.** Direct importers update to the new path.

## Concrete steps

### Step 1 — Audit current importers
Run from repo root, record output in a scratch file:
```
grep -rn "from app.services.config.field_mappings import" backend/ --include="*.py"
grep -rn "from app.services.field_alias_policy import" backend/ --include="*.py"
```

### Step 2 — Remove the re-export bridges in `config/field_mappings.py`
Strip any `from ..field_alias_policy import ...` (and matching re-exports) from `config/field_mappings.py`. If the `__getattr__` loader survived Slice 0, remove it here.

### Step 3 — Update importers of the removed re-exports
Every importer grepped in Step 1 that pulls `excluded_fields_for_surface`, `field_allowed_for_surface`, `get_surface_field_aliases`, or `REQUESTED_FIELD_ALIASES` from `config.field_mappings` must switch to:
```python
from app.services.field_alias_policy import excluded_fields_for_surface, field_allowed_for_surface, get_surface_field_aliases, REQUESTED_FIELD_ALIASES
```

Known importers per Batch B: `pipeline/field_normalization.py` (uses `field_allowed_for_surface`), potentially `dom_extraction.py`, `field_classifier.py`, `listing_item_mapper.py`. Verify with Step 1 grep.

### Step 4 — Rederive `excluded_fields_for_surface` from `CANONICAL_SCHEMAS`
In `field_alias_policy.py`:
```python
from app.services.config.field_mappings import CANONICAL_SCHEMAS, ECOMMERCE_ONLY_FIELDS, JOB_ONLY_FIELDS, INTERNAL_ONLY_FIELDS

def excluded_fields_for_surface(surface: str) -> frozenset[str]:
    """Fields disallowed for a given surface. Derived from CANONICAL_SCHEMAS."""
    allowed = frozenset(CANONICAL_SCHEMAS.get(surface, ()))
    all_canonical = frozenset().union(*CANONICAL_SCHEMAS.values())
    return (all_canonical - allowed) | INTERNAL_ONLY_FIELDS
```

Keep `field_allowed_for_surface(surface, field)` as a boolean wrapper.

**Validation:** before/after this change, for every (surface, field) pair in `CANONICAL_SCHEMAS`, `field_allowed_for_surface` must return the same boolean. Add a unit test in `backend/tests/services/test_field_alias_policy.py` that asserts this across the full cartesian product. If the new derivation diverges from the old blocklist on any pair, stop and flag — `ECOMMERCE_ONLY_FIELDS`/`JOB_ONLY_FIELDS` may encode information `CANONICAL_SCHEMAS` doesn't.

### Step 5 — Verify directional imports
After Steps 2-4:
```
grep -n "from app.services" backend/app/services/config/field_mappings.py
```
Must return zero hits. Config imports nothing from `app.services`.

### Step 6 — Tests
```
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe run_extraction_smoke.py
.\.venv\Scripts\python.exe run_acquire_smoke.py commerce
```

## Acceptance criteria

- [x] `config/field_mappings.py` imports nothing from `app.services.*`.
- [x] `excluded_fields_for_surface` is derived from `CANONICAL_SCHEMAS`, not declared independently.
- [x] A new unit test covers `field_allowed_for_surface` parity across every (surface, field) pair in `CANONICAL_SCHEMAS`.
- [x] All importers of the removed re-exports updated to `field_alias_policy` direct import.
- [ ] Full test suite green. Both smokes exit 0.
- [x] One-paragraph closing note appended under `## Closing note`.

## Out of scope

- Duplicate noise rule consolidation — Slice 2.
- Collapsing requested-field alias logic across 3 files — deferred; wait for Slice 2's noise consolidation pattern to inform the shape.
- Any changes to `FIELD_ALIASES` contents or `CANONICAL_SCHEMAS` contents.
- Any behavior change beyond import restructuring and the derivation in Step 4.

## Rollback

One revert per commit. If the derivation test in Step 4 reveals hidden semantics in `ECOMMERCE_ONLY_FIELDS` / `JOB_ONLY_FIELDS`, revert Step 4 and document the finding in `## Revival log` for Phase 1 review before retrying.

## Closing note

Slice 1 removed the config-to-policy bridge layer by deleting the `field_mappings.py` re-export functions and lazy `REQUESTED_FIELD_ALIASES` loader, moving the remaining live policy imports to `field_alias_policy.py`, and rederiving `excluded_fields_for_surface` from `CANONICAL_SCHEMAS` plus `INTERNAL_ONLY_FIELDS` instead of maintaining a separate blocklist contract. The final shape keeps `config/field_mappings.py` as a data-only leaf, keeps policy logic in `field_alias_policy.py`, and preserves the practical unknown-surface fallback by deriving it from the union of canonical schema fields rather than from duplicated policy tables. Verification added `backend/tests/services/test_field_alias_policy.py`, rewrote the stale `test_signal_inventory.py` dataclass assumptions to the current dict contract, and passed the focused Slice 1 checks (`test_field_alias_policy`, `test_field_mappings`, `test_requested_field_policy`, `test_signal_inventory`, `test_signal_inventory_integration`, and `test_json_extractor`). Full-suite acceptance is still blocked by pre-existing failures in `tests/services/adapters/test_base_adapter.py`, `tests/services/config/test_field_mappings_collisions.py`, `tests/services/extract/test_listing_extractor.py`, `tests/services/test_batch_runtime_retry_update.py`, and `tests/services/test_llm_runtime.py`, while `run_extraction_smoke.py` still fails with `ModuleNotFoundError: app.services.semantic_detail_extractor`; `run_acquire_smoke.py commerce` passed on April 17, 2026.
