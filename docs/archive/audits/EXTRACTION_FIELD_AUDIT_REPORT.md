Audit Report: Inline Config Violations + Variant/Noise Removal Patching
1. Inline Config Violations (AP-1)
Per @/c:/Projects/pre_poc_ai_crawler/docs/ENGINEERING_STRATEGY.md:103-105 — AP-1: Inline config: tunables must live in app/services/config/*, not in service bodies.

Confirmed Violations
File	Lines	Inline Constant	Should Be In
@/c:/Projects/pre_poc_ai_crawler/backend/app/services/field_value_dom.py:58-67	58-67	_CROSS_LINK_CONTAINER_HINTS — hardcoded tuple of 7 tokens	config/extraction_rules or config/surface_hints
@/c:/Projects/pre_poc_ai_crawler/backend/app/services/field_value_dom.py:68-78	68-78	_PRODUCT_GALLERY_CONTEXT_HINTS — 9 tokens	config/extraction_rules
@/c:/Projects/pre_poc_ai_crawler/backend/app/services/field_value_dom.py:79-95	79-95	_NON_PRODUCT_IMAGE_HINTS — 16 tokens	config/extraction_rules
@/c:/Projects/pre_poc_ai_crawler/backend/app/services/field_value_dom.py:96-104	96-104	_NON_PRODUCT_PROVIDER_HINTS — 6 tokens	config/extraction_rules
@/c:/Projects/pre_poc_ai_crawler/backend/app/services/acquisition/browser_detail.py:10-26	10-26	_DETAIL_BLOCKED_TOKENS — 16 commerce action tokens	config/extraction_rules (already has BROWSER_DETAIL_EXPAND_KEYWORDS but not blocked tokens)
@/c:/Projects/pre_poc_ai_crawler/backend/app/services/acquisition/browser_runtime.py:107-117	107-117	_DETAIL_EXPAND_SELECTORS — 9 CSS selectors	config/extraction_rules
@/c:/Projects/pre_poc_ai_crawler/backend/app/services/acquisition/browser_runtime.py:122-134	122-134	_DETAIL_EXPAND_KEYWORD_EXTENSIONS — ecommerce/job keyword extensions	config/extraction_rules (partially derived from config but extensions are hardcoded)
@/c:/Projects/pre_poc_ai_crawler/backend/app/services/extract/shared_variant_logic.py:16-35	16-35	_VARIANT_AXIS_SKIP_TOKENS (8), _VARIANT_VALUE_SKIP_TOKENS (7)	config/extraction_rules
@/c:/Projects/pre_poc_ai_crawler/backend/app/services/extract/shared_variant_logic.py:36-53	36-53	_VARIANT_SELECT_GROUP_SELECTOR, _VARIANT_CHOICE_GROUP_SELECTOR — CSS selectors for DOM variant cues	config/extraction_rules or config/surface_hints
@/c:/Projects/pre_poc_ai_crawler/backend/app/services/confidence.py:8-29	8-29	_SURFACE_WEIGHTS — per-surface field weight dicts with magic floats	config/extraction_rules or config/runtime_settings
@/c:/Projects/pre_poc_ai_crawler/backend/app/services/confidence.py:31-46	31-46	_SOURCE_TIERS — 12 source tier quality scores	config/extraction_rules or config/runtime_settings
@/c:/Projects/pre_poc_ai_crawler/backend/app/services/detail_extractor.py:100-118	100-118	_DOM_HIGH_VALUE_FIELDS, _DOM_OPTIONAL_CUE_FIELDS — per-surface field sets	config/field_mappings.py or config/surface_hints
@/c:/Projects/pre_poc_ai_crawler/backend/app/services/detail_extractor.py:120-156	120-156	_ECOMMERCE_DETAIL_JS_STATE_FIELDS, _VARIANT_DOM_FIELD_NAMES — field sets	config/field_mappings.py
@/c:/Projects/pre_poc_ai_crawler/backend/app/services/detail_extractor.py:84-99	84-99	_SOURCE_PRIORITY — 13-element source ordering tuple	config/extraction_rules
@/c:/Projects/pre_poc_ai_crawler/backend/app/services/extract/listing_candidate_ranking.py:101	101	Magic threshold score >= 18 for "strong record"	config/runtime_settings
@/c:/Projects/pre_poc_ai_crawler/backend/app/services/extraction_runtime.py:291-292	291-292	_MIN_FIELD_OVERLAP_RATIO = 0.25, _MIN_FIELD_OVERLAP_ABSOLUTE = 2	config/runtime_settings
Summary: 17+ inline config violations across 6 files. The worst offenders are field_value_dom.py (4 tuples of hint tokens), detail_extractor.py (5 field sets/priority tuples), and confidence.py (2 weight dicts). All of these should be in app/services/config/*.

2. Variant Builder + Noise Removal Patching Audit
What the agent built
The git diff shows 775 lines of new code across 4 new files in extract/:

shared_variant_logic.py — 203 lines added (was ~13 lines, now 254)
listing_candidate_ranking.py — 167 lines (entirely new)
listing_visual.py — 255 lines (entirely new)
detail_tiers.py — 150 lines (entirely new)
Plus significant additions to field_value_dom.py (~200 lines of section extraction) and detail_extractor.py (variant DOM extraction).

The core problem: noise filters to fix garbage that shouldn't exist
The pattern is clear:

shared_variant_logic.py added variant_axis_name_is_noise(), variant_value_is_noise(), variant_node_is_noise() — 3 noise-filter functions with hardcoded skip-token lists (_VARIANT_AXIS_SKIP_TOKENS, _VARIANT_VALUE_SKIP_TOKENS)
Why these exist: The variant extraction from DOM (_extract_variants_from_dom in detail_extractor.py) and from structured sources (field_value_candidates.py) pulls in garbage axes like "1_answers_to_question_will_the_7_cup_model_chop_cooked_pork..." (visible in the audit report at line 13 of EXTRACTION_FIELD_AUDIT_REPORT.md). Instead of fixing the upstream extraction to not produce these garbage axes, the agent added noise filters to clean them up downstream.
The text_sanitization.py file was deleted — it was a noise-removal module that imported from config/extraction_rules (CANDIDATE_UI_NOISE_TOKEN_PATTERN, CANDIDATE_SCRIPT_NOISE_PATTERN, etc.). Its removal means noise filtering was partially scattered into the variant logic instead of being centralized.
Does the patching actually help extraction?
Minimal impact. Here's why:

Feature	Lines Added	Actual Extraction Value	Problem
variant_axis_name_is_noise()	~10	Low — filters out review/FAQ axes that shouldn't be extracted as variant axes in the first place	Upstream fix needed: DOM variant extraction should not treat Q&A sections as variant groups
variant_value_is_noise()	~10	Low — filters "select", "choose", date patterns	These values come from placeholder <option> text; should be filtered at extraction time, not post-hoc
variant_node_is_noise()	~8	Near zero — only checks if "copy" is in node attributes	Extremely narrow filter; unlikely to fire in practice
resolve_variants() (Cartesian product)	~47	Medium — correctly pairs size×color for Salesforce/Magento schemas	This is the only genuinely useful addition; it fixes real variant matrix resolution
_VARIANT_SELECT_GROUP_SELECTOR / _VARIANT_CHOICE_GROUP_SELECTOR	~18	Medium — CSS selectors for variant DOM cues	Good selectors but hardcoded (AP-1); should be in config
listing_visual.py (255 lines)	255	Low-Medium — visual layout clustering for listing records	Complex spatial clustering that adds a _source: "visual_listing" path — but the ranking code penalizes it (score -= 6) suggesting it produces low-quality results
listing_candidate_ranking.py (167 lines)	167	Low — scoring heuristics with magic numbers	score >= 18 threshold, weight values like +6, -8, -12, +4 are all hardcoded; this is a scoring layer compensating for poor candidate quality
The anti-pattern: AP-2 (Downstream Compensation)
Per @/c:/Projects/pre_poc_ai_crawler/docs/ENGINEERING_STRATEGY.md:107-110:

AP-2: Downstream compensation — Adding a fallback in downstream code to handle malformed field values that should have been caught upstream. Fix: Trace the bad value to its source and fix it there.

The variant noise filters are textbook AP-2. The real fixes needed (per the audit report's own recommendations at lines 43-51):

_apply_dom_fallbacks should detect variant widgets (<<select>, swatch buttons) and extract them as structured variant data — not as raw text that then needs noise filtering
direct_record_to_surface_fields should map sizes→variants, colors→variants, options→variants — these keys aren't in the alias lookup
JSON-LD variant extraction should use hasVariant properly instead of producing garbage axes from Q&A content
What should be kept vs. removed
Code	Verdict
resolve_variants() (Cartesian product)	Keep — genuine fix for variant matrix resolution
split_variant_axes()	Keep — useful axis classification
variant_dom_cues_present() + selectors	Keep but move selectors to config
infer_variant_group_name() / resolve_variant_group_name()	Keep — reasonable DOM attribute inference
variant_axis_name_is_noise()	Remove — fix upstream instead (Now I have a thorough picture. Let me compile the audit.
Audit Report: Two Issues from Recent Agent Changes
1. Inline Config Violations (AP-1)
The ENGINEERING_STRATEGY.md anti-pattern AP-1 is clear: "Adding TIMEOUT = 30 or PLATFORM_RETRIES = 3 directly in service/extractor code. Fix: Move to app/services/config/ and import it."

The following files now have hardcoded config that violates this rule:

Critical Violations
File	Line(s)	Inline Constant	Should Be In
@/backend/app/services/field_value_dom.py:58-67	_CROSS_LINK_CONTAINER_HINTS	("cross-sell", "crosssell", "grid", "related", "recommend", "similar", "upsell", "widget")	config/extraction_rules
@/backend/app/services/field_value_dom.py:68-78	_PRODUCT_GALLERY_CONTEXT_HINTS	("carousel", "gallery", "media", "pdp", "photo", "product", "slider", "thumb", "zoom")	config/extraction_rules
@/backend/app/services/field_value_dom.py:79-95	_NON_PRODUCT_IMAGE_HINTS	("avatar", "badge", "blog", "brand", "breadcrumb", "flag", "icon", "logo", "payment", "placeholder", "promo", "rating", "review", "social", "sprite")	config/extraction_rules
@/backend/app/services/field_value_dom.py:96-104	_NON_PRODUCT_PROVIDER_HINTS	("affirm", "amex", "american express", "klarna", "mastercard", "paypal", "visa")	config/extraction_rules
@/backend/app/services/acquisition/browser_detail.py:10-26	_DETAIL_BLOCKED_TOKENS	("add to cart", "add to bag", "bag", "buy now", ...)	config/extraction_rules
@/backend/app/services/acquisition/browser_runtime.py:107-117	_DETAIL_EXPAND_SELECTORS	("summary", "details > summary", "[aria-expanded='false']", ...)	config/extraction_rules
@/backend/app/services/acquisition/browser_runtime.py:122-134	_DETAIL_EXPAND_KEYWORD_EXTENSIONS	{"ecommerce": ("care", "composition", ...)}	config/extraction_rules
@/backend/app/services/confidence.py:8-29	_SURFACE_WEIGHTS	{"ecommerce_detail": {"title": 0.2, "price": 0.15, ...}}	config/extraction_rules or config/runtime_settings
@/backend/app/services/confidence.py:31-46	_SOURCE_TIERS	{"adapter": ("authoritative", 1.0), ...}	config/extraction_rules
@/backend/app/services/detail_extractor.py:100-118	_DOM_HIGH_VALUE_FIELDS, _DOM_OPTIONAL_CUE_FIELDS	Surface→field-set mappings	config/field_mappings or config/extraction_rules
@/backend/app/services/detail_extractor.py:120-156	_ECOMMERCE_DETAIL_JS_STATE_FIELDS, _VARIANT_DOM_FIELD_NAMES	Frozensets of field names	config/field_mappings
@/backend/app/services/detail_extractor.py:158-179	_field_source_rank() inline dict title_source_ranks	{"adapter": 0, "network_payload": 1, ...}	config/extraction_rules
@/backend/app/services/extract/shared_variant_logic.py:16-35	_VARIANT_AXIS_SKIP_TOKENS, _VARIANT_VALUE_SKIP_TOKENS	Noise token tuples	config/extraction_rules
@/backend/app/services/extract/shared_variant_logic.py:36-53	_VARIANT_SELECT_GROUP_SELECTOR, _VARIANT_CHOICE_GROUP_SELECTOR	CSS selector strings	config/extraction_rules
@/backend/app/services/extraction_runtime.py:291-292	_MIN_FIELD_OVERLAP_RATIO = 0.25, _MIN_FIELD_OVERLAP_ABSOLUTE = 2	Thresholds	config/runtime_settings
@/backend/app/services/selector_self_heal.py:23	_SELECTOR_SYNTHESIS_MAX_HTML_CHARS = 200_000	Size limit	config/runtime_settings
@/backend/app/services/extract/listing_candidate_ranking.py:101	score >= 18 (magic number for "strong record")	Threshold	config/extraction_rules
Summary: The agent added 17+ inline config constants across 8 files. Some of these partially pull from config/extraction_rules (like _SECTION_LABEL_SKIP_TOKENS which reads SEMANTIC_SECTION_NOISE), but then the agent also added hardcoded tuples right next to them (_CROSS_LINK_CONTAINER_HINTS, _PRODUCT_GALLERY_CONTEXT_HINTS, etc.) that don't use config at all. This is the classic AP-1 pattern: some config is externalized, then more is added inline because it's "easier."

2. Variant Builder + Noise Removal Audit
What the Agent Built
The agent's objective (from EXTRACTION_FIELD_AUDIT_REPORT.md): extract variants and missing data from ecommerce detail pages. Variants coverage was 10% (2/20 detail runs).

What was added in extract/shared_variant_logic.py (203 new lines):
variant_dom_cues_present() — checks if soup has <select> or swatch elements
infer_variant_group_name() — probes DOM attributes to guess "color" or "size"
resolve_variant_group_name() — picks best name from attributes, with noise filtering
variant_axis_name_is_noise() — rejects axis names >48 chars, >6 words, or containing FAQ/review tokens
variant_value_is_noise() — rejects values like "select", "choose", dates, review noise
variant_node_is_noise() — rejects nodes with "copy" in attributes
split_variant_axes() — splits axes into multi-value (selectable) vs single-value
resolve_variants() — Cartesian product resolution of variant matrix
The noise removal chain:
extraction_context.py:42-52 — NOISE_CONTAINER_REMOVAL_SELECTOR decomposes noise containers from HTML before extraction
field_value_dom.py:109-136 — _SECTION_LABEL_SKIP_TOKENS and _SECTION_SKIP_PATTERNS (from SEMANTIC_SECTION_NOISE config) filter section headings and content
shared_variant_logic.py:121-154 — Three *_is_noise() functions that filter variant axes, values, and nodes
Assessment: Does This Actually Help Extraction?
Short answer: The variant DOM logic is structurally sound but the noise removal is a band-aid over the real problem.

What works:
resolve_variants() (Cartesian product) — This is genuinely useful. The Shopify adapter was producing mismatched option1/option2 arrays vs variant rows. The Cartesian resolver fixes that correctly.
split_variant_axes() — Correctly distinguishes selectable axes (multi-value → variants) from single-value attributes (→ product fields like color: "Red"). This is a real extraction improvement.
variant_dom_cues_present() — Simple detection, no harm.
What doesn't work / is wasted effort:
variant_axis_name_is_noise() and variant_value_is_noise() — These are post-hoc garbage filters. The real question is: why is garbage getting into the candidate pool in the first place? The answer is that infer_variant_group_name() and DOM traversal are too aggressive — they grab FAQ sections, review nodes, and shipping info as "variant axes." Instead of fixing the DOM selector specificity, the agent added noise filters to clean up the mess.Root cause: _VARIANT_SELECT_GROUP_SELECTOR and _VARIANT_CHOICE_GROUP_SELECTOR are overly broad. [class*='variant' i] matches any element with "variant" in its class — including "variant-review", "variant-answer", etc. The fix should be tighter selectors, not downstream noise removal.
_VARIANT_AXIS_SKIP_TOKENS / _VARIANT_VALUE_SKIP_TOKENS — These are hardcoded inline config (AP-1 again). And they're a losing game: every new site will produce new garbage tokens that need adding. The KitchenAid example in the audit report shows this perfectly — the axis name was "1_answers_to_question_will_the_7_cup_model_chop_cooked_pork..." which got through because none of the skip tokens matched.
The noise removal in extraction_context.py (NOISE_CONTAINER_REMOVAL_SELECTOR) — This is a pre-extraction DOM cleanup that removes nav, footer, cookie banners etc. before parsing. This is fine and useful — it's not the problematic kind of noise removal.
_SECTION_LABEL_SKIP_TOKENS / _SECTION_SKIP_PATTERNS in field_value_dom.py — These filter section headings during extract_heading_sections(). The section extraction itself was significantly improved (accordion-aware, ARIA-controls following, container selectors). But the skip tokens are again inline config and will need constant updating.
The Core Problem
The audit report's own root cause analysis was correct:

Root Cause 1: No DOM extraction for variant widgets — _apply_dom_fallbacks has no logic for <select>, swatch buttons, or variant attribute groups.

The agent's response was to build:

DOM cue detection ✅ (needed)
Variant name inference ⚠️ (too broad → needs noise removal to compensate)
Noise removal filters ❌ (band-aid, not root cause fix)
Cartesian variant resolution ✅ (genuinely useful)
What should have been done instead: Add targeted variant extraction to _apply_dom_fallbacks that specifically handles <select name*=size/color>, swatch button groups with data-option-name, and [role=radiogroup] containers — with narrow selectors that don't capture FAQ/review DOM in the first place. No noise removal needed if the selectors are specific.

The "Garbage In → Noise Removal Out" Cycle
This is exactly the pattern the agent fell into:

Broad selectors → garbage in candidates → noise filters to clean up → 
  noise filters miss new garbage → add more noise tokens → repeat
The EXTRACTION_FIELD_AUDIT_REPORT.md line 13 shows the result: KitchenAid extracted an axis named "1_answers_to_question_will_the_7_cup_model_chop_cooked_pork_into_a_small_size..." — this got through all the noise filters because it doesn't contain any of the skip tokens. A tighter selector would never have picked up a Q&A section as a variant axis.

Summary
Issue	Severity	Count	Verdict
Inline config (AP-1)	High	17+ constants across 8 files	Must move to config/
Variant noise removal	Medium	3 *_is_noise() functions + 2 skip-token tuples	Band-aid; fix selectors upstream
Cartesian variant resolution	Good	resolve_variants()	Keep — genuine fix
Section extraction upgrade	Good	Accordion/ARIA-aware extract_heading_sections()	Keep — real improvement
text_sanitization.py	Good	Deleted (was unused noise removal layer)	Correct removal
New files added	Mixed	4 new files (775 lines) in extract/	shared_variant_logic.py partially useful; listing_visual.py and listing_candidate_ranking.py are new listing recovery code (separate concern)