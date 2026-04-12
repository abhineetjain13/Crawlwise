from __future__ import annotations

from types import MappingProxyType

from pydantic import Field
from pydantic_settings import BaseSettings

from app.services.config.runtime_settings import _settings_config


class ExtractionAuditSettings(BaseSettings):
    model_config = _settings_config(env_prefix="CRAWLER_EXTRACTION_")

    listing_card_group_min_size: int = 2
    listing_card_group_min_signal_ratio: float = 0.45
    listing_card_group_sample_size: int = 30
    listing_card_substantial_text_min_chars: int = 40
    listing_card_multi_element_min_children: int = 2
    listing_card_max_regex_input_chars: int = 500
    listing_card_repeated_link_root_max_depth: int = 4
    listing_card_min_path_segments: int = 2
    listing_card_job_title_min_chars: int = 4
    listing_card_listing_title_min_chars: int = 3
    listing_card_job_metadata_text_max_chars: int = 120
    listing_card_job_metadata_salary_max_chars: int = 40
    listing_card_job_company_line_max_chars: int = 60
    listing_card_job_company_suffix_max_chars: int = 40
    listing_card_job_location_line_max_chars: int = 80
    listing_card_color_label_max_chars: int = 40
    listing_card_product_url_scan_max_depth: int = 6
    listing_card_product_url_scan_max_list_items: int = 40
    listing_card_commerce_strong_signal_score: float = 1.0
    listing_card_commerce_partial_signal_score: float = 0.5
    listing_card_job_strong_signal_score: float = 1.0
    listing_card_job_partial_signal_score: float = 0.6
    listing_card_generic_media_signal_score: float = 1.0
    listing_card_generic_heading_signal_score: float = 0.5
    listing_card_generic_text_signal_score: float = 0.4

    json_listing_search_max_depth: int = 5
    json_listing_alias_max_depth: int = 4
    json_listing_default_max_records: int = 100
    json_candidate_array_sample_size: int = 5
    json_candidate_title_score: int = 3
    json_candidate_url_score: int = 3
    json_candidate_job_score: int = 4
    json_candidate_commerce_score: int = 2
    json_alias_visit_list_limit: int = 40
    json_image_list_limit: int = 20

    source_parser_datalayer_field_weights: dict[str, int] = Field(
        default_factory=lambda: {
            "price": 3,
            "sale_price": 2,
            "discount_amount": 1,
            "discount_percentage": 1,
            "price_currency": 2,
            "availability": 2,
            "category": 1,
            "google_product_category": 1,
        }
    )
    source_parser_embedded_blob_max_depth: int = 5
    source_parser_embedded_blob_list_sample_size: int = 5
    source_parser_embedded_blob_strong_signal_threshold: int = 2
    source_parser_embedded_blob_supporting_signal_threshold: int = 1
    source_parser_embedded_blob_strong_only_threshold: int = 3
    source_parser_embedded_blob_weak_signal_threshold: int = 1
    source_parser_previous_heading_limit: int = 6


extraction_audit_settings = ExtractionAuditSettings()

