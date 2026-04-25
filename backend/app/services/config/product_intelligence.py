from __future__ import annotations

from pydantic import AliasChoices, Field, model_validator

from app.services.config.runtime_settings import _settings_config
from pydantic_settings import BaseSettings

PRODUCT_INTELLIGENCE_JOB_STATUS_QUEUED = "queued"
PRODUCT_INTELLIGENCE_JOB_STATUS_RUNNING = "running"
PRODUCT_INTELLIGENCE_JOB_STATUS_COMPLETE = "complete"
PRODUCT_INTELLIGENCE_JOB_STATUS_FAILED = "failed"

PRODUCT_INTELLIGENCE_CANDIDATE_STATUS_DISCOVERED = "discovered"
PRODUCT_INTELLIGENCE_CANDIDATE_STATUS_CRAWL_QUEUED = "crawl_queued"
PRODUCT_INTELLIGENCE_CANDIDATE_STATUS_CRAWL_COMPLETE = "crawl_complete"
PRODUCT_INTELLIGENCE_CANDIDATE_STATUS_NO_RECORDS = "no_records"
PRODUCT_INTELLIGENCE_CANDIDATE_STATUS_CRAWL_TIMEOUT = "crawl_timeout"
PRODUCT_INTELLIGENCE_CANDIDATE_STATUS_FAILED = "failed"

PRODUCT_INTELLIGENCE_REVIEW_PENDING = "pending"
PRODUCT_INTELLIGENCE_REVIEW_ACCEPTED = "accepted"
PRODUCT_INTELLIGENCE_REVIEW_REJECTED = "rejected"

SOURCE_TYPE_BRAND_DTC = "brand_dtc"
SOURCE_TYPE_RETAILER = "retailer"
SOURCE_TYPE_MARKETPLACE = "marketplace"
SOURCE_TYPE_AGGREGATOR = "aggregator"
SOURCE_TYPE_UNKNOWN = "unknown"

PRIVATE_LABEL_INCLUDE = "include"
PRIVATE_LABEL_FLAG = "flag"
PRIVATE_LABEL_EXCLUDE = "exclude"

SEARCH_PROVIDER_DUCKDUCKGO = "duckduckgo"
SEARCH_PROVIDER_SERPAPI = "serpapi"

DEFAULT_SCORE_LABEL_HIGH = "high"
DEFAULT_SCORE_LABEL_MEDIUM = "medium"
DEFAULT_SCORE_LABEL_LOW = "low"
DEFAULT_SCORE_LABEL_UNCERTAIN = "uncertain"

ECOMMERCE_DETAIL_SURFACE = "ecommerce_detail"
RUN_TYPE_CRAWL = "crawl"

SOURCE_TITLE_FIELDS = ("title", "name", "product_title")
SOURCE_BRAND_FIELDS = ("brand", "manufacturer", "vendor")
SOURCE_PRICE_FIELDS = ("price", "sale_price", "current_price", "final_price")
SOURCE_CURRENCY_FIELDS = ("currency", "price_currency")
SOURCE_IMAGE_FIELDS = ("image_url", "image", "primary_image", "thumbnail")
SOURCE_URL_FIELDS = ("url", "product_url", "canonical_url", "source_url")
SOURCE_SKU_FIELDS = ("sku", "style", "style_id")
SOURCE_MPN_FIELDS = ("mpn", "model", "model_number")
SOURCE_GTIN_FIELDS = ("gtin", "upc", "ean", "isbn")
SOURCE_AVAILABILITY_FIELDS = ("availability", "stock_status", "in_stock")

SEARCH_STOP_WORDS = {
    "a",
    "an",
    "and",
    "for",
    "in",
    "of",
    "or",
    "the",
    "with",
}
SEARCH_EXCLUDED_DOMAIN_PREFIX = "-site:"
SEARCH_SITE_PREFIX = "site:"
DUCKDUCKGO_HTML_URL = "https://html.duckduckgo.com/html/"
DUCKDUCKGO_BASE_URL = "https://duckduckgo.com"
DUCKDUCKGO_QUERY_PARAM = "q"
DUCKDUCKGO_RESULT_LINK_SELECTORS = (
    "a.result__a",
    "a.result__url",
)
DUCKDUCKGO_REDIRECT_QUERY_KEY = "uddg"
DUCKDUCKGO_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
SERPAPI_SEARCH_URL = "https://serpapi.com/search.json"
SERPAPI_ENGINE = "google"
SERPAPI_QUERY_PARAM = "q"
SERPAPI_KEY_PARAM = "api_key"
SERPAPI_ENGINE_PARAM = "engine"
SERPAPI_ORGANIC_RESULTS_FIELD = "organic_results"
SERPAPI_LINK_FIELD = "link"
SERPAPI_TITLE_FIELD = "title"
SERPAPI_SNIPPET_FIELD = "snippet"
SERPAPI_POSITION_FIELD = "position"
SERPAPI_SOURCE_FIELD = "source"
SERPAPI_DISPLAYED_LINK_FIELD = "displayed_link"
SERPAPI_PRICE_FIELDS = ("extracted_price", "price")
SERPAPI_THUMBNAIL_FIELDS = ("thumbnail", "image", "favicon")
PRODUCT_INTELLIGENCE_LLM_TASK = "product_intelligence_enrichment"

