# Slice 0 — Dead Code Kill (Policy + Extract layer)

> **Owner:** Codex. **Prerequisite:** none. **Can run in parallel with Slices 1-2? No** — Slice 1 touches some of these files; run Slice 0 first and land it.
> **Evidence basis:** Batch A findings [02-batch-a-findings.md](../02-batch-a-findings.md) + Batch B findings [03-batch-b-findings.md](../03-batch-b-findings.md).
> **Goal:** Remove declared-but-unused policy symbols and dead exports. Reduce surface area before Slice 1 restructures it.

## Safety rules — READ FIRST

1. **Every deletion is grep-gated.** Before deleting symbol `X`, run from repo root:
   ```
   grep -rn "X" backend/ --include="*.py"
   grep -rn "\"X\"\|'X'" backend/ --include="*.py"
   ```
   If any match outside the defining file exists, abort the deletion of that symbol and move on.
2. **Preserve symbols earmarked for revival.** `HYDRATED_STATE_PATTERNS` and `KNOWN_ATS_PLATFORMS` are flagged unused today but revived by `EXTRACTION_ENHANCEMENT_SPEC.md` §1.1 / §2.1. Instead of deleting, add:
   ```python
   # TODO(simplification phase 2): revived by EXTRACTION_ENHANCEMENT_SPEC.md §1.1
   ```
3. **Dynamic attribute access is not caught by grep.** For any `__getattr__` or attribute-string lookup (`getattr(module, "X")`), search the string form too.
4. **Run the affected tests after each file's deletions, not all at the end:**
   ```
   cd backend
   $env:PYTHONPATH='.'
   .\.venv\Scripts\python.exe -m pytest tests/services/extract -q
   .\.venv\Scripts\python.exe -m pytest tests/services -q -k "policy or mapping or normalization"
   .\.venv\Scripts\python.exe run_extraction_smoke.py
   ```
5. **No more than 3 file deletions per commit.** Use `git diff` to verify after each batch.
6. **Commit message format:** `chore(simplification): slice 0 — kill dead X in <file>` per file or per small group.

## Deletion targets

Grouped by file. Work through groups in order. Each group = one commit.

### Group 1 — `backend/app/services/shared_logic.py`
(Note: actual path likely `backend/app/services/extract/shared_logic.py` — verify.)
- [x] `normalized_field_token` — deleted after repo grep confirmed no cross-file references; local call sites in this file were inlined
- [x] `coerce_nested_text` — deleted after repo grep confirmed no cross-file references

### Group 2 — `backend/app/services/extract/signal_inventory.py`
- [x] `SignalInventory` class — deleted on the production-only pass; non-test usage was limited to a local build/classify handoff inside `signal_inventory.py` and `service.py`, so it was collapsed to a plain dict payload

### Group 3 — `backend/app/services/config/extraction_rules.py`
- [ ] `CANDIDATE_PROMO_ONLY_TITLE_PATTERN` — kept; live references exist in `backend/app/services/normalizers/__init__.py`
- [ ] `PRICE_FIELDS`, `PRICE_REGEX`, `SALARY_REGEX`, `CURRENCY_REGEX` — kept; `PRICE_FIELDS` and `PRICE_REGEX` are live in `backend/app/services/normalizers/__init__.py`; `SALARY_REGEX` / `CURRENCY_REGEX` are not present as top-level exports in this file
- [x] `VERDICT_RULES` — deleted after repo grep confirmed no cross-file references
- [ ] `EMPTY_SENTINEL_VALUES` — kept; live references exist in `backend/app/services/normalizers/listings.py`
- [ ] `REQUIRED_FIELDS_BY_SURFACE` — kept; live references exist in `backend/app/services/publish/verdict.py`
- [x] **DO NOT DELETE** `HYDRATED_STATE_PATTERNS` — TODO comment added per safety rule 2
- [x] **DO NOT DELETE** `KNOWN_ATS_PLATFORMS` — TODO comment added per safety rule 2

