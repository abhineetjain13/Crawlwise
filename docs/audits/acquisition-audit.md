I now have the full picture of all layers. Here is the complete audit.

Q1 — What Is an "Acquisition Plan"?
An AcquisitionPlan is a resolved, immutable crawl strategy object — it is neither a URL queue nor a raw job config. It is the normalized, runtime-bound decision of how to crawl a set of URLs: which surface, which proxies, traversal mode, pacing, record limits. It is a 32-line @dataclass(slots=True) with defaults pulled from crawler_runtime_settings at class definition time.

The lifecycle is: CrawlRun.settings_view.acquisition_plan(surface, max_records) → AcquisitionPlan → passed into URLProcessingConfig.from_acquisition_plan() → used by _batch_runtime.process_run. It does not hold URLs; URLs are resolved separately in _batch_runtime._resolve_run_urls. It is a scraping strategy config, not a queue.

One design risk: defaults are evaluated at import time (max_pages: int = crawler_runtime_settings.default_max_pages), not at instantiation time. If crawler_runtime_settings is mutated after import (e.g., in tests), AcquisitionPlan field defaults will not reflect the new values.

Q2 — What Is domain_run_profile_service.py Doing at 787 Lines?
It is the domain-intelligence persistence brain — responsible for learning, storing, normalizing, and merging per-domain crawl strategies across runs. Its 787 lines cover five distinct concerns:

Concern	Functions	Lines
Schema normalization — validate/coerce raw profile dicts into typed shapes	normalize_acquisition_contract, normalize_domain_run_profile	~160
Staleness logic — decide when a learned contract is no longer trusted	acquisition_contract_is_stale	~12
Contract mutation — apply outcomes (success/failure) to update the contract	apply_acquisition_contract_to_profile, build_success_acquisition_contract, note_acquisition_contract_failure	~130
Profile merging — merge saved DB profile with run-level overrides	merge_saved_run_profile, _merge_profile_section, _merge_acquisition_contract	~130
DB persistence — load/save DomainRunProfile rows	load_domain_run_profile, save_domain_run_profile, list_domain_run_profiles	~100
Runtime recipe resolution — produce the final AcquisitionPlan for a URL	resolve_url_acquisition_recipe, record_acquisition_contract_outcome	~120
It is the "config brain" you suspected. The fact that normalization (pure functions), DB access, and runtime recipe resolution are all here is why it is 787 lines. It should be split along those concern boundaries.

Q3 — What Does domain_memory_service.py Store?
It stores per-domain, per-surface learned CSS/XPath/regex selector rules only. The DomainMemory ORM model holds a selectors JSONB column structured as:

json
{
  "_meta": {"next_id": 14},
  "rules": [
    {"id": 1, "field_name": "price", "xpath": "//span[@data-price]", "sample_value": "$29.99", "source": "selector_self_heal", "is_active": true},
    ...
  ]
}
It is not a full crawl history log. It contains no timestamps of past crawl results, no per-URL outcomes, no field coverage history. Its sole purpose is to persist LLM-synthesized or user-provided selectors so they survive across runs. It also handles the legacy format (field-name-keyed dicts) vs the current rules-list format via selector_rules_from_memory's fallback branch.

The service also supports a "generic" surface fallback in load_domain_selector_rules — if no surface-specific rules exist, it falls back to rules stored under surface="generic", providing cross-surface selector inheritance.

Q4 — Are platform_policy.py and robots_policy.py Enforced on Every Request or Only at Job Setup?
robots_policy.py — enforced per-URL at fetch time, with a TTL cache.

The pattern is:

python
_ROBOTS_CACHE: TTLCache[str, _RobotsSnapshot] = TTLCache(
    maxsize=crawler_runtime_settings.robots_cache_size,
    ttl=crawler_runtime_settings.robots_cache_ttl,
)
check_robots_policy(url) is called from acquisition/policy.py before each fetch attempt. The TTL cache deduplicates robots.txt fetches per domain; a cache miss fetches the file fresh. There is in-flight deduplication via _ROBOTS_INFLIGHT_FETCHES to prevent stampede. The enforcement is per-request but cached — a cache hit means no network call, but the policy decision is re-evaluated on every URL.

platform_policy.py — enforced only at job setup / profile resolution.

platform_js_state_extractors(platform) and detect_platform_family(url) are called during domain profile resolution and JS state mapping — not on every HTTP request. Platform detection runs once per URL when building the acquisition_plan or when js_state_mapper processes the response. There is no per-request platform re-evaluation.

