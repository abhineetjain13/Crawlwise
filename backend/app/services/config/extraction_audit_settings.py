from __future__ import annotations

from types import MappingProxyType

from pydantic import Field
from pydantic_settings import BaseSettings

from app.services.config._module_exports import make_getattr, module_dir
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
_EXPORTS = {
    name: name.lower()
    for name in (
        "LISTING_CARD_GROUP_MIN_SIZE",
        "LISTING_CARD_GROUP_MIN_SIGNAL_RATIO",
        "LISTING_CARD_GROUP_SAMPLE_SIZE",
        "LISTING_CARD_SUBSTANTIAL_TEXT_MIN_CHARS",
        "LISTING_CARD_MULTI_ELEMENT_MIN_CHILDREN",
        "LISTING_CARD_MAX_REGEX_INPUT_CHARS",
        "LISTING_CARD_REPEATED_LINK_ROOT_MAX_DEPTH",
        "LISTING_CARD_MIN_PATH_SEGMENTS",
        "LISTING_CARD_JOB_TITLE_MIN_CHARS",
        "LISTING_CARD_LISTING_TITLE_MIN_CHARS",
        "LISTING_CARD_JOB_METADATA_TEXT_MAX_CHARS",
        "LISTING_CARD_JOB_METADATA_SALARY_MAX_CHARS",
        "LISTING_CARD_JOB_COMPANY_LINE_MAX_CHARS",
        "LISTING_CARD_JOB_COMPANY_SUFFIX_MAX_CHARS",
        "LISTING_CARD_JOB_LOCATION_LINE_MAX_CHARS",
        "LISTING_CARD_COLOR_LABEL_MAX_CHARS",
        "LISTING_CARD_PRODUCT_URL_SCAN_MAX_DEPTH",
        "LISTING_CARD_PRODUCT_URL_SCAN_MAX_LIST_ITEMS",
        "LISTING_CARD_COMMERCE_STRONG_SIGNAL_SCORE",
        "LISTING_CARD_COMMERCE_PARTIAL_SIGNAL_SCORE",
        "LISTING_CARD_JOB_STRONG_SIGNAL_SCORE",
        "LISTING_CARD_JOB_PARTIAL_SIGNAL_SCORE",
        "LISTING_CARD_GENERIC_MEDIA_SIGNAL_SCORE",
        "LISTING_CARD_GENERIC_HEADING_SIGNAL_SCORE",
        "LISTING_CARD_GENERIC_TEXT_SIGNAL_SCORE",
        "JSON_LISTING_SEARCH_MAX_DEPTH",
        "JSON_LISTING_ALIAS_MAX_DEPTH",
        "JSON_LISTING_DEFAULT_MAX_RECORDS",
        "JSON_CANDIDATE_ARRAY_SAMPLE_SIZE",
        "JSON_CANDIDATE_TITLE_SCORE",
        "JSON_CANDIDATE_URL_SCORE",
        "JSON_CANDIDATE_JOB_SCORE",
        "JSON_CANDIDATE_COMMERCE_SCORE",
        "JSON_ALIAS_VISIT_LIST_LIMIT",
        "JSON_IMAGE_LIST_LIMIT",
        "SOURCE_PARSER_EMBEDDED_BLOB_MAX_DEPTH",
        "SOURCE_PARSER_EMBEDDED_BLOB_LIST_SAMPLE_SIZE",
        "SOURCE_PARSER_EMBEDDED_BLOB_STRONG_SIGNAL_THRESHOLD",
        "SOURCE_PARSER_EMBEDDED_BLOB_SUPPORTING_SIGNAL_THRESHOLD",
        "SOURCE_PARSER_EMBEDDED_BLOB_STRONG_ONLY_THRESHOLD",
        "SOURCE_PARSER_EMBEDDED_BLOB_WEAK_SIGNAL_THRESHOLD",
        "SOURCE_PARSER_PREVIOUS_HEADING_LIMIT",
    )
}
_SPECIAL_EXPORTS = {
    "SOURCE_PARSER_DATALAYER_FIELD_WEIGHTS": lambda: MappingProxyType(
        extraction_audit_settings.source_parser_datalayer_field_weights
    ),
}

__all__ = sorted(
    [
        *(_EXPORTS.keys()),
        *(_SPECIAL_EXPORTS.keys()),
        "ExtractionAuditSettings",
        "extraction_audit_settings",
    ]
)

__getattr__ = make_getattr(
    attr_exports=_EXPORTS,
    dynamic_exports=_SPECIAL_EXPORTS,
    settings_obj=extraction_audit_settings,
)


def __dir__() -> list[str]:
    return module_dir(globals(), __all__)