### Group 4 — `backend/app/services/config/nested_field_rules.py`
All six table constants below are claimed unused. Grep each before deleting.
- [ ] `NESTED_TEXT_KEYS` — kept; live references exist in `backend/app/services/normalizers/listings.py`
- [ ] `NESTED_URL_KEYS` — kept; live references exist in `backend/app/services/normalizers/listings.py`
- [ ] `NESTED_PRICE_KEYS` — kept; live references exist in `backend/app/services/normalizers/listings.py`
- [ ] `NESTED_ORIGINAL_PRICE_KEYS` — kept; live references exist in `backend/app/services/normalizers/listings.py`
- [ ] `NESTED_CURRENCY_KEYS` — kept; live references exist in `backend/app/services/normalizers/listings.py`
- [ ] `NESTED_CATEGORY_KEYS` — kept; live references exist in `backend/app/services/normalizers/listings.py`

### Group 5 — `backend/app/services/config/field_mappings.py`
- [ ] `excluded_fields_for_surface` re-export — kept; live production references exist in `backend/app/services/pipeline/listing_helpers.py`
- [ ] `get_surface_field_aliases` re-export — kept; live production references exist in extractor modules
- [ ] `__getattr__` lazy loader for `REQUESTED_FIELD_ALIASES` — kept; production imports of `REQUESTED_FIELD_ALIASES` remain live outside this file, so Slice 1 should handle the import-path cleanup instead

### Group 6 — `backend/app/services/requested_field_policy.py`
- [x] `requested_field_alias_map` — deleted after repo grep confirmed no cross-file references
- [x] `requested_field_terms` — deleted after repo grep confirmed no cross-file references

### Group 7 — `backend/app/services/extract/noise_policy.py`
- [ ] `field_value_contains_noise` — kept; live references exist in `backend/app/services/normalizers/__init__.py`

## Acceptance criteria

- [x] Each deletion has a preceding grep showing zero cross-file usage.
- [ ] Tests green after each group:
  - [ ] `pytest tests/services/extract -q`
  - [ ] `pytest tests -q` (full suite — once at the end)
  - [ ] `run_extraction_smoke.py` exits 0
  - [x] `run_acquire_smoke.py commerce` exits 0
- [x] `HYDRATED_STATE_PATTERNS` and `KNOWN_ATS_PLATFORMS` still present with TODO comments.
- [x] One-paragraph "what changed + what this unblocks" note appended to this slice file under a `## Closing note` heading.
- [x] No new imports added. No symbol renames. No behavior changes beyond deletion.

## Out of scope for this slice

- Breaking the `config/field_mappings.py` ↔ `field_alias_policy.py` circular dependency — Slice 1.
- Consolidating duplicated noise rules — Slice 2.
- Touching extractor files (the 27 under `extract/`) beyond the three symbols listed above — Slice 3+.
- Any behavior changes or refactors beyond removing unused code.

## Rollback

Per-group commits mean per-group revert. If any deletion breaks tests, `git revert` the offending commit and flag the symbol back in this slice file under a `## Revival log` section.

## Closing note

Slice 0 removed five dead or unnecessary symbols in this checkout: `normalized_field_token` and `coerce_nested_text` from `backend/app/services/extract/shared_logic.py`, the local-only `SignalInventory` dataclass from `backend/app/services/extract/signal_inventory.py`, `VERDICT_RULES` from `backend/app/services/config/extraction_rules.py`, and `requested_field_alias_map` / `requested_field_terms` from `backend/app/services/requested_field_policy.py`; it also preserved `HYDRATED_STATE_PATTERNS` and `KNOWN_ATS_PLATFORMS` with the required phase-2 TODO markers. The final pass ignored test-only references and re-checked production usage only, which showed that the remaining targets are still part of live runtime flows in the normalizers, publish, pipeline, and extractor layers. This keeps Slice 0 focused on real surface-area reduction while leaving Slice 1 with the still-live import-path and config cleanup work. Verification is partially blocked by pre-existing failures in `tests/services/extract/test_listing_extractor.py`, `tests/services/config/test_field_mappings_collisions.py`, `tests/services/adapters/test_base_adapter.py`, `tests/services/test_batch_runtime_retry_update.py`, `tests/services/test_llm_runtime.py`, and by `run_extraction_smoke.py` failing with `ModuleNotFoundError: app.services.semantic_detail_extractor`; `run_acquire_smoke.py commerce` passed on April 17, 2026.
