from __future__ import annotations

import re
from typing import Final

from app.services.config.network_payload_specs import endpoint_type_path_tokens


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

BLOCKED_BROWSER_ROUTE_TOKENS: Final[tuple[str, ...]] = (
    "doubleclick",
    "facebook",
    "google-analytics",
    "googletagmanager",
)

BLOCKED_BROWSER_RESOURCE_TYPES: Final[tuple[str, ...]] = (
    "media",
)

PROTECTED_CHALLENGE_ROUTE_TOKENS: Final[tuple[str, ...]] = (
    "akamai",
    "akamaized",
    "captcha-delivery",
    "datadome",
    "perimeterx",
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

ENDPOINT_TYPE_PATH_TOKENS: Final[dict[str, dict[str, tuple[str, ...]]]] = (
    endpoint_type_path_tokens()
)

GRAPHQL_PATH_TOKENS: Final[tuple[str, ...]] = (
    "/graphql",
    "graphql?",
)

NETWORK_PAYLOAD_STREAMING_CONTENT_TYPES: Final[tuple[str, ...]] = (
    "text/x-component",
)

NETWORK_PAYLOAD_JSON_CONTENT_TYPE_HINTS: Final[tuple[str, ...]] = (
    "application/json",
    "application/trpc+json",
    "application/graphql-response+json",
)

NETWORK_PAYLOAD_URL_HINTS: Final[tuple[str, ...]] = (
    ".json",
    "__flight__",
    "_rsc=",
)

HIGH_VALUE_NETWORK_ENDPOINT_TYPES: Final[frozenset[str]] = frozenset(
    {"graphql", "product_api", "job_api"}
)

HIGH_VALUE_NETWORK_PAYLOAD_BUDGET_MULTIPLIER: Final[int] = 4


__all__ = [
    "BLOCKED_BROWSER_RESOURCE_TYPES",
    "BLOCKED_BROWSER_ROUTE_TOKENS",
    "ENDPOINT_TYPE_PATH_TOKENS",
    "GRAPHQL_PATH_TOKENS",
    "HIGH_VALUE_NETWORK_ENDPOINT_TYPES",
    "HIGH_VALUE_NETWORK_PAYLOAD_BUDGET_MULTIPLIER",
    "NETWORK_PAYLOAD_NOISE_DOMAINS",
    "NETWORK_PAYLOAD_NOISE_KEYWORDS",
    "NETWORK_PAYLOAD_NOISE_URL_RE",
    "NETWORK_PAYLOAD_JSON_CONTENT_TYPE_HINTS",
    "NETWORK_PAYLOAD_STREAMING_CONTENT_TYPES",
    "NETWORK_PAYLOAD_URL_HINTS",
    "PROTECTED_CHALLENGE_ROUTE_TOKENS",
]
