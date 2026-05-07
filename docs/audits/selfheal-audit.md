Now I have the full picture. Here is the complete production risk audit.

Q1 — When a Selector Fails in selectors_runtime.py: Raise, Fail Silently, or Heal?
It fails silently and returns None by default. The execution path is:

text
selectors_runtime.test_selector(html, css_selector=..., xpath=..., regex=...)
    └─► xpath_service.extract_selector_value(html, xpath=...)
            └─► lxml etree.fromstring() wrapped in try/except
                    on any parse/match failure → returns (None, 0, None)
    └─► _is_noise_value(value, field_name) → if noise, treat as None
    └─► returns {"value": None, "count": 0, ...}  # no exception raised
There is no automatic trigger to self-heal from within selectors_runtime.py. The runtime file only provides run_selector_synthesis as a standalone async function that callers invoke explicitly. The actual self-heal loop lives entirely in selector_self_heal.apply_selector_self_heal and is invoked from detail_extractor.py only after the full extraction pass has already completed. This means:

A selector can fail on every page for a domain for days before self-heal runs

test_selector (L498) is an ad-hoc API endpoint helper, not an internal health check

_is_noise_value at L745 silently drops values matching SELECTOR_NOISE_VALUES constants — this is a second silent failure mode with no logging

Q2 — Does selector_self_heal.py Use LLM? Is It Gated or Unbounded?
Yes, it calls discover_xpath_candidates from llm_runtime. There are two LLM call sites across these files:

File	Line	Function	Gate
selector_self_heal.py	265	apply_selector_self_heal	3 gates (see below)
selectors_runtime.py	432	run_selector_synthesis	1 gate only
apply_selector_self_heal — Gates Present
python
if (
    not enabled                         # Gate 1: run.settings_view.selector_self_heal.enabled
    or not run.settings_view.llm_enabled()  # Gate 2: run-level LLM kill switch
    or "detail" not in run.surface      # Gate 3: listing pages excluded
):
    return records, selector_rules
There is then a per-record confidence threshold gate:

python
if confidence_score >= threshold and not requested_missing_fields:
    updated_records.append(next_record)
    continue  # skip LLM for this record
Critical Unbounded Risk: No Per-Domain Call Limit
The gates above are per-run and per-record, but there is no per-domain, per-day, or per-hour call budget. The flow is:

text
For each record in records:  ← this loop has no max
    if target_fields exist:
        await discover_xpath_candidates(...)  ← one LLM call per record
If a crawl run returns 50 records (e.g., a paginated detail re-crawl) and all records have low confidence, this issues 50 LLM calls in a single run. No circuit breaker, no domain-level daily limit, no cost cap.

run_selector_synthesis in selectors_runtime.py — Weakly Gated
python
llm_candidates, llm_error = await discover_xpath_candidates(...)
This function has one implicit gate: it is only called if the caller passes domain and surface. There is no llm_enabled() check here — it relies entirely on the API endpoint caller to gate it. If this is exposed via a webhook or background job it can fire without the run-level LLM switch.

⚠️ Unbounded Cost Vectors
No per-domain daily cap on LLM calls from apply_selector_self_heal

No deduplication check: if the same domain's selector already failed yesterday and was healed with a saved rule, and that rule fails again today, LLM fires again — existing_rule_count > 0 only skips if requested_missing_fields is also empty; one missing field re-triggers

run_selector_synthesis in selectors_runtime.py has no llm_enabled() guard — bypasses the CrawlRun kill switch

Q3 — Is js_state_mapper.py (48KB, 54 functions) Covering Too Many Site-Specific Cases Inline?
Yes. The file has two distinct problems:

Problem 1 — Dual Responsibility
js_state_mapper.py does schema mapping (its stated job) and site-specific detection/normalization (not its job):

Concern	Functions	Should Be In
JS state schema mapping	map_js_state_to_fields, _map_ecommerce_detail_state, _map_job_detail_state, _map_configured_state_payload	Here (core job)
Payload detection/scoring	_looks_like_product_payload (55 lines), _product_payload_score (80 lines), _find_product_payloads, _find_product_payload	js_state/payload_detector.py
Shopify-specific detection	_looks_like_shopify_product (19 lines), interpret_integral_as_cents=shopify_like scattered through price logic	platform_policy.py
Nuxt-specific revival	_revive_nuxt_data_array	js_state/platform_revivers.py
Variant normalization	_normalize_variant (93 lines), _variant_axis_value, _variant_selection_values (55 lines), _variant_option_values (113 lines), _option_value_labels (59 lines)	js_state/variant_mapper.py
Product deduplication	_dedupe_product_payloads, _merge_same_product_record, _merge_variant_fields, _mapped_product_identity_matches, _mapped_product_family_matches	js_state/product_deduper.py
Price extraction	_raw_current_price_value, _raw_original_price_value, _discounted_percentage_price, _contextual_numeric_value, _raw_numeric_value, _raw_currency_value	js_state/price_extractor.py
Image extraction	_extract_product_images, _extract_nested_image_urls	dom/image_url_utils.py (already exists)
Problem 2 — Platform Dispatch Already Partially Externalized but Incomplete
_map_platform_job_detail_state correctly delegates to platform_policy.platform_js_state_extractors(). But _map_ecommerce_detail_state has its own inline platform detection loop (L237) that duplicates the pattern but is not backed by the same platform_policy abstraction — ecommerce platforms are detected by inline heuristics in _looks_like_product_payload (checking for variants, options, compare_at_price key presence) rather than named platform families.

Q4 — Is There a Test Fixture System for Selectors?
No. There is only one reference to test_selector in these files and it is a live API endpoint function in selectors_runtime.py (L498) that runs an XPath/CSS against a live-fetched or passed HTML document. There is no:

Frozen HTML snapshot directory (tests/fixtures/html/)

Expected field output files (tests/fixtures/expected/)

pytest parametrize or conftest.py fixture loading for selector regressions

Snapshot comparison of js_state_mapper output against known JS state payloads

The only regression safety net today is _validated_xpath_rules in selector_self_heal.py which runs XPath candidates against the current page HTML at heal-time — this is a live validation, not a frozen regression test.

Q5 — Failure Budget: How Many Failed Fields Before a Run Is Considered Failed?
There is no named failure budget. The closest approximations are:

SELECTOR_SELF_HEAL_DEFAULT_MIN_CONFIDENCE — config constant that sets the confidence score floor below which self-heal triggers; read as a float, default appears to be 0.6 from usage context. But this is a trigger for healing, not a declaration of run failure.

confidence_score >= threshold — if score is above threshold and no explicitly requested fields are missing, the record is accepted regardless of how many non-requested fields are null.

SELECTOR_SELF_HEAL_TARGET_LIMIT — capped at 6 fields maximum targeted per self-heal attempt; this is a repair limit, not a failure budget.

selector_self_heal_targets returns up to target_limit fields, priority-ordered by requested_fields first, then missing_fields from confidence metadata.

No code path causes a crawl run to be marked failed or degraded based on field miss rate. Runs complete with whatever fields were found, and downstream consumers receive records with nulls for missed fields.

Q6 — Proposed Selector Health Metric + Fallback Policy
Selector Health Metric Per Domain
python
# New: domain_selector_health.py
@dataclass
class SelectorHealthSnapshot:
    domain: str
    surface: str
    window_days: int                    # rolling window (default: 7)
    total_records_crawled: int
    total_field_attempts: int           # sum of requested_fields × records
    field_hit_rates: dict[str, float]   # {"price": 0.94, "title": 1.0, "sku": 0.43}
    critical_field_miss_rate: float     # miss rate on critical_fields only
    self_heal_trigger_rate: float       # fraction of records that triggered LLM
    self_heal_success_rate: float       # fraction of LLM calls that improved record
    llm_calls_last_24h: int             # for cost monitoring
    health_status: Literal["healthy", "degraded", "broken"]

CRITICAL_FIELDS_BY_SURFACE = {
    "ecommerce_detail": {"title", "price", "image_url"},
    "job_detail": {"title", "company", "location"},
}

def compute_health_status(snap: SelectorHealthSnapshot) -> str:
    if snap.critical_field_miss_rate > 0.40:
        return "broken"
    if snap.critical_field_miss_rate > 0.15 or snap.self_heal_trigger_rate > 0.30:
        return "degraded"
    return "healthy"
This snapshot should be computed from the _confidence metadata already written to records, with no new DB schema needed.

Proposed Fallback Policy (Current vs Proposed)
Current (implicit, unordered):

text
Selector attempt → silent None OR LLM synthesis (if enabled + confidence < threshold)
Proposed (explicit 4-stage fallback ladder):

text
STAGE 1 — SELECTOR EXECUTION
  Run stored CSS/XPath/regex rules from domain_memory
  On match: record value + update selector hit-count metric
  On miss (None OR noise value): → STAGE 2

STAGE 2 — HEURISTIC FALLBACK
  Run field_value_dom.extract_label_value_pairs + extract_heading_sections
  (DOM label/section scanning — already exists, currently runs in parallel, not as fallback)
  On match: record value, flag as source="heuristic", write to domain health log
  On miss: → STAGE 3

STAGE 3 — LLM SYNTHESIS (GATED)
  Gate conditions (ALL must pass):
    ✓ run.settings_view.llm_enabled()
    ✓ selector_self_heal.enabled == True
    ✓ "detail" in surface
    ✓ domain.llm_calls_today < LLM_DAILY_DOMAIN_CAP  ← NEW
    ✓ field is in CRITICAL_FIELDS_BY_SURFACE          ← NEW: LLM only for critical fields
    ✓ existing_rule_count == 0 OR last_heal_at > 7 days ago  ← NEW: re-heal cooldown
  On synthesized + validated XPath: save to domain_memory, flag source="llm_synthesized"
  On LLM failure/no valid XPath: → STAGE 4

STAGE 4 — NULL + ALERT
  field value = None
  Emit ExtractionWarning(field=..., stage_reached="null", domain=..., surface=...)
  If critical_field_miss_rate crosses threshold:
    → emit domain_health_alert (webhook / internal queue)
    → set domain health_status = "broken"
    → suppress further LLM attempts for this domain until manual review
Key Implementation Changes Required
Change	File	Impact
Change	File	Impact
Add LLM_DAILY_DOMAIN_CAP check before discover_xpath_candidates	selector_self_heal.py L263	Prevents unbounded cost
Add llm_enabled() guard to run_selector_synthesis	selectors_runtime.py L432	Closes the kill-switch bypass
Add per-domain LLM call counter to domain_memory or a Redis key	domain_memory_service.py	Enables cap enforcement
Add re-heal cooldown check (last_heal_at)	selector_self_heal.py	Prevents daily re-trigger on same broken selector
Add critical_field_miss_rate alert emission	selector_self_heal.py post-loop	Enables ops visibility
Restrict LLM to CRITICAL_FIELDS_BY_SURFACE only	selector_self_heal_targets() L189	Reduces token cost per trigger
Run DOM heuristic (label/section scan) as Stage 2 before LLM	apply_selector_self_heal	Reduces LLM trigger rate
Emit ExtractionWarning on Stage 4 null (not silent)	selector_self_heal.py	Gives callers null visibility