Risk: a domain can change platforms (e.g., migrate from Magento to Shopify) between the time the DomainRunProfile was saved and a new crawl run. The saved profile will continue using the old platform-specific extraction paths until the profile is manually invalidated or the staleness logic triggers.

Q5 — Where Is Config Validated? Is There a Pydantic Settings Model?
Config is validated at use time via manual coercers, not at load time via Pydantic. The pattern throughout domain_run_profile_service.py is:

python
def _coerce_choice(value, allowed, *, default): ...
def _coerce_optional_int(value, *, minimum, maximum): ...
def normalize_acquisition_contract(value): ...   # 60-line manual coercer
def normalize_domain_run_profile(profile, ...): ... # 90-line manual coercer
There is no Pydantic model for DomainRunProfile or AcquisitionPlan. AcquisitionPlan is a plain @dataclass. normalize_domain_run_profile returns a plain dict[str, object], not a typed model. Invalid values silently fall back to defaults via _coerce_choice/_coerce_optional_int — there is no validation error surface.

crawler_runtime_settings in config/runtime_settings.py uses a Pydantic BaseSettings model (inferred from the .robots_cache_size, .default_max_pages attribute access pattern and the file's 24KB size), but the domain profile normalization layer does not use it.

Q6 — Risk of Stale Domain Profiles Causing Wrong Extractions?
Yes — this is a live production risk with three distinct staleness vectors:

Vector 1 — Acquisition Contract Staleness (Partially Mitigated)
acquisition_contract_is_stale exists and checks stale_after_failures.stale == True. It is set by note_acquisition_contract_failure after repeated failures. However:

The staleness flag is set reactively (after failures) not proactively (based on age)

There is no time-based TTL on last_quality_success — a profile with last_quality_success.timestamp = "2024-01-01" is not considered stale unless failures have accumulated

stale_after_failures.failure_count threshold is not visible in these files — it is presumably in crawler_runtime_settings but is not enforced with a named constant

Vector 2 — Selector Staleness (No Mitigation)
domain_memory_service has no staleness concept at all for selector rules. A selector synthesized 6 months ago for a site that has since redesigned its product page DOM will silently return None values. There is no created_at on individual rules (only source_run_id), no hit-rate tracking per rule, and no automatic invalidation.

Vector 3 — Platform Detection Staleness (No Mitigation)
DomainRunProfile stores platform (e.g., "shopify", "magento"). If a domain migrates platforms, the stored platform string will direct extraction to the wrong JS state mapper path. platform_policy.detect_platform_family re-runs on each new crawl's URL, but the saved profile's platform field is not refreshed unless save_domain_run_profile is called with an updated value.

Q7 — Proposed Schema, Policy Middleware, and Config Validation
Proposed DomainProfile Schema With Versioning
python
# domain_profile_schema.py
from pydantic import BaseModel, Field, model_validator
from datetime import datetime

class SelectorRule(BaseModel):
    id: int
    field_name: str
    css_selector: str | None = None
    xpath: str | None = None
    regex: str | None = None
    sample_value: str | None = None
    source: str = "domain_memory"
    is_active: bool = True
    source_run_id: int | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)  # NEW
    last_hit_at: datetime | None = None                              # NEW
    hit_count: int = 0                                               # NEW
    miss_count: int = 0                                              # NEW

    @property
    def hit_rate(self) -> float | None:
        total = self.hit_count + self.miss_count
        return self.hit_count / total if total > 0 else None

    @property
    def is_stale(self) -> bool:  # NEW: rule-level staleness
        if self.last_hit_at is None:
            return False
        age_days = (datetime.utcnow() - self.last_hit_at).days
        return age_days > 30 and (self.hit_rate or 1.0) < 0.3

class FetchProfile(BaseModel):
    fetch_mode: Literal["auto","http_only","browser_only","http_then_browser"] = "auto"
    extraction_source: Literal["raw_html","rendered_dom","rendered_dom_visual","network_payload_first"] = "raw_html"
    js_mode: Literal["auto","enabled","disabled"] = "auto"
    request_delay_ms: int = Field(default=1000, ge=500)   # ← explicit floor
    max_pages: int = Field(default=3, ge=1, le=50)
    max_scrolls: int = Field(default=5, ge=1)
    preferred_browser_engine: Literal["auto","patchright","real_chrome"] = "auto"

