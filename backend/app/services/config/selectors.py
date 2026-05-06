from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from app.services.config._export_data import load_export_data

_EXPORTS_PATH = Path(__file__).with_name("selectors.exports.json")
_STATIC_EXPORTS = {
    name: value
    for name, value in load_export_data(str(_EXPORTS_PATH)).items()
    if not name.startswith("_")
}

for _name, _value in _STATIC_EXPORTS.items():
    globals()[_name] = _value

SELECTOR_SELF_HEAL_TARGET_LIMIT = 6
SELECTOR_SELF_HEAL_DEFAULT_MIN_CONFIDENCE = 0.55
# Final retention allow-list for interactive tags with useful selector attributes.
SELECTOR_SYNTHESIS_KEEP_WORTHY_TAGS = frozenset(
    _STATIC_EXPORTS.get(
        "SELECTOR_SYNTHESIS_KEEP_WORTHY_TAGS",
        ("button", "input", "select"),
    )
)

XPATH_ALLOWED_FUNCTIONS = frozenset(
    {
        "comment",
        "concat",
        "contains",
        "last",
        "normalize-space",
        "node",
        "not",
        "position",
        "processing-instruction",
        "starts-with",
        "string",
        "text",
    }
)
XPATH_DISALLOWED_PATTERNS = (
    (re.compile(r"\|"), "XPath unions are not supported"),
    (
        re.compile(
            r"(?<![\w-])(ancestor|ancestor-or-self|descendant-or-self|following|following-sibling|namespace|preceding|preceding-sibling|self)::"
        ),
        "XPath axis is not allowed",
    ),
    (re.compile(r"\$[A-Za-z_][\w.-]*"), "XPath variables are not allowed"),
)
XPATH_FUNCTION_PATTERN = re.compile(r"(?<![:\w-])([A-Za-z_][\w.-]*)\s*\(")
SELECTOR_SYNTHESIS_ALLOWED_ATTRS = frozenset(
    {
        "aria-label",
        "class",
        "data-price",
        "data-product-id",
        "data-sku",
        "data-testid",
        "data-variant-id",
        "href",
        "id",
        "itemprop",
        "name",
        "shadowrootmode",
        "slot",
        "value",
    }
)
SELECTOR_SYNTHESIS_DROP_TAGS = frozenset({"script", "style", "noscript", "svg"})
# Preliminary low-value filter; overlap is intentional because keep-worthy tags
# survive only when _keep_low_value_node sees useful attrs/tokens.
SELECTOR_SYNTHESIS_LOW_VALUE_TAGS = frozenset(
    {
        "nav",
        "footer",
        "aside",
        "button",
        "textarea",
        "input",
        "select",
        "iframe",
        "canvas",
    }
)
SELECTOR_SYNTHESIS_KEEP_ATTRS = frozenset(
    {"data-variant-id", "data-product-id", "data-price", "value"}
)
SELECTOR_SYNTHESIS_KEEP_TOKENS = frozenset(
    {"buy", "cart", "pdp", "product", "variant"}
)
LISTING_FIELD_SELECTORS: dict[str, list[str]] = {
    "title": [
        "[itemprop='name']",
        "[class*='title']",
        "[class*='Title']",
        "[data-testid*='title']",
        "[data-testid*='name']",
        "a[href]",
    ],
    "price": [
        "[itemprop='price']",
        "[class*='price']",
        "[class*='Price']",
        "[data-testid*='price']",
        "[data-price]",
        "[aria-label*='price']",
    ],
    "brand": [
        "[itemprop='brand']",
        "[class*='brand']",
        "[class*='Brand']",
        "[data-testid*='brand']",
        "[aria-label*='brand']",
    ],
    "image_url": [
        "[itemprop='image']",
        "img[src]",
        "[class*='image']",
        "[class*='Image']",
        "[data-testid*='image']",
    ],
    "rating": [
        "[itemprop='ratingValue']",
        "[class*='rating']",
        "[class*='Rating']",
        "[class*='stars']",
        "[data-testid*='rating']",
    ],
    "review_count": [
        "[itemprop='reviewCount']",
        "[class*='review-count']",
        "[class*='ReviewCount']",
        "[data-testid*='review']",
    ],
    "availability": [
        "[itemprop='availability']",
        "[class*='stock']",
        "[data-availability]",
        "[data-testid*='avail']",
    ],
    "sku": [
        "[itemprop='sku']",
        "[data-sku]",
        "[class*='sku']",
    ],
}


def __getattr__(name: str) -> Any:
    try:
        return _STATIC_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc


__all__ = sorted(
    list(_STATIC_EXPORTS.keys())
    + [
        "XPATH_ALLOWED_FUNCTIONS",
        "XPATH_DISALLOWED_PATTERNS",
        "XPATH_FUNCTION_PATTERN",
        "SELECTOR_SYNTHESIS_ALLOWED_ATTRS",
        "SELECTOR_SYNTHESIS_DROP_TAGS",
        "SELECTOR_SYNTHESIS_KEEP_ATTRS",
        "SELECTOR_SYNTHESIS_KEEP_TOKENS",
        "SELECTOR_SELF_HEAL_DEFAULT_MIN_CONFIDENCE",
        "SELECTOR_SELF_HEAL_TARGET_LIMIT",
        "SELECTOR_SYNTHESIS_KEEP_WORTHY_TAGS",
        "SELECTOR_SYNTHESIS_LOW_VALUE_TAGS",
        "LISTING_FIELD_SELECTORS",
    ]
)
