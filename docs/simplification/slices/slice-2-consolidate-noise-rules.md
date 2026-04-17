# Slice 2 — Consolidate Noise Rules (Data in Config, Functions in Policy)

> **Owner:** Codex. **Prerequisite:** Slice 1 landed. **Parallelizable:** No other slice touches the same files.
> **Evidence basis:** [03-batch-b-findings.md](../03-batch-b-findings.md) — noise rules split between `config/extraction_rules.py` and `extract/noise_policy.py` in three categories: field-level reject phrases, semantic-section skip lists, CSS-noise patterns.
> **Goal:** One home for each noise *rule set* (data in config) and one home for each noise *function* (policy in `extract/noise_policy.py`). Eliminate the parallel shadow-definitions.

## Principle

- **Config owns data:** phrase sets, regex patterns, token lists.
- **`extract/noise_policy.py` owns functions:** detection, stripping, sanitization.
- **No rule data duplicated in `noise_policy.py`.** Policy functions import data from config.
- **Config imports nothing from `app.services.extract.*`.** Matches the directionality established in Slice 1.

## Target mapping

| Concern | Data home (config) | Function home (policy) |
|---------|---------------------|-------------------------|
| Field reject phrases (per canonical field) | `config/extraction_rules.py::FIELD_POLLUTION_RULES` (keep, extended) | `noise_policy.sanitize_detail_field_value` |
| Generic detail reject phrases | **move** `_COMMON_DETAIL_REJECT_PHRASES` into `FIELD_POLLUTION_RULES["__common__"]` | same function, reads `__common__` entry |
| Title noise words | **move** `TITLE_NOISE_WORDS` into config as `TITLE_NOISE_WORDS` | `noise_policy.is_noise_title` |
| Section label/key/body skips | **merge** `SECTION_LABEL_SKIP_TOKENS`, `SECTION_KEY_SKIP_PREFIXES`, `SECTION_BODY_SKIP_PHRASES` with `SECTION_SKIP_PATTERNS`, `SECTION_ANCESTOR_STOP_*` in config under a single `SEMANTIC_SECTION_NOISE` dict | section-skip functions in `noise_policy` |
| CSS noise | **consolidate** `color_css_noise_tokens`, `size_css_noise_tokens`, `ui_noise_phrases`, `_CSS_NOISE_VALUE_RE` into one config constant `CSS_NOISE_TOKENS` + one compiled regex derived from it | `noise_policy._CSS_NOISE_VALUE_RE` becomes a cached property of the config table |
| Product-attribute noise | keep `CANDIDATE_NOISY_PRODUCT_ATTRIBUTE_KEY_TOKENS` / `CANDIDATE_PRODUCT_ATTRIBUTE_CSS_NOISE_PATTERN` / `CANDIDATE_PRODUCT_ATTRIBUTE_DIGIT_ONLY_KEY_PATTERN` in config | keep functions in `noise_policy` (already directional — just verify no shadow data crept in) |
| Noise container tokens | **move** `_NOISE_CONTAINER_TOKENS`, `_NOISE_CONTAINER_REMOVAL_SELECTOR`, `_SOCIAL_HOST_SUFFIXES` to config as public constants | functions stay in `noise_policy` |
| Low-quality merge tokens | **move** `LOW_QUALITY_MERGE_TOKENS` to config | `noise_policy.contains_low_quality_merge_token` |

## Concrete steps

### Step 1 — Inventory
Grep every named constant in the "Data home" column above and confirm its current file + exact definition. Produce a scratch file `scratch/slice-2-inventory.md` listing for each rule:
- current file : current line
- current name : new name (if renamed)
- target file : target section header

### Step 2 — Move in groups (one group per commit)
Groups match the rows in the target mapping table above. Per group:
1. Copy the data definition into `config/extraction_rules.py` under a clearly-titled section comment.
2. Update `noise_policy.py` imports to pull from config instead of defining locally.
3. Delete the local definition in `noise_policy.py`.
4. Run `pytest tests/services/extract -q` plus `run_extraction_smoke.py`.
5. Commit with message `refactor(simplification): slice 2 group N — move <rule-name> to config`.

