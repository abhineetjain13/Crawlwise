21. Prevent 413 Payload Too Large on Minified JSON (Reliability: 6 → 8)
File: app/services/llm_runtime.py
Problem: The _enforce_token_limit function prevents the LLM from crashing by splitting the payload on \n\n. However, if the site uses minified JSON or packed HTML, there are no double newlines. The function fails to split it, sending a 500,000+ character string to Groq/Anthropic, causing an unhandled 413 Payload Too Large error and killing the cleanup review phase.
Fix: Fall back to strict character-level truncation if section-based splitting fails.
Replace the _enforce_token_limit function (around line 348):
code
Python
def _enforce_token_limit(text: str, limit: int = 5600) -> str:
    """Shrink oversize prompts safely, handling both formatted and minified text."""
    char_limit = limit * 3
    if len(text) <= char_limit:
        return text
        
    suffix = "\n\n[TRUNCATED DUE TO TOKEN LIMIT]"
    budget = max(0, char_limit - len(suffix))
    
    # FIX: If the text is minified (no newlines), strictly slice it
    if "\n\n" not in text:
        return text[:budget] + suffix

    sections = text.split("\n\n")
    kept: list[str] = []
    used = 0

    for section in sections:
        separator = 0 if not kept else 2
        section_len = len(section)
        if used + separator + section_len <= budget:
            kept.append(section)
            used += separator + section_len
            continue
        remaining = budget - used - separator
        if remaining > 0:
            trimmed = _trim_prompt_section(section, remaining)
            if trimmed:
                kept.append(trimmed)
        break

    if not kept:
        return text[:budget] + suffix
        
    return "\n\n".join(kept) + suffix
22. Fix SQLite WAL Deadlocks by Debouncing Checkpoints (Performance: 5 → 8)
File: app/services/pipeline/core.py
Problem: _sqlite_live_checkpoint is called on every step of every URL (e.g., fetch, analyze, save). If a batch runs 1,000 URLs across 4 concurrency slots, this spams the SQLite database with thousands of sequential lock requests per minute, bringing the entire system to a grinding halt with OperationalError: database is locked.
Fix: Add a memory-based debounce so checkpoints only actually hit the database a maximum of once every 2 seconds per run.
Add an import and replace the _sqlite_live_checkpoint function (around line 560):
code
Python
# Add to imports at the top:
# import time

_LAST_CHECKPOINT_TIME: dict[int, float] = {}

async def _sqlite_live_checkpoint(session: AsyncSession, run: CrawlRun) -> None:
    bind = session.bind
    if bind is None or bind.dialect.name != "sqlite":
        return
        
    # FIX: Debounce SQLite live checkpoints to prevent WAL lock exhaustion
    now = time.monotonic()
    last_time = _LAST_CHECKPOINT_TIME.get(run.id, 0.0)
    if now - last_time < 2.0:
        return  # Skip checkpoint if we just did one less than 2 seconds ago
        
    _LAST_CHECKPOINT_TIME[run.id] = now

    # Persist stage/log snapshots so polling UI can render live progress.
    async def _commit_only_operation(retry_session: AsyncSession) -> None:
        return None

    await with_retry(session, _commit_only_operation)
    await session.refresh(run)
