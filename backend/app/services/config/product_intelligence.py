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

SEARCH_PROVIDER_SERPAPI = "serpapi"
SEARCH_PROVIDER_GOOGLE_NATIVE = "google_native"

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
SERPAPI_SEARCH_URL = "https://serpapi.com/search.json"
SERPAPI_ENGINE = "google"
SERPAPI_QUERY_PARAM = "q"
SERPAPI_KEY_PARAM = "api_key"
SERPAPI_ENGINE_PARAM = "engine"
SERPAPI_RESULT_COUNT_PARAM = "num"
SERPAPI_ORGANIC_RESULTS_FIELD = "organic_results"
SERPAPI_LINK_FIELD = "link"
SERPAPI_TITLE_FIELD = "title"
SERPAPI_SNIPPET_FIELD = "snippet"
SERPAPI_POSITION_FIELD = "position"
SERPAPI_SOURCE_FIELD = "source"
SERPAPI_DISPLAYED_LINK_FIELD = "displayed_link"
SERPAPI_PRICE_FIELDS = ("extracted_price", "price")
SERPAPI_THUMBNAIL_FIELDS = ("thumbnail", "image", "favicon")
GOOGLE_NATIVE_HOME_URL = "https://www.google.com/"
GOOGLE_NATIVE_SEARCH_URL = "https://www.google.com/search"
GOOGLE_NATIVE_QUERY_PARAM = "q"
GOOGLE_NATIVE_RESULT_COUNT_PARAM = "num"
GOOGLE_NATIVE_SEARCH_INPUT_SELECTOR = "textarea[name='q'], input[name='q']"
GOOGLE_NATIVE_RESULT_LINK_SELECTOR = "a[href]"
GOOGLE_NATIVE_TITLE_SELECTOR = "h3"
GOOGLE_NATIVE_THUMBNAIL_ANCESTOR_DEPTH = 6
GOOGLE_NATIVE_THUMBNAIL_MIN_SRC_LENGTH = 20
GOOGLE_NATIVE_REDIRECT_PATH = "/url"
GOOGLE_NATIVE_REDIRECT_TARGET_PARAM = "q"
GOOGLE_NATIVE_IGNORED_DOMAINS = ("google.com", "webcache.googleusercontent.com")
GOOGLE_NATIVE_PROVIDER_PAYLOAD = "google_native"
GOOGLE_NATIVE_BROWSER_ENGINE = "real_chrome"
GOOGLE_NATIVE_NAVIGATION_TIMEOUT_MS = 20000
GOOGLE_NATIVE_RESULT_WAIT_MS = 2500
GOOGLE_NATIVE_SUBMIT_KEY = "Enter"
PRODUCT_INTELLIGENCE_LLM_TASK = "product_intelligence_enrichment"
PRODUCT_INTELLIGENCE_BRAND_INFERENCE_LLM_TASK = "product_intelligence_brand_inference"

SEARCH_PHRASE_BUY = "buy"

BRAND_ALIAS_MAP = {
    "collection by michael strahan": "collection by michael strahan",
    "collection by michael strahan tm": "collection by michael strahan",
    "izod": "izod",
    "kenneth cole reaction": "kenneth cole",
    "levi s": "levi's",
    "levis": "levi's",
    "levi's": "levi's",
    "lee": "lee",
    "michael strahan": "collection by michael strahan",
    "polo ralph lauren": "ralph lauren",
    "ralph lauren childrenswear": "ralph lauren",
    "rare too": "rare editions",
    "skechers slip ins go walk": "skechers",
    "skechers men s slip ins": "skechers",
    "skechers men s max cushioning": "skechers",
    "skechers go run consistent": "skechers",
    "tommy bahama": "tommy bahama",
    "tommy bahama r": "tommy bahama",
}

BRAND_DOMAIN_MAP = {
    "adidas": "adidas.com",
    "bonnie jean": "bonniejean.com",
    "calvin klein": "calvinklein.com",
    "coach": "coach.com",
    "columbia": "columbia.com",
    "haggar": "haggar.com",
    "izod": "izod.com",
    "kenneth cole": "kennethcole.com",
    "lee": "lee.com",
    "levi's": "levi.com",
    "michael kors": "michaelkors.com",
    "nautica": "nautica.com",
    "nike": "nike.com",
    "puma": "puma.com",
    "rare editions": "therareeditions.com",
    "ralph lauren": "ralphlauren.com",
    "reebok": "reebok.com",
    "skechers": "skechers.com",
    "tommy bahama": "tommybahama.com",
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
    "jcpenney.com",
    "kohls.com",
    "macys.com",
    "menswearhouse.com",
    "myntra.com",
    "nykaa.com",
    "nordstrom.com",
    "saksfifthavenue.com",
    "target.com",
    "walmart.com",
    "zappos.com",
}