LISTING_CARD_GROUP_MIN_SIZE = extraction_audit_settings.listing_card_group_min_size
LISTING_CARD_GROUP_MIN_SIGNAL_RATIO = (
    extraction_audit_settings.listing_card_group_min_signal_ratio
)
LISTING_CARD_GROUP_SAMPLE_SIZE = extraction_audit_settings.listing_card_group_sample_size
LISTING_CARD_SUBSTANTIAL_TEXT_MIN_CHARS = (
    extraction_audit_settings.listing_card_substantial_text_min_chars
)
LISTING_CARD_MULTI_ELEMENT_MIN_CHILDREN = (
    extraction_audit_settings.listing_card_multi_element_min_children
)
LISTING_CARD_MAX_REGEX_INPUT_CHARS = extraction_audit_settings.listing_card_max_regex_input_chars
LISTING_CARD_REPEATED_LINK_ROOT_MAX_DEPTH = (
    extraction_audit_settings.listing_card_repeated_link_root_max_depth
)
LISTING_CARD_MIN_PATH_SEGMENTS = extraction_audit_settings.listing_card_min_path_segments
LISTING_CARD_JOB_TITLE_MIN_CHARS = (
    extraction_audit_settings.listing_card_job_title_min_chars
)
LISTING_CARD_LISTING_TITLE_MIN_CHARS = (
    extraction_audit_settings.listing_card_listing_title_min_chars
)
LISTING_CARD_JOB_METADATA_TEXT_MAX_CHARS = (
    extraction_audit_settings.listing_card_job_metadata_text_max_chars
)
LISTING_CARD_JOB_METADATA_SALARY_MAX_CHARS = (
    extraction_audit_settings.listing_card_job_metadata_salary_max_chars
)
LISTING_CARD_JOB_COMPANY_LINE_MAX_CHARS = (
    extraction_audit_settings.listing_card_job_company_line_max_chars
)
LISTING_CARD_JOB_COMPANY_SUFFIX_MAX_CHARS = (
    extraction_audit_settings.listing_card_job_company_suffix_max_chars
)
LISTING_CARD_JOB_LOCATION_LINE_MAX_CHARS = (
    extraction_audit_settings.listing_card_job_location_line_max_chars
)
LISTING_CARD_COLOR_LABEL_MAX_CHARS = (
    extraction_audit_settings.listing_card_color_label_max_chars
)
LISTING_CARD_PRODUCT_URL_SCAN_MAX_DEPTH = (
    extraction_audit_settings.listing_card_product_url_scan_max_depth
)
LISTING_CARD_PRODUCT_URL_SCAN_MAX_LIST_ITEMS = (
    extraction_audit_settings.listing_card_product_url_scan_max_list_items
)
LISTING_CARD_COMMERCE_STRONG_SIGNAL_SCORE = (
    extraction_audit_settings.listing_card_commerce_strong_signal_score
)
LISTING_CARD_COMMERCE_PARTIAL_SIGNAL_SCORE = (
    extraction_audit_settings.listing_card_commerce_partial_signal_score
)
LISTING_CARD_JOB_STRONG_SIGNAL_SCORE = (
    extraction_audit_settings.listing_card_job_strong_signal_score
)
LISTING_CARD_JOB_PARTIAL_SIGNAL_SCORE = (
    extraction_audit_settings.listing_card_job_partial_signal_score
)
LISTING_CARD_GENERIC_MEDIA_SIGNAL_SCORE = (
    extraction_audit_settings.listing_card_generic_media_signal_score
)
LISTING_CARD_GENERIC_HEADING_SIGNAL_SCORE = (
    extraction_audit_settings.listing_card_generic_heading_signal_score
)
LISTING_CARD_GENERIC_TEXT_SIGNAL_SCORE = (
    extraction_audit_settings.listing_card_generic_text_signal_score
)

JSON_LISTING_SEARCH_MAX_DEPTH = extraction_audit_settings.json_listing_search_max_depth
JSON_LISTING_ALIAS_MAX_DEPTH = extraction_audit_settings.json_listing_alias_max_depth
JSON_LISTING_DEFAULT_MAX_RECORDS = (
    extraction_audit_settings.json_listing_default_max_records
)
JSON_CANDIDATE_ARRAY_SAMPLE_SIZE = (
    extraction_audit_settings.json_candidate_array_sample_size
)
JSON_CANDIDATE_TITLE_SCORE = extraction_audit_settings.json_candidate_title_score
JSON_CANDIDATE_URL_SCORE = extraction_audit_settings.json_candidate_url_score
JSON_CANDIDATE_JOB_SCORE = extraction_audit_settings.json_candidate_job_score
JSON_CANDIDATE_COMMERCE_SCORE = (
    extraction_audit_settings.json_candidate_commerce_score
)
JSON_ALIAS_VISIT_LIST_LIMIT = extraction_audit_settings.json_alias_visit_list_limit
JSON_IMAGE_LIST_LIMIT = extraction_audit_settings.json_image_list_limit

SOURCE_PARSER_DATALAYER_FIELD_WEIGHTS = MappingProxyType(
    extraction_audit_settings.source_parser_datalayer_field_weights
)
SOURCE_PARSER_EMBEDDED_BLOB_MAX_DEPTH = (
    extraction_audit_settings.source_parser_embedded_blob_max_depth
)
SOURCE_PARSER_EMBEDDED_BLOB_LIST_SAMPLE_SIZE = (
    extraction_audit_settings.source_parser_embedded_blob_list_sample_size
)
SOURCE_PARSER_EMBEDDED_BLOB_STRONG_SIGNAL_THRESHOLD = (
    extraction_audit_settings.source_parser_embedded_blob_strong_signal_threshold
)
SOURCE_PARSER_EMBEDDED_BLOB_SUPPORTING_SIGNAL_THRESHOLD = (
    extraction_audit_settings.source_parser_embedded_blob_supporting_signal_threshold
)
SOURCE_PARSER_EMBEDDED_BLOB_STRONG_ONLY_THRESHOLD = (
    extraction_audit_settings.source_parser_embedded_blob_strong_only_threshold
)
SOURCE_PARSER_EMBEDDED_BLOB_WEAK_SIGNAL_THRESHOLD = (
    extraction_audit_settings.source_parser_embedded_blob_weak_signal_threshold
)
SOURCE_PARSER_PREVIOUS_HEADING_LIMIT = (
    extraction_audit_settings.source_parser_previous_heading_limit
)
