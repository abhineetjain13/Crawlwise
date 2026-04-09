16. Fix "Long Garbage Wins" Arbitration Bug (Correctness: 4 → 6)
File: app/services/pipeline/field_normalization.py
Problem: In _should_prefer_secondary_field, the pipeline assumes that for text fields, longer is better. If a site’s DOM yields {"brand": "Nike"} (4 chars), but the DataLayer yields {"brand": "Click here to read our privacy policy and terms"} (49 chars), the garbage string silently overwrites the correct brand because it is longer.
Fix: Introduce strict length constraints and word-count penalties for short-form categorical fields (brand, category, color) so paragraphs of noise cannot overwrite valid data.
Replace the _should_prefer_secondary_field function:
code
Python
def _should_prefer_secondary_field(
    field_name: str, existing: object, candidate: object
) -> bool:
    """Determine if secondary field value should be preferred."""
    from .utils import _clean_candidate_text
    
    if candidate in (None, "", [], {}):
        return False
    if existing in (None, "", [], {}):
        return True
        
    existing_text = _clean_candidate_text(existing, limit=None).casefold()
    candidate_text = _clean_candidate_text(candidate, limit=None).casefold()
    
    if not candidate_text:
        return False

    # 1. Long-form text fields: longer is generally better
    if field_name in {"description", "specifications", "responsibilities", "requirements"}:
        return len(candidate_text) > len(existing_text)

    # 2. Short-form categorical fields: prevent long noise from overwriting short facts
    if field_name in {"brand", "category", "color", "size", "availability"}:
        # FIX: If the candidate is suspiciously long (e.g., a sentence), reject it
        if len(candidate_text) > 40 or len(candidate_text.split()) > 5:
            return False
            
        low_quality_tokens = {
            "cookie", "privacy", "sign in", "log in", 
            "account", "home", "menu", "agree", "policy"
        }
        existing_is_noisy = any(token in existing_text for token in low_quality_tokens)
        candidate_is_noisy = any(token in candidate_text for token in low_quality_tokens)
        
        if existing_is_noisy and not candidate_is_noisy:
            return True
        if not existing_is_noisy and candidate_is_noisy:
            return False
            
        # If both are clean, prefer the slightly longer/richer label, 
        # but only up to our 40-character safety cap.
        return len(candidate_text) > len(existing_text)

    # 3. List-based fields (images)
    if field_name == "additional_images":
        existing_count = len([p for p in (existing if isinstance(existing, (list, tuple)) else str(existing or "").split(",")) if p])
        candidate_count = len([p for p in (candidate if isinstance(candidate, (list, tuple)) else str(candidate or "").split(",")) if p])
        return candidate_count > existing_count
        
    return False