MARKETPLACE_DOMAINS = {
    "amazon.com",
    "amazon.ca",
    "amazon.co.uk",
    "amazon.com.au",
    "amazon.com.mx",
    "amazon.de",
    "amazon.fr",
    "amazon.in",
    "amazon.it",
    "amazon.co.jp",
    "ebay.com",
    "ebay.ca",
    "ebay.co.uk",
    "ebay.com.au",
    "ebay.de",
    "ebay.fr",
    "ebay.in",
    "ebay.it",
    "etsy.com",
    "flipkart.com",
}

AGGREGATOR_DOMAINS = {
    "coolspringsgalleria.com",
    "google.com",
    "hamiltonplace.com",
    "shopmy.us",
    "shopstyle.com",
    "thesummitbirmingham.com",
}

DISCOVERY_SOURCE_TYPE_PRIORITY = {
    SOURCE_TYPE_BRAND_DTC: 0,
    SOURCE_TYPE_RETAILER: 1,
    SOURCE_TYPE_MARKETPLACE: 2,
    SOURCE_TYPE_UNKNOWN: 3,
    SOURCE_TYPE_AGGREGATOR: 4,
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
    PRODUCT_INTELLIGENCE_BRAND_INFERENCE_LLM_TASK: {
        "response_type": "object",
        "system_file": "product_intelligence_brand_inference.system.txt",
        "user_file": "product_intelligence_brand_inference.user.txt",
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
    max_source_products: int = 10
    max_candidates_per_product: int = 2
    discovery_pool_multiplier: int = 1
    max_urls_per_result_domain: int = 1
    search_timeout_seconds: float = 20.0
    search_delay_ms: int = 800
    google_native_max_results: int = 10
    google_native_max_queries_per_product: int = 2
    candidate_poll_seconds: float = 30.0
    candidate_poll_interval_seconds: float = 2.0
    confidence_threshold: float = 0.4
    title_token_limit: int = 6
    price_band_ratio: float = 0.25
    brand_inference_confidence_threshold: float = 0.6

    @model_validator(mode="after")
    def _validate(self) -> "ProductIntelligenceSettings":
        self.default_search_provider = str(self.default_search_provider or "").strip().lower()
        if self.default_search_provider not in {
            SEARCH_PROVIDER_SERPAPI,
            SEARCH_PROVIDER_GOOGLE_NATIVE,
        }:
            raise ValueError(
                "default_search_provider must be 'serpapi' or 'google_native'"
            )
        self.max_source_products = max(1, int(self.max_source_products))
        self.max_candidates_per_product = max(1, int(self.max_candidates_per_product))
        self.discovery_pool_multiplier = max(1, int(self.discovery_pool_multiplier))
        self.max_urls_per_result_domain = max(1, int(self.max_urls_per_result_domain))
        self.search_timeout_seconds = max(1.0, float(self.search_timeout_seconds))
        self.search_delay_ms = max(0, int(self.search_delay_ms))
        self.google_native_max_results = max(1, int(self.google_native_max_results))
        self.google_native_max_queries_per_product = max(
            1, int(self.google_native_max_queries_per_product)
        )
        self.candidate_poll_seconds = max(0.0, float(self.candidate_poll_seconds))
        self.candidate_poll_interval_seconds = max(
            0.5,
            float(self.candidate_poll_interval_seconds),
        )
        self.confidence_threshold = min(max(float(self.confidence_threshold), 0.0), 1.0)
        self.title_token_limit = max(1, int(self.title_token_limit))
        self.price_band_ratio = min(max(float(self.price_band_ratio), 0.0), 1.0)
        self.brand_inference_confidence_threshold = min(
            max(float(self.brand_inference_confidence_threshold), 0.0), 1.0
        )
        return self


product_intelligence_settings = ProductIntelligenceSettings()