23. Fix O(N) Proxy Rotator Memory Leak & CPU Hog (Performance/Reliability)
File: app/services/acquisition/acquirer.py
Problem: _evict_stale_proxy_entries is called on every single proxy access. It iterates over the entire _PROXY_FAILURE_STATE dictionary to find stale entries. If you use a rotating proxy pool (where every request is a new IP, leading to thousands of unique string keys), this becomes an unbounded memory leak and a severe CPU bottleneck.
Fix: Only run the O(N) eviction logic if the dictionary exceeds its capacity limit.
Replace the _evict_stale_proxy_entries function (around line 84):
code
Python
def _evict_stale_proxy_entries(now: float) -> None:
    # FIX: Don't iterate the dictionary on every single request. 
    # Only evict if we actually hit the memory limit threshold.
    if len(_PROXY_FAILURE_STATE) <= _PROXY_FAILURE_STATE_MAX_ENTRIES:
        return
        
    stale_cutoff = now - _PROXY_FAILURE_STATE_TTL_SECONDS
    stale_keys = [
        key
        for key, (_failures, last_failure_time, _cooldown_until) in _PROXY_FAILURE_STATE.items()
        if last_failure_time <= stale_cutoff
    ]
    for key in stale_keys:
        _PROXY_FAILURE_STATE.pop(key, None)

    # If still over limit after stale eviction, force prune the oldest entries
    if len(_PROXY_FAILURE_STATE) > _PROXY_FAILURE_STATE_MAX_ENTRIES:
        overflow = len(_PROXY_FAILURE_STATE) - _PROXY_FAILURE_STATE_MAX_ENTRIES
        for key, _state in sorted(_PROXY_FAILURE_STATE.items(), key=lambda item: item[1][1])[:overflow]:
            _PROXY_FAILURE_STATE.pop(key, None)
24. Fix Silent Data Corruption in Run Analytics (Correctness: 6 → 8)
File: app/services/crawl_events.py (and applies to _batch_runtime.py)
Problem: _merge_url_verdicts merges the url_verdicts lists from different concurrent workers by zipping them. If Worker A finishes URL #2, and Worker B finishes URL #5, the arrays are sparsely updated. The current logic falls back to empty strings "", permanently erasing the verdicts of URLs that were previously successful.
Fix: Ensure truthy string values always overwrite empty/null strings when merging arrays.
Replace the _merge_url_verdicts function (around line 178 in crawl_events.py and line 681 in _batch_runtime.py - make sure to update both):
code
Python
def _merge_url_verdicts(current: object, patch: object) -> list[str]:
    current_list = list(current) if isinstance(current, list) else []
    patch_list = list(patch) if isinstance(patch, list) else []
    max_len = max(len(current_list), len(patch_list))
    merged: list[str] = []
    
    # FIX: Prevent sparse array corruption by prioritizing truthy verdicts
    for idx in range(max_len):
        patch_value = str(patch_list[idx] or "").strip() if idx < len(patch_list) else ""
        current_value = str(current_list[idx] or "").strip() if idx < len(current_list) else ""
        
        # If the patch has a verdict, take it. Otherwise, keep the current verdict.
        # This prevents an empty string from a slower concurrent worker from wiping out a success.
        merged.append(patch_value if patch_value else current_value)
        
    return merged
25. Fix O(N) Domain Matching Bottleneck (Maintainability/Performance)
File: app/services/config/selectors.py
Problem: resolve_listing_readiness_override executes an O(N) loop over all configured ATS platforms, running substring checks (token in normalized_url) against the current URL on every single page load. As more platforms are added, this becomes a major regex/substring bottleneck in the main extraction path.
Fix: Use the pre-computed LISTING_READINESS_OVERRIDES dictionary (which already breaks patterns down by exact domain matches) for an O(1) dictionary lookup.
Replace resolve_listing_readiness_override (around line 185):
code
Python
def resolve_listing_readiness_override(page_url: str) -> dict[str, object] | None:
    """Return platform override using O(1) dictionary lookup on the domain."""
    normalized_url = str(page_url or "").strip().lower()
    if not normalized_url:
        return None
        
    from urllib.parse import urlparse
    domain = str(urlparse(normalized_url).netloc or "").strip().lower()
    
    # Remove 'www.' prefix for reliable matching
    if domain.startswith("www."):
        domain = domain[4:]

    # FIX: O(1) lookup instead of O(N) nested loop over all substring rules
    override = LISTING_READINESS_OVERRIDES.get(domain)
    if override:
        # Inject the current domain into the returned override payload
        return {**override, "domain": domain}
        
    # Fallback: check if it's a subdomain of a known override (e.g., jobs.company.icims.com)
    parts = domain.split(".")
    if len(parts) > 2:
        root_domain = f"{parts[-2]}.{parts[-1]}"
        override = LISTING_READINESS_OVERRIDES.get(root_domain)
        if override:
            return {**override, "domain": domain}
            
    return None