17. Refactor the God-Function in Pipeline Orchestration (Architecture: 5 → 7)
File: app/services/extract/service.py
Problem: _collect_candidates is a rigid "God Function" containing a massive sequential if/elif chain checking 9 different data sources. It violates the Open-Closed Principle; adding a new extractor requires modifying this core loop.
Fix: Refactor it to use a clean Strategy iteration pattern. This drastically improves readability and maintainability.
Replace the _collect_candidates function (around line 125):
code
Python
def _collect_candidates(
    url: str,
    surface: str,
    html: str,
    soup: BeautifulSoup,
    tree,
    page_sources: dict,
    adapter_records: list[dict],
    network_payloads: list[dict],
    target_fields: list[str],
    canonical_target_fields: set[str],
    contract_by_field: dict,
    semantic: dict,
    label_value_text_sources: dict,
) -> dict[str, list[dict]]:
    """Gather candidate values using a Strategy iteration pattern. (First-match wins)"""
    candidates: dict[str, list[dict]] = {}
    domain = _domain(url)
    
    # Pre-extract data subsets for strategies
    next_data = page_sources.get("next_data")
    hydrated_states = page_sources.get("hydrated_states") or []
    embedded_json = page_sources.get("embedded_json") or []
    open_graph = page_sources.get("open_graph") or {}
    json_ld = page_sources.get("json_ld") or []
    microdata = page_sources.get("microdata") or []
    datalayer = page_sources.get("datalayer") or {}
    
    semantic_sections = semantic.get("sections", {}) if isinstance(semantic.get("sections"), dict) else {}
    semantic_specifications = semantic.get("specifications", {}) if isinstance(semantic.get("specifications"), dict) else {}
    semantic_promoted = semantic.get("promoted_fields", {}) if isinstance(semantic.get("promoted_fields"), dict) else {}

    # Define extraction strategies in priority order
    strategies = [
        lambda rows, f: _collect_contract_candidates(rows, field_name=f, tree=tree, html=html, contract_by_field=contract_by_field),
        lambda rows, f: _collect_adapter_candidates(rows, field_name=f, adapter_records=adapter_records),
        lambda rows, f: _collect_datalayer_candidates(rows, field_name=f, datalayer=datalayer),
        lambda rows, f: _collect_network_payload_candidates(rows, field_name=f, network_payloads=network_payloads, base_url=url),
        lambda rows, f: _collect_jsonld_candidates(rows, field_name=f, json_ld=json_ld, base_url=url),
        lambda rows, f: _collect_structured_state_candidates(rows, field_name=f, next_data=next_data, hydrated_states=hydrated_states, embedded_json=embedded_json, network_payloads=network_payloads, base_url=url)
    ]

    for field_name in target_fields:
        rows: list[dict] = []
        
        # 1-6. Execute high-priority structured strategies
        strategy_matched = False
        for strategy in strategies:
            if strategy(rows, field_name):
                candidates[field_name] = rows
                strategy_matched = True
                break
                
        if strategy_matched:
            continue
            
        # 7. DOM selectors
        _collect_dom_and_meta_candidates(
            rows, field_name=field_name, html=html, soup=soup, domain=domain,
            microdata=microdata, open_graph=open_graph, base_url=url
        )
        
        # 8. Semantic extraction
        if _is_semantic_requested_field(field_name, canonical_target_fields):
            semantic_rows = resolve_requested_field_values(
                [field_name], sections=semantic_sections, specifications=semantic_specifications, promoted_fields=semantic_promoted
            )
            if semantic_value := semantic_rows.get(field_name):
                if semantic_value not in (None, "", [], {}):
                    rows.append({"value": semantic_value, "source": "semantic_section"})
        
        # 9. Text patterns
        if _is_semantic_requested_field(field_name, canonical_target_fields):
            if text_value := _extract_label_value_from_text(field_name, label_value_text_sources, html):
                rows.append({"value": text_value, "source": "text_pattern"})
        
        if rows:
            candidates[field_name] = rows
            
    return candidates
18. Prevent "Zombie" Browser Deadlocks (Reliability: 6 → 8)
File: app/services/acquisition/browser_client.py
Problem: In _fetch_rendered_html_attempt, if proxy negotiation is slow or headless Chrome hangs on initialization, await browser.new_context() blocks forever. Standard Python timeouts at the worker level kill the task, but the orphaned Chrome instance keeps running on the server, eventually causing an Out-Of-Memory (OOM) crash.
Fix: Wrap the inner browser startup commands in strict asyncio.wait_for blocks so Playwright yields control back to Python to clean up.
Update the context and page creation block inside _fetch_rendered_html_attempt (around line 140):
code
Python
try:
        # FIX: Wrap context creation in a strict timeout to prevent zombie browsers
        context = await asyncio.wait_for(
            browser.new_context(**_context_kwargs(prefer_stealth, browser_channel=browser_channel)),
            timeout=15.0
        )
    except (PlaywrightError, asyncio.TimeoutError):
        # Browser in pool may have died or hung; evict and retry once.
        await _evict_browser(_browser_pool_key(launch_profile, proxy), browser)
        browser, _ = await _acquire_browser(
            browser_type=browser_type,
            launch_kwargs=launch_kwargs,
            browser_pool_key=_browser_pool_key(launch_profile, proxy),
            force_new=True,
        )
        context = await asyncio.wait_for(
            browser.new_context(**_context_kwargs(prefer_stealth, browser_channel=browser_channel)),
            timeout=15.0
        )
        
    original_domain = _domain(url)
    try:
        await _load_cookies(context, original_domain)
        # FIX: Wrap page creation in timeout
        page = await asyncio.wait_for(context.new_page(), timeout=10.0)