### Step 3 — Verify no shadow data remains in `noise_policy.py`
After all groups:
```
grep -nE "^_?[A-Z][A-Z0-9_]* = " backend/app/services/extract/noise_policy.py
```
Every remaining module-level constant must be either:
- a compiled cache of config data (e.g., `_CSS_NOISE_VALUE_RE = re.compile(...)` built from `CSS_NOISE_TOKENS`), or
- a private implementation detail that cannot be meaningfully expressed as config data (document why inline).

### Step 4 — Add a unit test for rule-set parity
`backend/tests/services/extract/test_noise_policy_consolidation.py`:
- For each consolidated rule, pick 3-5 representative inputs known to be noise and 2-3 known to be legitimate. Assert the policy function classifies them correctly. This locks in behavior during consolidation and catches drift if anyone later re-adds a shadow definition.

### Step 5 — Tests
```
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe run_extraction_smoke.py
.\.venv\Scripts\python.exe run_acquire_smoke.py commerce
```

## Acceptance criteria

- [x] Every consolidation target in the table above landed.
- [x] `noise_policy.py` contains no module-level rule *data* except compiled caches of config data.
- [x] `config/extraction_rules.py` imports nothing from `app.services.extract.*`.
- [x] Parity tests added in `test_noise_policy_consolidation.py`.
- [ ] Full test suite green. Both smokes exit 0.
- [x] One-paragraph closing note appended under `## Closing note`.

## Out of scope

- Changing any noise *behavior* (the set of things classified as noise must be unchanged by this slice).
- Collapsing requested-field alias logic across 3 files — deferred.
- Touching arbitration logic in `field_decision.py` — Slice 3+.
- New Invariant 6 backfill wiring — Phase 5.

## Rollback

Per-group revert. If a parity test fails after consolidation, revert the offending group and document the divergence in `## Revival log`.

## Guardrail — new Invariant 12 alignment

During this slice, if you encounter any noise rule that rejects a field value *because the value is a page-native label that doesn't match a canonical field name*, flag it in the closing note under `### Invariant 12 concerns`. Do not remove the rule in this slice — just record it. Invariant 12 (page-native field identity) will drive a dedicated slice later; this slice is consolidation only.

## Closing note

Slice 2 consolidated the remaining noise-rule data into `backend/app/services/config/extraction_rules.py` and left `backend/app/services/extract/noise_policy.py` with functions plus compiled caches only. The moved tables now include low-quality merge tokens, title-noise words, field-pollution reject phrases, semantic-section skip data, CSS noise inputs, product-attribute noise tables, noise-container tokens/selectors, social-host suffixes, and the network-payload noise URL pattern; downstream consumers that previously read noise data from `noise_policy.py` were updated to read config-backed values instead. Verification added `scratch/slice-2-inventory.md` and `backend/tests/services/extract/test_noise_policy_consolidation.py`; the focused consolidation checks passed, `pytest tests/services/extract -q` returned to the same two pre-existing listing failures, `pytest tests -q` remains blocked by the existing failures in `tests/services/adapters/test_base_adapter.py`, `tests/services/config/test_field_mappings_collisions.py`, `tests/services/extract/test_listing_extractor.py`, `tests/services/test_batch_runtime_retry_update.py`, and `tests/services/test_llm_runtime.py`, `run_extraction_smoke.py` still fails with `ModuleNotFoundError: app.services.semantic_detail_extractor`, and `run_acquire_smoke.py commerce` passed on April 17, 2026.

### Invariant 12 concerns

Rules that reject values such as `select size`, `select color`, `select colour`, `availability`, and generic navigation/UI labels remain in place after consolidation. Those rules may be filtering page-native labels rather than purely synthetic noise, so they should be revisited in the later Invariant 12 slice instead of being changed here.
