from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


DATA_ENRICHMENT_STATUS_UNENRICHED = "unenriched"
DATA_ENRICHMENT_STATUS_PENDING = "pending"
DATA_ENRICHMENT_STATUS_RUNNING = "running"
DATA_ENRICHMENT_STATUS_ENRICHED = "enriched"
DATA_ENRICHMENT_STATUS_DEGRADED = "degraded"
DATA_ENRICHMENT_STATUS_FAILED = "failed"
DATA_ENRICHMENT_LLM_TASK = "data_enrichment_semantic"
DATA_ENRICHMENT_TAXONOMY_VERSION = "shopify-2026-02"

DATA_ENRICHMENT_SKIP_RECORD_STATUSES = (
    DATA_ENRICHMENT_STATUS_ENRICHED,
    DATA_ENRICHMENT_STATUS_DEGRADED,
)
DATA_ENRICHMENT_JOB_TERMINAL_STATUSES = (
    DATA_ENRICHMENT_STATUS_ENRICHED,
    DATA_ENRICHMENT_STATUS_DEGRADED,
    DATA_ENRICHMENT_STATUS_FAILED,
)

ECOMMERCE_DETAIL_SURFACE = "ecommerce_detail"
DATA_ENRICHMENT_TAXONOMY_FILENAME = "shopify_categories.json"
DATA_ENRICHMENT_ATTRIBUTES_FILENAME = "shopify_attributes.json"
DATA_ENRICHMENT_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "enrichment"
DATA_ENRICHMENT_TAXONOMY_PATH = (
    DATA_ENRICHMENT_DATA_DIR / DATA_ENRICHMENT_TAXONOMY_FILENAME
)
DATA_ENRICHMENT_ATTRIBUTES_PATH = (
    DATA_ENRICHMENT_DATA_DIR / DATA_ENRICHMENT_ATTRIBUTES_FILENAME
)
DATA_ENRICHMENT_BASE_REQUIRED_ATTRIBUTES = (
    "title",
    "description",
    "link",
    "image_link",
    "availability",
    "price",
)
DATA_ENRICHMENT_LLM_BACKFILL_FIELDS = (
    "category_path",
    "color_family",
    "size_normalized",
    "size_system",
    "gender_normalized",
    "materials_normalized",
    "availability_normalized",
)
DATA_ENRICHMENT_SHOPIFY_NORMALIZATION_ATTRIBUTE_NAMES = {
    "color": "Color",
    "size": "Size",
    "gender": "Target gender",
    "fabric": "Fabric",
    "material": "Material",
}
DATA_ENRICHMENT_COLOR_FAMILY_ALIASES = {
    "black": ("black",),
    "blue": ("blue", "navy"),
    "brown": ("beige", "brown", "tan"),
    "gold": ("gold", "bronze", "rose gold"),
    "gray": ("gray", "grey", "silver"),
    "green": ("green",),
    "multi": ("multicolor",),
    "orange": ("orange",),
    "pink": ("pink",),
    "purple": ("purple",),
    "red": ("red",),
    "white": ("white", "clear"),
    "yellow": ("yellow",),
}
DATA_ENRICHMENT_GENDER_ALIASES = {
    "female": (
        "female",
        "women",
        "woman",
        "womens",
        "women's",
        "ladies",
        "girl",
        "girls",
    ),
    "male": ("male", "men", "man", "mens", "men's", "boy", "boys"),
    "unisex": (
        "unisex",
        "all gender",
        "all-gender",
        "gender neutral",
        "gender-neutral",
    ),
}
DATA_ENRICHMENT_AVAILABILITY_TERMS = {
    "in_stock": (
        "in_stock",
        "in stock",
        "available",
        "ready to ship",
        "ships now",
        "add to cart",
        "preorder available",
    ),
    "limited_stock": (
        "limited_stock",
        "limited stock",
        "limited availability",
        "low stock",
        "few left",
        "left in stock",
    ),
    "out_of_stock": (
        "out_of_stock",
        "out of stock",
        "sold out",
        "unavailable",
        "notify me",
        "currently unavailable",
    ),
    "preorder": ("preorder", "pre-order", "pre order"),
    "backorder": ("backorder", "back order"),
}
DATA_ENRICHMENT_MATERIAL_PRIMARY_FIELDS = (
    "materials",
    "material",
    "fabric",
    "composition",
    "product_attributes",
)
DATA_ENRICHMENT_MATERIAL_FALLBACK_FIELDS = ("description",)
DATA_ENRICHMENT_MATERIAL_CONTEXT_STRIP_PATTERNS = (
    r"\bcare\b.*$",
    r"\bcare instructions?\b.*$",
    r"\bwash\b.*$",
    r"\biron\b.*$",
    r"\bdry clean\b.*$",
)
DATA_ENRICHMENT_TAXONOMY_CONTEXT_BLOCKS = (
    {
        "context_terms": (
            "apparel",
            "clothing",
            "dress",
            "fashion",
            "pant",
            "shirt",
            "t-shirt",
            "tee",
            "trouser",
        ),
        "path_terms": ("furniture", "shopping bags"),
    },
    {
        "context_terms": ("boot", "footwear", "oxford", "shoe", "sneaker"),
        "path_terms": ("undergarments", "underwear"),
    },
)
DATA_ENRICHMENT_SEO_STOPWORDS = (
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "new",
    "of",
    "on",
    "or",
    "sale",
    "the",
    "to",
    "with",
    "your",
)
DATA_ENRICHMENT_SHOPIFY_ATTRIBUTE_CRAWL_FIELDS = {
    "age_group": ("age_group", "gender", "category", "product_type", "title"),
    "availability": ("availability", "stock_status", "variants", "selected_variant"),
    "brand": ("brand", "vendor", "manufacturer"),
    "care_instructions": ("care_instructions", "product_attributes", "details"),
    "color": ("color", "variant_axes", "selected_variant", "title"),
    "description": ("description", "short_description", "summary"),
    "fabric": ("materials", "material", "product_attributes", "description"),
    "gender": ("gender", "department", "category", "product_type", "title"),
    "image_link": ("image_url", "image", "thumbnail"),
    "link": ("canonical_url", "source_url", "url"),
    "material": ("materials", "material", "product_attributes", "description"),
    "pattern": ("pattern", "product_attributes", "description", "title"),
    "price": ("price", "original_price"),
    "size": ("size", "available_sizes", "variant_axes", "selected_variant"),
    "size_system": ("size_system", "size", "available_sizes"),
    "target_gender": ("gender", "department", "category", "product_type", "title"),
    "title": ("title", "name"),
}

DATA_ENRICHMENT_PROMPT_REGISTRY = {
    DATA_ENRICHMENT_LLM_TASK: {
        "response_type": "object",
        "system_file": "data_enrichment_semantic.system.txt",
        "user_file": "data_enrichment_semantic.user.txt",
    },
}


@dataclass(frozen=True, slots=True)
class DataEnrichmentSettings:
    max_source_records: int = 500
    max_concurrency: int = 3
    taxonomy_path: Path = DATA_ENRICHMENT_TAXONOMY_PATH
    attributes_path: Path = DATA_ENRICHMENT_ATTRIBUTES_PATH
    category_match_threshold: float = 0.42
    max_seo_keywords: int = 20
    llm_description_excerpt_chars: int = 300
    llm_taxonomy_hint_count: int = 5


data_enrichment_settings = DataEnrichmentSettings()