19. Remove Hazardous Dead Code (Maintainability: 4 → 8)
File: app/services/db_utils.py
Problem: The function commit_with_retry is explicitly marked as deprecated and dangerous in the comments ("commit-only retries are unsafe for mutable unit-of-work paths"), but it still exists in the codebase, creating a hazard for future developers who might accidentally import and use it.
Fix: Delete it entirely. It serves no purpose.
Open app/services/db_utils.py and completely delete this block at the bottom of the file (around line 63):
code
Python
# DELETE THIS ENTIRE BLOCK FROM db_utils.py:
async def commit_with_retry(
    session: AsyncSession,
    *,
    max_retries: int = 5,
    base_delay_ms: int = 50,
    max_delay_ms: int = 2000,
) -> None:
    """Deprecated: commit-only retries are unsafe for mutable unit-of-work paths."""
    del session, max_retries, base_delay_ms, max_delay_ms
    raise RuntimeError(
        "commit_with_retry is deprecated and unsafe; use with_retry(session, operation) "
        "to retry the full unit-of-work."
    )
20. Introduce High-Leverage Arbitration Test Harness (Test Maturity: 3 → 8)
File: Create a new file: tests/services/extract/test_arbitration.py
Problem: The core business logic of this crawler is resolving conflicting data from multiple sources (DOM vs JSON-LD vs DataLayer). There are no tests verifying that schema pollution guards work.
Fix: Provide a comprehensive pytest harness that mocks extract_candidates and ensures that garbage values are correctly rejected in favor of high-quality fallbacks.
Create this file in your tests directory (you can copy-paste this whole block):
code
Python
import pytest
from bs4 import BeautifulSoup
from app.services.extract.service import extract_candidates
from app.services.pipeline_config import EXTRACTION_RULES

@pytest.mark.asyncio
async def test_schema_arbitration_rejects_datalayer_pollution():
    """
    Tests that a noisy/garbage string in a high-priority source (datalayer) 
    is correctly rejected by the validator, allowing a clean lower-priority 
    source (DOM) to win arbitration.
    """
    url = "https://www.example-store.com/product/nike-shoes"
    surface = "ecommerce_detail"
    
    # Mock HTML containing both a polluted datalayer and a clean DOM
    html = """
    <html>
        <head>
            <script>
                dataLayer.push({
                    "ecommerce": {
                        "detail": {
                            "products": [{
                                "brand": "Home > Privacy Policy > Nike",
                                "category": "Sign in to view categories",
                                "price": "120.00"
                            }]
                        }
                    }
                });
            </script>
        </head>
        <body>
            <h1 class="product-title">Nike Air Max 90</h1>
            <span itemprop="brand">Nike</span>
            <div itemprop="category">Sneakers</div>
        </body>
    </html>
    """
    
    # Execute the extraction pipeline
    candidates, source_trace = await extract_candidates(
        url=url,
        surface=surface,
        html=html,
        xhr_payloads=[],
        additional_fields=[],
        extraction_contract=[],
        resolved_fields=["title", "brand", "category", "price"]
    )
    
    final_candidates = source_trace.get("candidates", {})
    
    # Assertions
    # 1. Price should be extracted from datalayer (clean scalar)
    assert final_candidates["price"][0]["value"] == "120.00"
    assert "datalayer" in final_candidates["price"][0]["source"]
    
    # 2. Brand should REJECT the datalayer noise and fallback to DOM
    assert final_candidates["brand"][0]["value"] == "Nike"
    assert "dom" in final_candidates["brand"][0]["source"] or "selector" in final_candidates["brand"][0]["source"]
    
    # 3. Category should REJECT the datalayer noise and fallback to DOM
    assert final_candidates["category"][0]["value"] == "Sneakers"
    assert "dom" in final_candidates["category"][0]["source"] or "selector" in final_candidates["category"][0]["source"]

@pytest.mark.asyncio
async def test_should_prefer_secondary_field_logic():
    """Tests the merge logic ensuring short noise doesn't overwrite short facts."""
    from app.services.pipeline.field_normalization import _should_prefer_secondary_field
    
    # Existing valid short string, candidate is a noisy long string
    existing = "Nike"
    candidate = "Click here to accept cookie policy and agree to terms"
    assert _should_prefer_secondary_field("brand", existing, candidate) is False
    
    # Existing is noisy, candidate is clean
    existing_noisy = "Home > Brands"
    candidate_clean = "Adidas"
    assert _should_prefer_secondary_field("brand", existing_noisy, candidate_clean) is True