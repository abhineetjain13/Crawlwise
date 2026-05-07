Q1 — Execution Flow: What Calls What, In What Order
The pipeline has three distinct entry tiers but no single orchestrator file — callers (detail_extractor.py, DOM completers) wire the stages together ad-hoc:

text
[Caller: detail_extractor.py / dom_completer]
    │
    ├─1─► extraction_context.prepare_extraction_context(html)
    │         Runs Lexbor noise removal → returns frozen ExtractionContext
    │
    ├─2─► extraction_context.collect_structured_source_payloads(context, page_url)
    │         Parses JSON-LD, Microdata, OpenGraph, embedded JSON, JS state
    │         Returns tuple of (source_name, [payload_dicts])
    │
    ├─3─► field_policy.get_surface_field_aliases(surface)  [once per run]
    │         Builds alias_lookup: {"normalized_key": "canonical_field"}
    │
    ├─4─► field_value_candidates.collect_structured_candidates(payload, alias_lookup, ...)
    │         Walks each structured payload dict recursively
    │         Calls field_value_core.coerce_field_value() on each value
    │         Calls field_policy.normalize_field_key() on every key
    │         Populates candidates dict: {"field_name": [raw_values]}
    │
    ├─5─► field_value_dom.extract_*(context.soup, ...)  [for DOM-sourced fields]
    │         extract_label_value_pairs, extract_heading_sections, extract_page_images
    │         Also calls field_policy.normalize_field_key / normalize_requested_field
    │         Also calls field_value_core.coerce_field_value, add_candidate
    │         Also calls field_value_candidates.add_candidate directly
    │
    ├─6─► field_value_candidates.finalize_candidate_value(field, values)
    │         Merges multi-source candidates per field type
    │         (STRUCTURED_OBJECT, STRUCTURED_MULTI, LONG_TEXT, scalar)
    │
    ├─7─► field_value_core.coerce_field_value(field, value, page_url)  [final coerce]
    │         Large dispatcher → field-specific coercers
    │
    ├─8─► field_url_normalization  [called inside coerce_field_value for URL fields]
    │         normalize_image_url, normalize_page_url
    │
    └─9─► field_value_core.validate_record_for_surface / finalize_record
              Surface field gating, clean_record, template URL removal
Q2 — Is ExtractionContext a True Context Object or a Data Bag?
It is a frozen data bag with one lazy-computed property, not a true context object. The ExtractionContext dataclass holds three pre-computed artifacts (original_html, cleaned_html, dom_parser) and lazily materializes a BeautifulSoup object on first access via soup. It has no methods, no pipeline state, no field tracking, and no mutation.

The critical design problem is the lazy soup property on a frozen=True dataclass — it uses object.__setattr__ to bypass the freeze, which is a documented anti-pattern for frozen=True. This works but it means ExtractionContext is neither truly immutable nor truly mutable.

prepare_extraction_context is called at the top of extraction pipelines, and the resulting object is threaded through every stage as a parameter — collect_structured_source_payloads(context, ...), DOM functions receive context.soup or context.cleaned_html individually. No stage mutates the context. It is never enriched with partial results as the pipeline progresses, which means there is no single place that shows "what has been found so far." That state lives in the caller-owned candidates: dict[str, list[object]] dict instead.

Q3 — Do field_value_core.py and field_value_dom.py Overlap?
They overlap significantly in three directions:

Concern	In field_value_core.py	In field_value_dom.py
Coerce dispatch	coerce_field_value (200-line dispatcher)	Calls coerce_field_value for every DOM-extracted value
URL handling	absolute_url, extract_urls, URL field coercers	absolute_url re-imported + image URL normalization functions live here
add_candidate	Not in core	DOM functions call field_value_candidates.add_candidate directly — bypassing core entirely
Surface alias	surface_alias_lookup defined in core	field_value_dom imports and calls it for section extraction
Image URL fields	_is_placeholder_image_url stranded in core	All other image URL logic in dom
field_value_core.py is not the orchestrator — it is the coercion library. field_value_dom.py is not purely DOM-specific either — it contains field-matching logic (which fields are long-text, which are image fields, which aliases apply) that properly belongs in field_policy.py. The actual orchestrator is the caller (detail_extractor.py) and there is no single pipeline coordinator file.

