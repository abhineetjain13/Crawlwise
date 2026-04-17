# Batch B Findings — Field-Policy Fragmentation Audit

> **Source:** Gemini audit of 8 policy files, run 2026-04-17 per [01-gemini-audit-prompt-pack.md](./01-gemini-audit-prompt-pack.md) Batch B template.
> **Status:** Accepted. Findings drive Phase 0/1/2 slice specs in [slices/](./slices/). Raw Gemini deliverables are in chat log, not re-embedded.

## Executive summary

1. **Circular dependency exists.** `config/field_mappings.py` ↔ `field_alias_policy.py` import each other — config re-exports service functions and lazy-loads service constants via `__getattr__`. Service imports raw config tables. This breaks the stage-ownership principle (config = data, service = policy).
2. **Surface contract is defined twice.** `CANONICAL_SCHEMAS` (allowlist, config) and `excluded_fields_for_surface` (blocklist, service) encode the same truth in two shapes.
3. **Noise rules are split between config and policy.** `FIELD_POLLUTION_RULES`, `SECTION_SKIP_PATTERNS`, CSS-noise constants live in `config/extraction_rules.py`; their operational twins (`_DETAIL_FIELD_REJECT_PHRASES`, `SECTION_LABEL_SKIP_TOKENS`, `_CSS_NOISE_VALUE_RE`) live in `extract/noise_policy.py`. Same intent, two homes.
4. **Requested-field alias logic spans three files.** `config/field_mappings.py` (FIELD_ALIASES source), `field_alias_policy.py` (base + extra builder), `requested_field_policy.py` (normalizer). No single place defines "what is a requested field alias."
5. **Significant dead / unused surface area.** At least 15 declared rules have zero importers — per-field regex re-exports, unused verdict/required-field contracts, unused nested-key tables, unused lazy loaders, unused re-exports. Phase 0 kill list is large and low-risk.
6. **Invariant 1 confirmed violated.** Price, salary, currency, noise-phrase regexes live inside `config/extraction_rules.py` but are consumed via direct module imports (not via `pipeline_config.py` the invariant mandates). Also, regex constants are re-exported as `PRICE_REGEX`, `PRICE_FIELDS`, etc. that nobody imports — pure export cruft.

## Invariant updates landed in this session

- **Invariant 6 rewritten.** First-match → backfill + quality-scored arbitration. Transition note references Phase 5 confidence scorer. See `docs/INVARIANTS.md`.
- **Invariant 12 rewritten.** Canonical-schema-plus-residual → page-native field identity preserved; canonical fields apply only when the page exposes them, never invented or force-fitted.

## Cross-reference: EXTRACTION_ENHANCEMENT_SPEC.md (v1.1) against Batch B

The enhancement spec's Phase 1-4 items map cleanly onto the policy layer Batch B inventoried. Flagging where they intersect so slices don't collide.

| Spec item | Touches in Batch B inventory | Simplification-phase position |
|-----------|------------------------------|-------------------------------|
| §1.1 JS state pattern expansion (`__NUXT__`, `__APOLLO_STATE__`) | `HYDRATED_STATE_PATTERNS` in `extraction_rules.py` (currently unused — revives during this work) | Phase 2 (after policy consolidation) |
| §1.2 Surface-aware glom specs | Would supersede scattered alias logic across `field_alias_policy`, `requested_field_policy`, `field_mappings` | Phase 2 |
| §1.3 Surface-partition `FIELD_ALIASES` | `field_alias_policy.get_surface_field_aliases` already partial; `FIELD_ALIASES` master still flat | Phase 1 |
| §2.1 Platform detector | `KNOWN_ATS_PLATFORMS` in `extraction_rules.py` (currently unused — revives) | Phase 2 |
| §2.2 JMESPath XHR mappers | New policy surface area — aligns with page-native identity (Invariant 12) since XHR keys are page-native | Phase 2 |
| §4.1 Confidence scorer | Prerequisite for new Invariant 6 backfill behavior | Phase 5 |
| §4.2 LLM selector synthesis | Gated by §4.1, consumes `domain_memory` | Phase 5 |
| §4.3 `domain_memory` table | New DB object — not in Batch B scope | Phase 5 |

**Dead-code preservation note:** `HYDRATED_STATE_PATTERNS` and `KNOWN_ATS_PLATFORMS` flagged "unused" by Gemini. Phase 0 must NOT delete these — they're plumbing the enhancement spec revives. Add `# TODO(phase-2-spec-§1.1)` comments instead.

## Concrete duplication / contradiction findings

