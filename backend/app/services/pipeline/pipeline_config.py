from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class PipelineConfig:
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