Q4 — Does field_policy.py Enforce Rules Before or After Candidate Generation?
Both, inconsistently. field_policy.py is called at three separate points:

Before candidates — get_surface_field_aliases(surface) produces the alias_lookup dict that controls which keys from structured payloads are accepted. This is a pre-filter gate.

During candidates — normalize_field_key and normalize_requested_field are called inline inside field_value_candidates.collect_structured_candidates on every payload key to decide whether to add a candidate.

After candidates, in DOM extraction — field_value_dom calls normalize_field_key and exact_requested_field_key during label/section extraction, which happens after structured candidates are already collected.

After finalization — field_value_core.validate_record_for_surface calls surface_fields() (imported from core, but backed by field_policy's CANONICAL_SCHEMAS) to gate which fields survive into the final record.

The policy is not a single gate — it is sprinkled as a utility across four stages. There is no point where "this candidate is ruled out by policy" is a named, explicit step.

Q5 — Where Is Field-Level Validation? Is It Typed (Pydantic) or Implicit?
Validation is implicit throughout, with no Pydantic in this pipeline. The validation pattern is:

coerce_field_value(field_name, value, page_url) — 200-line if field_name == "price": ... elif field_name == "sku": ... dispatcher. Each branch calls a type-specific coercer (_coerce_sku, _coerce_brand_text, coerce_rating_value, etc.) that returns None on failure.

finalize_record — calls clean_record which drops None/empty values, then validate_record_for_surface which gates fields against surface_fields().

field_value_candidates.finalize_candidate_value — merges multi-source lists but does no schema validation; it trusts coercers to have already normalized values.

No Pydantic is used. The field-level contracts are enforced by return-None-on-invalid conventions and frozenset membership checks against CANONICAL_SCHEMAS. This means:

Invalid field values that don't match a coercer's expectation silently become None and disappear — no validation error is raised or logged.

There is no schema document that describes expected types for each field; the type contract lives only in the coercer function bodies.

Q6 — Inline Heuristics in field_value_dom.py That Should Move to field_policy.py
field_value_dom.py contains these policy decisions hardcoded as constants or inline logic:

Heuristic	Current Location	Should Be In
SCOPE_SCORE_MAIN_WEIGHT, SCOPE_SCORE_PRIORITY_WEIGHT, SCOPE_SCORE_PRODUCT_CONTEXT_WEIGHT	Imported from config/extraction_rules but only consumed by DOM scope scoring	field_policy.py as named scoring policy, not raw weights
SEMANTIC_SECTION_NOISE / SEMANTIC_SECTION_LABEL_SKIP_TOKENS	extraction_rules config, used only in DOM section extraction	Should be co-located with field_policy.HTML_SECTION_FIELDS as "section eligibility policy"
NON_PRODUCT_IMAGE_HINTS / NON_PRODUCT_PROVIDER_HINTS	Used in _is_garbage_image_candidate inside dom	Image rejection policy — belongs as a named image_is_eligible(url) -> bool in field_policy or a dedicated image_policy.py
VARIANT_OPTION_TEXT_FIELDS	Controls which DOM fields trigger variant option node scanning	Variant field policy — belongs alongside field_policy.HTML_SECTION_FIELDS
DETAIL_LONG_TEXT_RANK_FIELDS, DETAIL_LONG_TEXT_MAX_SECTION_BLOCKS, DETAIL_LONG_TEXT_MAX_SECTION_CHARS	Long-text extraction limits	Long-text field policy — should be named constants in field_policy, not anonymous config integers
CROSS_LINK_CONTAINER_HINTS	Used in _is_garbage_image_candidate and section filtering	Cross-product noise policy — belongs in field_policy
Q7 — Current Flow vs Proposed Pipeline Contract
Current Flow (actual)
text
html
  │
  ▼
[extraction_context.prepare_extraction_context]
  Lexbor noise removal → ExtractionContext(frozen bag)
  │
  ├──► [extraction_context.collect_structured_source_payloads]
  │        JSON-LD + Microdata + OG + EmbeddedJSON + JS state
  │        → tuple of (source, [dicts])
  │
  │    [field_policy.get_surface_field_aliases]  ◄── called once by caller
  │        alias_lookup: {normalized_key → canonical}
  │
  ├──► [field_value_candidates.collect_structured_candidates]
  │        walks payloads recursively
  │        calls field_policy.normalize_field_key inline
  │        calls field_value_core.coerce_field_value inline
  │        → candidates dict (mutable, caller-owned)
  │
  ├──► [field_value_dom.extract_label_value_pairs / extract_heading_sections / extract_page_images]
  │        calls field_policy.normalize_field_key inline
  │        calls field_value_candidates.add_candidate directly
  │        calls field_value_core.coerce_field_value inline
  │        NO consistent return type — mutates caller's candidates dict as side effect
  │
  ├──► [field_value_candidates.finalize_candidate_value]   ◄── called per-field by caller
  │        merges multi-source lists → single value per field
  │
  ├──► [field_value_core.coerce_field_value]               ◄── called again per value
  │        field-specific coercers → typed scalar/list/dict or None
  │        calls field_url_normalization inline for URL fields
  │
  └──► [field_value_core.validate_record_for_surface + finalize_record]
           surface field gate + clean_record
           → final dict (untyped)
Problems with current flow:

No single orchestrator; callers wire stages themselves

DOM extraction mutates a shared candidates dict as a side effect — no return value

Policy checks happen at 4 different stages without a named "policy" step

coerce_field_value is called twice on many values (once during candidate collection, once during finalization)

Validation is silent → None with no error surface

Proposed Pipeline Contract
text
INPUT
─────
PageInput(html: str, page_url: str, surface: str, requested_fields: list[str])


STAGE 1 — PARSE
───────────────
extraction_context.prepare_extraction_context(html)
  → ExtractionContext
     .cleaned_html    (noise-pruned)
     .dom_parser      (Lexbor)
     .soup            (lazy BS4)


STAGE 2 — COLLECT CANDIDATES
─────────────────────────────
NEW: pipeline_candidates.collect_all_candidates(context, page_url, alias_lookup)
  Internally delegates to:
    field_value_candidates.collect_structured_candidates  ← structured sources
    field_value_dom.extract_dom_candidates                ← new unified DOM return
  Returns: CandidateSet(field_name → [RawCandidate(value, source, confidence)])
           (not a bare dict — typed, immutable after collection)


STAGE 3 — POLICY GATE  ← NEW explicit stage
────────────────────────
field_policy.apply_candidate_policy(candidates, surface, requested_fields)
  Applies:
    - field_allowed_for_surface (surface gate)
    - image_is_eligible (image noise policy — moved from dom)
    - section_field_eligible (long-text section policy — moved from dom)
    - variant_field_eligible (variant policy — moved from dom)
  Returns: PolicyFilteredCandidates (same type, subset)


STAGE 4 — FINALIZE PER FIELD
─────────────────────────────
field_value_candidates.finalize_candidate_value (unchanged)
  Merges multi-source lists → one value per field
  Returns: dict[str, object]


STAGE 5 — NORMALIZE
────────────────────
field_url_normalization.normalize_record_urls(record, page_url)
  Runs URL normalization on all URL-type fields in one pass
  (currently called piecemeal inside coerce_field_value)
  Returns: dict[str, object]


STAGE 6 — VALIDATE + OUTPUT
─────────────────────────────
field_value_core.finalize_record(record, surface)
  validate_record_for_surface + clean_record
  Returns: ExtractionOutput (typed TypedDict per surface, or plain dict)
  Validation errors → ExtractionWarning list (logged, not silent None)


OUTPUT
──────
ExtractionResult(
    record: dict[str, object],
    warnings: list[ExtractionWarning],
    candidate_sources: dict[str, str],   ← which source won per field
)
Priority Changes to Implement
Give DOM extraction functions a return value — currently field_value_dom functions mutate a passed-in candidates dict. They should return dict[str, list[object]] and the caller merges, making data flow explicit.

Create an explicit policy stage — move all inline normalize_field_key / field_allowed_for_surface calls out of collect_structured_candidates and DOM functions into a named apply_candidate_policy() call in field_policy.py.

Single coerce call per value — coerce_field_value is currently called during candidate collection and again during finalization for some paths; a RawCandidate type that defers coercion to Stage 4 eliminates the double-coerce.

Move image/section/variant eligibility logic from DOM into policy — the six heuristic clusters in Q6 become named policy functions with testable inputs/outputs rather than inline magic numbers.

Replace silent → None validation with ExtractionWarning — gives callers visibility into which fields were found-but-rejected versus never-found.