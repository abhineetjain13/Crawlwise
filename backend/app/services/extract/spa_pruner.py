from typing import Any
import re

# Keys that typically contain boilerplate framework structure, tracking, or UI state
# rather than product or listing data.
KNOWN_NOISE_KEYS = {
    # Bundlers/Data Fetching
    "webpack", "apollostate", "relay", "__apollo", "__relay", "urql", "apollo",
    # UI/Theme/Styling
    "theme", "styles", "css", "fonts", "colors", "icons", "svgs",
    # Internationalization
    "locales", "translations", "lang", "i18n", "intl",
    # Tracking/Analytics/Ads
    "tracking", "analytics", "metrics", "telemetry", "gtm", "adzones", "advertisements", "ads", "pixel", "facebook", "google", "tagmanager",
    # Layout/Structural
    "header", "footer", "nav", "menu", "sidebar", "navigation", "layout", "breadcrumbs", "seo",
    # Session/Routing
    "router", "routing", "paths", "url", "cookies", "session", "auth", "query", "pathname", "aspath", "apptree", "useragent",
    # Specific DigiKey/E-commerce noise
    "_links", "_actions", "omniture", "adobe", "everest", "ensighten", "marketing", "promotion", "banner", "popup"
}
_ZERO_VECTOR_RE = re.compile(r"^\[?\s*(?:0\s*,\s*){6,}0\s*\]?$")
_FUNCTION_BODY_RE = re.compile(r"\bfunction\s*\([^)]*\)\s*\{", re.IGNORECASE)


def prune_spa_state(data: Any, max_string_len: int = 2000) -> Any:
    """Recursively strip out unhelpful keys and massive string values (e.g. base64/HTML)
    from SPA state before passing it to the LLM. Focuses on conservative exclusion.
    """
    if isinstance(data, dict):
        pruned_dict = {}
        for k, v in data.items():
            k_clean = str(k).strip().lower()
            
            # Substring match for aggressiveness
            is_noise = False
            for noise_key in KNOWN_NOISE_KEYS:
                if noise_key in k_clean:
                    is_noise = True
                    break
                    
            if is_noise:
                continue
            
            # Prune children
            child_pruned = prune_spa_state(v, max_string_len)
            
            # If the child is completely empty after pruning, we can often skip it
            # unless we want to keep explicit nulls. We drop empty dicts/lists here to save tokens.
            if child_pruned in (None, "", [], {}):
                continue
                
            pruned_dict[k] = child_pruned
        return pruned_dict

    elif isinstance(data, list):
        if data and all(item == 0 for item in data):
            return None
        pruned_list = []
        for item in data:
            child_pruned = prune_spa_state(item, max_string_len)
            if child_pruned not in (None, "", [], {}):
                pruned_list.append(child_pruned)
        return pruned_list

    elif isinstance(data, str):
        if _FUNCTION_BODY_RE.search(data):
            return None
        if _ZERO_VECTOR_RE.fullmatch(data.strip()):
            return None
        # Drop likely base64 or massive raw HTML chunks injected into state
        if len(data) > max_string_len:
            lowered = data.lower()
            if lowered.startswith("data:image") or "<html" in lowered or "<div" in lowered or "base64" in lowered:
                return None
            return data[:max_string_len] + "... [TRUNCATED]"
        return data

    return data
