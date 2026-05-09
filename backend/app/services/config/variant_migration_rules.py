from __future__ import annotations

DETAIL_VARIANT_CONTEXT_NOISE_TOKENS_EXTRA = (
    "tabs", "tab-list", "tablist", "tab-nav", "reviews", "review-section",
    "ratings", "social", "share-bar", "protection", "warranty",
)
DETAIL_VARIANT_SOFT_SCOPE_SELECTOR = (
    "[class*='variant' i], [class*='option' i], [class*='selector' i], "
    "[class*='swatch' i], [id*='variant' i], [id*='option' i], "
    "[id*='selector' i], [id*='swatch' i], [data-testid*='variant' i], "
    "[data-component*='variant' i], fieldset, [role='radiogroup'], select"
)
VARIANT_SOFT_SCOPE_MIN_RADIO_INPUTS = 2
VARIANT_URL_BLOCKED_PATH_SUFFIXES = frozenset({
    "/reviews", "/review", "/print", "/share", "/overview", "/specifications",
    "/specs", "/wishlist", "/cart", "/returns-policy", "/credit", "/payment",
    "/help",
})
VARIANT_URL_BLOCKED_PATH_PREFIXES = frozenset({
    "/pl/", "/c/", "/collections/", "/category/", "/browse/", "/search/", "/l/",
})
VARIANT_OPTION_VALUE_UI_NOISE_PHRASES_EXTRA = (
    "view more", "view all", "view all images", "view all photos", "overview",
    "specifications", "description", "features", "share", "print", "save",
    "bookmark", "show more", "more details", "see details", "return policy",
    "returns policy", "payment options", "shop the collection", "shop all",
    "year protection plan", "protection plan", "extended warranty",
    "increment or decrement number", "increment or decrement",
)
VARIANT_OPTION_VALUE_NOISE_FULLMATCH_PATTERNS_EXTRA = (
    r"\d+\+?\s+reviews?", r"\d+\+?\s+ratings?",
    r"(\b\w+\b)(?:\s+\1)+", r"shop\s+\w+(?:\s+\w+){0,2}",
)
VARIANT_STRONG_OPTION_SELECTOR = (
    "[role='radio'], [role='option'], input[type='radio'], input[type='checkbox'], "
    "[data-option-value], [data-value], [data-variant-id], [data-selected], "
    "[aria-pressed][aria-pressed!=''], button[data-option], button[data-value], "
    "button[data-variant]"
)
VARIANT_WEAK_OPTION_SELECTOR = (
    "button:not([data-dismiss]):not([type='submit']):not([type='reset']), "
    "a[href]"
)
VARIANT_GROUP_MIN_CONFIDENCE = 0.35
