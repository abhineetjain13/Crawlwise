from __future__ import annotations

from dataclasses import dataclass, field

BLOCKED_PAGE_MIN_HTML_LENGTH: int = 100
"""Minimum stripped HTML length before blocked-page detection treats content as usable."""

BLOCKED_PAGE_LARGE_HTML_THRESHOLD: int = 100000
"""HTML size above which blocked-page detection uses the bounded large-document path."""

BLOCKED_PAGE_VISIBLE_TEXT_CAP: int = 50000
"""Maximum visible-text length retained during blocked-page analysis."""

BLOCKED_PAGE_FALLBACK_VISIBLE_LIMIT: int = 20000
"""Maximum raw-HTML prefix scanned when visible-text parsing falls back."""


@dataclass(frozen=True, slots=True)
class PipelineConfig:
    schema_max_age_days: int = 7
    listing_promotion_text_hints: tuple[str, ...] = (
        "shop all",
        "all ",
        "see all",
        "view all",
    )
    listing_promotion_penalty_tokens: set[str] = field(
        default_factory=lambda: {"accessories", "parts", "support", "help", "service"}
    )
    listing_promotion_text_noise: tuple[str, ...] = ("skip", "navigation", "menu")
    listing_tile_allowed_fields: set[str] = field(
        default_factory=lambda: {"title", "url", "image_url", "additional_images"}
    )
    listing_tile_strong_fields: set[str] = field(
        default_factory=lambda: {
            "availability",
            "brand",
            "currency",
            "original_price",
            "part_number",
            "price",
            "rating",
            "review_count",
            "sale_price",
            "sku",
        }
    )
    listing_path_token_stopwords: set[str] = field(
        default_factory=lambda: {
            "all",
            "and",
            "categories",
            "category",
            "collection",
            "collections",
            "for",
            "html",
            "htm",
            "page",
            "product",
            "products",
            "shop",
            "store",
            "the",
            "with",
        }
    )


PIPELINE_CONFIG = PipelineConfig()
SCHEMA_MAX_AGE_DAYS = PIPELINE_CONFIG.schema_max_age_days