| Pair | Kind | Action |
|------|------|--------|
| `CANONICAL_SCHEMAS` (config) vs `excluded_fields_for_surface` (policy) | DUPLICATION | Slice 1 — collapse to one representation (allowlist wins; blocklist computed from it) |
| `FIELD_POLLUTION_RULES` (config) vs `_DETAIL_FIELD_REJECT_PHRASES` / `TITLE_NOISE_WORDS` (policy) | DUPLICATION / potential drift | Slice 2 — data stays in config, functions stay in policy, delete duplicated intent |
| `SECTION_SKIP_PATTERNS` + `SECTION_ANCESTOR_STOP_*` (config) vs `SECTION_LABEL_SKIP_TOKENS` + `SECTION_KEY_SKIP_PREFIXES` + `SECTION_BODY_SKIP_PHRASES` (policy) | DUPLICATION | Slice 2 |
| `color_css_noise_tokens` / `size_css_noise_tokens` / `ui_noise_phrases` (config) vs `_CSS_NOISE_VALUE_RE` (policy) | OVERLAP | Slice 2 |
| `config/field_mappings.py` ↔ `field_alias_policy.py` | CIRCULAR IMPORT | Slice 1 |
| Requested-field alias spread across 3 files | 3-way OVERLAP | Slice 1 |

## Dead / unused inventory (Phase 0 candidates)

Gemini flagged as "unused." Codex must verify each with a repo-wide grep before deletion.

**`config/extraction_rules.py`:**
- `CANDIDATE_PROMO_ONLY_TITLE_PATTERN`
- `PRICE_FIELDS`, `PRICE_REGEX`, `SALARY_REGEX`, `CURRENCY_REGEX` re-exports (raw regexes stay via `NORMALIZATION_RULES`)
- `VERDICT_RULES`
- `EMPTY_SENTINEL_VALUES`
- `REQUIRED_FIELDS_BY_SURFACE`
- **KEEP** `HYDRATED_STATE_PATTERNS`, `KNOWN_ATS_PLATFORMS` (revived by spec §1.1 and §2.1 — add TODO comments)

**`config/nested_field_rules.py`:**
- `NESTED_TEXT_KEYS`, `NESTED_URL_KEYS`, `NESTED_PRICE_KEYS`, `NESTED_ORIGINAL_PRICE_KEYS`, `NESTED_CURRENCY_KEYS`, `NESTED_CATEGORY_KEYS` (all unused)

**`config/field_mappings.py`:**
- `excluded_fields_for_surface` re-export
- `get_surface_field_aliases` re-export
- `__getattr__` lazy loader for `REQUESTED_FIELD_ALIASES`

**`requested_field_policy.py`:**
- `requested_field_alias_map`
- `requested_field_terms`

**`extract/noise_policy.py`:**
- `field_value_contains_noise`

**From Batch A (already queued for Phase 0):**
- `shared_logic.normalized_field_token`
- `shared_logic.coerce_nested_text`
- `signal_inventory.SignalInventory` (type-hint only — verify before deletion)

## Implicit coupling findings

Three cases of implicit shape dependencies (policy logic assumes shapes defined elsewhere without importing):
1. `extract/field_decision.py` assumes `candidate_source_rank` shape defined via `config/extraction_rules.py:SOURCE_RANKING`.
2. `extract/field_decision.py` relies on `sanitize_field_value_with_reason` whose rules live in `config/extraction_rules.py:FIELD_POLLUTION_RULES`.
3. `pipeline/field_normalization.py` assumes surfaces match keys in `config/field_mappings.py:CANONICAL_SCHEMAS`.

These are addressed by Slice 1 (single-owner surface contract) and Slice 2 (centralized noise rules).

## Data quality caveats

- Gemini flagged `DATALAYER_ECOMMERCE_FIELD_MAP` as "used implicitly" by `json_extractor.py` — Codex must confirm actual import before changes.
- `__getattr__` lazy loader claimed unused — but `__getattr__` is called by attribute access, not imports. Grep for literal `REQUESTED_FIELD_ALIASES` access on the `field_mappings` module specifically.
- "Unused" designations are static. Celery task registrations and dynamic string-to-function maps can hide usage. Each deletion in Slice 0 is grep-gated.

## What this unlocks

After Slices 0-2 complete, the policy module shape will be:
- **config** — pure data: alias tables, canonical schemas, noise rule-data, source ranking.
- **services/field_policy/** (new or consolidated from existing) — pure functions operating on config data.
- **extract/** — uses field_policy, no circular dependency, no re-implementation of noise rules.
- **pipeline/field_normalization.py** — consumes field_policy, owns persistence/contract enforcement only.

This is the foundation for Phase 2 (collapse duplicate extractors), Phase 3 (extract real `unify/` module), and ultimately Phase 5 (backfill + scorer per new Invariant 6).
