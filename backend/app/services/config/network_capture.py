from __future__ import annotations

import re
from typing import Final


NETWORK_PAYLOAD_NOISE_DOMAINS: Final[tuple[str, ...]] = (
    "klarna.com",
    "affirm.com",
    "afterpay.com",
    "olapic-cdn.com",
    "zendesk.com",
    "intercom.io",
    "facebook.com",
    "sentry.io",
)

NETWORK_PAYLOAD_NOISE_KEYWORDS: Final[tuple[str, ...]] = (
    "geolocation",
    "geoip",
    "geo/",
    "/geo",
    "analytics",
    "tracking",
    "telemetry",
    "livechat",
    "google-analytics",
    "googletagmanager",
    "datadome",
    "px.ads",
    "cdn-cgi/",
    "captcha",
)

NETWORK_PAYLOAD_NOISE_URL_RE: Final[re.Pattern[str]] = re.compile(
    "|".join(
        tuple(re.escape(kw) for kw in NETWORK_PAYLOAD_NOISE_KEYWORDS)
        + tuple(re.escape(domain) for domain in NETWORK_PAYLOAD_NOISE_DOMAINS)
    ),
    re.I,
)


ENDPOINT_TYPE_PATH_TOKENS: Final[dict[str, dict[str, tuple[str, ...]]]] = {
    "job_detail": {
        "job_api": (
            "/jobs/",
            "/job_posts/",
            "/postings/",
            "/positions/",
            "/requisition/",
            "/careers/",
        ),
    },
    "ecommerce_detail": {
        "product_api": (
            "/products/",
            "/product/",
            "product.js",
            "/variants/",
            "/cart.js",
        ),
    },
}

GRAPHQL_PATH_TOKENS: Final[tuple[str, ...]] = (
    "/graphql",
    "graphql?",
)

HIGH_VALUE_NETWORK_ENDPOINT_TYPES: Final[frozenset[str]] = frozenset(
    {"graphql", "product_api", "job_api"}
)

HIGH_VALUE_NETWORK_PAYLOAD_BUDGET_MULTIPLIER: Final[int] = 4


__all__ = [
    "ENDPOINT_TYPE_PATH_TOKENS",
    "GRAPHQL_PATH_TOKENS",
    "HIGH_VALUE_NETWORK_ENDPOINT_TYPES",
    "HIGH_VALUE_NETWORK_PAYLOAD_BUDGET_MULTIPLIER",
    "NETWORK_PAYLOAD_NOISE_DOMAINS",
    "NETWORK_PAYLOAD_NOISE_KEYWORDS",
    "NETWORK_PAYLOAD_NOISE_URL_RE",
]