SEARCH_PHRASE_BUY = "buy"

BRAND_ALIAS_MAP = {
    "levi s": "levi's",
    "levis": "levi's",
    "levi's": "levi's",
    "lee": "lee",
}

BRAND_DOMAIN_MAP = {
    "adidas": "adidas.com",
    "calvin klein": "calvinklein.com",
    "coach": "coach.com",
    "columbia": "columbia.com",
    "lee": "lee.com",
    "levi's": "levi.com",
    "michael kors": "michaelkors.com",
    "nike": "nike.com",
    "ralph lauren": "ralphlauren.com",
    "tommy hilfiger": "tommy.com",
    "under armour": "underarmour.com",
}

PRIVATE_LABEL_BRANDS = {
    "belk",
    "kaari blue",
    "new directions",
    "requirements",
    "studio 1",
}

RETAILER_DOMAINS = {
    "belk.com",
    "bloomingdales.com",
    "dillards.com",
    "kohls.com",
    "macys.com",
    "nordstrom.com",
    "saksfifthavenue.com",
    "target.com",
    "walmart.com",
    "zappos.com",
}

MARKETPLACE_DOMAINS = {
    "amazon.com",
    "ebay.com",
}

AGGREGATOR_DOMAINS = {
    "google.com",
    "shopstyle.com",
}

SOURCE_TYPE_AUTHORITY_BONUS = {
    SOURCE_TYPE_BRAND_DTC: 0.18,
    SOURCE_TYPE_RETAILER: 0.10,
    SOURCE_TYPE_MARKETPLACE: 0.06,
    SOURCE_TYPE_AGGREGATOR: 0.04,
    SOURCE_TYPE_UNKNOWN: 0.0,
}

MATCH_SCORE_WEIGHTS = {
    "title_similarity": 0.34,
    "brand_match": 0.24,
    "identifier_match": 0.25,
    "price_band": 0.05,
    "source_authority": 0.12,
}

PRODUCT_INTELLIGENCE_PROMPT_REGISTRY = {
    PRODUCT_INTELLIGENCE_LLM_TASK: {
        "response_type": "object",
        "system_file": "product_intelligence_enrichment.system.txt",
        "user_file": "product_intelligence_enrichment.user.txt",
    },
}


class ProductIntelligenceSettings(BaseSettings):
    model_config = _settings_config(env_prefix="PRODUCT_INTELLIGENCE_")

    default_search_provider: str = SEARCH_PROVIDER_SERPAPI
    serpapi_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "PRODUCT_INTELLIGENCE_SERPAPI_KEY",
            "SERP_API_KEY",
            "SERPAPI_API_KEY",
            "SERPAPI_KEY",
            "serp_api_key",
        ),
    )
    max_source_products: int = 50
    max_candidates_per_product: int = 5
    max_urls_per_result_domain: int = 1
    search_timeout_seconds: float = 20.0
    search_delay_ms: int = 800
    candidate_poll_seconds: float = 30.0
    candidate_poll_interval_seconds: float = 2.0
    confidence_threshold: float = 0.4
    title_token_limit: int = 6
    price_band_ratio: float = 0.25

    @model_validator(mode="after")
    def _validate(self) -> "ProductIntelligenceSettings":
        self.default_search_provider = str(self.default_search_provider or "").strip().lower()
        if self.default_search_provider not in {
            SEARCH_PROVIDER_DUCKDUCKGO,
            SEARCH_PROVIDER_SERPAPI,
        }:
            raise ValueError(
                "default_search_provider must be 'duckduckgo' or 'serpapi'"
            )
        if (
            self.default_search_provider == SEARCH_PROVIDER_SERPAPI
            and not str(self.serpapi_key or "").strip()
        ):
            self.default_search_provider = SEARCH_PROVIDER_DUCKDUCKGO
        self.max_source_products = max(1, int(self.max_source_products))
        self.max_candidates_per_product = max(1, int(self.max_candidates_per_product))
        self.max_urls_per_result_domain = max(1, int(self.max_urls_per_result_domain))
        self.search_timeout_seconds = max(1.0, float(self.search_timeout_seconds))
        self.search_delay_ms = max(0, int(self.search_delay_ms))
        self.candidate_poll_seconds = max(0.0, float(self.candidate_poll_seconds))
        self.candidate_poll_interval_seconds = max(
            0.5,
            float(self.candidate_poll_interval_seconds),
        )
        self.confidence_threshold = min(max(float(self.confidence_threshold), 0.0), 1.0)
        self.title_token_limit = max(1, int(self.title_token_limit))
        self.price_band_ratio = min(max(float(self.price_band_ratio), 0.0), 1.0)
        return self


product_intelligence_settings = ProductIntelligenceSettings()