class DomainProfileV2(BaseModel):
    schema_version: int = 2                                # NEW: version field
    domain: str
    surface: str
    platform: str | None = None
    platform_detected_at: datetime | None = None           # NEW
    fetch_profile: FetchProfile = Field(default_factory=FetchProfile)
    selector_rules: list[SelectorRule] = []
    acquisition_contract: AcquisitionContract = Field(default_factory=AcquisitionContract)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    profile_stale_after_days: int = 30                     # NEW: time-based TTL

    @property
    def is_stale(self) -> bool:
        age_days = (datetime.utcnow() - self.updated_at).days
        return age_days > self.profile_stale_after_days

    @property
    def active_selector_rules(self) -> list[SelectorRule]:
        return [r for r in self.selector_rules if r.is_active and not r.is_stale]
Proposed Policy Enforcement Middleware
text
Current (scattered):
─────────────────
fetch_page() ──►  [no pre-check]
                  [acquisition/policy.py calls robots inline]
                  [platform detection in js_state_mapper inline]
                  [rate limiting in pacing.py called ad-hoc]

Proposed (explicit middleware stack):
──────────────────────────────────────
fetch_page(url, plan)
    │
    ▼
PolicyMiddleware.pre_fetch(url, plan) → PolicyDecision
    ├── 1. robots_policy.check(url)            → ALLOWED / DISALLOWED / MISSING
    ├── 2. domain_rate_limiter.acquire(domain) → token bucket, raises if overloaded
    ├── 3. host_protection_memory.check(url)   → skip if recently blocked
    └── 4. url_safety.ensure_public(url)       → no RFC-1918 ranges
    On DISALLOWED: return PolicyDecision(skip=True, reason="robots")
    On ALLOWED:    proceed to fetch

    │
    ▼
fetch_page() → FetchResult
    │
    ▼
PolicyMiddleware.post_fetch(url, result, plan) → void
    ├── 1. record_acquisition_contract_outcome() ← currently done by caller
    ├── 2. update selector hit/miss counts       ← NEW
    ├── 3. emit domain_health metric             ← NEW
    └── 4. refresh platform detection if changed ← NEW
Config Validation Entrypoint
python
# config/validation.py — NEW

from pydantic import ValidationError

def validate_startup_config() -> list[str]:
    """Called at app startup. Returns list of warnings."""
    errors = []

    # 1. Runtime settings (already Pydantic BaseSettings)
    try:
        s = crawler_runtime_settings
        assert s.min_request_delay_ms >= 500, "min_request_delay_ms below 500ms"
        assert s.robots_cache_ttl >= 3600, "robots_cache_ttl below 1 hour"
    except AssertionError as e:
        errors.append(f"runtime_settings: {e}")

    # 2. AcquisitionPlan defaults (currently evaluated at import time — risk)
    plan = AcquisitionPlan(surface="ecommerce_detail")
    if plan.sleep_ms < 500:
        errors.append(f"AcquisitionPlan.sleep_ms default {plan.sleep_ms}ms is below 500ms floor")

    # 3. platforms.json integrity
    for family, config in platform_js_state_extractors_all().items():
        if not config.get("jmespath_fields"):
            errors.append(f"platform {family}: missing jmespath_fields")

    return errors
Implicit Config That Must Be Made Explicit
Implicit Value	Location	Should Be Named Constant
Implicit Value	Location	Should Be Named Constant
minimum=crawler_runtime_settings.min_request_delay_ms used as floor	domain_run_profile_service.py L ~210	REQUEST_DELAY_FLOOR_MS in config/runtime_settings.py
stale_after_failures threshold not named	apply_acquisition_contract_to_profile	ACQUISITION_CONTRACT_MAX_FAILURES: int = 3
age_days > 30 for selector staleness (proposed above, does not exist today)	Missing entirely	SELECTOR_RULE_STALE_AFTER_DAYS: int = 30
"generic" surface fallback string	domain_memory_service.load_domain_selector_rules L literal	FALLBACK_SURFACE = "generic"
version: 1 hardcoded in normalize_domain_run_profile	domain_run_profile_service.py L ~250	DOMAIN_PROFILE_SCHEMA_VERSION = 1 + migration check on read
TTLCache(maxsize=..., ttl=...) for robots	robots_policy.py	Already in crawler_runtime_settings — good, but robots_cache_ttl default value should be documented as 86400 (24h) or explicit
LLM discover_xpath_candidates prompt token budget	llm_runtime.py (not in scope here)